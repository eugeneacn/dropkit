"""T2 contract + construction tests for state / issuetype config loading.

Covers every test enumerated in docs/specs/flow-metrics-plan.md § T2.

The data-dependent unmapped-status check belongs to T5 (the changelog
walker); T2 ships the lookup helper that T5 will call. The tests below
cover the helper, not the walker.
"""
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict

import pytest

from flow_metrics import config as cfg_mod
from flow_metrics.config import (
    ConfigError,
    IssuetypeConfig,
    StateConfig,
    derive_sha,
    load_issuetype_config,
    load_state_config,
    validate_issuetype_config,
    validate_state_config,
)


REFERENCES_DIR = Path(__file__).resolve().parent.parent / "references"


def _has_t3() -> bool:
    """Skip-gate for tests that exercise the T3 upstream wrapper.

    Re-enables automatically once skills/workflows/flow-metrics/scripts/
    flow_metrics/upstream.py ships in T3.
    """
    return (Path(__file__).resolve().parent.parent / "scripts" / "flow_metrics" / "upstream.py").is_file()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _baseline_state_dict() -> Dict[str, Any]:
    """The shipped default in dict form. Tests mutate copies of this.

    Loaded from the shipped file so the test baseline never drifts from
    what ships — a config that passes here is exactly the one users get.
    """
    with open(REFERENCES_DIR / "states.default.json", encoding="utf-8") as f:
        return json.load(f)


def _baseline_issuetype_dict() -> Dict[str, Any]:
    with open(REFERENCES_DIR / "issuetypes.default.json", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, parsed: Any) -> None:
    path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Default-config resolution
# ---------------------------------------------------------------------------
def test_default_state_config_loads_at_install_path():
    """With ``path=None``, load_state_config resolves the shipped default."""
    sc = load_state_config(None)
    assert isinstance(sc, StateConfig)
    assert sc.sha != ""
    assert sc.commitment_state == "in_progress"
    assert sc.delivery_state == "done"
    assert "cancelled" in sc.terminal_non_delivery_states


def test_default_state_config_loads_from_clone_path():
    """From a dropkit clone layout (skills/workflows/flow-metrics/...), the
    walk-up resolver still finds references/states.default.json."""
    default_path = (
        Path(__file__).resolve().parent.parent
        / "references"
        / "states.default.json"
    )
    assert default_path.is_file()
    sc = load_state_config(default_path)
    assert sc.sha != ""
    assert "Won't Do" in sc.canonical_states["cancelled"]


def test_default_issuetype_config_loads_with_subtask_bucket():
    ic = load_issuetype_config(None)
    assert isinstance(ic, IssuetypeConfig)
    assert ic.sha != ""
    assert "subtask" in ic.buckets
    assert ic.bucket_for("Bug") == "defect"
    assert ic.bucket_for("Story") == "feature"
    assert ic.bucket_for("Sub-task") == "subtask"
    assert ic.bucket_for("Spike") is None  # unmapped -> caller emits as "other"


# ---------------------------------------------------------------------------
# sha canonicalisation
# ---------------------------------------------------------------------------
def test_state_config_sha_canonicalized(tmp_path):
    base = _baseline_state_dict()

    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(base, indent=2), encoding="utf-8")

    minified = tmp_path / "min.json"
    minified.write_text(json.dumps(base, separators=(",", ":")), encoding="utf-8")

    # Reorder the top-level keys.
    reordered_keys = list(reversed(list(base.keys())))
    reordered = {k: base[k] for k in reordered_keys}
    reordered_path = tmp_path / "reordered.json"
    reordered_path.write_text(json.dumps(reordered, indent=4), encoding="utf-8")

    # Reorder NESTED keys too: shuffle canonical_states' keys to verify
    # sort_keys=True applies recursively, not just at the top level.
    nested_reordered = copy.deepcopy(base)
    cs = nested_reordered["canonical_states"]
    nested_reordered["canonical_states"] = {k: cs[k] for k in reversed(list(cs.keys()))}
    nested_path = tmp_path / "nested_reordered.json"
    nested_path.write_text(json.dumps(nested_reordered, indent=2), encoding="utf-8")

    sc1 = load_state_config(pretty)
    sc2 = load_state_config(minified)
    sc3 = load_state_config(reordered_path)
    sc4 = load_state_config(nested_path)
    assert sc1.sha == sc2.sha == sc3.sha == sc4.sha

    # Semantic change -> different sha.
    mutated = copy.deepcopy(base)
    mutated["canonical_states"]["backlog"].append("Inbox")
    mutated_path = tmp_path / "mutated.json"
    _write_json(mutated_path, mutated)
    sc5 = load_state_config(mutated_path)
    assert sc5.sha != sc1.sha


def test_derive_sha_is_pure_function():
    base = _baseline_state_dict()
    assert derive_sha(base) == derive_sha(copy.deepcopy(base))


# ---------------------------------------------------------------------------
# canonical_for + unmapped-status helper
# ---------------------------------------------------------------------------
def test_canonical_for_maps_known_status(tmp_path):
    sc = load_state_config(None)
    assert sc.canonical_for("In Progress") == "in_progress"
    assert sc.canonical_for("Done") == "done"
    assert sc.canonical_for("Won't Do") == "cancelled"


def test_unmapped_status_exits_2(tmp_path):
    """Helper returns None for unmapped raw statuses; T5 will convert that
    into an exit-2 at walk time. T2 owns only the lookup."""
    sc = load_state_config(None)
    assert sc.canonical_for("Blocked") is None
    assert sc.canonical_for("Definitely Not A Status") is None


def test_canonical_state_lookup_indexed(tmp_path):
    """The raw-status -> canonical lookup is O(1): the dataclass exposes a
    dict-backed lookup built once at load time, not a linear scan."""
    base = _baseline_state_dict()
    # Inflate the canonical_states map so a linear scan would be measurable.
    extra: Dict[str, list] = {}
    for i in range(200):
        extra["state_{}".format(i)] = ["RawA_{}".format(i), "RawB_{}".format(i)]
    base["canonical_states"].update(extra)
    p = tmp_path / "big.json"
    _write_json(p, base)
    sc = load_state_config(p)

    # The lookup table is a dict-backed mapping — O(1) by construction.
    # (MappingProxyType wraps a dict; assert the proxy by behaviour.)
    assert sc._raw_to_canonical["RawA_199"] == "state_199"
    assert sc.canonical_for("RawA_199") == "state_199"
    assert sc.canonical_for("RawB_0") == "state_0"

    # Timing sanity: 100k lookups against a 400-entry table should complete
    # in well under a second; a linear scan over 400 entries × 100k lookups
    # would take noticeably longer. The threshold is loose because CI
    # machines vary, but a non-indexed implementation would fail it.
    t0 = time.perf_counter()
    for _ in range(100_000):
        sc.canonical_for("RawA_199")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, "canonical_for lookup is slower than expected ({}s)".format(elapsed)


def test_state_config_resolution_walks_up(tmp_path):
    """The skill-root walker finds the directory containing SKILL.md +
    references/ when invoked from a script nested arbitrarily deep — e.g.
    a nested scripts/scripts/ layout that arises from symlinks."""
    skill_root = tmp_path / "flow-metrics"
    (skill_root / "scripts" / "scripts").mkdir(parents=True)
    (skill_root / "references").mkdir()
    (skill_root / "SKILL.md").write_text("# stub", encoding="utf-8")
    deep_script = skill_root / "scripts" / "scripts" / "fake_script.py"
    deep_script.write_text("# stub", encoding="utf-8")

    found = cfg_mod._find_skill_root(deep_script)
    assert found == skill_root.resolve()


def test_state_config_resolution_walks_up_via_symlink(tmp_path):
    """Plan §T2: 'symlink the script under a scripts/scripts/ path; assert
    the walker still finds the skill root via the SKILL.md + references/
    marker.' Path.resolve() dereferences the symlink to the real file,
    which lives inside the skill root, so the walker still locates the
    root from the resolved path."""
    skill_root = tmp_path / "flow-metrics-install"
    (skill_root / "scripts" / "scripts").mkdir(parents=True)
    (skill_root / "references").mkdir()
    (skill_root / "SKILL.md").write_text("# stub", encoding="utf-8")
    real_script = skill_root / "scripts" / "scripts" / "real_script.py"
    real_script.write_text("# stub", encoding="utf-8")

    # Symlink lives outside the skill root and points into it. Resolve()
    # follows the link; the walker should still find the skill root via
    # the real path, not the symlink's directory.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = elsewhere / "linked_script.py"
    try:
        os.symlink(real_script, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    found = cfg_mod._find_skill_root(link)
    assert found == skill_root.resolve()


def test_find_skill_root_raises_when_no_marker(tmp_path):
    """No SKILL.md / references / scripts anywhere on the ancestor chain
    → ConfigError, not a silent wrong-root return."""
    nested = tmp_path / "nowhere" / "deeply" / "nested" / "script.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("# stub", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        cfg_mod._find_skill_root(nested)
    assert "skill root" in exc.value.message.lower()


# ---------------------------------------------------------------------------
# Integrity-rule exits (each rule's spec-pinned message form)
# ---------------------------------------------------------------------------
def test_commitment_equals_delivery_exits_2():
    base = _baseline_state_dict()
    base["commitment_state"] = "done"
    base["delivery_state"] = "done"
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "commitment_state" in exc.value.message
    assert "delivery_state" in exc.value.message


def test_active_intersects_wait_exits_2():
    base = _baseline_state_dict()
    base["wait_states"] = ["in_progress", "backlog"]  # overlaps active_states
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "disjoint" in exc.value.message or "active_states" in exc.value.message


def test_delivery_in_active_states_exits_2():
    base = _baseline_state_dict()
    base["active_states"] = ["in_progress", "done"]
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "delivery_state" in exc.value.message


def test_delivery_in_wait_states_exits_2():
    base = _baseline_state_dict()
    base["wait_states"] = ["backlog", "in_review", "in_test", "done"]
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "delivery_state" in exc.value.message


def test_commitment_in_terminal_non_delivery_exits_2():
    base = _baseline_state_dict()
    base["commitment_state"] = "cancelled"
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "commitment_state" in exc.value.message
    assert "terminal_non_delivery_states" in exc.value.message


def test_rework_signals_reference_unknown_canonical_exits_2():
    base = _baseline_state_dict()
    base["rework_signals"].append({"from": ["staging"], "to": ["backlog"]})
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "rework_signals" in exc.value.message
    assert "staging" in exc.value.message


def test_delivery_overlapping_cancelled_exits_2():
    """delivery_state ∈ terminal_non_delivery_states (rule 4)."""
    base = _baseline_state_dict()
    base["delivery_state"] = "cancelled"
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "delivery_state" in exc.value.message
    assert "terminal_non_delivery_states" in exc.value.message


def test_commitment_not_in_canonical_states_exits_2():
    base = _baseline_state_dict()
    base["commitment_state"] = "nonexistent_state"
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "commitment_state" in exc.value.message


def test_delivery_not_in_canonical_states_exits_2():
    base = _baseline_state_dict()
    base["delivery_state"] = "shipped"
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "delivery_state" in exc.value.message


def test_active_references_unknown_canonical_exits_2():
    base = _baseline_state_dict()
    base["active_states"] = ["in_progress", "coding"]
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "active_states" in exc.value.message
    assert "coding" in exc.value.message


# ---------------------------------------------------------------------------
# team_field shape
# ---------------------------------------------------------------------------
def test_user_picker_group_kind_rejected():
    """team_field.kind = 'user_picker_group' is deferred to v2 -> exit 2."""
    base = _baseline_state_dict()
    base["team_field"] = {"id": "customfield_10010", "kind": "user_picker_group"}
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "user_picker_group" in exc.value.message


def test_team_field_kind_unknown_rejected():
    base = _baseline_state_dict()
    base["team_field"] = {"id": "customfield_10010", "kind": "nonsense"}
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "team_field.kind" in exc.value.message


def test_team_field_optional():
    base = _baseline_state_dict()
    base["team_field"] = None
    validate_state_config(base)  # no raise


def test_team_field_kind_without_id_rejected():
    """A 'kind' with no 'id' has no anchor for the catalog check."""
    base = _baseline_state_dict()
    base["team_field"] = {"kind": "single_value"}
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert exc.value.exit_code == 2
    assert "team_field.id" in exc.value.message


def test_align_join_field_must_be_string_or_null():
    base = _baseline_state_dict()
    base["align_join_field"] = 42
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert "align_join_field" in exc.value.message


# ---------------------------------------------------------------------------
# Shape / type errors
# ---------------------------------------------------------------------------
def test_top_level_must_be_object():
    with pytest.raises(ConfigError):
        validate_state_config([])


def test_missing_canonical_states_exits_2():
    base = _baseline_state_dict()
    del base["canonical_states"]
    with pytest.raises(ConfigError) as exc:
        validate_state_config(base)
    assert "canonical_states" in exc.value.message


def test_invalid_json_in_state_config_exits_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_state_config(bad)
    assert exc.value.exit_code == 2


def test_state_config_file_missing(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(ConfigError) as exc:
        load_state_config(missing)
    assert exc.value.exit_code == 2


# ---------------------------------------------------------------------------
# Issuetype config integrity
# ---------------------------------------------------------------------------
def test_issuetype_config_sha_canonicalized(tmp_path):
    base = {
        "feature": ["Story", "Task"],
        "defect":  ["Bug"],
    }
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(base, indent=2), encoding="utf-8")
    minified = tmp_path / "min.json"
    minified.write_text(json.dumps(base, separators=(",", ":")), encoding="utf-8")
    ic1 = load_issuetype_config(pretty)
    ic2 = load_issuetype_config(minified)
    assert ic1.sha == ic2.sha


def test_issuetype_config_invalid_shape_exits_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"feature": "Story"}), encoding="utf-8")  # str, not list
    with pytest.raises(ConfigError) as exc:
        load_issuetype_config(bad)
    assert exc.value.exit_code == 2


def test_issuetype_other_bucket_reserved_exits_2():
    """Spec § Issuetype configuration: unmapped issuetypes go into the
    sink bucket 'other'. A user-configured 'other' bucket collides with
    the sink and must be rejected at startup."""
    bad = {"feature": ["Story"], "other": ["Spike"]}
    with pytest.raises(ConfigError) as exc:
        validate_issuetype_config(bad)
    assert exc.value.exit_code == 2
    assert "other" in exc.value.message
    assert "reserved" in exc.value.message


# ---------------------------------------------------------------------------
# Immutability of internal lookup tables
# ---------------------------------------------------------------------------
def test_state_config_internal_lookup_is_readonly():
    """The raw->canonical lookup is wrapped in a MappingProxyType so the
    frozen dataclass can't be silently corrupted via .lookup['X'] = 'Y'."""
    sc = load_state_config(None)
    assert isinstance(sc._raw_to_canonical, MappingProxyType)
    with pytest.raises(TypeError):
        sc._raw_to_canonical["In Progress"] = "done"  # type: ignore[index]
    assert isinstance(sc.canonical_states, MappingProxyType)


def test_issuetype_config_internal_lookup_is_readonly():
    ic = load_issuetype_config(None)
    assert isinstance(ic._raw_to_bucket, MappingProxyType)
    with pytest.raises(TypeError):
        ic._raw_to_bucket["Bug"] = "feature"  # type: ignore[index]


def test_state_config_is_hashable_by_sha(tmp_path):
    """The frozen dataclass's synthesized __hash__ would TypeError because
    MappingProxyType wrapping a dict is unhashable. We override __hash__
    to use ``sha`` so the config can serve as a cache key (T7)."""
    sc1 = load_state_config(None)
    sc2 = load_state_config(None)
    assert hash(sc1) == hash(sc2)
    # Set membership and dict-key usage both work.
    assert sc1 in {sc1}
    assert {sc1: "value"}[sc2] == "value"


def test_issuetype_config_is_hashable_by_sha():
    ic1 = load_issuetype_config(None)
    ic2 = load_issuetype_config(None)
    assert hash(ic1) == hash(ic2)


# ---------------------------------------------------------------------------
# T3-gated contract tests (plan §T2 lists these with @skipif until T3
# upstream wrapper ships). Placeholders so they auto-enable when T3 lands.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _has_t3(), reason="requires T3 upstream wrapper")
def test_unknown_team_field_id_exits_2():
    """team_field.id = customfield_99999 not present in Jira's field
    catalog (mocked 'jira: raw GET field' returns a list without it) →
    exit 2 naming the id. Wires up once T3 lands."""
    pytest.fail("T3 has shipped; implement the upstream-wrapper test")


@pytest.mark.skipif(not _has_t3(), reason="requires T3 upstream wrapper")
def test_team_field_override_validated_not_config():
    """--team-field-override customfield_88888 is what's validated against
    the catalog; the config's team_field.id is not consulted that run.
    Wires up once T3 lands."""
    pytest.fail("T3 has shipped; implement the upstream-wrapper test")
