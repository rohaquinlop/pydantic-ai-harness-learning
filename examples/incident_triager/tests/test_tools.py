from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from incident_triager import tools
from incident_triager.bundle import load_deploys
from incident_triager.models import TriageDeps
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

Tool = Callable[..., str]


def call(bundle: Path, tool: Tool, **args: Any) -> str:
    ctx = RunContext(
        deps=TriageDeps(bundle), model=TestModel(), usage=RunUsage()
    )
    return tool(ctx, **args)


@pytest.mark.parametrize(
    ("fixture", "tool", "args", "expected"),
    [
        ("incident", tools.read_alert, {}, '"service": "checkout"'),
        ("incident", tools.list_sources, {}, "metric:db_pool_wait_ms: 181"),
        (
            "incident",
            tools.count_logs,
            {"pattern": "TimeoutError", "bucket_minutes": 60},
            "2026-11-20T11:00:00+00:00 logs/api.log 1160",
        ),
        (
            "incident",
            tools.search_logs,
            {"pattern": "TimeoutError"},
            "[next cursor: 40 of 1160 matches]",
        ),
        (
            "incident",
            tools.search_logs,
            {"pattern": "TimeoutError", "cursor": 1120},
            "[end: 1160 matches]",
        ),
        (
            "incident",
            tools.search_logs,
            {"pattern": "TimeoutError", "until": "2026-11-20T11:02:05Z"},
            "[end: 2 matches]",
        ),
        (
            "incident",
            tools.search_logs,
            {"pattern": ".", "file_glob": "../*"},
            "[end: 0 matches]",
        ),
        (
            "incident",
            tools.read_log,
            {"file": "api.log", "start_line": 2, "max_lines": 1},
            "logs/api.log:2: 2026-11-20T09:00:05+00:00 INFO",
        ),
        (
            "incident",
            tools.read_log,
            {"file": "logs/api.log", "max_lines": 999},
            "[200 of 3320 lines]",
        ),
        ("incident", tools.read_log, {"file": "x.log"}, "No such log file"),
        (
            "incident",
            tools.read_log,
            {"file": "api.log", "max_lines": -5},
            "[1 of 3320 lines]",
        ),
        (
            "incident",
            tools.query_metric,
            {"name": "metric:db_pool_wait_ms"},
            "[downsampled 181 points to 60",
        ),
        (
            "incident",
            tools.query_metric,
            {"name": "requests_per_s", "until": "2026-11-20T09:01:00Z"},
            (
                "metric:requests_per_s\n2026-11-20T09:00:00+00:00 210\n"
                "2026-11-20T09:01:00+00:00 210"
            ),
        ),
        (
            "incident",
            tools.list_deploys,
            {"since": "2026-11-20T10:00:00Z"},
            "deploy:d-102 2026-11-20T11:00:00+00:00 checkout code v2.3.1",
        ),
        (
            "incident",
            tools.git_log,
            {"since": "2026-11-20T10:00:00Z"},
            "Reduce DB pool size",
        ),
        ("incident", tools.git_log, {"path": "db.py"}, "Initial import"),
        (
            "odd",
            tools.search_logs,
            {"pattern": ".", "since": "2026-11-20T09:58:00+00:00"},
            "[end: 2 matches]\n[skipped 1 unparseable lines]",
        ),
        ("odd", tools.search_logs, {"pattern": "x{400}"}, "[+127 chars]"),
        ("odd", tools.count_logs, {"pattern": "."}, "[skipped 1 unparseable"),
        ("odd", tools.list_sources, {}, "repo: no"),
        ("odd", tools.list_deploys, {}, "no deploys in this window"),
        ("odd", tools.git_log, {}, "this bundle has no repo/"),
        ("odd", tools.git_show, {"sha": "abcd"}, "this bundle has no repo/"),
    ],
)
def test_tool_output(
    request: pytest.FixtureRequest,
    fixture: str,
    tool: Tool,
    args: dict[str, Any],
    expected: str,
) -> None:
    assert expected in call(request.getfixturevalue(fixture), tool, **args)


@pytest.mark.parametrize(
    ("tool", "args", "message"),
    [
        (tools.search_logs, {"pattern": "("}, "Invalid regular expression"),
        (
            tools.search_logs,
            {"pattern": "x", "since": "yesterday"},
            "Invalid timestamp",
        ),
        (tools.read_log, {"file": "../alert.json"}, "outside logs/"),
        (tools.count_logs, {"pattern": "x", "file_glob": "/etc/*"}, "relative"),
        (tools.search_logs, {"pattern": "x", "file_glob": ""}, "relative"),
        (tools.query_metric, {"name": "nope"}, "Unknown metric 'nope'"),
        (tools.git_show, {"sha": "--output=/x"}, "is not a commit SHA"),
        (tools.git_show, {"sha": "deadbeef"}, "git failed"),
        (tools.git_log, {"path": "../alert.json"}, "outside repo/"),
    ],
)
def test_tool_asks_for_a_retry(
    incident: Path, tool: Tool, args: dict[str, Any], message: str
) -> None:
    with pytest.raises(ModelRetry, match=message):
        call(incident, tool, **args)


def test_git_show_prints_the_deployed_commit(incident: Path) -> None:
    sha = load_deploys(incident)[1]["commit"]
    out = call(incident, tools.git_show, sha=f"commit:{sha}")
    assert out.startswith(f"commit:{sha} ")
    assert "+POOL_SIZE = 5" in out
