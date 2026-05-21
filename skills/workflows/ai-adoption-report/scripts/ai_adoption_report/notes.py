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
    # T3 — baseline-mode + cohort-mode
    # ------------------------------------------------------------------
    @classmethod
    def config_sha_drift(cls, sha_name: str, a: str, b: str) -> str:
        """Spec line 163: ``"config-sha-drift: <sha_name> <a> → <b>"``.

        ``sha_name`` is ``"state_config_sha"`` or ``"issuetype_config_sha"``;
        the spec gives both variants under one rule.
        """
        return "config-sha-drift: {} {} → {}".format(sha_name, a, b)

    @classmethod
    def cohort_jql_mismatch(cls, a_jql: str, b_jql: str) -> str:
        """Spec lines 173-175: ``"cohort-jql-mismatch: <baseline-jql>
        vs <current-jql>; cohort breakdown comparison omitted"``."""
        return (
            "cohort-jql-mismatch: {} vs {}; cohort breakdown comparison "
            "omitted".format(a_jql, b_jql)
        )

    @classmethod
    def cohort_breakdown_absent_noop(cls, basenames: Iterable[str]) -> str:
        """Spec lines 167-172. ``--include-cohort-breakdown`` set in
        baseline mode but at least one input lacks ``cohort_breakdown``;
        the flag no-ops.

        Spec does not pin the wording verbatim. Literal form chosen by T3
        (spec reviewers should bless or amend):
        ``"cohort-breakdown-absent: cohort_breakdown missing from
        <comma-sep basenames sorted codepoint-ascending>;
        --include-cohort-breakdown no-op"``.
        """
        names = sorted(set(str(b) for b in basenames))
        if not names:
            raise ValueError(
                "Note.cohort_breakdown_absent_noop requires >=1 basename"
            )
        return (
            "cohort-breakdown-absent: cohort_breakdown missing from {}; "
            "--include-cohort-breakdown no-op".format(", ".join(names))
        )

    @classmethod
    def per_team_ignored_in_baseline(cls, basename: str) -> str:
        """Spec lines 180-182: ``"per_team data present in <file>;
        ignored in baseline mode (use program mode for multi-team
        rollup)"``."""
        return (
            "per_team data present in {}; ignored in baseline mode "
            "(use program mode for multi-team rollup)".format(basename)
        )

    # ------------------------------------------------------------------
    # T4 — program-mode input discovery, dedupe, overlap, per_team
    # ------------------------------------------------------------------
    @classmethod
    def per_team_cohort_deferred(cls, n_rows: int) -> str:
        """Spec lines 241-244. Literal form:
        ``"per_team-cohort-deferred: N flattened per-team rows have no
        cohort_breakdown; excluded from cohort rollup"``.

        T4 emits this only when ``--include-cohort-breakdown`` is set
        and at least one per_team-flattened row exists (n_rows > 0).
        ``n_rows`` is the count of ``from_per_team=True`` rows in
        :class:`ProgramInputs.scopes`.
        """
        return (
            "per_team-cohort-deferred: {} flattened per-team rows have no "
            "cohort_breakdown; excluded from cohort rollup".format(n_rows)
        )

    @classmethod
    def per_team_double_counted(cls, basenames: Iterable[str]) -> str:
        """Spec lines 246-250. Literal form:
        ``"per_team-double-counted: <comma-separated input basenames
        whose meta.per_team_double_counted is true, sorted
        codepoint-ascending>; flattened per-team rows may double-count
        issues that span multiple teams"`` (one entry covering all such
        inputs).

        ``basenames`` need not be pre-sorted; the factory sorts
        codepoint-ascending so callers can pass any iterable.
        """
        sorted_names = sorted(set(basenames))
        if not sorted_names:
            raise ValueError(
                "Note.per_team_double_counted requires at least one basename"
            )
        return (
            "per_team-double-counted: {}; flattened per-team rows may "
            "double-count issues that span multiple teams".format(
                ", ".join(sorted_names)
            )
        )

    @classmethod
    def duplicate_scope(
        cls,
        scope: dict,
        sources: Iterable[Tuple[str, bool]],
    ) -> str:
        """Spec lines 222-225. Literal form:
        ``"duplicate scope in input set: <scope dict> in <basename-a>
        and <basename-b>"``.

        Exits 2; the report never emits this as a soft note, but the
        wording lives here so the error message has a single source of
        truth.

        ``sources`` is an iterable of ``(basename, from_per_team)``
        tuples. ``from_per_team=True`` basenames are annotated with
        ``" (per_team flattened)"`` to distinguish a post-flatten
        collision (plan lines 287-301) from a pre-flatten duplicate of
        two explicit inputs. The annotation deliberately omits the
        source's parent kind (program/portfolio/project+team) because
        the per_team flattening path admits all three; the source's
        identity is the basename, which is already in the message.

        The factory sorts sources by basename codepoint-ascending; if
        more than two are present, every basename is listed.
        ``<scope dict>`` is rendered with keys sorted so the message is
        stable across Python dict-order accidents.
        """
        items = sorted(sources, key=lambda s: s[0])
        if len(items) < 2:
            raise ValueError(
                "Note.duplicate_scope requires at least two sources; got {}".format(
                    items
                )
            )
        labels = [
            "{} (per_team flattened)".format(b) if from_per_team else b
            for b, from_per_team in items
        ]
        if len(labels) == 2:
            joined = "{} and {}".format(labels[0], labels[1])
        else:
            joined = "{}, and {}".format(", ".join(labels[:-1]), labels[-1])
        sorted_scope = {k: scope[k] for k in sorted(scope)}
        return "duplicate scope in input set: {} in {}".format(
            sorted_scope, joined
        )

    @classmethod
    def overlapping_scopes(
        cls,
        pairs: Iterable[Tuple[Tuple[dict, str], Tuple[dict, str]]],
    ) -> str:
        """Spec lines 210-228. The spec pins the *behaviour* ("exit 2
        listing the overlapping scopes") but not a verbatim wording. T4
        introduces this literal form so the error is a single source of
        truth across the overlap rules:

        ``"overlapping scopes in input set: <a-basename> (<a-scope>) "
        "overlaps <b-basename> (<b-scope>); ..."``

        ``pairs`` is an iterable of ``((scope_a, basename_a),
        (scope_b, basename_b))`` tuples. Multiple overlaps are joined
        with ``"; "`` so a single error names every offending pair.
        """
        items = list(pairs)
        if not items:
            raise ValueError(
                "Note.overlapping_scopes requires at least one pair"
            )

        def _pair_str(pair):
            (scope_a, basename_a), (scope_b, basename_b) = pair
            sa = {k: scope_a[k] for k in sorted(scope_a)}
            sb = {k: scope_b[k] for k in sorted(scope_b)}
            return "{} ({}) overlaps {} ({})".format(
                basename_a, sa, basename_b, sb
            )

        return "overlapping scopes in input set: " + "; ".join(
            _pair_str(p) for p in items
        )

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
