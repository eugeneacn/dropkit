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
    # T5 — delta math (compute_deltas note factories)
    # ------------------------------------------------------------------
    @classmethod
    def metric_absent(cls, metric: str, side_label: str) -> str:
        """Spec lines 110-112: ``"<metric> absent in <file>; cell omitted"``.

        T5 calls this when a metric key is present on one side of the
        comparison but missing on the other. ``side_label`` is the
        per-side label supplied to :func:`compute_deltas` (``"baseline"``
        / ``"current"`` / ``"cohort"`` / ``"control"`` / a basename in
        program-mode rollups) — T5 has no access to filenames, so the
        caller pre-resolves ``<file>`` into the label.
        """
        return "{} absent in {}; cell omitted".format(metric, side_label)

    @classmethod
    def metric_null_on_one_side(cls, metric: str, side_label: str) -> str:
        """Spec line 331: ``"<metric> null in <which-side> for <scope>"``.

        T5 does not know the scope (it operates on raw aggregate dicts),
        so it emits the leading clause only. T3 / T6 may later wrap or
        rewrite if they want to thread the scope through; the stable
        wording lives here.
        """
        return "{} null in {}".format(metric, side_label)

    @classmethod
    def metric_zero_both_sides(cls, metric: str) -> str:
        """Spec lines 323-325: ``"<metric> zero on both sides; percent
        delta undefined"``."""
        return "{} zero on both sides; percent delta undefined".format(metric)

    @classmethod
    def n_differs(
        cls,
        metric: str,
        n_a: int,
        n_b: int,
        side_labels: Tuple[str, str],
    ) -> str:
        """Spec lines 338-345 (per-side ``n`` differs by more than 10%,
        or zero on either side).

        The spec text describes the *behaviour* ("records the per-side
        ``n`` values when they differ by more than 10%") but does NOT
        pin a verbatim wording. T5 introduced the literal form below;
        spec reviewers should bless or amend.

        Literal form (T5-introduced, not spec-pinned):
        ``"n-differs: <metric> n=<n_a> in <a_label>, n=<n_b> in <b_label>
        (>10% delta)"``.
        """
        a_label, b_label = side_labels
        return (
            "n-differs: {} n={} in {}, n={} in {} (>10% delta)".format(
                metric, n_a, a_label, n_b, b_label
            )
        )


__all__ = ["Note"]
