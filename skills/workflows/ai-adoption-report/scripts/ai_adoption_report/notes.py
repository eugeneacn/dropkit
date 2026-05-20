"""T2 notes-string formatter.

Every ``notes`` entry the report emits goes through one of :class:`Note`'s
factory methods. Centralising the wording prevents drift across the
modes (baseline, cohort, program) and keeps the spec-literal strings in
one auditable place.

The factories are pure formatters — they return strings. Buffering and
sorting live in a higher layer (T3/T4's report assembly), mirroring the
``flow_metrics.notes`` collector-vs-formatter split.

Spec line references point at ``docs/specs/ai-adoption-report.md`` unless
noted otherwise.

Stdlib only. Python >= 3.10.
"""
from __future__ import annotations

from typing import Iterable, List, Tuple


class Note:
    """Spec-literal note-string factories.

    Each ``@classmethod`` renders one entry exactly as the spec pins it.
    Where the spec gives a verbatim example the wording is reproduced;
    later tasks (T3/T4/T6) only fill in the stubbed methods, never
    invent new wording outside this class.
    """

    # ------------------------------------------------------------------
    # T2 — emitted during input loading
    # ------------------------------------------------------------------
    @classmethod
    def mixed_major_schema_versions(
        cls,
        versions_and_basenames: Iterable[Tuple[int, str]],
    ) -> str:
        """Spec lines 116-118: ``"mixed-major-schema-versions: <list of
        distinct majors and their input basenames>"``.

        Accepts an iterable of ``(major, basename)`` pairs. Groups by
        major (ascending), sorts basenames lex within each group, and
        renders ``"<major> (<basename>, <basename>)"`` segments joined
        by ``", "``. The spec pins the prefix but not the precise
        rendering of the list; this format keeps the output stable
        across runs (deterministic sort) and human-readable.

        Raises ``ValueError`` on empty input or a single-major input.
        The spec only emits this note when majors disagree; calling
        with one or zero majors is a caller bug.
        ``inputs.collect_mixed_major_note`` is the canonical caller and
        already short-circuits in those cases.
        """
        groups: dict[int, list[str]] = {}
        for major, basename in versions_and_basenames:
            groups.setdefault(int(major), []).append(str(basename))
        if len(groups) < 2:
            raise ValueError(
                "Note.mixed_major_schema_versions requires >=2 distinct "
                "majors; got {}".format(sorted(groups))
            )
        parts: List[str] = []
        for major in sorted(groups):
            basenames = sorted(set(groups[major]))
            parts.append("{} ({})".format(major, ", ".join(basenames)))
        return "mixed-major-schema-versions: " + ", ".join(parts)

    # ------------------------------------------------------------------
    # T3 — baseline-mode stubs (filled when T3 lands)
    # ------------------------------------------------------------------
    @classmethod
    def config_sha_drift(cls, *args, **kwargs) -> str:
        """TODO(T3): spec lines 163-164. Literal form:
        ``"config-sha-drift: state_config_sha <a> -> <b>"`` (similarly
        for ``issuetype_config_sha``). Decide on one method per SHA
        kind or a single method taking the SHA name as a parameter
        when T3 wires it up."""
        raise NotImplementedError("Note.config_sha_drift is a T3 stub")

    @classmethod
    def cohort_jql_mismatch(cls, *args, **kwargs) -> str:
        """TODO(T3): spec lines 173-175. Literal form:
        ``"cohort-jql-mismatch: <baseline-jql> vs <current-jql>; cohort
        breakdown comparison omitted"``."""
        raise NotImplementedError("Note.cohort_jql_mismatch is a T3 stub")

    @classmethod
    def cohort_breakdown_missing_in_baseline(cls, *args, **kwargs) -> str:
        """TODO(T3): spec lines 167-172. When ``--include-cohort-breakdown``
        is set in baseline mode but at least one input lacks
        ``cohort_breakdown``, the flag no-ops with a notes entry. Spec
        does not pin the wording verbatim; T3 picks one and adds the
        literal string here."""
        raise NotImplementedError(
            "Note.cohort_breakdown_missing_in_baseline is a T3 stub"
        )

    @classmethod
    def per_team_ignored_in_baseline(cls, *args, **kwargs) -> str:
        """TODO(T3): spec lines 180-182. Literal form:
        ``"per_team data present in <file>; ignored in baseline mode
        (use program mode for multi-team rollup)"``."""
        raise NotImplementedError(
            "Note.per_team_ignored_in_baseline is a T3 stub"
        )

    # ------------------------------------------------------------------
    # T4 — program-mode stubs
    # ------------------------------------------------------------------
    @classmethod
    def per_team_cohort_deferred(cls, *args, **kwargs) -> str:
        """TODO(T4): spec lines 241-244. Literal form:
        ``"per_team-cohort-deferred: N flattened per-team rows have no
        cohort_breakdown; excluded from cohort rollup"``."""
        raise NotImplementedError("Note.per_team_cohort_deferred is a T4 stub")

    @classmethod
    def per_team_double_counted(cls, *args, **kwargs) -> str:
        """TODO(T4): spec lines 246-250. Literal form:
        ``"per_team-double-counted: <comma-separated input basenames
        whose meta.per_team_double_counted is true, sorted
        codepoint-ascending>; flattened per-team rows may double-count
        issues that span multiple teams"`` (one entry covering all such
        inputs)."""
        raise NotImplementedError("Note.per_team_double_counted is a T4 stub")

    @classmethod
    def duplicate_scope(cls, *args, **kwargs) -> str:
        """TODO(T4): spec lines 222-225. Literal form:
        ``"duplicate scope in input set: <scope dict> in <basename-a>
        and <basename-b>"``. Exits 2; the report never emits this as a
        soft note, but the wording lives here so the error message is
        a single source of truth."""
        raise NotImplementedError("Note.duplicate_scope is a T4 stub")

    # ------------------------------------------------------------------
    # T6 — delta math stubs
    # ------------------------------------------------------------------
    @classmethod
    def metric_absent(cls, *args, **kwargs) -> str:
        """TODO(T6): spec lines 110-112. Literal form:
        ``"<metric> absent in <file>; cell omitted"``."""
        raise NotImplementedError("Note.metric_absent is a T6 stub")


__all__ = ["Note"]
