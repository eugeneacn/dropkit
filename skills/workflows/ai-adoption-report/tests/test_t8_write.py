"""T8 contract tests for write.py + CLI write-dispatch.

Covers every test from plan §T8 (collision, both-format collision,
format-json skips Markdown render) plus the implied tests from the T8
task brief (overwrite replaces, atomic-no-partial, sidecar derivation,
format dispatch, env-var generated_at, byte-identical rerun, path safety).

Most tests drive the CLI via ``main(argv)`` so the dispatch + render +
write pipeline is exercised end-to-end. A handful of unit tests poke
:func:`write_outputs` and :func:`derive_sidecar_path` directly.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import ai_adoption_report
from ai_adoption_report import ValidationError, main
from ai_adoption_report.write import (
    GENERATED_AT_ENV_VAR,
    derive_sidecar_path,
    write_outputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "inputs"


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return rc, out.getvalue(), err.getvalue()


def _seed_baseline_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the alpha baseline+current fixtures into ``tmp_path`` so
    validate_local_path (CWD-bound) accepts them.

    Returns ``(baseline_path, current_path)``.
    """
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    shutil.copy(FIXTURES / "baseline_q1_alpha.json", baseline)
    shutil.copy(FIXTURES / "current_q2_alpha.json", current)
    return baseline, current


def _baseline_argv(tmp_path: Path, out: str = "report.md", *extra) -> list[str]:
    baseline, current = _seed_baseline_inputs(tmp_path)
    return [
        "baseline",
        "--baseline", baseline.name,
        "--current", current.name,
        "--output", out,
        *extra,
    ]


@pytest.fixture(autouse=True)
def _clear_generated_at_env(monkeypatch):
    """Tests that pin generated_at set it explicitly; clear by default
    so a stray export in the developer's shell doesn't taint baselines.
    """
    monkeypatch.delenv(GENERATED_AT_ENV_VAR, raising=False)


# ---------------------------------------------------------------------------
# derive_sidecar_path: parametrised rule coverage
# ---------------------------------------------------------------------------
def test_sidecar_path_md_to_json(tmp_path):
    assert derive_sidecar_path(tmp_path / "report.md") == tmp_path / "report.json"


def test_sidecar_path_no_extension(tmp_path):
    assert derive_sidecar_path(tmp_path / "report") == tmp_path / "report.json"


def test_sidecar_path_json_extension_raises(tmp_path):
    with pytest.raises(ValidationError) as exc:
        derive_sidecar_path(tmp_path / "report.json")
    msg = str(exc.value)
    assert "--output is treated as the Markdown-shaped path" in msg
    assert "report.json" in msg


def test_sidecar_path_unusual_extension_preserved(tmp_path):
    """An unusual extension like ``.txt`` is preserved: the sidecar
    appends ``.json`` to the full name rather than replacing the suffix.
    """
    assert (
        derive_sidecar_path(tmp_path / "report.txt")
        == tmp_path / "report.txt.json"
    )


def test_sidecar_path_uppercase_json_rejected(tmp_path):
    """Suffix detection is case-insensitive: ``.JSON`` is also rejected
    so a macOS user typing ``REPORT.JSON`` doesn't slip past the rule.
    """
    with pytest.raises(ValidationError) as exc:
        derive_sidecar_path(tmp_path / "report.JSON")
    assert "--output is treated as the Markdown-shaped path" in str(exc.value)


def test_sidecar_path_uppercase_md_maps_to_lowercase_json(tmp_path):
    """``.MD`` is recognised as Markdown; the derived sidecar uses the
    canonical lowercase ``.json`` suffix.
    """
    assert (
        derive_sidecar_path(tmp_path / "report.MD")
        == tmp_path / "report.json"
    )


# ---------------------------------------------------------------------------
# write_outputs: direct unit tests
# ---------------------------------------------------------------------------
def test_write_outputs_creates_file(tmp_path):
    target = tmp_path / "out.md"
    write_outputs([(target, "hello\n")], overwrite=False)
    assert target.read_text() == "hello\n"


def test_write_outputs_collision_no_overwrite_raises(tmp_path):
    target = tmp_path / "out.md"
    target.write_text("ORIGINAL")
    with pytest.raises(ValidationError) as exc:
        write_outputs([(target, "NEW")], overwrite=False)
    assert "use --overwrite" in str(exc.value)
    assert str(target) in str(exc.value)
    # Pre-flight: original bytes untouched.
    assert target.read_text() == "ORIGINAL"


def test_write_outputs_collision_message_lists_all_paths(tmp_path):
    """Both .md and .json pre-exist; the error must name BOTH."""
    md = tmp_path / "out.md"
    js = tmp_path / "out.json"
    md.write_text("A")
    js.write_text("B")
    with pytest.raises(ValidationError) as exc:
        write_outputs([(md, "NEW_MD"), (js, "NEW_JSON")], overwrite=False)
    msg = str(exc.value)
    assert str(md) in msg
    assert str(js) in msg
    # Neither file was touched (pre-flight runs before any write).
    assert md.read_text() == "A"
    assert js.read_text() == "B"


def test_write_outputs_overwrite_replaces(tmp_path):
    target = tmp_path / "out.md"
    target.write_text("ORIGINAL")
    write_outputs([(target, "NEW")], overwrite=True)
    assert target.read_text() == "NEW"


def test_write_outputs_empty_targets_is_noop(tmp_path):
    # No-op: must not raise even when overwrite=False.
    write_outputs([], overwrite=False)


def test_write_outputs_leaves_no_tmp_files_behind(tmp_path):
    """After a successful write the .tmp sibling must be gone."""
    target = tmp_path / "out.md"
    write_outputs([(target, "x")], overwrite=False)
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Plan-pinned: overwrite collision exits 2 without flag
# ---------------------------------------------------------------------------
def test_overwrite_collision_exits_2_without_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pre_existing = tmp_path / "report.md"
    pre_existing.write_bytes(b"PRE-EXISTING BYTES")

    rc, _, err = _run(_baseline_argv(tmp_path, "report.md", "--format", "markdown"))
    assert rc == 2
    assert "use --overwrite" in err
    # Bytes unchanged.
    assert pre_existing.read_bytes() == b"PRE-EXISTING BYTES"


# ---------------------------------------------------------------------------
# Plan-pinned: --format=both checks both files; error names all colliders
# ---------------------------------------------------------------------------
def test_collision_both_format_only_md_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    md = tmp_path / "report.md"
    js = tmp_path / "report.json"
    md.write_bytes(b"MD-ORIG")
    rc, _, err = _run(_baseline_argv(tmp_path, "report.md"))
    assert rc == 2
    assert md.read_bytes() == b"MD-ORIG"
    assert not js.exists()


def test_collision_both_format_only_json_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    md = tmp_path / "report.md"
    js = tmp_path / "report.json"
    js.write_bytes(b"JSON-ORIG")
    rc, _, err = _run(_baseline_argv(tmp_path, "report.md"))
    assert rc == 2
    assert js.read_bytes() == b"JSON-ORIG"
    assert not md.exists()


def test_collision_both_format_both_exist_lists_both(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    md = tmp_path / "report.md"
    js = tmp_path / "report.json"
    md.write_bytes(b"MD-ORIG")
    js.write_bytes(b"JSON-ORIG")
    rc, _, err = _run(_baseline_argv(tmp_path, "report.md"))
    assert rc == 2
    assert "report.md" in err
    assert "report.json" in err
    # Pre-flight: neither file modified.
    assert md.read_bytes() == b"MD-ORIG"
    assert js.read_bytes() == b"JSON-ORIG"


# ---------------------------------------------------------------------------
# Plan-pinned: --format=json skips Markdown render
# ---------------------------------------------------------------------------
def test_format_json_skips_markdown_render(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def boom(*a, **kw):
        raise AssertionError("render_markdown must NOT run under --format=json")

    monkeypatch.setattr("ai_adoption_report.render.render_markdown", boom)

    rc, _, err = _run(_baseline_argv(tmp_path, "report.md", "--format", "json"))
    assert rc == 0, err
    # Only the JSON sidecar exists; the .md was never written.
    assert (tmp_path / "report.json").exists()
    assert not (tmp_path / "report.md").exists()


# ---------------------------------------------------------------------------
# Implied: --overwrite replaces existing file
# ---------------------------------------------------------------------------
def test_overwrite_flag_replaces_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "report.md"
    target.write_bytes(b"OLD")
    rc, _, err = _run(_baseline_argv(
        tmp_path, "report.md", "--format", "markdown", "--overwrite",
    ))
    assert rc == 0, err
    bytes_now = target.read_bytes()
    assert bytes_now != b"OLD"
    # Sanity: the new content looks like a Markdown report.
    assert b"# " in bytes_now and b"## Summary" in bytes_now


# ---------------------------------------------------------------------------
# Implied: atomic write — no partial file on render-time failure
# ---------------------------------------------------------------------------
def test_atomic_write_no_partial_file_on_render_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def boom(*a, **kw):
        raise RuntimeError("simulated render failure")

    # Patch the renderer that the dispatch imports. Local import in
    # _render_and_write happens at call time, so patching the module
    # attribute is sufficient.
    monkeypatch.setattr("ai_adoption_report.render.render_markdown", boom)

    with pytest.raises(RuntimeError):
        # The dispatch propagates the renderer's RuntimeError (only
        # ValidationError is converted to exit 2 by main()).
        _run(_baseline_argv(tmp_path, "report.md"))

    # Target file never created, no .tmp leftover.
    assert not (tmp_path / "report.md").exists()
    assert not (tmp_path / "report.json").exists()
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Implied: --format=markdown writes only Markdown
# ---------------------------------------------------------------------------
def test_format_markdown_writes_only_markdown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(_baseline_argv(tmp_path, "report.md", "--format", "markdown"))
    assert rc == 0, err
    assert (tmp_path / "report.md").exists()
    assert not (tmp_path / "report.json").exists()


# ---------------------------------------------------------------------------
# Implied: --format=json writes ONLY .json (NOT .md), even when --output is .md
# ---------------------------------------------------------------------------
def test_format_json_writes_only_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(_baseline_argv(tmp_path, "report.md", "--format", "json"))
    assert rc == 0, err
    assert (tmp_path / "report.json").exists()
    assert not (tmp_path / "report.md").exists()


# ---------------------------------------------------------------------------
# Implied: --format=json with --output report.json exits 2 (sidecar collision)
# ---------------------------------------------------------------------------
def test_format_json_with_json_output_exits_2(tmp_path, monkeypatch):
    """--output report.json would derive sidecar = report.json (same
    path); the sidecar-derivation rule rejects this with exit 2.
    """
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(_baseline_argv(tmp_path, "report.json", "--format", "json"))
    assert rc == 2
    assert "--output is treated as the Markdown-shaped path" in err


# ---------------------------------------------------------------------------
# Implied: generated_at honors the env var
# ---------------------------------------------------------------------------
def test_generated_at_from_env_var(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pinned = "2026-05-19T14:30:00Z"
    monkeypatch.setenv(GENERATED_AT_ENV_VAR, pinned)
    rc, _, err = _run(_baseline_argv(tmp_path, "report.md", "--format", "json"))
    assert rc == 0, err
    doc = json.loads((tmp_path / "report.json").read_text())
    assert doc["meta"]["generated_at"] == pinned


# ---------------------------------------------------------------------------
# Implied: byte-identical rerun with pinned generated_at (the determinism gate)
# ---------------------------------------------------------------------------
def test_byte_identical_rerun_with_pinned_generated_at(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(GENERATED_AT_ENV_VAR, "2026-05-19T14:30:00Z")

    rc, _, err = _run(_baseline_argv(tmp_path, "report.md"))
    assert rc == 0, err
    md_a = (tmp_path / "report.md").read_bytes()
    js_a = (tmp_path / "report.json").read_bytes()

    rc, _, err = _run(_baseline_argv(tmp_path, "report.md", "--overwrite"))
    assert rc == 0, err
    md_b = (tmp_path / "report.md").read_bytes()
    js_b = (tmp_path / "report.json").read_bytes()

    assert md_a == md_b
    assert js_a == js_b


# ---------------------------------------------------------------------------
# Implied: validate_local_path runs before any write
# ---------------------------------------------------------------------------
def test_validate_local_path_runs_before_write(tmp_path, monkeypatch):
    """An --output path outside CWD must exit 2 before any write happens."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    _seed_baseline_inputs(work)

    outside = tmp_path / "stray.md"  # outside the work dir
    rc, _, err = _run([
        "baseline",
        "--baseline", "baseline.json",
        "--current", "current.json",
        "--output", str(outside),
    ])
    assert rc == 2
    assert "--output:" in err
    # The path-safety helper bails before the writer; nothing landed
    # at the outside-CWD location.
    assert not outside.exists()
    assert not outside.with_suffix(".json").exists()


# ---------------------------------------------------------------------------
# Smoke: end-to-end --format=both writes both files and exits 0
# ---------------------------------------------------------------------------
def test_format_both_writes_md_and_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(_baseline_argv(tmp_path, "report.md"))
    assert rc == 0, err
    md = (tmp_path / "report.md").read_text()
    js = (tmp_path / "report.json").read_text()
    assert md.startswith("# ")
    assert "## Summary" in md
    parsed = json.loads(js)
    assert parsed["meta"]["skill"] == "ai-adoption-report"
    assert parsed["meta"]["mode"] == "baseline"


# ---------------------------------------------------------------------------
# Construction: GENERATED_AT_ENV_VAR is the pinned name (T9 SKILL.md ref)
# ---------------------------------------------------------------------------
def test_generated_at_env_var_name_pinned():
    """T9's SKILL.md documents this env var by name; keep the constant
    stable so docs and behavior do not drift.
    """
    assert GENERATED_AT_ENV_VAR == "AI_ADOPTION_REPORT_GENERATED_AT"


# ---------------------------------------------------------------------------
# Output file mode reflects umask, not the tempfile's 0600 security default.
# ---------------------------------------------------------------------------
def test_output_file_mode_respects_umask(tmp_path, monkeypatch):
    """Without this guard, ``tempfile.NamedTemporaryFile`` would force
    mode 0600 (owner-only) onto every report — surprising for users
    sharing or committing reports. The mode must match what a freshly-
    touched file would have under the current umask.
    """
    # Pin umask so the test is independent of the developer's shell.
    old_umask = os.umask(0o022)
    try:
        target = tmp_path / "out.md"
        write_outputs([(target, "hello\n")], overwrite=False)
        mode = target.stat().st_mode & 0o777
        # umask 0o022 → mode 0o644.
        assert mode == 0o644, "expected 0644, got {:o}".format(mode)
    finally:
        os.umask(old_umask)


# ---------------------------------------------------------------------------
# _atomic_write cleanup: covers the actual try/except path inside the
# atomic-write helper (the render-failure test only exercises the path
# *before* write_outputs is called).
# ---------------------------------------------------------------------------
def test_atomic_write_cleans_up_tmp_when_replace_fails(tmp_path, monkeypatch):
    """Patch ``os.replace`` to raise mid-write. The temp file must be
    unlinked, the original target must be unchanged, and the original
    exception must propagate.
    """
    target = tmp_path / "out.md"
    target.write_text("ORIGINAL")

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_outputs([(target, "NEW BYTES")], overwrite=True)

    # Atomic semantic preserved: original target untouched.
    assert target.read_text() == "ORIGINAL"
    # Cleanup: no .tmp sibling left over in the target's parent.
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == [], "stale tempfile(s) left behind: {}".format(leftovers)


# ---------------------------------------------------------------------------
# Partial-write window: documented behaviour is "no rollback of the first
# target on second-target failure". Lock the behaviour in so a future
# defensive change doesn't surprise readers without an explicit test
# update.
# ---------------------------------------------------------------------------
def test_partial_write_first_target_remains_replaced_on_second_failure(
    tmp_path, monkeypatch
):
    """Brief lines 60-64: 'mid-write IO error during the second file is
    rare enough to not roll back the first'. Pre-flight covers the
    common case (collision); this test pins the documented behaviour
    when the rare case fires.
    """
    md = tmp_path / "out.md"
    js = tmp_path / "out.json"

    real_replace = os.replace
    calls = {"n": 0}

    def replace_then_fail(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            real_replace(src, dst)
            return
        raise OSError("simulated second-write failure")

    monkeypatch.setattr(os, "replace", replace_then_fail)

    with pytest.raises(OSError, match="simulated second-write failure"):
        write_outputs(
            [(md, "FIRST"), (js, "SECOND")],
            overwrite=False,
        )

    # First target was written (no rollback).
    assert md.read_text() == "FIRST"
    # Second target was never written.
    assert not js.exists()
    # Second-write tempfile cleaned up.
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == [], "stale tempfile(s) left behind: {}".format(leftovers)
