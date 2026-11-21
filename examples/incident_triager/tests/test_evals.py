from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from incident_triager.bundle import load_deploys
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from examples.incident_triager.evals.cases import (
    CASES,
    IncidentCase,
    PlantedCause,
    build_bundle,
)
from examples.incident_triager.evals.triage_evals import run_evals
from examples.incident_triager.tests.helpers import final, hypothesis

Reply = Callable[[PlantedCause], list[dict[str, Any]]]
DECOY = hypothesis("capacity", "metric:requests_per_s")
CAUSES = {c.inputs.title: c.metadata for c in CASES if c.metadata}


def right(cause: PlantedCause) -> dict[str, Any]:
    return hypothesis(cause.category, cause.key_refs[0])


def model_from(reply: Reply) -> FunctionModel:
    """Look at the bundle with two tools, then answer for the case's alert."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            calls = [("list_sources", {}), ("list_deploys", {})]
        else:
            prompt = "".join(
                str(p.content)
                for p in messages[0].parts
                if isinstance(p, UserPromptPart)
            )
            title = prompt.split("Alert: ")[1].splitlines()[0]
            calls = [final(*reply(CAUSES[title]))]
        return ModelResponse(parts=[ToolCallPart(n, a) for n, a in calls])

    return FunctionModel(respond)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_case_builds_and_lists_its_key_refs(case: Any, tmp_path: Path) -> None:
    inputs: IncidentCase = case.inputs
    bundle = build_bundle(inputs, tmp_path / "b")
    deploys = load_deploys(bundle)
    assert [d["id"] for d in deploys] == [d.id for d in inputs.deploys]
    assert all(len(d["commit"]) >= 7 for d in deploys)
    listed = "\n".join(
        [*(f"deploy:{d['id']}" for d in deploys)]
        + [f"metric:{m}" for m in inputs.metrics]
        + [f"logs/{name}" for name in inputs.logs]
    )
    assert all(key in listed for key in case.metadata.key_refs)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        pytest.param(
            lambda cause: [right(cause)],
            {c.name: (True, True, 1) for c in CASES},
            id="right-first",
        ),
        pytest.param(
            lambda cause: [DECOY, right(cause)],
            {c.name: (c.name == "traffic_spike", True, 2) for c in CASES},
            id="right-second",
        ),
        pytest.param(
            lambda cause: [DECOY],
            {c.name: (c.name == "traffic_spike",) * 2 + (1,) for c in CASES},
            id="decoy-only",
        ),
    ],
)
def test_evaluators_score_each_case(
    reply: Reply, expected: dict[str, tuple[bool, bool, int]]
) -> None:
    report = run_evals(model_from(reply))
    assert not report.failures
    assert {
        c.name: (
            c.assertions["TopHypothesis"].value,
            c.assertions["InTopThree"].value,
            c.scores["HypothesisCount"].value,
        )
        for c in report.cases
    } == expected
