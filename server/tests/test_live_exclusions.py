"""Live eligibility is a licence rule, not an observation about HTTP 403.

These tests are hermetic: they read the committed manifest and write copies
under ``tmp_path``. They prove that selection and input construction refuse the
same rows independently, that the licence is the deciding field, and that the
offline scope does not move.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import harness
from golden_inputs import (
    LiveIneligibleRow,
    input_for_row,
    live_licence,
    load_manifest,
)
from locale_scope import evidence_scope

INDEPENDENT_OVER_NETWORK = "Non-commercial research only"


def write_manifest(directory: Path, rows: list[dict]) -> Path:
    path = directory / "manifest.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def manifest_copy() -> list[dict]:
    return load_manifest(harness.GOLDEN)


def row_by_id(rows: list[dict], sample_id: str) -> dict:
    return next(row for row in rows if row["sample_id"] == sample_id)


def full_live_scope() -> tuple[list[str], list[str]]:
    return evidence_scope(harness.manifest_locales())


def test_full_live_scope_requests_75_rows_and_excludes_two_by_licence():
    locales, _ = full_live_scope()
    exclusions = []

    selected = harness.select_rows(
        locales=set(locales), live=True, exclusions=exclusions
    )

    assert len(selected) == 75
    assert len(exclusions) == 2
    assert [row.sample_id for row in exclusions] == ["jp_0001", "jp_0002"]
    for row in exclusions:
        assert INDEPENDENT_OVER_NETWORK in (row.image_license or "")
        assert "not in the live allowlist" in row.reason
    assert not {row.sample_id for row in exclusions} & {
        row["sample_id"] for row in selected
    }


def test_include_restricted_live_excludes_the_text_row_without_a_licence():
    locales, _ = evidence_scope(harness.manifest_locales(), include_restricted=True)
    exclusions = []

    selected = harness.select_rows(
        locales=set(locales), live=True, exclusions=exclusions
    )

    ids = {row["sample_id"] for row in selected}
    assert len(selected) == 77
    assert {"tr_0001", "tr_0002"} <= ids
    excluded = {row.sample_id: row for row in exclusions}
    assert set(excluded) == {"jp_0001", "jp_0002", "tr_0003"}
    assert "no image_license recorded" in excluded["tr_0003"].reason


def test_limit_applies_after_exclusion(tmp_path):
    rows = load_manifest(harness.GOLDEN)
    jp_rows = [
        row for row in rows if row["sample_id"] in {"jp_0001", "jp_0002"}
    ]
    n5k_rows = [row for row in rows if row["sample_id"].startswith("n5k")][:10]
    path = write_manifest(tmp_path, jp_rows + n5k_rows)
    exclusions = []

    selected = harness.select_rows(path, limit=10, live=True, exclusions=exclusions)

    assert len(selected) == 10
    assert all(row["sample_id"].startswith("n5k") for row in selected)
    assert [row.sample_id for row in exclusions] == ["jp_0001", "jp_0002"]


def test_input_for_row_refuses_jp_before_reading_bytes_or_calling_a_provider(
    tmp_path, monkeypatch
):
    jp = row_by_id(load_manifest(harness.GOLDEN), "jp_0001")
    images = tmp_path / "images"
    images.mkdir()
    # A directory at the manifest filename: reaching read_bytes() would raise
    # IsADirectoryError instead of the licence refusal.
    (images / jp["image_filename"]).mkdir()

    class RecordingVision:
        instances: ClassVar[list] = []

        def __init__(self, *args, **kwargs):
            type(self).instances.append(self)
            self.seen = []

        def perceive(self, input_ref):
            self.seen.append(input_ref)
            return []

    monkeypatch.setattr(harness, "GeminiVision", RecordingVision)

    with pytest.raises(LiveIneligibleRow) as caught:
        input_for_row(jp, images)

    message = str(caught.value)
    assert "jp_0001" in message
    assert INDEPENDENT_OVER_NETWORK in message
    assert "not in the live allowlist" in message
    assert RecordingVision.instances == []

    # The refusal does not depend on a file existing at all.
    with pytest.raises(LiveIneligibleRow):
        input_for_row(jp, tmp_path / "does-not-exist")


def test_live_evaluate_skips_jp_without_calling_perceive(tmp_path, monkeypatch):
    jp = row_by_id(load_manifest(harness.GOLDEN), "jp_0001")
    manifest = write_manifest(tmp_path, [jp])

    class RecordingVision:
        instances: ClassVar[list] = []

        def __init__(self, *args, **kwargs):
            type(self).instances.append(self)
            self.seen = []

        def perceive(self, input_ref):
            self.seen.append(input_ref)
            return []

    monkeypatch.setattr(harness, "GeminiVision", RecordingVision)

    results, errors = harness.evaluate(
        "V3", live=True, manifest_path=manifest, images_dir=tmp_path / "none"
    )

    assert results == []
    assert errors == []
    assert RecordingVision.instances[-1].seen == []


def test_changing_a_jp_licence_makes_it_selectable(tmp_path):
    rows = manifest_copy()
    jp = row_by_id(rows, "jp_0001")
    jp["image_license"] = "CC BY 4.0 (Wikimedia Commons; attribution required)"
    jp.pop("live_eligible", None)
    path = write_manifest(tmp_path, rows)
    exclusions = []

    selected = harness.select_rows(
        path, locales={"ja_JP"}, live=True, exclusions=exclusions
    )

    assert [row["sample_id"] for row in selected] == ["jp_0001"]
    assert [row.sample_id for row in exclusions] == ["jp_0002"]


@pytest.mark.parametrize(
    "licence", [None, "", "All rights reserved (unknown source)"]
)
def test_unrecognised_n5k_licence_makes_it_ineligible(tmp_path, licence):
    rows = manifest_copy()
    row_by_id(rows, "n5k_0001")["image_license"] = licence
    path = write_manifest(tmp_path, rows)
    exclusions = []

    selected = harness.select_rows(
        path, locales={"en_US"}, live=True, exclusions=exclusions
    )

    assert "n5k_0001" not in {row["sample_id"] for row in selected}
    excluded = {row.sample_id: row for row in exclusions}
    assert "n5k_0001" in excluded
    assert live_licence(licence) is None
    if licence is None or not licence.strip():
        assert "no image_license recorded" in excluded["n5k_0001"].reason
    else:
        assert "is not in the live allowlist" in excluded["n5k_0001"].reason


def test_override_subtracts_even_when_the_licence_is_allowlisted(tmp_path):
    rows = manifest_copy()
    row = row_by_id(rows, "n5k_0002")
    assert live_licence(row["image_license"]) == "CC BY 4.0"
    row["live_eligible"] = False
    path = write_manifest(tmp_path, rows)
    exclusions = []

    selected = harness.select_rows(
        path, locales={"en_US"}, live=True, exclusions=exclusions
    )

    assert "n5k_0002" not in {row["sample_id"] for row in selected}
    excluded = {row.sample_id: row for row in exclusions}
    assert excluded["n5k_0002"].reason == "live_eligible=false override"


def test_override_true_cannot_add_an_ineligible_row(tmp_path):
    rows = manifest_copy()
    jp = row_by_id(rows, "jp_0001")
    jp["live_eligible"] = True
    path = write_manifest(tmp_path, rows)
    exclusions = []

    selected = harness.select_rows(
        path, locales={"ja_JP"}, live=True, exclusions=exclusions
    )

    assert "jp_0001" not in {row["sample_id"] for row in selected}
    excluded = {row.sample_id: row for row in exclusions}
    assert "not in the live allowlist" in excluded["jp_0001"].reason


def test_live_header_and_summary_report_the_rule():
    locales, excluded_locales = full_live_scope()
    exclusions = []
    selected = harness.select_rows(
        locales=set(locales), live=True, exclusions=exclusions
    )

    scoped = len(harness.select_rows(locales=set(locales)))
    header = harness.scorecard(
        {},
        mode="live",
        provider_model="fake-model",
        rows_requested=len(selected),
        rows_scoped=scoped,
        live_exclusions=exclusions,
    )
    assert "75 of 77 scoped manifest rows requested" in header
    assert "2 excluded by image licence" in header
    assert "jp_0001" in header and "jp_0002" in header
    assert INDEPENDENT_OVER_NETWORK in header

    limited = harness.scorecard(
        {},
        mode="live",
        provider_model="fake-model",
        rows_requested=10,
        rows_scoped=scoped,
        live_exclusions=exclusions,
    )
    assert "75 of 77 scoped manifest rows eligible" in limited
    assert "10 requested after --limit" in limited

    summary = harness.summary(
        {},
        locales,
        excluded_locales,
        mode="live",
        provider_model="fake-model",
        rows_requested=len(selected),
        live_exclusions=exclusions,
    )
    assert summary["rows_excluded_live"] == 2
    assert [row["sample_id"] for row in summary["live_exclusions"]] == [
        "jp_0001",
        "jp_0002",
    ]
    assert all(
        INDEPENDENT_OVER_NETWORK in row["image_license"]
        and "not in the live allowlist" in row["reason"]
        for row in summary["live_exclusions"]
    )


def test_offline_selection_and_summary_are_unchanged():
    locales, excluded_locales = full_live_scope()
    rows = harness.select_rows(locales=set(locales))

    assert len(rows) == 77
    assert "jp_0001" in {row["sample_id"] for row in rows}

    all_locales, _ = evidence_scope(
        harness.manifest_locales(), include_restricted=True
    )
    assert len(harness.select_rows(locales=set(all_locales))) == 80

    summary = harness.summary({}, locales, excluded_locales)
    assert "rows_excluded_live" not in summary
    assert "live_exclusions" not in summary
    assert "Live scope" not in harness.scorecard({}, mode="offline")
