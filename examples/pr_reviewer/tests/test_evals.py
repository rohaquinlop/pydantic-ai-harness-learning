import re
from collections.abc import Callable

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from examples.pr_reviewer.evals.review_evals import run_evals
from examples.pr_reviewer.tests.helpers import final, finding

Reply = Callable[[str], ToolCallPart]


def _prompt(messages: list[ModelMessage]) -> str:
    return "".join(
        str(p.content)
        for p in messages[0].parts
        if isinstance(p, UserPromptPart)
    )


def silent(prompt: str) -> ToolCallPart:
    sha = re.search(r"Candidate head SHA: (\w+)", prompt)
    assert sha
    return ToolCallPart(*final("Current", {"sha": sha.group(1)}))


def first_changed_file(prompt: str) -> ToolCallPart:
    file = re.search(r"^\+\+\+ b/(\S+)", prompt, re.MULTILINE)
    assert file
    args = finding(file.group(1))
    args["findings"][0]["line"] = 1
    return ToolCallPart(*final("Findings", args))


def model_from(reply: Reply) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[reply(_prompt(messages))])

    return FunctionModel(respond)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        pytest.param(
            silent,
            {
                "guard_removed": (False, None, 0),
                "off_by_one": (False, None, 0),
                "rule_violation": (False, None, 0),
                "scope_creep": (False, None, 0),
                "clean_docstring": (None, True, 0),
            },
            id="always-current",
        ),
        pytest.param(
            first_changed_file,
            {
                "guard_removed": (True, None, 0),
                "off_by_one": (False, None, 1),
                "rule_violation": (True, None, 0),
                "scope_creep": (True, None, 0),
                "clean_docstring": (None, False, 1),
            },
            id="flags-line-1",
        ),
    ],
)
def test_evaluators_score_each_case(
    reply: Reply, expected: dict[str, tuple[bool | None, bool | None, int]]
) -> None:
    report = run_evals(model_from(reply))

    def value(results: dict, key: str) -> bool | None:
        return results[key].value if key in results else None

    assert {
        c.name: (
            value(c.assertions, "finds_bug"),
            value(c.assertions, "clean_is_current"),
            c.scores["ExtraFindings"].value,
        )
        for c in report.cases
    } == expected
