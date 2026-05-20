#!/usr/bin/env python3
"""Fixture-replay shim that impersonates the ``jira-align`` skill's CLI.

Same shape as ``jira_replay.py`` but for Jira Align's four allowlisted
``raw GET`` patterns:

- ``programs/<id>``
- ``programs/<id>/teams``
- ``portfolios/<id>``
- ``portfolios/<id>/programs``

Fixtures live under ``<FLOW_METRICS_TEST_FIXTURE_DIR>/align/``; one file
per path, slashes replaced with underscores (e.g.,
``align/programs_42_teams.json``).

Stdlib only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_UPSTREAM = 3


def _fixture_dir() -> Path:
    p = os.environ.get("FLOW_METRICS_TEST_FIXTURE_DIR")
    if not p:
        sys.stderr.write("jira_align_replay: FLOW_METRICS_TEST_FIXTURE_DIR not set\n")
        sys.exit(EXIT_UPSTREAM)
    return Path(p)


def _log_call(verb: str, args: list) -> None:
    log_path = os.environ.get("FLOW_METRICS_TEST_CALL_LOG")
    if not log_path:
        return
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"skill": "jira-align", "verb": verb, "args": args}) + "\n")


def _emit_text(text: str, output: str) -> None:
    if output and output != "-":
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        sys.stdout.flush()


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_argv(argv: list):
    fmt = "json"
    output = "-"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--format":
            fmt = argv[i + 1]
            i += 2
        elif a == "--output":
            output = argv[i + 1]
            i += 2
        else:
            break
    sub = argv[i] if i < len(argv) else ""
    rest = argv[i + 1:] if i < len(argv) else []
    return fmt, output, sub, rest


def main(argv=None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    fmt, output, sub, rest = _parse_argv(argv)

    fdir = _fixture_dir()
    _log_call(sub, list(rest))

    if sub != "raw":
        sys.stderr.write("jira_align_replay: only 'raw' is supported\n")
        return EXIT_VALIDATION

    method = rest[0] if rest else ""
    if method != "GET":
        sys.stderr.write("jira_align_replay: only GET is supported\n")
        return EXIT_VALIDATION
    path = rest[1] if len(rest) > 1 else ""

    fp = fdir / "align" / (path.replace("/", "_") + ".json")
    if not fp.is_file():
        sys.stderr.write("jira_align_replay: missing fixture {}\n".format(fp))
        return EXIT_UPSTREAM
    _emit_text(json.dumps(_load_json(fp)), output)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
