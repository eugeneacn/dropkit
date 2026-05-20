#!/usr/bin/env python3
"""Fixture-replay shim that impersonates the ``jira`` skill's CLI.

The integration tests point ``FLOW_METRICS_JIRA_SCRIPT`` at this script
so :class:`flow_metrics.upstream.JiraClient` invokes it via subprocess
instead of the real ``jira`` skill. The argv shape matches what
``JiraClient`` produces (``--format ... --output ... <subcommand> ...``);
responses are loaded from JSON / JSONL files under the directory named
by ``FLOW_METRICS_TEST_FIXTURE_DIR``.

The script also appends one line per invocation to
``FLOW_METRICS_TEST_CALL_LOG`` (when set) so tests can assert which
upstream verbs / paths the pipeline actually invoked — the read-only
allowlist contract is enforced by walking that log.

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
        sys.stderr.write("jira_replay: FLOW_METRICS_TEST_FIXTURE_DIR not set\n")
        sys.exit(EXIT_UPSTREAM)
    return Path(p)


def _log_call(verb: str, args: list) -> None:
    log_path = os.environ.get("FLOW_METRICS_TEST_CALL_LOG")
    if not log_path:
        return
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"skill": "jira", "verb": verb, "args": args}) + "\n")


def _emit_text(text: str, output: str) -> None:
    if output and output != "-":
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        sys.stdout.flush()


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        out.append(json.loads(s))
    return out


def _parse_argv(argv: list):
    """Mimic jira.py's argparse: ``--format X --output Y subcommand rest...``.

    We hand-parse rather than using argparse so ``raw GET <path> --param k=v``
    keeps its ``--param k=v`` repetition behaviour without argparse mangling
    it into a list of one entry per flag instance.
    """
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


def _params_from_rest(rest: list) -> dict:
    params: dict = {}
    j = 0
    while j < len(rest):
        if rest[j] == "--param" and j + 1 < len(rest):
            k, _, v = rest[j + 1].partition("=")
            params[k] = v
            j += 2
        else:
            j += 1
    return params


def main(argv=None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    fmt, output, sub, rest = _parse_argv(argv)

    fdir = _fixture_dir()
    _log_call(sub, list(rest))

    if sub == "check":
        _emit_text(json.dumps({"ok": True}), output)
        return EXIT_OK

    if sub == "whoami":
        path = fdir / "whoami.json"
        payload = _load_json(path) if path.is_file() else {"accountId": "test-account"}
        _emit_text(json.dumps(payload), output)
        return EXIT_OK

    if sub == "get-project":
        key = rest[0] if rest else ""
        path = fdir / "get-project.{}.json".format(key)
        if not path.is_file():
            sys.stderr.write("jira_replay: missing fixture {}\n".format(path))
            return EXIT_UPSTREAM
        _emit_text(json.dumps(_load_json(path)), output)
        return EXIT_OK

    if sub == "get-issue":
        key = rest[0] if rest else ""
        path = fdir / "get-issue.{}.json".format(key)
        if not path.is_file():
            sys.stderr.write("jira_replay: missing fixture {}\n".format(path))
            return EXIT_UPSTREAM
        _emit_text(json.dumps(_load_json(path)), output)
        return EXIT_OK

    if sub == "search":
        # JQL is in rest[0]. We pick a fixture by the override env var (set by
        # the cohort path which needs a different result set) or fall back to
        # search.jsonl.
        override = os.environ.get("FLOW_METRICS_TEST_SEARCH_OVERRIDE")
        # The cohort search composes "(scope) AND (cohort_jql) ORDER BY key ASC"
        # — detect the cohort-jql substring so the same replay can serve both
        # the main and cohort searches without an env handoff.
        jql = rest[0] if rest else ""
        cohort_marker = os.environ.get("FLOW_METRICS_TEST_COHORT_MARKER")
        if cohort_marker and cohort_marker in jql:
            search_file = fdir / "search.cohort.jsonl"
            if not search_file.is_file():
                sys.stderr.write("jira_replay: missing cohort fixture {}\n".format(search_file))
                return EXIT_UPSTREAM
        elif override:
            search_file = fdir / override
        else:
            search_file = fdir / "search.jsonl"
        if not search_file.is_file():
            sys.stderr.write("jira_replay: missing fixture {}\n".format(search_file))
            return EXIT_UPSTREAM
        items = _load_jsonl(search_file)
        # JiraClient.search() uses ``--format jsonl --output -`` (streaming);
        # emit one JSON object per line regardless of the declared format —
        # the parent will always be streaming.
        lines = "".join(json.dumps(item) + "\n" for item in items)
        _emit_text(lines, output)
        return EXIT_OK

    if sub == "raw":
        method = rest[0] if rest else ""
        if method != "GET":
            sys.stderr.write("jira_replay: only GET is supported\n")
            return EXIT_VALIDATION
        path = rest[1] if len(rest) > 1 else ""
        params = _params_from_rest(rest[2:])

        # Changelog drain: issue/<KEY>/changelog ± pageToken / startAt
        if path.startswith("issue/") and path.endswith("/changelog"):
            key = path.split("/")[1]
            token = params.get("pageToken") or params.get("startAt")
            if token:
                fp = fdir / "changelog" / "{}.{}.json".format(key, token)
            else:
                fp = fdir / "changelog" / "{}.json".format(key)
            if not fp.is_file():
                sys.stderr.write("jira_replay: missing fixture {}\n".format(fp))
                return EXIT_UPSTREAM
            _emit_text(json.dumps(_load_json(fp)), output)
            return EXIT_OK

        # Field catalog / project statuses
        fp = fdir / "raw" / (path.replace("/", "_") + ".json")
        if not fp.is_file():
            sys.stderr.write("jira_replay: missing fixture {}\n".format(fp))
            return EXIT_UPSTREAM
        _emit_text(json.dumps(_load_json(fp)), output)
        return EXIT_OK

    sys.stderr.write("jira_replay: unknown subcommand {!r}\n".format(sub))
    return EXIT_VALIDATION


if __name__ == "__main__":
    sys.exit(main())
