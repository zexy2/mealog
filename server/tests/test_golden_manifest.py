import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / "eval/golden/manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_non_text_golden_entries_declare_reproducible_image_sources() -> None:
    rows = [row for row in _rows() if row["input_type"] != "text"]
    assert rows
    for row in rows:
        assert row["image_source_url"].startswith(("http://", "https://"))
        assert row["image_license"].strip()
        assert SHA256.fullmatch(row["image_sha256"])


def test_seeded_truth_never_claims_tier_one() -> None:
    for row in _rows():
        assert not (row["tier"] == "tier_1" and row.get("truth_source") == "seeded")


def test_no_unmapped_ingredient_matches_the_catalogue_exactly() -> None:
    """D25: truth may not go stale when the catalogue grows.

    The manifest once listed broccoli, pork and tofu as outside the catalogue
    after those foods had been added, so correct predictions scored as false
    positives. This asserts the remap tool finds nothing left to do; if it
    finds a match, either the manifest or the tool is wrong.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "mealog_remap_golden", ROOT / "scripts/remap_golden_ingredients.py"
    )
    assert spec is not None and spec.loader is not None
    remap = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = remap
    spec.loader.exec_module(remap)

    rows = _rows()
    proposals, problems = remap.find_matches(rows, remap.load_catalogue())
    assert problems == []
    mapped = [p for p in proposals if p["action"] == "map"]
    assert mapped == [], (
        "unmapped ingredients now match the catalogue exactly; run "
        f"scripts/remap_golden_ingredients.py --apply: {mapped[:5]}"
    )
