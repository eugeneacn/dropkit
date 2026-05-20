"""Regenerate golden files for integration tests against synthetic fixtures.

WARNING — this script BYPASSES the contract gate. The integration suite
exists precisely to catch silent output drift; regenerating the goldens
unconditionally erases that signal. Run this only when the implementation
has *legitimately* changed output (e.g., a spec update bumps the wire
format) and the new output has been hand-reviewed.

Fixtures themselves (search.jsonl, changelog/*.json, align/*.json,
whoami.json, ...) are hand-edited; this script never regenerates them.

Usage:

    python tests/regen_goldens.py                # regen all goldens
    python tests/regen_goldens.py proj_alpha     # regen only this fixture

Run from the skill root (``skills/workflows/flow-metrics/``). The script
invokes the wired ``flow_metrics.main`` directly — no subprocess — so the
clock is hermetically pinned to the same instant the integration tests
use (``2026-05-19T14:00:00Z``).
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent / "scripts"
FIXTURES_DIR = HERE / "fixtures"
REPLAY_DIR = FIXTURES_DIR / "_replay"

sys.path.insert(0, str(SCRIPTS_DIR))

import flow_metrics  # noqa: E402
from flow_metrics import main as cli_main  # noqa: E402


_GENERATED_AT_PLACEHOLDER = "__GENERATED_AT__"
# Match _substitute_generated_at in test_integration.py — scope the
# substitution to the pinned-clock value so per-issue timestamps survive.
_PINNED_GENERATED_AT_BYTES = b"2026-05-19T14:00:00Z"


def _substitute(payload: bytes) -> bytes:
    return payload.replace(
        _PINNED_GENERATED_AT_BYTES,
        _GENERATED_AT_PLACEHOLDER.encode("ascii"),
    )


def _setup_sandbox(fixture_dir: Path, *, cohort_marker: Optional[str] = None, tmp_root: Path):
    """Mirror conftest.IntegrationSandbox setup at module level."""
    os.environ["FLOW_METRICS_JIRA_SCRIPT"] = str(REPLAY_DIR / "jira_replay.py")
    os.environ["FLOW_METRICS_JIRAALIGN_SCRIPT"] = str(REPLAY_DIR / "jira_align_replay.py")
    os.environ["FLOW_METRICS_TEST_FIXTURE_DIR"] = str(fixture_dir)
    if cohort_marker:
        os.environ["FLOW_METRICS_TEST_COHORT_MARKER"] = cohort_marker
    else:
        os.environ.pop("FLOW_METRICS_TEST_COHORT_MARKER", None)
    for var in (
        "JIRA_BASE_URL", "JIRA_USERNAME", "JIRA_API_TOKEN",
        "JIRA_PERSONAL_ACCESS_TOKEN",
        "JIRA_ALIGN_BASE_URL", "JIRA_ALIGN_API_TOKEN",
    ):
        os.environ.pop(var, None)

    fixed = datetime(2026, 5, 19, 14, 0, 0, tzinfo=timezone.utc)
    flow_metrics.clock.today_utc = lambda: fixed  # type: ignore[assignment]

    os.chdir(tmp_root)


def _run_capture(argv: list) -> bytes:
    """Run main(argv); return stdout bytes. Stderr is forwarded."""
    stdout_buf = io.BytesIO()

    class _BytesStdout(io.TextIOBase):
        def __init__(self, buf):
            self._buf = buf

        @property
        def buffer(self):
            return self._buf

        def write(self, s):
            if isinstance(s, str):
                self._buf.write(s.encode("utf-8"))
            else:
                self._buf.write(s)
            return len(s)

        def flush(self):
            pass

    real_stdout = sys.stdout
    sys.stdout = _BytesStdout(stdout_buf)
    try:
        rc = cli_main(argv)
    finally:
        sys.stdout = real_stdout
    if rc != 0:
        sys.stderr.write("WARNING: cli_main exited {} for argv={}\n".format(rc, argv))
    return stdout_buf.getvalue()


def regen_proj_alpha(tmp_root: Path) -> None:
    fdir = FIXTURES_DIR / "proj_alpha"

    # Default JSON output
    _setup_sandbox(fdir, tmp_root=tmp_root)
    out = _run_capture([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--no-cache",
    ])
    (fdir / "golden.json").write_bytes(_substitute(out))

    # Cohort variant
    _setup_sandbox(fdir, cohort_marker="labels = ai-assisted", tmp_root=tmp_root)
    out = _run_capture([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--cohort-jql", "labels = ai-assisted",
        "--no-cache",
    ])
    (fdir / "golden.cohort.json").write_bytes(_substitute(out))

    # Metrics filter variant
    _setup_sandbox(fdir, tmp_root=tmp_root)
    out = _run_capture([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--metrics", "throughput,cycle_time",
        "--no-cache",
    ])
    (fdir / "golden.metrics_filter.json").write_bytes(_substitute(out))

    # CSV variant
    _setup_sandbox(fdir, tmp_root=tmp_root)
    out = _run_capture([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--format", "csv",
        "--no-cache",
    ])
    (fdir / "golden.csv").write_bytes(_substitute(out))

    # Per-issue JSONL (writes to file; we copy its bytes into the golden)
    _setup_sandbox(fdir, tmp_root=tmp_root)
    out_path = tmp_root / "per_issue_regen.jsonl"
    if out_path.exists():
        out_path.unlink()
    _run_capture([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--per-issue",
        "--output", str(out_path),
        "--yes",
        "--no-cache",
    ])
    (fdir / "golden.per_issue.jsonl").write_bytes(_substitute(out_path.read_bytes()))


def regen_program_42(tmp_root: Path) -> None:
    fdir = FIXTURES_DIR / "program_42"
    if not fdir.is_dir():
        sys.stderr.write("regen_goldens: skipping program_42 — fixture dir missing\n")
        return

    _setup_sandbox(fdir, tmp_root=tmp_root)
    out = _run_capture([
        "--program-id", "42",
        "--align-join-field", "customfield_10001",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--no-cache",
    ])
    (fdir / "golden.json").write_bytes(_substitute(out))

    # Array-kind variant — same data, different team_field.kind.
    _setup_sandbox(fdir, tmp_root=tmp_root)
    out = _run_capture([
        "--program-id", "42",
        "--align-join-field", "customfield_10001",
        "--state-config", str(fdir / "state.array.json"),
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--no-cache",
    ])
    (fdir / "golden.array.json").write_bytes(_substitute(out))


def main() -> int:
    targets = set(sys.argv[1:]) or {"proj_alpha", "program_42"}
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_root = Path(td)
        if "proj_alpha" in targets:
            print("regenerating proj_alpha goldens ...")
            regen_proj_alpha(tmp_root)
        if "program_42" in targets:
            print("regenerating program_42 goldens ...")
            regen_program_42(tmp_root)
    print("done. Re-run pytest to confirm byte-equality.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
