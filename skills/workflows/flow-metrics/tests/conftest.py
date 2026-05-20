"""pytest config for flow-metrics.

Two responsibilities:

1. Put ``scripts/`` on ``sys.path`` so test files can ``import flow_metrics``.
2. Provide the ``integration_sandbox`` fixture that points the pipeline's
   upstream-discovery probe at the fixture-replay scripts under
   ``tests/fixtures/_replay/`` instead of the real ``jira`` / ``jira-align``
   skills. Every integration test MUST consume this fixture — the spec's
   test-isolation contract (plan line 1029-1033) forbids any test from
   shelling out to a real upstream skill.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPLAY_DIR = FIXTURES_DIR / "_replay"


class IntegrationSandbox:
    """Handle returned by the ``integration_sandbox`` fixture.

    Tests use :meth:`use_fixture` to pin a fixture directory (and the
    pipeline's discovery probe to the replay scripts), then call into
    :func:`flow_metrics.main`. The ``call_log_path`` attribute lets a
    test assert which upstream verbs / paths were invoked — the
    read-only allowlist regression check (plan risk line 1039-1042).
    """

    def __init__(
        self,
        fixture_dir: Path,
        call_log_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        self.fixture_dir = fixture_dir
        self.call_log_path = call_log_path
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path

    def use_fixture(self, name: str, *, cohort_marker: Optional[str] = None) -> "IntegrationSandbox":
        """Point the replay at ``fixtures/<name>/``.

        ``cohort_marker`` enables the cohort-search override: the replay
        returns ``search.cohort.jsonl`` instead of ``search.jsonl`` when
        the composed JQL contains the marker substring. Tests that don't
        exercise ``--cohort-jql`` pass ``cohort_marker=None``.
        """
        new_dir = FIXTURES_DIR / name
        assert new_dir.is_dir(), "no such fixture dir: {}".format(new_dir)
        self.fixture_dir = new_dir
        self.monkeypatch.setenv("FLOW_METRICS_TEST_FIXTURE_DIR", str(new_dir))
        if cohort_marker is None:
            self.monkeypatch.delenv("FLOW_METRICS_TEST_COHORT_MARKER", raising=False)
        else:
            self.monkeypatch.setenv("FLOW_METRICS_TEST_COHORT_MARKER", cohort_marker)
        # Truncate the call log between fixture switches.
        self.call_log_path.write_text("", encoding="utf-8")
        return self

    def call_log(self) -> list:
        """Return the list of recorded {skill, verb, args} dicts."""
        import json as _json
        if not self.call_log_path.is_file():
            return []
        out = []
        for line in self.call_log_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s:
                continue
            out.append(_json.loads(s))
        return out


@pytest.fixture
def integration_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[IntegrationSandbox]:
    """Spec-pinned test-isolation harness for the wired CLI.

    Sets ``FLOW_METRICS_JIRA_SCRIPT`` and ``FLOW_METRICS_JIRAALIGN_SCRIPT``
    to the replay shims under ``fixtures/_replay/``, **unsets** any real-
    skill credentials that might leak through (``JIRA_*``,
    ``JIRA_ALIGN_*``), pins a hermetic clock at ``2026-05-19T14:00:00Z``
    to match the spec-example fixture timestamp, and changes cwd to a
    per-test temp directory so cache writes stay scoped to the sandbox.

    The ``FLOW_METRICS_TEST_CALL_LOG`` env var points at a per-test log
    file so the integration tests can assert which upstream calls
    fired — the spec's read-only allowlist regression check rides on
    that log.
    """
    jira_script = REPLAY_DIR / "jira_replay.py"
    align_script = REPLAY_DIR / "jira_align_replay.py"
    assert jira_script.is_file(), "missing replay script: {}".format(jira_script)
    assert align_script.is_file(), "missing replay script: {}".format(align_script)

    monkeypatch.setenv("FLOW_METRICS_JIRA_SCRIPT", str(jira_script))
    monkeypatch.setenv("FLOW_METRICS_JIRAALIGN_SCRIPT", str(align_script))

    # Unset every credential-bearing env var the upstream skills would
    # consult. The replay doesn't read them, but a misconfigured test
    # that bypassed the sandbox would silently hit a real instance —
    # this strips that path out from under it.
    for var in (
        "JIRA_BASE_URL",
        "JIRA_USERNAME",
        "JIRA_API_TOKEN",
        "JIRA_PERSONAL_ACCESS_TOKEN",
        "JIRA_ALIGN_BASE_URL",
        "JIRA_ALIGN_API_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)

    # Hermetic clock — flow_metrics.clock.today_utc() is the only place
    # the pipeline reads the wall clock for meta.generated_at.
    import flow_metrics
    fixed = datetime(2026, 5, 19, 14, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(flow_metrics.clock, "today_utc", lambda: fixed)

    # Per-test cwd so cache writes (.context/flow-metrics/cache/) land in
    # tmp_path, not the developer's working tree.
    monkeypatch.chdir(tmp_path)

    call_log = tmp_path / "_calls.jsonl"
    call_log.write_text("", encoding="utf-8")
    monkeypatch.setenv("FLOW_METRICS_TEST_CALL_LOG", str(call_log))

    sandbox = IntegrationSandbox(
        fixture_dir=FIXTURES_DIR / "proj_alpha",
        call_log_path=call_log,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    yield sandbox
