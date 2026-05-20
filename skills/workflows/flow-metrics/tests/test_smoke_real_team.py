"""T13 smoke test against one real team's recorded fixture.

Per spec § "Manual verification gate" (plan line 962-964) and brief:

> Per-team smoke test passes against one real team's recorded fixture
> with hand-computed reference values for cycle time, lead time,
> throughput, rework rate, cancelled count, to within ±1%.

This file ships in T13 as **scaffolding**. The real-team fixture itself
is gated on the user supplying anonymised data (real PII / internal
issue keys aren't checked in). If no fixture is present, every test
in this module is skipped with a clear message — the build still passes
the 9-combo matrix, and the smoke gate gets ticked in a follow-up PR
when the fixture lands.

Fixture layout (when supplied):

- ``tests/fixtures/smoke_real_team/whoami.json``,
  ``search.jsonl``, ``changelog/<KEY>.<token>.json`` — same shape as
  ``proj_alpha`` / ``program_42``, anonymised per the brief
  ("no real assignee names, no internal issue keys — replace with
  PROJ-001, etc.").
- ``tests/fixtures/smoke_real_team/reference_values.json`` — hand-computed
  ground truth, keyed by contract metric (``cycle_time_p50``,
  ``cycle_time_p75``, ``cycle_time_p90``, ``lead_time_p50``,
  ``throughput``, ``rework_rate``, ``cancelled_count``).
- ``tests/fixtures/smoke_real_team/SHOW_YOUR_WORK.md`` — markdown
  derivation of each reference number, line-by-line from the issue list.
- ``tests/fixtures/smoke_real_team/invocation.json`` — the exact CLI
  arguments the smoke test should pass (``--project``, ``--from``,
  ``--to``, etc.). Avoids embedding scope details in this file so the
  test is fixture-driven.

Stdlib only.
"""
from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from flow_metrics import main as cli_main


SMOKE_DIR = Path(__file__).resolve().parent / "fixtures" / "smoke_real_team"
TOLERANCE = 0.01  # ±1% per spec


def _smoke_files_present() -> bool:
    return (
        SMOKE_DIR.is_dir()
        and (SMOKE_DIR / "search.jsonl").is_file()
        and (SMOKE_DIR / "reference_values.json").is_file()
        and (SMOKE_DIR / "invocation.json").is_file()
    )


pytestmark = pytest.mark.skipif(
    not _smoke_files_present(),
    reason=(
        "smoke_real_team fixture not supplied — see "
        "tests/test_smoke_real_team.py docstring for layout. "
        "T13 ships the synthetic suite + CI matrix; the real-team smoke "
        "gate lands in a follow-up PR once the user provides the fixture."
    ),
)


def _run_cli(argv):
    """Run main(argv); return rc + JSON-parsed stdout dict."""
    stdout_buf = io.BytesIO()
    stderr_buf = io.StringIO()

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
        with redirect_stderr(stderr_buf):
            rc = cli_main(argv)
    finally:
        sys.stdout = real_stdout
    return rc, json.loads(stdout_buf.getvalue().decode("utf-8")) if stdout_buf.getvalue() else None, stderr_buf.getvalue()


def _within_tolerance(actual, expected, label):
    if actual is None and expected is None:
        return
    assert actual is not None, "{}: expected {}, got None".format(label, expected)
    assert expected is not None, "{}: expected None, got {}".format(label, actual)
    if expected == 0:
        # Avoid divide-by-zero; require exact match when reference is 0.
        assert actual == 0, "{}: expected 0, got {}".format(label, actual)
        return
    rel = abs(actual - expected) / abs(expected)
    assert rel <= TOLERANCE, "{}: {} not within ±{:.1%} of {} (rel diff {:.2%})".format(
        label, actual, TOLERANCE, expected, rel
    )


@pytest.fixture
def smoke_sandbox(integration_sandbox):
    """Reuse the integration_sandbox setup but point at smoke_real_team."""
    integration_sandbox.use_fixture("smoke_real_team")
    return integration_sandbox


def test_smoke_real_team_metrics_within_tolerance(smoke_sandbox):
    """Run the smoke fixture's CLI invocation and assert every contract
    metric lands within ±1% of its hand-computed reference."""
    invocation = json.loads((SMOKE_DIR / "invocation.json").read_text(encoding="utf-8"))
    argv = list(invocation.get("argv", []))
    # Force --no-cache so the smoke run never sees a stale cache from a
    # prior invocation against a different fixture.
    if "--no-cache" not in argv:
        argv.append("--no-cache")

    rc, payload, stderr = _run_cli(argv)
    assert rc == 0, "smoke run exited {}; stderr={}".format(rc, stderr)
    assert payload is not None

    refs = json.loads((SMOKE_DIR / "reference_values.json").read_text(encoding="utf-8"))
    agg = payload.get("aggregates", {})

    # cycle_time p50/p75/p90
    cycle = agg.get("cycle_time_hours") or {}
    _within_tolerance(cycle.get("p50"), refs.get("cycle_time_p50"), "cycle_time.p50")
    _within_tolerance(cycle.get("p75"), refs.get("cycle_time_p75"), "cycle_time.p75")
    _within_tolerance(cycle.get("p90"), refs.get("cycle_time_p90"), "cycle_time.p90")

    # lead_time p50
    lead = agg.get("lead_time_hours") or {}
    _within_tolerance(lead.get("p50"), refs.get("lead_time_p50"), "lead_time.p50")

    # throughput, rework_rate, defect_ratio, cancelled count (cancelled is
    # in notes; we don't expose it on aggregates directly — pull from the
    # in-window notes line or store a derived counter on the smoke side).
    _within_tolerance(
        agg.get("throughput"), refs.get("throughput"), "throughput"
    )
    _within_tolerance(
        agg.get("rework_rate"), refs.get("rework_rate"), "rework_rate"
    )
    _within_tolerance(
        agg.get("defect_ratio"), refs.get("defect_ratio"), "defect_ratio"
    )

    # Cancelled count surfaces as a notes line; extract via regex.
    cancelled_ref = refs.get("cancelled_count")
    if cancelled_ref is not None:
        notes = payload.get("notes") or []
        m = next(
            (re.match(r"^(\d+) issues cancelled in window", n) for n in notes if "cancelled" in n),
            None,
        )
        actual = int(m.group(1)) if m else 0
        _within_tolerance(actual, cancelled_ref, "cancelled_count")
