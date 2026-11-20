from typing import Any, get_args

import pytest
from pr_reviewer.agent import reviewer
from pr_reviewer.harness_agent import READ_TOOLS, harness_reviewer
from pr_reviewer.models import Current, Findings, ReviewDeps, ReviewResult
from pr_reviewer.review import Engine, run_reviewer
from pr_reviewer.state import LIGHT_MODEL
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.test import TestModel

from examples.pr_reviewer.tests.helpers import (
    CLAUDE_MD,
    HEAD_SHA,
    Call,
    Script,
    final,
    finding,
)

CURRENT = final("Current", {"sha": HEAD_SHA})
ENGINES = pytest.mark.parametrize("engine", get_args(Engine))
AGENTS = {"custom": reviewer, "harness": harness_reviewer}


@pytest.mark.parametrize(
    ("engine", "tool", "args", "expected"),
    [
        ("custom", "glob", {"pattern": "*.py"}, "['calc.py']"),
        ("custom", "glob", {"pattern": "../*"}, "[]"),
        (
            "custom",
            "read_file",
            {"path": "calc.py", "max_lines": 1},
            "1: def ratio(a, b):\n[lines 1-1 of 2]",
        ),
        (
            "custom",
            "read_file",
            {"path": "missing.py"},
            "missing.py is not a file",
        ),
        (
            "custom",
            "read_file",
            {"path": "../outside.txt"},
            "outside the policy base",
        ),
        (
            "custom",
            "grep",
            {"pattern": r"return \w", "file_glob": "*.py"},
            "calc.py:2:",
        ),
        ("custom", "grep", {"pattern": "("}, "Invalid regular expression"),
        ("harness", "find_files", {"pattern": "*.py"}, "calc.py"),
        ("harness", "read_file", {"path": "calc.py"}, "def ratio(a, b):"),
        (
            "harness",
            "read_file",
            {"path": "../outside.txt"},
            "outside the project root",
        ),
        ("harness", "grep", {"pattern": r"return \w"}, "calc.py"),
    ],
)
def test_tool_result_seen_by_model(
    deps: ReviewDeps,
    engine: Engine,
    tool: str,
    args: dict[str, Any],
    expected: str,
) -> None:
    script = Script([[(tool, args)], [CURRENT]])
    result = run_reviewer(engine, "review", script.model(), deps)
    seen = [
        str(part.content)
        for message in result.all_messages()
        for part in message.parts
        if getattr(part, "tool_name", None) == tool and hasattr(part, "content")
    ]
    assert expected in seen[0]


@pytest.mark.parametrize(
    ("engine", "autoloaded"), [("custom", False), ("harness", True)]
)
def test_rules_in_instructions(
    deps: ReviewDeps, engine: Engine, autoloaded: bool
) -> None:
    script = Script([[CURRENT]])
    run_reviewer(engine, "review", script.model(), deps)
    assert (CLAUDE_MD.strip() in script.instructions[0]) is autoloaded


@pytest.mark.parametrize(
    ("replies", "expected"),
    [
        pytest.param(
            [final("Current", {"sha": "zzz"}), CURRENT],
            Current(sha=HEAD_SHA),
            id="wrong-sha-then-right",
        ),
        pytest.param(
            [
                final("Findings", finding("nope.py")),
                final("Findings", finding()),
            ],
            Findings.model_validate(finding()),
            id="invented-file-then-diff-file",
        ),
        pytest.param(
            [final("Findings", finding("CLAUDE.md"))],
            Findings.model_validate(finding("CLAUDE.md")),
            id="file-outside-diff-in-base",
        ),
        pytest.param(
            [final("Findings", finding("../outside.txt")), CURRENT],
            Current(sha=HEAD_SHA),
            id="path-escape-rejected",
        ),
    ],
)
@ENGINES
def test_output_validator(
    deps: ReviewDeps,
    engine: Engine,
    replies: list[Call],
    expected: ReviewResult,
) -> None:
    script = Script([[reply] for reply in replies])
    result = run_reviewer(engine, "review", script.model(), deps)
    assert result.output == expected


@ENGINES
def test_output_validator_gives_up_after_retries(
    deps: ReviewDeps, engine: Engine
) -> None:
    script = Script(
        [[final("Findings", finding(f"nope{i}.py"))] for i in range(2)]
    )
    with pytest.raises(UnexpectedModelBehavior, match="output retries"):
        run_reviewer(engine, "review", script.model(), deps)


@pytest.mark.parametrize(
    ("engine", "tools"),
    [("custom", {"read_file", "glob", "grep"}), ("harness", set(READ_TOOLS))],
)
def test_test_model_sees_only_read_tools(
    deps: ReviewDeps, engine: Engine, tools: set[str]
) -> None:
    model = TestModel(call_tools=[], custom_output_args=finding())
    with AGENTS[engine].override(model=model):
        result = run_reviewer(engine, "review", LIGHT_MODEL, deps)
    assert result.output == Findings.model_validate(finding())
    params = model.last_model_request_parameters
    assert params is not None
    assert {t.name for t in params.function_tools} == tools
