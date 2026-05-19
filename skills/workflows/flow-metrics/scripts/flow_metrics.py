#!/usr/bin/env python3
"""flow-metrics CLI entry point.

T1 scaffold: argparse, version guard, window resolution, path safety,
flag-combo validation. Every command path is a stub that prints
"not yet implemented" and exits 0. Later tasks fill in the actual work.

Stdlib only. Python >= 3.10.
"""
from __future__ import annotations

import sys

PYTHON_FLOOR = (3, 10)

EXIT_OK = 0
EXIT_USER_ABORT = 1
EXIT_VALIDATION = 2
EXIT_UPSTREAM = 3


def _check_python_version(version_info=None) -> None:
    info = version_info if version_info is not None else sys.version_info
    if (info[0], info[1]) < PYTHON_FLOOR:
        floor = ".".join(str(x) for x in PYTHON_FLOOR)
        have = ".".join(str(info[i]) for i in range(min(3, len(info))))
        print(
            "flow-metrics requires Python {} or later; running under {}".format(floor, have),
            file=sys.stderr,
        )
        sys.exit(EXIT_VALIDATION)


# Run guard BEFORE internal imports so any 3.10+ syntax in sibling modules
# (T2+: config.py, upstream.py, ...) only parses on a supported interpreter.
# stdlib imports below are 3.7-safe; internal imports follow.
_check_python_version()

import argparse
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import clock


class ValidationError(Exception):
    """Flag-combo / config-shape / path-safety errors. Exit 2."""


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------
_POSIX_SYSTEM_ROOTS = ("/etc", "/sys", "/proc", "/dev", "/boot")
# macOS firmlinks: /etc -> /private/etc. After Path.resolve() "/etc/foo"
# becomes "/private/etc/foo" on darwin. /var and /tmp are NOT spec-banned
# roots (only /etc /sys /proc /dev /boot are), and the user's temp dir
# lives under /private/var, so don't touch it.
_DARWIN_RESOLVED_ROOTS = ("/private/etc",)
_WINDOWS_SYSTEM_ROOTS = (
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
)


def _is_under_system_root(p: Path) -> bool:
    s = str(p)
    if os.name == "nt":
        # Normalize separators so "C:/Windows/foo" and "C:\\Windows\\foo" both
        # match the canonical roots stored with backslashes. Case-insensitive
        # per Windows filesystem semantics.
        sl = s.lower().replace("\\", "/")
        for r in _WINDOWS_SYSTEM_ROOTS:
            rl = r.lower().replace("\\", "/")
            if sl == rl or sl.startswith(rl + "/"):
                return True
        return False
    # posix (linux, darwin)
    roots = _POSIX_SYSTEM_ROOTS
    if sys.platform == "darwin":
        roots = roots + _DARWIN_RESOLVED_ROOTS
    for r in roots:
        if s == r or s.startswith(r + "/"):
            return True
    return False


def validate_path(p: str, label: str) -> Path:
    """Reject null bytes and any path inside an OS system root.

    Checks both the raw path string and the resolved form (so users can't
    sneak past via /private/etc on darwin or via symlinks).
    """
    if "\x00" in p:
        raise ValidationError("--{}: path contains a null byte".format(label))
    raw = Path(p)
    candidates = [raw]
    try:
        candidates.append(raw.resolve())
    except OSError:
        pass
    for c in candidates:
        if _is_under_system_root(c):
            raise ValidationError(
                "--{}: path '{}' is under a system root and is refused".format(label, p)
            )
    return raw


# ---------------------------------------------------------------------------
# Window parsing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Window:
    """Resolved window. ``to_exclusive`` is one day past the named end day."""
    from_date: date           # inclusive named day
    to_date: date             # inclusive named day
    from_utc: datetime        # from_date 00:00:00 UTC
    to_exclusive_utc: datetime  # (to_date + 1d) 00:00:00 UTC


def _parse_iso_date(s: str, label: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(
            "--{}: invalid date '{}'; expected YYYY-MM-DD".format(label, s)
        )


def parse_window(
    from_str: Optional[str],
    to_str: Optional[str],
    now: Optional[datetime] = None,
) -> Window:
    """Resolve the window.

    Both ``--from`` and ``--to`` are inclusive of the named day. Internally
    the window is ``[from 00:00 UTC, (to + 1 day) 00:00 UTC)`` — the
    ``to_exclusive_utc`` field is the open upper bound.

    Default window is the last 90 days ending today (UTC). "90 days" refers
    to the ``to − from`` difference; the inclusive-day count is 91.
    """
    src = now if now is not None else clock.today_utc()
    # Treat naive datetimes as UTC rather than letting astimezone() interpret
    # them as local-tz; clock.today_utc() always returns tz-aware UTC, but
    # tests / future callers might pass naive instants by mistake.
    if src.tzinfo is None:
        src = src.replace(tzinfo=timezone.utc)
    else:
        src = src.astimezone(timezone.utc)
    today = src.date()
    if to_str is None:
        to_d = today
    else:
        to_d = _parse_iso_date(to_str, "to")
    if from_str is None:
        from_d = to_d - timedelta(days=90)
    else:
        from_d = _parse_iso_date(from_str, "from")
    if from_d > to_d:
        raise ValidationError(
            "--from ({}) must be <= --to ({})".format(from_d.isoformat(), to_d.isoformat())
        )
    from_utc = datetime(from_d.year, from_d.month, from_d.day, tzinfo=timezone.utc)
    to_excl = datetime(to_d.year, to_d.month, to_d.day, tzinfo=timezone.utc) + timedelta(days=1)
    return Window(from_date=from_d, to_date=to_d, from_utc=from_utc, to_exclusive_utc=to_excl)


# ---------------------------------------------------------------------------
# JQL composition
# ---------------------------------------------------------------------------
def compose_jql(scope_clause: str, user_clause: Optional[str], *, order_by_key: bool = True) -> str:
    """Compose a JQL query from a scope clause and an optional user clause.

    Always wraps both clauses in parentheses before ``AND`` (spec § Inputs,
    Decision #15). Appends ``ORDER BY key ASC`` for canonical iteration
    order unless suppressed (spec § Output canonicalization).

    Used identically for ``--jql`` (Jira) and ``--align-filter`` (Jira
    Align OData) at the string-shape level — both follow the same
    parenthesization rule.
    """
    if user_clause is not None and user_clause.strip() != "":
        body = "({}) AND ({})".format(scope_clause, user_clause)
    else:
        body = scope_clause
    if order_by_key:
        return body + " ORDER BY key ASC"
    return body


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------
ALL_METRICS = (
    "cycle_time",
    "lead_time",
    "throughput",
    "wip",
    "flow_load",
    "rework_rate",
    "flow_time",
    "flow_efficiency",
    "flow_distribution",
    "defect_ratio",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flow-metrics",
        description=(
            "Compute DORA / Flow Framework metrics for a Jira project, team, "
            "Jira Align program, or portfolio over a time window."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Scope (exactly one of project / program-id / portfolio-id required;
    # validated manually so we can also enforce --team coupling).
    parser.add_argument("--project", help="Jira project key. Mutually exclusive with --program-id / --portfolio-id.")
    parser.add_argument("--team", help="Sub-scope within a --project. Only valid with --project.")
    parser.add_argument("--program-id", dest="program_id", help="Jira Align program ID.")
    parser.add_argument("--portfolio-id", dest="portfolio_id", help="Jira Align portfolio ID.")

    # Window
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD",
                        help="Window start (inclusive). Default: --to minus 90 days.")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD",
                        help="Window end (inclusive). Default: today (UTC).")

    # Filters
    parser.add_argument("--jql", help="Extra JQL ANDed into the scope query. Always parenthesized.")
    parser.add_argument("--align-filter", dest="align_filter",
                        help="Extra OData ANDed into Jira Align queries. Always parenthesized.")
    parser.add_argument("--cohort-jql", dest="cohort_jql",
                        help="JQL marking matching issues with cohort: true.")

    # Output selection
    parser.add_argument("--metrics", help="Comma list. Default: all. Names: " + ", ".join(ALL_METRICS))

    # Config files
    parser.add_argument("--state-config", dest="state_config",
                        help="JSON state-mapping config. Defaults to shipped references/states.default.json.")
    parser.add_argument("--issuetype-config", dest="issuetype_config",
                        help="JSON issuetype-bucket config. Defaults to shipped references/issuetypes.default.json.")

    # Overrides
    parser.add_argument("--team-field-override", dest="team_field_override",
                        help="Override team_field.id from the state config.")
    parser.add_argument("--align-join-field", dest="align_join_field",
                        help="Override the Jira <-> Jira Align join field.")
    parser.add_argument("--align-teams-path", dest="align_teams_path",
                        help="Override the Jira Align teams enumeration path.")
    parser.add_argument("--include-subtasks", dest="include_subtasks", action="store_true",
                        help="Include subtasks in throughput / cycle / lead / flow_efficiency / rework_rate.")

    # Output format
    parser.add_argument("--format", choices=("json", "csv"), default="json", help="Output format.")
    parser.add_argument("--output", help="Write to file instead of stdout. Required for --per-issue.")
    parser.add_argument("--per-issue", dest="per_issue", action="store_true",
                        help="Emit one JSONL row per issue. Requires --output.")
    parser.add_argument("--yes", action="store_true",
                        help="Overwrite --output without prompting.")

    # Cache / debug
    parser.add_argument("--no-cache", dest="no_cache", action="store_true", help="Bypass the on-disk cache.")
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")

    return parser


# ---------------------------------------------------------------------------
# Flag-combo validation
# ---------------------------------------------------------------------------
def validate_args(args: argparse.Namespace) -> None:
    """Apply flag-combo rules. Raise ``ValidationError`` (exit 2) on miss.

    Runs before any upstream call. Order matters only for error-message
    clarity — every check is total.
    """
    scopes = [
        ("--project", args.project),
        ("--program-id", args.program_id),
        ("--portfolio-id", args.portfolio_id),
    ]
    present = [name for name, value in scopes if value is not None]
    if len(present) == 0:
        raise ValidationError(
            "exactly one of --project / --program-id / --portfolio-id is required; none given"
        )
    if len(present) > 1:
        raise ValidationError(
            "exactly one of --project / --program-id / --portfolio-id may be given; got {}".format(
                ", ".join(present)
            )
        )

    if args.team is not None and args.project is None:
        raise ValidationError("--team is only valid with --project")

    if args.per_issue and args.output is None:
        raise ValidationError("--per-issue requires --output FILE")

    # Path safety on every path-bearing flag.
    if args.output is not None:
        validate_path(args.output, "output")
    if args.state_config is not None:
        validate_path(args.state_config, "state-config")
    if args.issuetype_config is not None:
        validate_path(args.issuetype_config, "issuetype-config")

    # Metrics list (just shape-check here; no fail-on-unknown until T10
    # owns the canonical list emission. But typo'd metric names should
    # surface early).
    if args.metrics is not None:
        names = [m.strip() for m in args.metrics.split(",") if m.strip()]
        unknown = [n for n in names if n not in ALL_METRICS]
        if unknown:
            raise ValidationError(
                "--metrics: unknown metric(s) {}; valid: {}".format(
                    ", ".join(unknown), ", ".join(ALL_METRICS)
                )
            )


# ---------------------------------------------------------------------------
# Overwrite-confirm helper (T1 ships the prompt + TTY-detection helper that
# the test exercises via a stub; the actual write path is T10).
# ---------------------------------------------------------------------------
def confirm_overwrite(
    path: Path,
    *,
    yes: bool,
    stdin_isatty: Optional[bool] = None,
    stdout_isatty: Optional[bool] = None,
    prompt_response: Optional[str] = None,
) -> bool:
    """Return True iff overwrite is allowed.

    - ``--yes`` short-circuits to True.
    - No TTY and no ``--yes`` -> abort (False). Caller exits 1.
    - TTY present -> consult ``prompt_response`` (test seam) or stdin.
    """
    if yes:
        return True
    if not path.exists():
        return True
    if stdin_isatty is None:
        stdin_isatty = sys.stdin.isatty()
    if stdout_isatty is None:
        stdout_isatty = sys.stdout.isatty()
    if not (stdin_isatty and stdout_isatty):
        return False
    if prompt_response is None:
        try:
            prompt_response = input("Overwrite {} ? [y/N] ".format(path))
        except EOFError:
            return False
    return prompt_response.strip().lower() in ("y", "yes")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        validate_args(args)
        window = parse_window(args.from_date, args.to_date)
    except ValidationError as e:
        print("error: {}".format(e), file=sys.stderr)
        return EXIT_VALIDATION

    # Overwrite confirmation gate. Real write path is in T10; T1 just
    # owns the TTY-abort guarantee so the contract test can lock it in.
    if args.output is not None:
        out_path = Path(args.output)
        if not confirm_overwrite(out_path, yes=args.yes):
            print(
                "error: --output {} exists and overwrite was not confirmed".format(out_path),
                file=sys.stderr,
            )
            return EXIT_USER_ABORT

    # Stub. Real command paths land in T2+.
    print(
        "not yet implemented (T1 scaffold). window=[{}, {}], scope={}".format(
            window.from_date.isoformat(),
            window.to_date.isoformat(),
            _scope_summary(args),
        )
    )
    return EXIT_OK


def _scope_summary(args: argparse.Namespace) -> str:
    if args.project is not None:
        if args.team is not None:
            return "project={} team={}".format(args.project, args.team)
        return "project={}".format(args.project)
    if args.program_id is not None:
        return "program-id={}".format(args.program_id)
    if args.portfolio_id is not None:
        return "portfolio-id={}".format(args.portfolio_id)
    return "(unknown)"


if __name__ == "__main__":
    sys.exit(main())
