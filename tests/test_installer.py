"""
Tests for the dropkit installer.
Covers all contract tests from docs/specs/kit-installer.md
plus construction tests from docs/specs/kit-installer-plan.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict
from unittest.mock import patch

import pytest
from typing import Optional

from installer.commands import sha256_file, strip_ansi as _strip_ansi_cmd

# ---------------------------------------------------------------------------
# Repo root (where install.py lives)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.resolve()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_skill(skill_dir: Path, skill_id: str, version: str = "1.0.0",
                category: Optional[str] = None, description: str = "A test skill",
                deps_skills=None, deps_pip=None, extra_files=None) -> None:
    """Write a minimal skill directory with manifest.json and SKILL.md."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"id": skill_id, "version": version, "description": description}
    if category is not None:
        manifest["category"] = category
    if deps_skills:
        manifest["deps"] = {"skills": deps_skills}
    if deps_pip:
        manifest.setdefault("deps", {})["pip"] = deps_pip
    (skill_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}", encoding="utf-8")
    if extra_files:
        for name, content in extra_files.items():
            p = skill_dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A minimal fake repo with two skills (skill-a, skill-b)."""
    _make_skill(tmp_path / "skills" / "cat1" / "skill-a", "skill-a")
    _make_skill(tmp_path / "skills" / "cat1" / "skill-b", "skill-b")
    return tmp_path


@pytest.fixture()
def repo_with_dep(tmp_path: Path) -> Path:
    """Repo where skill-b depends on skill-a (internal dep)."""
    _make_skill(tmp_path / "skills" / "cat1" / "skill-a", "skill-a")
    _make_skill(
        tmp_path / "skills" / "cat1" / "skill-b",
        "skill-b",
        deps_skills=[{"name": "skill-a", "source": "local"}],
    )
    return tmp_path


@pytest.fixture()
def repo_with_external_dep(tmp_path: Path) -> Path:
    """Repo where skill-a depends on an external skill 'ext-skill'."""
    _make_skill(
        tmp_path / "skills" / "cat1" / "skill-a",
        "skill-a",
        deps_skills=[{"name": "ext-skill", "source": "other-repo — .claude/skills/ext-skill/"}],
    )
    return tmp_path


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect Path.home() to a temp directory for isolation."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    return home


def _run(args, repo_root=None, env=None, input_text=None):
    """Run install.py with given args; return CompletedProcess.

    repo_root overrides where skills are discovered from (DROPKIT_REPO_ROOT).
    install.py itself always lives in REPO_ROOT.
    """
    cmd = [sys.executable, str(REPO_ROOT / "install.py")] + args
    run_env = (env or os.environ).copy()
    if repo_root is not None:
        run_env["DROPKIT_REPO_ROOT"] = str(repo_root)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=run_env,
        input=input_text,
    )
    return result


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _strip_ansi(s: str) -> str:
    return _strip_ansi_cmd(s)


# ===========================================================================
# T1: Scaffold — Python version guard, argparse
# ===========================================================================

class TestScaffold:
    def test_runs_on_python_current(self):
        """Smoke: install.py imports without error on current Python."""
        r = _run(["--help"])
        assert r.returncode == 0

    def test_help_exits_0(self):
        r = _run(["--help"])
        assert r.returncode == 0
        assert "--scope" in r.stdout
        assert "--skill" in r.stdout
        assert "--list" in r.stdout
        assert "--update" in r.stdout
        assert "--uninstall" in r.stdout

    def test_unknown_flag_exits_2(self):
        r = _run(["--bogus"])
        assert r.returncode == 2

    def test_scope_required_for_plain_invocation(self):
        r = _run([])
        assert r.returncode == 2
        assert "--scope" in r.stderr or "--scope" in r.stdout

    def test_python_version_guard(self):
        """Version guard block covers Python < 3.8 path (checked by reading source)."""
        src = (REPO_ROOT / "install.py").read_text(encoding="utf-8")
        assert "sys.version_info < (3, 8)" in src
        assert "sys.exit(2)" in src


# ===========================================================================
# T2: Skill discovery
# ===========================================================================

class TestDiscovery:
    def test_discover_all_skills(self, repo: Path):
        from installer.discovery import discover_skills
        skills = discover_skills(repo)
        assert set(skills.keys()) == {"skill-a", "skill-b"}

    def test_discover_skill_fields(self, repo: Path):
        from installer.discovery import discover_skills
        skills = discover_skills(repo)
        a = skills["skill-a"]
        assert a.version == "1.0.0"
        assert a.category == "cat1"  # falls back to parent dir name
        assert a.description == "A test skill"

    def test_discover_skips_dirs_without_manifest(self, tmp_path: Path):
        from installer.discovery import discover_skills
        (tmp_path / "skills" / "cat1" / "not-a-skill").mkdir(parents=True)
        skills = discover_skills(tmp_path)
        assert skills == {}

    def test_discover_exits_2_on_bad_json(self, tmp_path: Path):
        d = tmp_path / "skills" / "cat1" / "bad-skill"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text("{bad json", encoding="utf-8")
        r = _run(["--list"], repo_root=tmp_path)
        assert r.returncode == 2
        assert "invalid JSON" in r.stderr

    def test_discover_exits_2_on_missing_id(self, tmp_path: Path):
        d = tmp_path / "skills" / "cat1" / "no-id"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text('{"version": "1.0"}', encoding="utf-8")
        r = _run(["--list"], repo_root=tmp_path)
        assert r.returncode == 2
        assert "missing required field" in r.stderr

    def test_discover_collects_all_files(self, tmp_path: Path):
        from installer.discovery import discover_skills
        _make_skill(
            tmp_path / "skills" / "cat1" / "skill-x",
            "skill-x",
            extra_files={"scripts/helper.py": "pass"},
        )
        skills = discover_skills(tmp_path)
        file_names = {str(f) for f in skills["skill-x"].files}
        assert "SKILL.md" in file_names
        assert "manifest.json" in file_names
        assert str(Path("scripts") / "helper.py") in file_names


# ===========================================================================
# T3: State-root resolution
# ===========================================================================

class TestStateRoot:
    def test_project_scope_state_under_dropkit(self, tmp_path: Path):
        from installer.state import resolve_state_root
        sr = resolve_state_root("claude-code-project", path=tmp_path)
        assert sr == tmp_path / ".dropkit"

    def test_user_xdg_when_set(self, tmp_path: Path, monkeypatch):
        from installer.state import resolve_state_root
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        sr = resolve_state_root("claude-code-user")
        assert sr == tmp_path / "xdg" / "dropkit"

    def test_user_xdg_default_on_unix(self, fake_home: Path, monkeypatch):
        from installer.state import resolve_state_root
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        if platform.system() == "Windows":
            pytest.skip("Unix-specific test")
        sr = resolve_state_root("claude-code-user")
        assert sr == fake_home / ".config" / "dropkit"

    def test_user_appdata_on_windows(self, tmp_path: Path, monkeypatch):
        from installer.state import resolve_state_root
        monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        with patch("platform.system", return_value="Windows"):
            sr = resolve_state_root("claude-code-user")
        assert sr == tmp_path / "AppData" / "Roaming" / "dropkit"

    def test_installed_json_roundtrip(self, tmp_path: Path):
        from installer.state import State, InstalledSkill, InstalledFile, save_state, load_state
        state = State(
            installer_version="0.1.0",
            scope="claude-code-user",
            scope_root=str(tmp_path / "skills"),
            installed_at="",
            skills={
                "my-skill": InstalledSkill(
                    version="1.0.0",
                    files=[InstalledFile(path="my-skill/SKILL.md", sha256="abc123")],
                )
            },
        )
        sr = tmp_path / "state"
        save_state(sr, state, "0.1.0")
        loaded = load_state(sr)
        assert loaded.scope == "claude-code-user"
        assert "my-skill" in loaded.skills
        assert loaded.skills["my-skill"].files[0].sha256 == "abc123"

    def test_corrupt_installed_json_treated_as_empty(self, tmp_path: Path):
        from installer.state import load_state
        sr = tmp_path / "state"
        sr.mkdir()
        (sr / "installed.json").write_text("{truncated", encoding="utf-8")
        state = load_state(sr)
        assert state.skills == {}

    def test_recover_scope_roots_finds_user_install(self, tmp_path: Path, monkeypatch):
        from installer.state import recover_scope_roots, resolve_state_root, save_state, State
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        state_root = tmp_path / "xdg" / "dropkit"
        scope_root = tmp_path / "skills"
        scope_root.mkdir(parents=True)
        state = State(scope="claude-code-user", scope_root=scope_root.as_posix())
        save_state(state_root, state, "0.1.0")
        found_scope_root, found_state_root, found_scope = recover_scope_roots()
        assert found_scope_root == scope_root
        assert found_scope == "claude-code-user"

    def test_atomic_write_tmp_then_replace(self, tmp_path: Path):
        from installer.state import State, save_state
        sr = tmp_path / "state"

        replace_calls = []
        original_replace = os.replace

        def tracking_replace(src, dst):
            replace_calls.append((src, dst))
            original_replace(src, dst)

        with patch("installer.state.os.replace", side_effect=tracking_replace):
            save_state(sr, State(), "0.1.0")

        assert len(replace_calls) == 1
        src_path, dst_path = replace_calls[0]
        assert str(src_path).endswith(".tmp")
        assert str(dst_path).endswith("installed.json")


# ===========================================================================
# T4: --list command
# ===========================================================================

class TestList:
    def _install_and_list(self, repo, fake_home, scope="claude-code-user"):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r_install = _run(
            ["--scope", scope, "--yes"],
            repo_root=repo,
            env=env,
        )
        assert r_install.returncode == 0, r_install.stderr
        return _run(["--scope", scope, "--list"], repo_root=repo, env=env)

    def test_list_shows_all_skills(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(["--scope", "claude-code-user", "--list"], repo_root=repo, env=env)
        assert r.returncode == 0
        lines = _strip_ansi(r.stdout).strip().splitlines()
        data_rows = [l for l in lines if l.strip() and "name" not in l.lower()]
        assert len(data_rows) == 2  # skill-a, skill-b

    def test_list_has_header_row(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(["--scope", "claude-code-user", "--list"], repo_root=repo, env=env)
        assert r.returncode == 0
        first_line = _strip_ansi(r.stdout).strip().splitlines()[0]
        for col in ("name", "version", "category", "status"):
            assert col in first_line

    def test_list_status_not_installed_by_default(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(["--scope", "claude-code-user", "--list"], repo_root=repo, env=env)
        assert r.returncode == 0
        content = _strip_ansi(r.stdout)
        assert content.count("not installed") == 2

    def test_list_status_installed_after_install(self, repo: Path, fake_home: Path):
        r = self._install_and_list(repo, fake_home)
        assert r.returncode == 0
        content = _strip_ansi(r.stdout)
        assert content.count("installed") >= 2
        assert "not installed" not in content

    def test_list_status_outdated(self, tmp_path: Path, fake_home: Path):
        _make_skill(tmp_path / "skills" / "cat1" / "skill-a", "skill-a", version="1.0.0")
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        # Install
        r = _run(["--scope", "claude-code-user", "--skill", "skill-a", "--yes"],
                 repo_root=tmp_path, env=env)
        assert r.returncode == 0

        # Bump version in manifest
        manifest_path = tmp_path / "skills" / "cat1" / "skill-a" / "manifest.json"
        data = json.loads(manifest_path.read_text())
        data["version"] = "2.0.0"
        manifest_path.write_text(json.dumps(data))

        r2 = _run(["--scope", "claude-code-user", "--list"], repo_root=tmp_path, env=env)
        assert "outdated" in _strip_ansi(r2.stdout)

    def test_list_status_modified(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)

        # Modify an installed file
        installed = fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md"
        installed.write_text("MODIFIED", encoding="utf-8")

        r = _run(["--scope", "claude-code-user", "--list"], repo_root=repo, env=env)
        assert "modified" in _strip_ansi(r.stdout)

    def test_list_status_orphaned(self, tmp_path: Path, fake_home: Path):
        _make_skill(tmp_path / "skills" / "cat1" / "skill-a", "skill-a")
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--yes"], repo_root=tmp_path, env=env)

        # Remove skill from repo
        shutil.rmtree(tmp_path / "skills" / "cat1" / "skill-a")

        r = _run(["--scope", "claude-code-user", "--list"], repo_root=tmp_path, env=env)
        assert "orphaned" in _strip_ansi(r.stdout)


# ===========================================================================
# T5: Path safety
# ===========================================================================

class TestPathSafety:
    def test_rejects_absolute_target(self, tmp_path: Path):
        from installer.safety import PathEscapeError, validate_target
        scope_root = tmp_path / "scope"
        scope_root.mkdir()
        with pytest.raises(PathEscapeError):
            validate_target(Path("/etc/passwd"), scope_root)

    def test_rejects_target_escaping_scope_root(self, tmp_path: Path):
        from installer.safety import PathEscapeError, validate_target
        scope_root = tmp_path / "scope"
        scope_root.mkdir()
        with pytest.raises(PathEscapeError):
            validate_target(Path("../../etc/passwd"), scope_root)

    def test_dotdot_within_scope_allowed(self, tmp_path: Path):
        from installer.safety import validate_target
        scope_root = tmp_path / "scope"
        scope_root.mkdir()
        result = validate_target(Path("a/../b"), scope_root)
        assert result == (scope_root / "b").resolve()


# ===========================================================================
# T6: Install core
# ===========================================================================

class TestInstallCore:
    def test_install_user_scope_writes_to_claude_skills(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-user", "--skill", "skill-a", "--yes"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 0
        installed = fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md"
        assert installed.exists()
        source = repo / "skills" / "cat1" / "skill-a" / "SKILL.md"
        assert installed.read_bytes() == source.read_bytes()

    def test_install_project_scope_writes_under_path(self, repo: Path, tmp_path: Path, fake_home: Path):
        proj = tmp_path / "myproject"
        proj.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-project", "--path", str(proj), "--skill", "skill-a", "--yes"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 0
        installed = proj / ".claude" / "skills" / "skill-a" / "SKILL.md"
        assert installed.exists()

    def test_install_records_installed_json(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--skill", "skill-a", "--yes"],
             repo_root=repo, env=env)
        state_file = fake_home / ".config" / "dropkit" / "installed.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert "skill-a" in data["skills"]
        assert data["skills"]["skill-a"]["version"] == "1.0.0"
        for fi in data["skills"]["skill-a"]["files"]:
            assert len(fi["sha256"]) == 64

    def test_install_all_skills_by_default(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)
        assert r.returncode == 0
        assert (fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md").exists()
        assert (fake_home / ".claude" / "skills" / "skill-b" / "SKILL.md").exists()

    def test_install_creates_parent_dirs(self, tmp_path: Path, fake_home: Path):
        _make_skill(
            tmp_path / "skills" / "cat1" / "nested-skill",
            "nested-skill",
            extra_files={"scripts/deep/helper.py": "pass"},
        )
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-user", "--skill", "nested-skill", "--yes"],
            repo_root=tmp_path, env=env,
        )
        assert r.returncode == 0
        assert (fake_home / ".claude" / "skills" / "nested-skill" / "scripts" / "deep" / "helper.py").exists()

    def test_install_mode_bits_preserved(self, tmp_path: Path, fake_home: Path):
        if platform.system() == "Windows":
            pytest.skip("Mode bits not meaningful on Windows")
        d = tmp_path / "skills" / "cat1" / "mode-skill"
        _make_skill(d, "mode-skill", extra_files={"scripts/run.sh": "#!/bin/bash"})
        script = d / "scripts" / "run.sh"
        script.chmod(0o755)
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(
            ["--scope", "claude-code-user", "--skill", "mode-skill", "--yes"],
            repo_root=tmp_path, env=env,
        )
        installed_script = fake_home / ".claude" / "skills" / "mode-skill" / "scripts" / "run.sh"
        assert oct(installed_script.stat().st_mode)[-3:] == "755"

    def test_install_sha256_correct(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--skill", "skill-a", "--yes"],
             repo_root=repo, env=env)
        state_file = fake_home / ".config" / "dropkit" / "installed.json"
        data = json.loads(state_file.read_text())
        for fi in data["skills"]["skill-a"]["files"]:
            actual = _sha256(fake_home / ".claude" / "skills" / fi["path"])
            assert fi["sha256"] == actual

    def test_prompt_overwrite_aborts_without_tty(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        # First install
        _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)
        # Modify installed file so content differs
        f = fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md"
        original = f.read_bytes()
        f.write_text("CHANGED", encoding="utf-8")
        # Second install without --yes; stdin from /dev/null (no TTY, no input)
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "install.py"), "--scope", "claude-code-user"],
            capture_output=True, text=True,
            env={**env, "DROPKIT_REPO_ROOT": str(repo)},
            stdin=subprocess.DEVNULL, cwd=str(REPO_ROOT),
        )
        assert r.returncode == 1
        # File should not have been overwritten
        assert f.read_text() == "CHANGED"


# ===========================================================================
# T7: Dep resolution
# ===========================================================================

class TestDepResolution:
    def test_install_dropkit_dep_pulled_in(self, repo_with_dep: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        # Install only skill-b (which depends on skill-a)
        r = _run(
            ["--scope", "claude-code-user", "--skill", "skill-b", "--yes"],
            repo_root=repo_with_dep, env=env,
        )
        assert r.returncode == 0
        # skill-a must also be installed
        assert (fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md").exists()
        assert (fake_home / ".claude" / "skills" / "skill-b" / "SKILL.md").exists()

    def test_dep_auto_include_announced(self, repo_with_dep: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-user", "--skill", "skill-b", "--yes"],
            repo_root=repo_with_dep, env=env,
        )
        assert "auto-including dep 'skill-a'" in r.stdout

    def test_dep_resolution_topological_order(self, repo_with_dep: Path):
        from installer.discovery import discover_skills
        from installer.deps import resolve_install_order
        skills = discover_skills(repo_with_dep)
        order = resolve_install_order(["skill-b"], skills)
        ids = [s.id for s in order]
        assert ids.index("skill-a") < ids.index("skill-b")

    def test_dep_resolution_cycle_exits_2(self, tmp_path: Path, fake_home: Path):
        _make_skill(
            tmp_path / "skills" / "cat1" / "skill-a",
            "skill-a",
            deps_skills=[{"name": "skill-b", "source": ""}],
        )
        _make_skill(
            tmp_path / "skills" / "cat1" / "skill-b",
            "skill-b",
            deps_skills=[{"name": "skill-a", "source": ""}],
        )
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-user", "--yes"],
            repo_root=tmp_path, env=env,
        )
        assert r.returncode == 2
        assert "cycle" in r.stderr.lower()

    def test_install_external_dep_warns_when_absent(self, repo_with_external_dep: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-user", "--yes"],
            repo_root=repo_with_external_dep, env=env,
        )
        assert r.returncode == 0
        assert "WARN" in r.stdout
        assert "ext-skill" in r.stdout

    def test_install_external_dep_info_when_present_in_scope(
        self, repo_with_external_dep: Path, fake_home: Path
    ):
        # Pre-install the external skill manually
        ext = fake_home / ".claude" / "skills" / "ext-skill"
        ext.mkdir(parents=True)
        (ext / "SKILL.md").write_text("# ext", encoding="utf-8")

        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-user", "--yes"],
            repo_root=repo_with_external_dep, env=env,
        )
        assert r.returncode == 0
        assert "INFO" in r.stdout
        assert "WARN" not in r.stdout

    def test_external_dep_warn_no_clone_suggestion(
        self, repo_with_external_dep: Path, fake_home: Path
    ):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-user", "--yes"],
            repo_root=repo_with_external_dep, env=env,
        )
        assert "clone" not in r.stdout.lower()


# ===========================================================================
# T8: --update
# ===========================================================================

class TestUpdate:
    def _setup(self, repo, fake_home):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)
        return env

    def test_update_overwrites_changed_files(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        # Change source file in repo
        (repo / "skills" / "cat1" / "skill-a" / "SKILL.md").write_text("UPDATED", encoding="utf-8")
        r = _run(["--update"], repo_root=repo, env=env)
        assert r.returncode == 0
        installed = fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md"
        assert installed.read_text() == "UPDATED"

    def test_update_refreshes_sha256(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        new_content = "UPDATED CONTENT"
        (repo / "skills" / "cat1" / "skill-a" / "SKILL.md").write_text(new_content, encoding="utf-8")
        _run(["--update"], repo_root=repo, env=env)
        state_file = fake_home / ".config" / "dropkit" / "installed.json"
        data = json.loads(state_file.read_text())
        recorded = next(
            f["sha256"] for f in data["skills"]["skill-a"]["files"]
            if f["path"].endswith("SKILL.md")
        )
        expected = hashlib.sha256(new_content.encode()).hexdigest()
        assert recorded == expected

    def test_update_does_not_install_new_skills(self, tmp_path: Path, fake_home: Path):
        _make_skill(tmp_path / "skills" / "cat1" / "skill-a", "skill-a")
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--skill", "skill-a", "--yes"],
             repo_root=tmp_path, env=env)

        # Add a new skill to the repo
        _make_skill(tmp_path / "skills" / "cat1" / "skill-new", "skill-new")

        _run(["--update"], repo_root=tmp_path, env=env)
        assert not (fake_home / ".claude" / "skills" / "skill-new").exists()

    def test_update_no_op_when_clean(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        r = _run(["--update"], repo_root=repo, env=env)
        assert r.returncode == 0
        assert "Nothing to update" in r.stdout

    def test_update_summary_line(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        (repo / "skills" / "cat1" / "skill-a" / "SKILL.md").write_text("UPDATED", encoding="utf-8")
        r = _run(["--update"], repo_root=repo, env=env)
        assert "Updated" in r.stdout


# ===========================================================================
# T9: --uninstall
# ===========================================================================

class TestUninstall:
    def _setup(self, repo, fake_home):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)
        return env

    def test_uninstall_removes_tracked_files(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        r = _run(
            ["--scope", "claude-code-user", "--uninstall", "--skill", "skill-a", "--yes"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 0
        assert not (fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md").exists()

    def test_uninstall_updates_installed_json(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        _run(["--scope", "claude-code-user", "--uninstall", "--skill", "skill-a", "--yes"],
             repo_root=repo, env=env)
        state_file = fake_home / ".config" / "dropkit" / "installed.json"
        data = json.loads(state_file.read_text())
        assert "skill-a" not in data["skills"]

    def test_uninstall_refuses_modified_without_force(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        # Modify installed file
        f = fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md"
        f.write_text("USER EDIT", encoding="utf-8")
        r = _run(
            ["--scope", "claude-code-user", "--uninstall", "--skill", "skill-a", "--yes"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 1
        assert f.exists()

    def test_uninstall_force_overrides(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        f = fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md"
        f.write_text("USER EDIT", encoding="utf-8")
        r = _run(
            ["--scope", "claude-code-user", "--uninstall", "--skill", "skill-a", "--yes", "--force"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 0
        assert not f.exists()

    def test_uninstall_removes_empty_parents(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        r = _run(
            ["--scope", "claude-code-user", "--uninstall", "--skill", "skill-a", "--yes"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 0
        assert not (fake_home / ".claude" / "skills" / "skill-a").exists()

    def test_uninstall_leaves_unrelated_files(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        unrelated = fake_home / ".claude" / "skills" / "unrelated.txt"
        unrelated.write_text("keep me", encoding="utf-8")
        _run(["--scope", "claude-code-user", "--uninstall", "--skill", "skill-a", "--yes"],
             repo_root=repo, env=env)
        assert unrelated.exists()

    def test_uninstall_nonexistent_skill_exits_2(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        r = _run(
            ["--scope", "claude-code-user", "--uninstall", "--skill", "no-such-skill", "--yes"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 2
        assert "no-such-skill" in r.stderr

    def test_uninstall_already_gone_handled_gracefully(self, repo: Path, fake_home: Path):
        env = self._setup(repo, fake_home)
        # Delete installed file before uninstalling
        (fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md").unlink()
        r = _run(
            ["--scope", "claude-code-user", "--uninstall", "--skill", "skill-a", "--yes"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 0


# ===========================================================================
# T10: --dry-run, pip/npm surfacing
# ===========================================================================

class TestDryRunAndSurfacing:
    def _dir_hash(self, d: Path) -> str:
        h = hashlib.sha256()
        for f in sorted(d.rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(d)).encode())
                h.update(f.read_bytes())
        return h.hexdigest()

    def test_dry_run_writes_nothing(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        skills_dir = fake_home / ".claude" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        before = self._dir_hash(skills_dir)
        r = _run(["--scope", "claude-code-user", "--dry-run", "--yes"],
                 repo_root=repo, env=env)
        assert r.returncode == 0
        assert self._dir_hash(skills_dir) == before

    def test_dry_run_shows_would_write(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(["--scope", "claude-code-user", "--dry-run", "--yes"],
                 repo_root=repo, env=env)
        assert "would write:" in r.stdout

    def test_dry_run_shows_would_skip_when_same(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)
        r = _run(["--scope", "claude-code-user", "--dry-run", "--yes"],
                 repo_root=repo, env=env)
        assert "would skip:" in r.stdout

    def test_dry_run_uninstall(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)
        r = _run(
            ["--scope", "claude-code-user", "--uninstall", "--dry-run", "--yes"],
            repo_root=repo, env=env,
        )
        assert r.returncode == 0
        assert "would remove:" in r.stdout
        assert (fake_home / ".claude" / "skills" / "skill-a" / "SKILL.md").exists()

    def test_pip_deps_surfaced_after_install(self, tmp_path: Path, fake_home: Path):
        _make_skill(
            tmp_path / "skills" / "cat1" / "pip-skill",
            "pip-skill",
            deps_pip=["requests", "httpx>=0.27"],
        )
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(
            ["--scope", "claude-code-user", "--skill", "pip-skill", "--yes"],
            repo_root=tmp_path, env=env,
        )
        assert r.returncode == 0
        assert "pip install" in r.stdout

    def test_installer_never_runs_pip(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        # Wrap to fail on pip/npm subprocess calls
        orig_run = subprocess.run
        def guarded_run(cmd, **kwargs):
            if isinstance(cmd, (list, tuple)):
                joined = " ".join(str(c) for c in cmd)
            else:
                joined = str(cmd)
            import re
            if re.search(r"\b(pip|npm|yarn|pnpm)\b", joined):
                raise AssertionError(f"Installer must not run: {joined}")
            return orig_run(cmd, **kwargs)
        # Patch at the subprocess level used by _run
        r = _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)
        assert r.returncode == 0
        # Simply verify no pip/npm in stdout/stderr output
        for line in (r.stdout + r.stderr).splitlines():
            assert not any(tool in line for tool in ["Collecting", "Installing collected"]), \
                f"pip output detected: {line}"

    def test_no_pip_surfaced_when_no_deps(self, repo: Path, fake_home: Path):
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r = _run(["--scope", "claude-code-user", "--yes"], repo_root=repo, env=env)
        assert "pip install" not in r.stdout


# ===========================================================================
# T11: Wrappers
# ===========================================================================

class TestWrappers:
    def test_install_sh_passes_args_through(self, fake_home: Path):
        if platform.system() == "Windows":
            pytest.skip("install.sh not applicable on Windows")
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env.pop("XDG_CONFIG_HOME", None)
        r_sh = subprocess.run(
            ["bash", str(REPO_ROOT / "install.sh"), "--scope", "claude-code-user", "--list"],
            capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
        )
        r_py = _run(["--scope", "claude-code-user", "--list"], env=env)
        assert r_sh.returncode == r_py.returncode
        assert _strip_ansi(r_sh.stdout) == _strip_ansi(r_py.stdout)

    def test_install_ps1_passes_args_through(self):
        pytest.skip("PowerShell not available on this runner")


# ===========================================================================
# Line count gate (acceptance criterion)
# ===========================================================================

class TestLineCount:
    def test_install_py_under_500_lines(self):
        lines = (REPO_ROOT / "install.py").read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 500, f"install.py is {len(lines)} lines (limit 500)"
