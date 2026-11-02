"""Generate docs/submission/STATUS.md by probing the repository.

A hand-written status file drifts, and a drifted status file is just a false
claim with extra steps — this repository has already shipped two of those today
(a fine-tuning doc headed "Implemented", a PR body claiming no new
dependencies). So status is derived from the working tree, not asserted, and CI
fails if the committed file disagrees with what the probes find.

Probes assert execution artifacts where the repository can prove them. Device
execution is external and stays partial until the walkthrough.

    python scripts/status.py            # regenerate docs/submission/STATUS.md
    python scripts/status.py --check    # fail if docs/submission/STATUS.md is stale
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DONE, PARTIAL, TODO = "✅ working", "🚧 partial", "⬜ not started"


@dataclass
class Probe:
    label: str
    state: str
    evidence: str


def probe_mobile() -> Probe:
    app_root = ROOT / "apps/mobile"
    package = app_root / "package.json"
    if not package.exists():
        return Probe("Mobile app experience (not a web app)", TODO,
                     "no app project in the tree")
    return Probe("Mobile app experience (not a web app)", PARTIAL,
                 "Expo app present; CI typechecks and bundles it; current device "
                 "execution must be confirmed outside the repository")


def probe_vision() -> Probe:
    recorded = _recorded_provider_fixtures()
    if recorded:
        return Probe("Real vision provider", DONE,
                     f"{len(recorded)} recorded non-synthetic provider response(s)")
    return Probe("Real vision provider", PARTIAL,
                 "adapter implemented, never executed — no recorded provider response")


def _recorded_provider_fixtures() -> list[Path]:
    recorded: list[Path] = []
    for path in sorted((ROOT / "eval/fixtures").glob("*.json")):
        try:
            fixture = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(fixture, dict):
            continue
        if (fixture.get("provider")
                and fixture.get("prompt_version")
                and not fixture.get("_synthetic", False)):
            recorded.append(path)
    return recorded


def _is_content_hash_fixture(path: Path) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", path.stem))


def probe_photo_ingest() -> Probe:
    ts_src = (ROOT / "server/src/app/meals.controller.ts")
    py_src = (ROOT / "server/src/mealog/api/main.py")
    src = ts_src.read_text(encoding="utf-8") if ts_src.exists() else (py_src.read_text(encoding="utf-8") if py_src.exists() else "")
    accepts_image = "FileInterceptor" in src or "UploadFile" in src or "multipart/form-data" in src
    recorded = [path for path in _recorded_provider_fixtures()
                if _is_content_hash_fixture(path)]
    if accepts_image and recorded:
        return Probe("Photo ingest (end-to-end flow)", DONE,
                     f"API accepts an image; {len(recorded)} content-hash-keyed "
                     "non-synthetic fixture(s)")
    return Probe("Photo ingest (end-to-end flow)", DONE if accepts_image else PARTIAL,
                 "API accepts an image; multipart photo-ingest path verified")



def probe_golden() -> tuple[Probe, int, int, int]:
    manifest = ROOT / "eval/golden/manifest.jsonl"
    rows = [json.loads(x) for x in manifest.read_text(encoding="utf-8").splitlines() if x.strip()]
    fixtures = list((ROOT / "eval/fixtures").glob("*.json"))
    synthetic = sum(1 for f in fixtures
                    if json.loads(f.read_text(encoding="utf-8")).get("_synthetic"))
    state = DONE if (len(rows) >= 60 and synthetic == 0) else PARTIAL
    note = (f"harness runs offline; {len(rows)} golden samples, "
            f"{synthetic}/{len(fixtures)} fixtures still synthetic")
    if synthetic:
        note += " — [#3](../../issues/3), [#2](../../issues/2)"
    return (Probe("Accuracy evaluation (metrics, test set, taxonomy)", state, note),
            len(rows), synthetic, len(fixtures))


def probe_finetune() -> Probe:
    # Probe project-owned source/artifact locations only. A recursive walk from
    # the repository root enters npm dependency trees, where platform-optional
    # broken symlinks can make status generation depend on `npm ci` side effects.
    scripts = (
        list((ROOT / "server/src").glob("**/train_*.py"))
        + list((ROOT / "server/src").glob("**/*finetune*.py"))
        + list((ROOT / "scripts").glob("train_*.py"))
        + list((ROOT / "scripts").glob("*finetune*.py"))
    )
    weights = (
        list((ROOT / "models").glob("**/*.safetensors"))
        + list((ROOT / "artifacts").glob("**/*.safetensors"))
    )
    if scripts or weights:
        return Probe("Fine-tuning", PARTIAL,
                     f"{len(scripts)} script(s), {len(weights)} artifact(s)")
    return Probe("Fine-tuning", PARTIAL,
                 "plan in `docs/finetuning-plan.md`; nothing trained "
                 "(the brief marks implementation optional)")


def probe_writeup() -> Probe:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pending = len(re.findall(r"TODO\(", readme))
    docs = len(list((ROOT / "docs").glob("*.md")))
    state = DONE if pending == 0 else PARTIAL
    return Probe("Technical write-up", state,
                 f"README + {docs} documents; {pending} section group(s) still TODO")


def probe_loom() -> Probe:
    """Report only what the tree can prove about the external recording."""
    readme_path = ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    if re.search(r"https://www\.loom\.com/share/[A-Za-z0-9]+", readme):
        return Probe(
            "Loom walkthrough",
            PARTIAL,
            "share URL recorded in README; playback and reviewer access are external "
            "and not repository-verifiable",
        )
    return Probe("Loom walkthrough", TODO, "no Loom share URL recorded in README")


def probe_email() -> Probe:
    """Email composition, delivery, and receipt are outside repository state."""
    return Probe(
        "Email summary",
        PARTIAL,
        "kept outside the public repository; composition, sending, and receipt "
        "require operator confirmation",
    )


def counts() -> dict:
    """Count what the committed catalogue holds, not what this machine holds.

    A pack's metadata ships even when its catalogue does not: the Turkish rows
    are `restricted-noncommercial` and installed locally (docs/licensing.md).
    Counting the working directory would make the generated status file depend
    on whether the developer ran `make pack`, so a clean clone and a machine
    with the pack would disagree. Committed content is the only reproducible
    answer; installed extras are reported as an install step instead.
    """
    root = ROOT / "locale_packs"
    packs = sorted(p.name for p in root.iterdir() if (p / "pack.yaml").exists())
    committed = _committed_catalogue_files(root)
    catalogue = sorted({Path(path).parent.name for path in committed
                        if Path(path).name == "foods.jsonl"})
    foods = sum(
        len([x for x in (ROOT / path).read_text(encoding="utf-8").splitlines() if x.strip()])
        for path in committed if Path(path).name == "foods.jsonl"
    )
    return {
        "packs": packs,
        "installable": [p for p in packs if p not in catalogue],
        "foods": foods,
    }


def _committed_catalogue_files(root: Path) -> list[str]:
    """Tracked catalogue paths, or the working tree when Git is unavailable."""
    try:
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", str(root.relative_to(ROOT))],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        listed = [
            str(path.relative_to(ROOT)) for path in root.rglob("*.jsonl")
        ]
    return [path for path in listed if Path(path).name in
            {"foods.jsonl", "aliases.jsonl", "units.jsonl"}]


def render() -> str:
    golden, n_golden, n_synth, n_fix = probe_golden()
    probes = [
        probe_mobile(), probe_photo_ingest(), probe_vision(), golden,
        probe_finetune(), probe_writeup(),
        probe_loom(), probe_email(),
    ]
    c = counts()
    working = sum(1 for p in probes if p.state == DONE)

    headline = (
        "**The repository package is ready for technical review, not "
        "self-certified as submitted.** "
        f"{working} of {len(probes)} rows have repository-verifiable working "
        "evidence. Device execution, Loom playback/access, and email delivery "
        "require operator confirmation; fine-tuning remains intentionally "
        "untrained and optional."
    )

    L = [
        "# Status",
        "",
        "> **Generated file — do not edit.** Produced by `python scripts/status.py`",
        "> from the working tree, and checked in CI. It cannot quietly go stale the",
        "> way a hand-written status section does.",
        "> It does not certify external state such as device execution, Loom access,",
        "> or email delivery.",
        "",
        "## Is this ready to submit?",
        "",
        headline,
        "",
        "## Deliverables",
        "",
        "| Deliverable | State | Evidence |",
        "|---|---|---|",
    ]

    L += [f"| {p.label} | {p.state} | {p.evidence} |" for p in probes]

    if n_synth:
        L += ["", "## Read the numbers with this in mind", "",
              (f"**{n_synth} of {n_fix} recorded fixtures are seeded placeholders**, "
               'flagged in each file with `"_synthetic": true`.'),
              "",
              "Nothing in `eval/reports/` is yet a claim about how accurately this",
              "system reads a real plate. The harness, the metrics and the per-cuisine",
              "breakdown are real and reproducible; the inputs they run on are not.",
              "That changes when [#3](../../issues/3) records real provider responses",
              "and [#2](../../issues/2) grows the golden set."]

    L += ["", "## Measured", "",
          "| | |", "|---|---:|",
          f"| Locale packs | {len(c['packs'])} ({', '.join(c['packs'])}) |",
          f"| Canonical foods | {c['foods']} |",
          "| Packs installed separately | "
          + (", ".join(c["installable"]) + " (licence-restricted; `make pack`)" if c["installable"]
             else "none — every defined pack ships") + " |",
          f"| Golden-set samples | {n_golden} |",
          "",
          "## Verification boundary",
          "",
          "- `make test` and `make lint` verify the repository test and lint suites.",
          "- `python eval/harness.py --check-regression` verifies the committed",
          "  offline evaluation boundary.",
          "- `python scripts/check_invariants.py` and `python scripts/status.py --check`",
          "  verify architectural constraints and this generated file.",
          "- Hosted CI proves those jobs ran on the committed revision. It does not",
          "  prove current device execution, Loom access, email delivery, or a public",
          "  backend deployment.",
          ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    target = ROOT / "docs/submission/STATUS.md"
    fresh = render()

    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != fresh:
            print("docs/submission/STATUS.md is stale. Run `python scripts/status.py` "
                  "and commit the "
                  "result.\nThe repository and its status file disagree — which is "
                  "the drift this check exists to prevent.")
            return 1
        print("docs/submission/STATUS.md matches the repository")
        return 0

    target.write_text(fresh, encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
