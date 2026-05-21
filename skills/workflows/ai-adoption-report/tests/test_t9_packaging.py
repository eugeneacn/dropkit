"""T9 packaging tests.

Covers the spec's read-only-contract pair plus the SKILL.md / manifest
diff checks, the three golden-file byte-identity tests, and a smoke
test that exercises all three modes end-to-end against the canonical
fixture set.

Implementation notes:

- The CLI's ``main()`` returns an ``int``; only the ``__main__`` shim
  calls ``sys.exit``. So the tests assert on the return value, not on a
  raised :class:`SystemExit`.
- Every CLI invocation runs in a tmp-path cwd because the path-safety
  rule rejects paths outside ``Path.cwd()``. The fixtures and goldens
  live under the repo tree, so the tmp dir gets a copy of the relevant
  fixture subtree.
- Golden byte-identity is checked at the byte level
  (``Path.read_bytes()``) so any trailing-whitespace or line-ending
  drift fails the test. Diffs are rendered via
  :func:`difflib.unified_diff` so a regression points at the line that
  changed instead of dumping both files end-to-end.
- The read-only filesystem-writes contract is checked by snapshotting
  the cwd's file set before and after a run and asserting the only new
  files are ``--output`` and its ``.json`` sidecar. Atomic-write temp
  files in the parent dir are renamed onto the final paths via
  ``os.replace``, so they leave no trace; if any leak (e.g. a
  ``.tmp`` file from a failed write) it shows up here.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_adoption_report import build_parser, main, PYTHON_FLOOR


SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent.parent.parent
SPEC_PATH = REPO_ROOT / "docs" / "specs" / "ai-adoption-report.md"
SKILL_MD = SKILL_DIR / "SKILL.md"
MANIFEST = SKILL_DIR / "manifest.json"
GOLDEN_DIR = SKILL_DIR / "tests" / "fixtures" / "golden"
DEMO_DIR = REPO_ROOT / "examples" / "ai-adoption-report"
DEMO_GENERATED_AT = "2026-01-15T09:00:00Z"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PINNED_ENV = {
    "AI_ADOPTION_REPORT_GENERATED_AT": "2026-05-19T14:30:00Z",
    "LC_ALL": "C",
}


def _flag_tokens(text: str) -> set[str]:
    """Extract every distinct ``--flag`` token from text."""
    return set(re.findall(r"--[a-z][a-z0-9-]*", text))


def _run_main(argv: list[str], cwd: Path) -> int:
    """Invoke ``main(argv)`` from ``cwd`` with the pinned env vars set.

    Snapshots and restores ``cwd`` and the pinned env keys so the
    in-process invocation does not leak state across tests.
    """
    saved_cwd = Path.cwd()
    saved_env = {k: os.environ.get(k) for k in PINNED_ENV}
    try:
        os.chdir(cwd)
        for k, v in PINNED_ENV.items():
            os.environ[k] = v
        return main(argv)
    finally:
        os.chdir(saved_cwd)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# SKILL.md ↔ CLI flag diff
# ---------------------------------------------------------------------------
def test_skill_md_lists_every_flag_from_spec() -> None:
    """SKILL.md must document the same flag set that build_parser exposes."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    skill_flags = _flag_tokens(skill_text)

    parser = build_parser()
    help_text = parser.format_help()
    for sub_mode in ("baseline", "cohort", "program"):
        sub_parser = parser._subparsers._actions[-1].choices[sub_mode]  # type: ignore[attr-defined]
        help_text += "\n" + sub_parser.format_help()
    cli_flags = _flag_tokens(help_text)
    cli_flags.discard("--help")
    skill_flags.discard("--help")

    missing_from_skill = cli_flags - skill_flags
    orphaned_in_skill = skill_flags - cli_flags
    assert not missing_from_skill, (
        "SKILL.md is missing CLI flags: {}".format(sorted(missing_from_skill))
    )
    assert not orphaned_in_skill, (
        "SKILL.md mentions flags absent from the CLI: {}".format(
            sorted(orphaned_in_skill)
        )
    )


def test_skill_md_examples_match_spec_examples() -> None:
    """The three example commands in spec §Users-and-use-cases must
    appear verbatim somewhere inside SKILL.md's Examples code blocks."""
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    expected_commands = [
        "ai-adoption-report baseline --baseline outputs/PROJ-Foo-2024Q1.json --current outputs/PROJ-Foo-2025Q4.json --output report.md",
        "ai-adoption-report cohort --input outputs/PROJ-Foo-2025Q4-with-cohort.json --output report.md",
        "ai-adoption-report program --inputs outputs/ --window 2025-10-01..2025-12-31 --output q4-program.md",
    ]

    def _collapse_whitespace(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    spec_normalised = _collapse_whitespace(spec_text)
    skill_normalised = _collapse_whitespace(skill_text)
    for cmd in expected_commands:
        norm = _collapse_whitespace(cmd)
        assert norm in spec_normalised, (
            "Test fixture has drifted from spec — '{}' not found in spec".format(norm)
        )
        assert norm in skill_normalised, (
            "SKILL.md missing example command '{}'".format(norm)
        )


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------
def test_manifest_registers_under_workflows() -> None:
    """manifest.json must register the skill under the same category
    string that every other ``skills/workflows/*`` manifest uses.

    The kit-installer's :func:`installer.discovery._parse_manifest`
    reads ``data["category"]``, falling back to the parent directory
    name when absent. Both must agree to avoid drift in installed-skill
    listings.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["category"] == "workflows", (
        "manifest.json category must be 'workflows' to match the parent "
        "directory and every sibling workflow manifest; got {!r}".format(
            manifest.get("category")
        )
    )

    # Read-only contract: every other workflow declares its upstream
    # dependencies via deps.skills (a list of {name, source} dicts).
    # ai-adoption-report has none — it consumes JSON files, not skills.
    deps = manifest.get("deps", {})
    assert deps.get("skills") == [], (
        "ai-adoption-report is read-only and consumes JSON files, not "
        "skills; deps.skills must be []"
    )


def test_manifest_id_matches_skill_dir() -> None:
    """The kit-installer keys skills by ``manifest.id``; the id must
    match the skill directory so ``skills/workflows/<id>/manifest.json``
    is discoverable by name."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["id"] == SKILL_DIR.name, (
        "manifest.id ({}) must equal skill directory name ({})".format(
            manifest["id"], SKILL_DIR.name
        )
    )


def test_manifest_python_floor_matches_implementation() -> None:
    """The python version pinned in ``deps.system`` must agree with the
    runtime ``PYTHON_FLOOR`` constant.

    The kit-installer surfaces ``deps.system`` to the user as
    install-prerequisite information; runtime enforcement is the
    skill's own job (see :func:`ai_adoption_report._check_python_version`).
    Drift between the two would surface as either a confusing install-
    time message or a silently-relaxed runtime check.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    deps_system = manifest.get("deps", {}).get("system", [])
    floor_str = "python >= {}.{}".format(*PYTHON_FLOOR)
    assert floor_str in deps_system, (
        "manifest.deps.system must declare {!r}; got {!r}".format(
            floor_str, deps_system
        )
    )


# ---------------------------------------------------------------------------
# Read-only contract: no upstream skill invocations
# ---------------------------------------------------------------------------
def _baseline_argv(work: Path) -> list[str]:
    inputs = work / "inputs"
    return [
        "baseline",
        "--baseline", str(inputs / "PROJ-Foo-2024Q1.json"),
        "--current", str(inputs / "PROJ-Foo-2025Q4.json"),
        "--output", str(work / "out.md"),
        "--overwrite",
    ]


def _cohort_argv(work: Path) -> list[str]:
    return [
        "cohort",
        "--input", str(work / "input.json"),
        "--output", str(work / "out.md"),
        "--overwrite",
    ]


def _program_argv(work: Path) -> list[str]:
    return [
        "program",
        "--inputs", str(work / "inputs"),
        "--window", "2025-10-01..2025-12-31",
        "--output", str(work / "out.md"),
        "--overwrite",
    ]


def _stage_baseline(tmp_path: Path) -> Path:
    work = tmp_path / "baseline"
    work.mkdir()
    shutil.copytree(GOLDEN_DIR / "baseline" / "inputs", work / "inputs")
    return work


def _stage_cohort(tmp_path: Path) -> Path:
    work = tmp_path / "cohort"
    work.mkdir()
    shutil.copy2(GOLDEN_DIR / "cohort" / "input.json", work / "input.json")
    return work


def _stage_program(tmp_path: Path) -> Path:
    work = tmp_path / "program"
    work.mkdir()
    shutil.copytree(GOLDEN_DIR / "program" / "inputs", work / "inputs")
    return work


# The full subprocess + low-level spawn surface we need to fence. A
# regression that uses any of these would shell out to flow-metrics /
# jira / jira-align / etc., breaking the read-only contract. We patch
# every entry point we can name; ``hasattr`` filtering allows the
# patch to no-op on platforms where the symbol does not exist (e.g.
# ``os.fork`` / ``os.posix_spawn`` on Windows).
#
# Known limitation: ``patch.object(subprocess, attr)`` rebinds the
# module attribute, so a regression that did
# ``from subprocess import run`` at module scope inside the skill
# would bind a local reference before the patch is applied and slip
# past detection. Verified non-issue today —
# ``scripts/ai_adoption_report/**.py`` has zero ``subprocess`` /
# ``os.spawn`` / ``os.exec`` imports. If a future change adds an
# import, either route it through the runtime ``subprocess`` lookup
# (``import subprocess; subprocess.run(...)``) or extend this fence
# to walk ``sys.modules`` after the run.
_SUBPROCESS_ATTRS = ("run", "Popen", "call", "check_call", "check_output")
_OS_ATTRS = (
    "system",
    "popen",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "posix_spawn", "posix_spawnp",
    "execv", "execve", "execvp", "execvpe",
    "execl", "execle", "execlp", "execlpe",
    "fork", "forkpty",
)


def _patches_blocking_process_spawn() -> list:
    """Build the list of ``unittest.mock`` patchers that block every
    avenue for spawning a subprocess.

    Each entry is a context manager; the caller stacks them via
    ``contextlib.ExitStack``. Per-attr existence is checked so the
    helper works on Windows where the ``os.fork`` / ``os.posix_spawn``
    family is missing.
    """
    patchers = []
    for attr in _SUBPROCESS_ATTRS:
        if hasattr(subprocess, attr):
            patchers.append(patch.object(subprocess, attr))
    for attr in _OS_ATTRS:
        if hasattr(os, attr):
            patchers.append(patch.object(os, attr))
    return patchers


def test_no_upstream_skill_invocations(tmp_path: Path) -> None:
    """For each mode, run the CLI in-process and assert no
    subprocess / Popen / os.system / os.spawn* / os.posix_spawn /
    os.exec* / os.fork call was made.

    The skill consumes flow-metrics JSON files; it must not shell out
    to flow-metrics, jira, jira-align, or any other tool. The patch
    surface covers every documented stdlib entry point for spawning a
    child process; if a regression reaches for any of them the test
    fails with the offending mock's call_count.
    """
    from contextlib import ExitStack

    stagers = (
        ("baseline", _stage_baseline, _baseline_argv),
        ("cohort", _stage_cohort, _cohort_argv),
        ("program", _stage_program, _program_argv),
    )
    for mode_label, stage_fn, argv_fn in stagers:
        work = stage_fn(tmp_path)
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in _patches_blocking_process_spawn()]
            rc = _run_main(argv_fn(work), cwd=work)
            assert rc == 0, "mode {} exited {}".format(mode_label, rc)
            for m in mocks:
                # ``_mock_name`` is the patched attribute's qualified name;
                # the assertion message names the exact entry-point that
                # was reached so a regression is debuggable from the
                # failure alone.
                assert m.call_count == 0, (
                    "mode {} invoked process-spawn entry point {} {} time(s)".format(
                        mode_label, m._mock_name or "<unnamed>", m.call_count
                    )
                )


def test_no_filesystem_writes_outside_output_and_sidecar(tmp_path: Path) -> None:
    """For each mode, snapshot the work dir before and after a run; the
    only new files allowed are ``--output`` and its ``.json`` sidecar.

    Atomic-write temp files in the same parent directory are renamed
    onto the final paths via ``os.replace`` and leave no trace, so any
    surviving ``.tmp`` artefact indicates a contract regression. The
    snapshot uses ``rglob("*")`` which traverses hidden / dotfiles too,
    so a leaked ``.tmp`` is caught.
    """
    stagers = (
        ("baseline", _stage_baseline, _baseline_argv),
        ("cohort", _stage_cohort, _cohort_argv),
        ("program", _stage_program, _program_argv),
    )
    for mode_label, stage_fn, argv_fn in stagers:
        work = stage_fn(tmp_path)
        before = {p for p in work.rglob("*") if p.is_file()}
        rc = _run_main(argv_fn(work), cwd=work)
        assert rc == 0, "mode {} exited {}".format(mode_label, rc)
        after = {p for p in work.rglob("*") if p.is_file()}
        new_files = sorted(p.relative_to(work) for p in (after - before))
        expected = sorted([Path("out.md"), Path("out.json")])
        assert new_files == expected, (
            "mode {} wrote unexpected files: {}".format(
                mode_label, [str(p) for p in new_files]
            )
        )


# ---------------------------------------------------------------------------
# Golden-file byte-identity, one per mode
# ---------------------------------------------------------------------------
def _assert_byte_identical(actual: Path, expected: Path) -> None:
    """Assert ``actual`` and ``expected`` are byte-identical.

    Diff is rendered via :func:`difflib.unified_diff` against the
    text decoding (UTF-8 with replacement on undecodable bytes) so the
    failure message points at the line that drifted instead of dumping
    both files end-to-end. The byte comparison is the actual contract
    — the diff is presentation only.
    """
    actual_bytes = actual.read_bytes()
    expected_bytes = expected.read_bytes()
    if actual_bytes == expected_bytes:
        return
    actual_text = actual_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
    expected_text = expected_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            expected_text, actual_text,
            fromfile=str(expected), tofile=str(actual),
            n=3,
        )
    )
    raise AssertionError(
        "{} bytes differ from {}:\n{}".format(actual, expected, diff)
    )


def test_baseline_golden_byte_identical(tmp_path: Path) -> None:
    work = _stage_baseline(tmp_path)
    rc = _run_main(_baseline_argv(work), cwd=work)
    assert rc == 0
    _assert_byte_identical(work / "out.md", GOLDEN_DIR / "baseline" / "expected.md")
    _assert_byte_identical(work / "out.json", GOLDEN_DIR / "baseline" / "expected.json")


def test_cohort_golden_byte_identical(tmp_path: Path) -> None:
    work = _stage_cohort(tmp_path)
    rc = _run_main(_cohort_argv(work), cwd=work)
    assert rc == 0
    _assert_byte_identical(work / "out.md", GOLDEN_DIR / "cohort" / "expected.md")
    _assert_byte_identical(work / "out.json", GOLDEN_DIR / "cohort" / "expected.json")


def test_program_golden_byte_identical(tmp_path: Path) -> None:
    work = _stage_program(tmp_path)
    rc = _run_main(_program_argv(work), cwd=work)
    assert rc == 0
    _assert_byte_identical(work / "out.md", GOLDEN_DIR / "program" / "expected.md")
    _assert_byte_identical(work / "out.json", GOLDEN_DIR / "program" / "expected.json")


# ---------------------------------------------------------------------------
# Demo: examples/ai-adoption-report/ reproducibility
# ---------------------------------------------------------------------------
# The checked-in demo outputs in ``examples/ai-adoption-report/outputs/``
# are user-facing docs — broken demo bytes leak to the README rendering
# and to anyone reading along. Re-run the demo with its documented env
# var (``AI_ADOPTION_REPORT_GENERATED_AT=2026-01-15T09:00:00Z``) and
# assert byte-identity, the same way the golden tests do.
#
# Cross-tree coupling: these tests reach into ``REPO_ROOT/examples/``,
# which lives outside the skill's own subtree. To keep the skill
# extractable as a standalone package, the demo tests skip cleanly
# when ``DEMO_DIR`` is absent — the rest of the suite still runs.
#
# Regenerate recipe (when a renderer change updates demo bytes):
#   See ``examples/ai-adoption-report/README.md`` §"Running the demo".
#   The three documented commands ARE the regenerate recipe; commit
#   the updated ``outputs/`` after running them.
_DEMO_SKIP_REASON = (
    "examples/ai-adoption-report/ is absent; demo regression tests "
    "skip cleanly so the skill remains extractable as a standalone "
    "package."
)


def _require_demo() -> None:
    if not DEMO_DIR.is_dir():
        pytest.skip(_DEMO_SKIP_REASON)


def _stage_demo(tmp_path: Path, sub: str) -> Path:
    """Copy the demo input directory ``sub`` into a tmp work dir.

    Returns the staged work dir; the test then invokes the CLI with
    paths under that dir (avoiding the path-safety rule's CWD check).
    """
    work = tmp_path / "demo-{}".format(sub)
    work.mkdir()
    shutil.copytree(DEMO_DIR / "inputs" / sub, work / "inputs")
    return work


def _run_demo(argv: list[str], cwd: Path) -> int:
    saved_cwd = Path.cwd()
    saved_env = os.environ.get("AI_ADOPTION_REPORT_GENERATED_AT")
    saved_lc = os.environ.get("LC_ALL")
    try:
        os.chdir(cwd)
        os.environ["AI_ADOPTION_REPORT_GENERATED_AT"] = DEMO_GENERATED_AT
        os.environ["LC_ALL"] = "C"
        return main(argv)
    finally:
        os.chdir(saved_cwd)
        if saved_env is None:
            os.environ.pop("AI_ADOPTION_REPORT_GENERATED_AT", None)
        else:
            os.environ["AI_ADOPTION_REPORT_GENERATED_AT"] = saved_env
        if saved_lc is None:
            os.environ.pop("LC_ALL", None)
        else:
            os.environ["LC_ALL"] = saved_lc


def test_demo_baseline_reproduces_checked_in_outputs(tmp_path: Path) -> None:
    """Demo regen: ``examples/ai-adoption-report/README.md`` §Running the demo."""
    _require_demo()
    work = _stage_demo(tmp_path, "baseline")
    argv = [
        "baseline",
        "--baseline", str(work / "inputs" / "CHECKOUT-Foo-2024Q1.json"),
        "--current", str(work / "inputs" / "CHECKOUT-Foo-2025Q4.json"),
        "--output", str(work / "baseline-report.md"),
        "--overwrite",
    ]
    rc = _run_demo(argv, cwd=work)
    assert rc == 0
    _assert_byte_identical(work / "baseline-report.md", DEMO_DIR / "outputs" / "baseline-report.md")
    _assert_byte_identical(work / "baseline-report.json", DEMO_DIR / "outputs" / "baseline-report.json")


def test_demo_cohort_reproduces_checked_in_outputs(tmp_path: Path) -> None:
    """Demo regen: ``examples/ai-adoption-report/README.md`` §Running the demo."""
    _require_demo()
    work = _stage_demo(tmp_path, "cohort")
    argv = [
        "cohort",
        "--input", str(work / "inputs" / "CHECKOUT-Foo-2025Q4-with-cohort.json"),
        "--output", str(work / "cohort-report.md"),
        "--overwrite",
    ]
    rc = _run_demo(argv, cwd=work)
    assert rc == 0
    _assert_byte_identical(work / "cohort-report.md", DEMO_DIR / "outputs" / "cohort-report.md")
    _assert_byte_identical(work / "cohort-report.json", DEMO_DIR / "outputs" / "cohort-report.json")


def test_demo_program_reproduces_checked_in_outputs(tmp_path: Path) -> None:
    """Demo regen: ``examples/ai-adoption-report/README.md`` §Running the demo."""
    _require_demo()
    work = _stage_demo(tmp_path, "program")
    argv = [
        "program",
        "--inputs", str(work / "inputs"),
        "--window", "2025-10-01..2025-12-31",
        "--output", str(work / "program-report.md"),
        "--overwrite",
    ]
    rc = _run_demo(argv, cwd=work)
    assert rc == 0
    _assert_byte_identical(work / "program-report.md", DEMO_DIR / "outputs" / "program-report.md")
    _assert_byte_identical(work / "program-report.json", DEMO_DIR / "outputs" / "program-report.json")


# ---------------------------------------------------------------------------
# Acceptance: three modes end-to-end (smoke)
# ---------------------------------------------------------------------------
def test_acceptance_three_modes_end_to_end(tmp_path: Path) -> None:
    """Spec §"Acceptance criteria" first bullet: 'Three modes work
    end-to-end against flow-metrics JSON fixtures.' Each mode runs
    without the pinned env vars so the runtime-clock path is exercised
    alongside the golden tests."""
    stagers = (
        ("baseline", _stage_baseline, _baseline_argv),
        ("cohort", _stage_cohort, _cohort_argv),
        ("program", _stage_program, _program_argv),
    )

    saved_cwd = Path.cwd()
    saved_pin = os.environ.pop("AI_ADOPTION_REPORT_GENERATED_AT", None)
    try:
        for mode_label, stage_fn, argv_fn in stagers:
            work = stage_fn(tmp_path)
            os.chdir(work)
            rc = main(argv_fn(work))
            assert rc == 0, "mode {} exited {}".format(mode_label, rc)
            assert (work / "out.md").exists()
            assert (work / "out.json").exists()
    finally:
        os.chdir(saved_cwd)
        if saved_pin is not None:
            os.environ["AI_ADOPTION_REPORT_GENERATED_AT"] = saved_pin
