"""T3 contract + construction tests for the upstream-skill wrappers.

Covers every test enumerated in docs/specs/flow-metrics-plan.md § T3
and the corresponding contract tests in docs/specs/flow-metrics.md
§ "Read-only contract — upstream-skill allowlist".

The wrapper is tested in isolation: ``subprocess.run`` /
``subprocess.Popen`` are monkeypatched in every test that exercises an
upstream invocation. No test ever spawns a real ``jira`` / ``jira-align``
process — per the plan, T3 is the substrate, not an integration gate.
"""
from __future__ import annotations

import ast
import builtins
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, List, Optional

import pytest

from flow_metrics import upstream as up
from flow_metrics.upstream import (
    AllowlistError,
    JiraAlignClient,
    JiraClient,
    JiraError,
    UpstreamNotFoundError,
    discover_skill_path,
    exit_code_for,
)


SKILL_ROOT = Path(__file__).resolve().parent.parent
FLOW_METRICS_PKG = SKILL_ROOT / "scripts" / "flow_metrics"


# ---------------------------------------------------------------------------
# Fakes for subprocess
# ---------------------------------------------------------------------------
class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _ClosableIter:
    """Iterator wrapper that exposes a ``close()`` method.

    The production wrapper closes ``proc.stdout`` before ``wait()`` to
    SIGPIPE the upstream subprocess on abort; tests need that close()
    call to succeed against the fake stdout too.
    """

    def __init__(self, source: Iterable[bytes]) -> None:
        self._it = iter(source)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        return next(self._it)

    def close(self) -> None:
        self.closed = True


class _FakePopen:
    """Minimal Popen stand-in: stdout is an iterable of bytes lines.

    Mirrors real ``subprocess.Popen`` semantics for stderr: the wrapper
    passes a file-like object as the ``stderr`` kwarg (a tempfile in
    production); a real subprocess would write its stderr to that fd.
    This fake does the same — it writes ``stderr_payload`` to the
    ``stderr`` kwarg if one was passed. Tests that want to assert on
    forwarded stderr therefore work regardless of whether the wrapper
    uses ``stderr=PIPE`` or ``stderr=<tempfile>``.
    """

    def __init__(
        self,
        argv: List[str],
        *,
        stdout_lines: Iterable[bytes] = (),
        stderr_payload: bytes = b"",
        returncode: int = 0,
        **kwargs: Any,
    ) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.stdout = _ClosableIter(stdout_lines)
        # Mirror real-subprocess stderr behavior: write payload to the
        # caller-supplied stderr fd / file object.
        stderr_target = kwargs.get("stderr")
        if stderr_payload and hasattr(stderr_target, "write"):
            stderr_target.write(stderr_payload)
        self.stderr_payload = stderr_payload  # for legacy assertions, if any
        self._rc = returncode
        self.returncode = None  # set by wait()
        self.waited = False

    def wait(self, timeout: Optional[float] = None) -> int:
        self.waited = True
        self.returncode = self._rc
        return self._rc

    def poll(self) -> Optional[int]:
        return self.returncode


def _install_fake_run(monkeypatch, factory):
    """Replace subprocess.run AND upstream._run_capture's subprocess.run.

    The wrapper imports ``subprocess`` at module load and calls
    ``subprocess.run`` qualified; patching the attribute on the
    subprocess module is sufficient.
    """
    calls: List[List[str]] = []
    captured_env: List[Optional[dict]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        captured_env.append(kw.get("env"))
        return factory(argv, kw)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls, captured_env


def _install_fake_popen(monkeypatch, factory):
    calls: List[List[str]] = []
    captured_env: List[Optional[dict]] = []

    def fake_popen(argv, **kw):
        calls.append(list(argv))
        captured_env.append(kw.get("env"))
        return factory(argv, kw)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls, captured_env


def _block_other(monkeypatch, name: str) -> None:
    """Raise if the wrapper accidentally uses the wrong subprocess API."""

    def boom(*a, **kw):
        raise AssertionError("unexpected subprocess.{} call: {}".format(name, a))

    monkeypatch.setattr(subprocess, name, boom)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def test_discovery_probes_in_order(tmp_path, monkeypatch):
    """env var > sibling > user-scope > cwd."""
    # Build four candidate locations under tmp_path; touch them one at a
    # time and assert the discovered path matches the highest-priority
    # existing file.
    env_target = tmp_path / "env_dir" / "jira.py"
    sibling_skill_root = tmp_path / "skills_root" / "flow-metrics"
    sibling_target = tmp_path / "skills_root" / "jira" / "scripts" / "jira.py"
    user_target = tmp_path / "home" / ".claude" / "skills" / "jira" / "scripts" / "jira.py"
    cwd_target = tmp_path / "work" / ".claude" / "skills" / "jira" / "scripts" / "jira.py"

    for p in (env_target, sibling_target, user_target, cwd_target):
        p.parent.mkdir(parents=True, exist_ok=True)

    # Patch _THIS_SKILL_DIR so "sibling" resolves under tmp_path.
    monkeypatch.setattr(up, "_THIS_SKILL_DIR", sibling_skill_root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    # No candidates exist → UpstreamNotFoundError, no env var.
    with pytest.raises(UpstreamNotFoundError):
        discover_skill_path("jira", env={}, cwd=tmp_path / "work")

    # Only project-scope exists.
    cwd_target.write_text("# jira cli")
    assert discover_skill_path("jira", env={}, cwd=tmp_path / "work") == cwd_target

    # User-scope wins over project.
    user_target.write_text("# jira cli")
    assert discover_skill_path("jira", env={}, cwd=tmp_path / "work") == user_target

    # Sibling wins over user.
    sibling_target.write_text("# jira cli")
    assert discover_skill_path("jira", env={}, cwd=tmp_path / "work") == sibling_target

    # Env var wins over everything.
    env_target.write_text("# jira cli")
    found = discover_skill_path(
        "jira",
        env={"FLOW_METRICS_JIRA_SCRIPT": str(env_target)},
        cwd=tmp_path / "work",
    )
    assert found == env_target


def test_discovery_not_found_exits_2(tmp_path, monkeypatch):
    """None of the four candidates exists → exit 2 naming each."""
    monkeypatch.setattr(up, "_THIS_SKILL_DIR", tmp_path / "nope" / "flow-metrics")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "homedoesntexist"))
    with pytest.raises(UpstreamNotFoundError) as ei:
        discover_skill_path("jira", env={}, cwd=tmp_path / "cwddoesntexist")
    msg = str(ei.value)
    # Sibling, user, and project candidates are each named in the
    # message. The sibling candidate is ``<skill-dir>/../jira/scripts/jira.py``
    # so the "nope" parent appears via ``nope/jira``.
    for substring in (
        os.sep + "nope" + os.sep + "jira" + os.sep,
        ".claude" + os.sep + "skills" + os.sep + "jira",
        "homedoesntexist",
        "cwddoesntexist",
    ):
        assert substring in msg, "missing {!r} in {!r}".format(substring, msg)
    # Exit-code helper agrees.
    assert exit_code_for(ei.value) == 2


def test_discovery_jira_align_env_var_uppercased_without_hyphen(tmp_path, monkeypatch):
    """``jira-align`` discovers via ``FLOW_METRICS_JIRAALIGN_SCRIPT``."""
    target = tmp_path / "ja" / "jira_align.py"
    target.parent.mkdir(parents=True)
    target.write_text("# stub")
    found = discover_skill_path(
        "jira-align",
        env={"FLOW_METRICS_JIRAALIGN_SCRIPT": str(target)},
        cwd=tmp_path,
    )
    assert found == target


def test_discovery_jira_align_sibling_uses_module_name(tmp_path, monkeypatch):
    """Sibling layout: ``../jira-align/scripts/jira_align.py``."""
    sibling_root = tmp_path / "skills_root" / "flow-metrics"
    target = tmp_path / "skills_root" / "jira-align" / "scripts" / "jira_align.py"
    target.parent.mkdir(parents=True)
    target.write_text("# stub")
    monkeypatch.setattr(up, "_THIS_SKILL_DIR", sibling_root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "noexist_home"))
    assert (
        discover_skill_path("jira-align", env={}, cwd=tmp_path / "noexist_cwd")
        == target
    )


def test_discovery_env_typo_falls_through_to_real_candidate(tmp_path, monkeypatch):
    """Env var pointing at a non-existent file should not pin discovery
    to a bogus path — fall through to the next real candidate."""
    sibling_root = tmp_path / "skills_root" / "flow-metrics"
    real_sibling = tmp_path / "skills_root" / "jira" / "scripts" / "jira.py"
    real_sibling.parent.mkdir(parents=True)
    real_sibling.write_text("# stub")
    monkeypatch.setattr(up, "_THIS_SKILL_DIR", sibling_root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "noexist"))
    found = discover_skill_path(
        "jira",
        env={"FLOW_METRICS_JIRA_SCRIPT": str(tmp_path / "typo.py")},
        cwd=tmp_path,
    )
    assert found == real_sibling


# ---------------------------------------------------------------------------
# Allowlist — jira
# ---------------------------------------------------------------------------
def test_only_allowlisted_jira_verbs_invoked(monkeypatch, tmp_path):
    """Every JiraClient public method routes through an allowlisted verb;
    every recorded subprocess argv's verb is in the spec's allowlist;
    every ``raw`` invocation is ``GET`` with a permitted path."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)

    calls, _ = _install_fake_run(
        monkeypatch,
        lambda argv, kw: _FakeCompleted(returncode=0, stdout=b'{"ok":true}'),
    )
    _install_fake_popen(
        monkeypatch,
        lambda argv, kw: _FakePopen(argv, stdout_lines=[b'{"k":1}\n']),
    )

    client.check()
    client.whoami()
    client.get_issue("PROJ-1", fields="summary", expand="changelog")
    client.get_project("PROJ")
    client.raw_get("field")
    client.raw_get("project/PROJ/statuses")
    client.raw_get("issue/PROJ-1/changelog", params={"startAt": "50"})
    # Drain the streaming generator so the subprocess actually fires.
    list(client.search("project = PROJ", page_size=50))

    invoked_verbs = set()
    raw_targets = []
    for argv in calls:
        # Skip --format / --output / "-" / sys.executable / script path.
        # Subcommand is the first arg that isn't a global flag value.
        # By construction it sits immediately after the global flags.
        idx = 2  # after [executable, script]
        while idx < len(argv) and argv[idx].startswith("--"):
            idx += 2  # skip "--flag value"
        verb = argv[idx] if idx < len(argv) else ""
        invoked_verbs.add(verb)
        if verb == "raw":
            method = argv[idx + 1]
            path = argv[idx + 2]
            assert method == "GET", "non-GET raw method recorded: {}".format(method)
            raw_targets.append(path)

    # Popen call for search: pull verb the same way.
    for popen_argv in subprocess.Popen.__wrapped__ if False else []:  # noqa: E501  (placeholder, see below)
        pass

    allowlist = {"check", "whoami", "get-issue", "search", "get-project", "raw"}
    assert invoked_verbs <= allowlist, "out-of-allowlist verb(s): {}".format(
        invoked_verbs - allowlist
    )
    assert "transition" not in invoked_verbs
    assert "create-issue" not in invoked_verbs

    # Every recorded raw path matches one of the three allowed patterns.
    permitted = [p.pattern for p in JiraClient._ALLOWED_RAW_PATTERNS]
    import re as _re

    for path in raw_targets:
        assert any(_re.match(p, path) for p in permitted), \
            "raw path {!r} matches none of {}".format(path, permitted)


def test_search_verb_recorded_in_popen_calls(monkeypatch, tmp_path):
    """The 'search' verb invocation goes through Popen, not run, so we
    record it on the Popen side and assert it is allowlisted."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    popen_calls, _ = _install_fake_popen(
        monkeypatch,
        lambda argv, kw: _FakePopen(argv, stdout_lines=[]),
    )
    # Block run() so we'd notice if search accidentally routed there.
    _block_other(monkeypatch, "run")
    list(client.search("project = PROJ"))
    assert len(popen_calls) == 1
    # search is in the allowlist.
    assert "search" in popen_calls[0]


@pytest.mark.parametrize(
    "bad_path",
    [
        "dashboard",
        "project/PROJ/components",
        "issue/PROJ-1/comments",
        "features/123",
        "programs/123/features",
        # Almost-matches that must still fail (anchored patterns):
        "field/",
        "field/123",
        "fieldfoo",
        "project/proj/statuses",  # lowercase
        "issue/PROJ-1/changelog/",  # trailing slash
        "project/PROJ/statuses/extra",
    ],
)
def test_raw_get_outside_allowed_patterns_blocked(monkeypatch, tmp_path, bad_path):
    """Every forbidden path raises AllowlistError even though verb is GET."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    # Block subprocess: AllowlistError must fire before any spawn.
    _block_other(monkeypatch, "run")
    _block_other(monkeypatch, "Popen")
    with pytest.raises(AllowlistError):
        client.raw_get(bad_path)


def test_attach_never_invoked(monkeypatch, tmp_path):
    """JiraClient exposes no ``attach`` method; any low-level dispatch
    to ``attach`` raises AllowlistError before subprocess spawn."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    # Public surface: no attach method.
    assert not hasattr(client, "attach")
    # Low-level dispatch refuses.
    _block_other(monkeypatch, "run")
    _block_other(monkeypatch, "Popen")
    with pytest.raises(AllowlistError):
        client._invoke(["attach", "PROJ-1", "--file", "/tmp/x"])


def test_upstream_jira_failure_exits_3(monkeypatch, capsys, tmp_path):
    """Mocked jira returns non-zero → JiraError; exit-code mapping is 3;
    stderr relayed verbatim to this process's stderr."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    _install_fake_run(
        monkeypatch,
        lambda argv, kw: _FakeCompleted(
            returncode=2, stdout=b"", stderr=b"auth failed for caller@example.com\n"
        ),
    )
    with pytest.raises(JiraError) as ei:
        client.check()
    assert ei.value.returncode == 2
    assert b"auth failed" in ei.value.stderr
    # Stderr was forwarded.
    captured = capsys.readouterr()
    assert "auth failed for caller@example.com" in captured.err
    # Exit-code mapping.
    assert exit_code_for(ei.value) == 3


# ---------------------------------------------------------------------------
# Allowlist — jira-align
# ---------------------------------------------------------------------------
def test_only_allowlisted_jira_align_verbs_invoked(monkeypatch, tmp_path):
    """jira-align allowlist: only raw GET on four exact patterns."""
    script = tmp_path / "jira_align.py"
    script.write_text("#")
    client = JiraAlignClient(script)
    calls, _ = _install_fake_run(
        monkeypatch,
        lambda argv, kw: _FakeCompleted(returncode=0, stdout=b'{"ok":true}'),
    )
    _block_other(monkeypatch, "Popen")

    client.raw_get("programs/42")
    client.raw_get("programs/42/teams")
    client.raw_get("portfolios/9")
    client.raw_get("portfolios/9/programs")

    for argv in calls:
        # After [executable, script, --format, json] comes the verb.
        idx = 4
        verb = argv[idx]
        assert verb == "raw"
        method = argv[idx + 1]
        path = argv[idx + 2]
        assert method == "GET"
        permitted = [p.pattern for p in JiraAlignClient._ALLOWED_RAW_PATTERNS]
        import re as _re

        assert any(_re.match(p, path) for p in permitted), (
            "jira-align raw path {!r} matches none of {}".format(path, permitted)
        )


@pytest.mark.parametrize(
    "bad_path",
    [
        "programs/42/features",
        "features/123",
        "portfolios/abc",  # non-numeric id
        "teams/1",
        "programs/42/teams/extra",
        "programs/",
        "PROGRAMS/42",  # case-sensitive
    ],
)
def test_jira_align_raw_get_outside_patterns_blocked(monkeypatch, tmp_path, bad_path):
    script = tmp_path / "jira_align.py"
    script.write_text("#")
    client = JiraAlignClient(script)
    _block_other(monkeypatch, "run")
    _block_other(monkeypatch, "Popen")
    with pytest.raises(AllowlistError):
        client.raw_get(bad_path)


def test_jira_align_exposes_only_raw_get(tmp_path):
    """No ``search`` / ``check`` / ``whoami`` / etc. on JiraAlignClient.

    Defends against future drift adding verbs without a spec update.
    """
    script = tmp_path / "jira_align.py"
    script.write_text("#")
    client = JiraAlignClient(script)
    public = {
        name for name in dir(client)
        if not name.startswith("_") and callable(getattr(client, name))
    }
    assert public == {"raw_get"}, "unexpected public surface: {}".format(public)


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
def test_search_streams_via_popen_not_run(monkeypatch, tmp_path):
    """``search`` uses Popen; ``run`` is never called for it. Memory bound:
    a 10k-row stream is consumed without ever materialising the full
    list in memory (verified via a lazy generator stand-in)."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)

    # If anyone calls subprocess.run for search, fail loudly.
    _block_other(monkeypatch, "run")

    # Track the high-water mark of "lines that have been pulled from
    # stdout but not yet consumed by the search iterator". This is a
    # proxy for peak memory: if the wrapper buffered every line into a
    # list before yielding, this would equal N. We expect it to stay at
    # 1 (the line currently being decoded).
    pulled = [0]
    consumed = [0]

    def gen_lines(n: int):
        for i in range(n):
            pulled[0] += 1
            yield ('{"key":"A-' + str(i) + '"}\n').encode("utf-8")

    fake_proc = _FakePopen(["fake"], stdout_lines=gen_lines(10_000))
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: fake_proc)

    high_water = 0
    for row in client.search("project = PROJ"):
        consumed[0] += 1
        delta = pulled[0] - consumed[0]
        if delta > high_water:
            high_water = delta

    assert consumed[0] == 10_000
    # The wrapper pulls one line, decodes it, yields, then the loop body
    # increments consumed[0] — so the delta stays bounded by a small
    # constant. Allowing slack for any internal buffering: bound at 4.
    assert high_water <= 4, "wrapper appears to buffer ({} ahead)".format(high_water)


def test_search_yields_one_dict_per_line(monkeypatch, tmp_path):
    """Mock stdout {"key":"A-1"}\\n{"key":"A-2"}\\n yields exactly two dicts in order."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    fake_proc = _FakePopen(
        ["fake"], stdout_lines=[b'{"key":"A-1"}\n', b'{"key":"A-2"}\n']
    )
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: fake_proc)
    _block_other(monkeypatch, "run")
    rows = list(client.search("project = PROJ"))
    assert rows == [{"key": "A-1"}, {"key": "A-2"}]


def test_search_skips_blank_lines(monkeypatch, tmp_path):
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    fake_proc = _FakePopen(
        ["fake"], stdout_lines=[b'\n', b'{"key":"A-1"}\n', b'   \n', b'{"key":"A-2"}\n']
    )
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: fake_proc)
    _block_other(monkeypatch, "run")
    rows = list(client.search("project = PROJ"))
    assert rows == [{"key": "A-1"}, {"key": "A-2"}]


def test_search_failure_after_drain_raises_jira_error(monkeypatch, capsys, tmp_path):
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda argv, **kw: _FakePopen(
            argv,
            stdout_lines=[b'{"key":"A-1"}\n'],
            stderr_payload=b"upstream choked\n",
            returncode=4,
            **kw,
        ),
    )
    _block_other(monkeypatch, "run")
    with pytest.raises(JiraError) as ei:
        list(client.search("project = PROJ"))
    assert ei.value.returncode == 4
    assert b"upstream choked" in ei.value.stderr
    captured = capsys.readouterr()
    assert "upstream choked" in captured.err
    assert exit_code_for(ei.value) == 3


# ---------------------------------------------------------------------------
# Subprocess hygiene
# ---------------------------------------------------------------------------
def test_jira_call_args_quoting(monkeypatch, tmp_path):
    """Args with spaces / quotes pass via list-form; never shell=True."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    seen_run_kwargs: List[dict] = []
    seen_popen_kwargs: List[dict] = []

    # Non-streaming: a get-issue carrying spaces/quotes in the key
    # arrives as a single argv element.
    weird_key = "PROJ-1 with 'quotes'"

    def fake_run(argv, **kw):
        seen_run_kwargs.append(kw)
        assert weird_key in argv, "tricky arg lost: {}".format(argv)
        # shell=True is forbidden by the spec.
        assert kw.get("shell") in (None, False), "shell=True forbidden"
        return _FakeCompleted(returncode=0, stdout=b"{}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _block_other(monkeypatch, "Popen")
    client.get_issue(weird_key)

    # Streaming: same property holds for Popen.
    tricky_jql = "project = PROJ AND assignee = 'a b'"

    def fake_popen(argv, **kw):
        seen_popen_kwargs.append(kw)
        assert tricky_jql in argv
        assert kw.get("shell") in (None, False), "shell=True forbidden"
        return _FakePopen(argv, stdout_lines=[])

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    list(client.search(tricky_jql))

    assert seen_run_kwargs and seen_popen_kwargs
    for kw in seen_run_kwargs + seen_popen_kwargs:
        assert kw.get("shell") in (None, False)


def test_jira_call_does_not_read_credentials_file(monkeypatch, tmp_path):
    """flow-metrics' own process must never open ~/.config/dropkit/credentials.env.

    The upstream subprocess (a separate process) may read it; this
    contract only covers in-process file opens, verified by tapping
    ``builtins.open``.
    """
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    opened: List[str] = []
    real_open = builtins.open

    def tracking_open(path, *a, **kw):
        opened.append(str(path))
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", tracking_open)

    # Wire fake subprocess so the call actually runs.
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: _FakeCompleted(returncode=0, stdout=b'{"ok":true}'),
    )
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda argv, **kw: _FakePopen(argv, stdout_lines=[b'{"k":1}\n']),
    )

    client.check()
    client.raw_get("field")
    list(client.search("project = PROJ"))

    forbidden = "credentials.env"
    matches = [p for p in opened if forbidden in p]
    assert not matches, "wrapper opened credentials file(s): {}".format(matches)


def test_subprocess_inherits_full_env(monkeypatch, tmp_path):
    """The subprocess env must be the parent's full os.environ — no
    filter that strips JIRA_* / JIRA_ALIGN_* credentials env vars.

    Verified by setting a sentinel in the parent and asserting it
    reaches the captured env kwarg passed to subprocess.
    """
    script = tmp_path / "jira.py"
    script.write_text("#")
    sentinel = "FLOW_METRICS_T3_SENTINEL_{}".format(os.getpid())
    monkeypatch.setenv(sentinel, "ok")
    monkeypatch.setenv("JIRA_API_TOKEN", "fake-token-not-real")

    # Non-streaming.
    client = JiraClient(script)
    _, run_envs = _install_fake_run(
        monkeypatch,
        lambda argv, kw: _FakeCompleted(returncode=0, stdout=b"{}"),
    )
    client.check()
    assert run_envs, "no run env captured"
    env = run_envs[-1]
    assert env is not None, "subprocess.run must pass an explicit env (got None)"
    assert env.get(sentinel) == "ok"
    assert env.get("JIRA_API_TOKEN") == "fake-token-not-real"

    # Streaming.
    _, popen_envs = _install_fake_popen(
        monkeypatch,
        lambda argv, kw: _FakePopen(argv, stdout_lines=[]),
    )
    list(client.search("project = PROJ"))
    assert popen_envs[-1] is not None
    assert popen_envs[-1].get(sentinel) == "ok"
    assert popen_envs[-1].get("JIRA_API_TOKEN") == "fake-token-not-real"


def test_no_subprocess_calls_outside_upstream_module():
    """Static AST scan: no file in flow_metrics/ outside upstream.py
    imports ``subprocess`` or calls ``subprocess.*``.

    Prevents future code from bypassing the allowlist wrapper.
    """
    offenders: List[str] = []
    for py_path in FLOW_METRICS_PKG.rglob("*.py"):
        if py_path.name == "upstream.py":
            continue
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        except SyntaxError as e:
            offenders.append("{}: parse error {}".format(py_path, e))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess" or alias.name.startswith("subprocess."):
                        offenders.append("{}: import {}".format(py_path, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "subprocess" or node.module.startswith("subprocess.")):
                    offenders.append("{}: from {} import ...".format(py_path, node.module))
            elif isinstance(node, ast.Attribute):
                # subprocess.run / subprocess.Popen / etc.
                v = node.value
                if isinstance(v, ast.Name) and v.id == "subprocess":
                    offenders.append("{}:{} subprocess.{}".format(py_path, node.lineno, node.attr))
    assert not offenders, "subprocess usage outside upstream.py:\n  " + "\n  ".join(offenders)


def test_flow_metrics_stderr_forwarded_on_success(monkeypatch, capsys, tmp_path):
    """On exit 0, the upstream's stderr (e.g. permission-undercount note)
    still appears on this skill's stderr."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: _FakeCompleted(
            returncode=0,
            stdout=b'{"ok":true}',
            stderr=b"permissions: 3 issues are inaccessible to the caller\n",
        ),
    )
    _block_other(monkeypatch, "Popen")
    client.check()
    captured = capsys.readouterr()
    assert "permissions: 3 issues are inaccessible to the caller" in captured.err


def test_stream_stderr_forwarded_on_success(monkeypatch, capsys, tmp_path):
    """Streaming path forwards stderr on success too."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    # Forward **kw so _FakePopen can mirror the stderr_payload into the
    # wrapper's stderr=tempfile kwarg, the way a real subprocess would.
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda argv, **kw: _FakePopen(
            argv,
            stdout_lines=[b'{"k":1}\n'],
            stderr_payload=b"note: 0 issues found\n",
            returncode=0,
            **kw,
        ),
    )
    _block_other(monkeypatch, "run")
    list(client.search("project = PROJ"))
    captured = capsys.readouterr()
    assert "note: 0 issues found" in captured.err


# ---------------------------------------------------------------------------
# Argv shape — sanity checks on the argv the wrapper composes
# ---------------------------------------------------------------------------
def test_jira_search_argv_has_jsonl_and_dash_output(monkeypatch, tmp_path):
    """Streaming verb invokes jira.py with ``--format jsonl --output -``."""
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    captured = []

    def fake_popen(argv, **kw):
        captured.append(list(argv))
        return _FakePopen(argv, stdout_lines=[])

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    _block_other(monkeypatch, "run")
    list(client.search("project = PROJ", fields="summary", expand="changelog", page_size=100))
    argv = captured[0]
    assert "--format" in argv and "jsonl" in argv
    assert "--output" in argv and "-" in argv
    # search subcommand and its args present.
    assert "search" in argv
    assert "project = PROJ" in argv
    assert "--fields" in argv and "summary" in argv
    assert "--expand" in argv and "changelog" in argv
    assert "--page-size" in argv and "100" in argv


def test_jira_raw_get_argv_carries_params(monkeypatch, tmp_path):
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    captured = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: captured.append(list(argv)) or _FakeCompleted(stdout=b"{}"),
    )
    _block_other(monkeypatch, "Popen")
    client.raw_get("issue/PROJ-1/changelog", params={"startAt": "50"})
    argv = captured[0]
    assert "raw" in argv and "GET" in argv and "issue/PROJ-1/changelog" in argv
    assert "--param" in argv
    assert "startAt=50" in argv


# ---------------------------------------------------------------------------
# Deadlock-prevention invariants — locked in by regression tests so a
# future "simplification" can't reintroduce the stderr=PIPE deadlock.
# ---------------------------------------------------------------------------
def test_search_uses_tempfile_for_stderr_not_pipe(monkeypatch, tmp_path):
    """The streaming path passes a writable file object (not ``PIPE``) as
    ``stderr`` to Popen. Reverting to ``stderr=subprocess.PIPE`` would
    re-introduce the pipe-buffer deadlock the wrapper was designed to
    avoid: a verbose upstream blocked on a full stderr pipe never
    finishes, and our ``proc.wait()`` deadlocks behind it.
    """
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    captured_kwargs: List[dict] = []

    def fake_popen(argv, **kw):
        captured_kwargs.append(kw)
        return _FakePopen(argv, stdout_lines=[], **kw)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    _block_other(monkeypatch, "run")
    list(client.search("project = PROJ"))

    assert captured_kwargs, "Popen was never invoked"
    stderr_arg = captured_kwargs[0].get("stderr")
    assert stderr_arg is not subprocess.PIPE, (
        "search() must NOT use stderr=PIPE — that re-introduces the "
        "pipe-buffer deadlock the tempfile design fixed."
    )
    # The tempfile object exposes a write/seek/read API.
    for method in ("write", "seek", "read"):
        assert hasattr(stderr_arg, method), (
            "stderr arg should be a writable file-like; missing {!r}".format(method)
        )


def test_search_drains_large_stderr_without_deadlock(monkeypatch, capsys, tmp_path):
    """Simulate an upstream that writes >256 KiB to stderr — far above
    the OS pipe buffer (typically 16-64 KiB). With the old ``PIPE``
    design this would deadlock; with the tempfile design it drains
    cleanly and forwards the full payload.
    """
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)
    big_stderr = (b"x" * 1024 + b"\n") * 256  # 256 KiB
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda argv, **kw: _FakePopen(
            argv,
            stdout_lines=[b'{"k":1}\n'],
            stderr_payload=big_stderr,
            returncode=0,
            **kw,
        ),
    )
    _block_other(monkeypatch, "run")
    rows = list(client.search("project = PROJ"))
    assert rows == [{"k": 1}]
    captured = capsys.readouterr()
    # Full payload (or its decoded equivalent) reaches stderr — the
    # fact that we got here at all is the deadlock check.
    assert len(captured.err) >= len(big_stderr) - 16  # decode slack


def test_search_closes_stdout_before_wait(monkeypatch, tmp_path):
    """Ordering invariant: ``proc.stdout.close()`` happens before
    ``proc.wait()`` so an upstream still trying to emit rows after a
    consumer abort receives SIGPIPE and exits instead of blocking us
    forever on ``wait()``.
    """
    script = tmp_path / "jira.py"
    script.write_text("#")
    client = JiraClient(script)

    sequence: List[str] = []

    class _OrderingFakePopen(_FakePopen):
        def wait(self, timeout=None):
            sequence.append("wait")
            return super().wait(timeout)

    class _OrderingStdout(_ClosableIter):
        def close(self):
            sequence.append("close")
            super().close()

    def fake_popen(argv, **kw):
        fp = _OrderingFakePopen(argv, stdout_lines=[b'{"k":1}\n'], **kw)
        fp.stdout = _OrderingStdout([b'{"k":1}\n'])
        return fp

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    _block_other(monkeypatch, "run")
    list(client.search("project = PROJ"))
    assert sequence == ["close", "wait"], (
        "stdout must close before wait(); saw {}".format(sequence)
    )


# ---------------------------------------------------------------------------
# Exit-code mapping helper
# ---------------------------------------------------------------------------
def test_exit_code_mapping():
    assert exit_code_for(JiraError(1, b"")) == 3
    assert exit_code_for(AllowlistError("nope")) == 2
    assert exit_code_for(UpstreamNotFoundError("jira", [Path("/nope")])) == 2
    with pytest.raises(TypeError):
        exit_code_for(ValueError("unrelated"))


# ---------------------------------------------------------------------------
# main() wiring: exit codes for AllowlistError / JiraError / UpstreamNotFound
# ---------------------------------------------------------------------------
def test_main_catches_allowlist_error(monkeypatch, capsys):
    """main() maps AllowlistError raised inside its try-block to exit 2."""
    import flow_metrics

    def boom(*a, **kw):
        raise AllowlistError("blocked verb")

    # Replace validate_args so the AllowlistError is raised inside the
    # try-block at exactly the seam main() guards.
    monkeypatch.setattr(flow_metrics, "validate_args", boom)
    rc = flow_metrics.main(["--project", "P"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "blocked verb" in captured.err


def test_main_catches_jira_error(monkeypatch):
    import flow_metrics

    def boom(*a, **kw):
        raise JiraError(2, b"auth failed\n")

    monkeypatch.setattr(flow_metrics, "validate_args", boom)
    rc = flow_metrics.main(["--project", "P"])
    assert rc == 3


def test_main_catches_upstream_not_found(monkeypatch, capsys):
    import flow_metrics

    def boom(*a, **kw):
        raise UpstreamNotFoundError("jira", [Path("/no/such")])

    monkeypatch.setattr(flow_metrics, "validate_args", boom)
    rc = flow_metrics.main(["--project", "P"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "jira" in captured.err
    assert "/no/such" in captured.err
