from pathlib import Path

import pytest
from pr_reviewer.models import CallPlan, Findings, ReviewState
from pr_reviewer.state import (
    HEAVY_MODEL,
    LIGHT_MODEL,
    BudgetSpent,
    load_state,
    plan_call,
    save_state,
)

from examples.pr_reviewer.tests.helpers import finding

FINDINGS = Findings.model_validate(finding()).findings


@pytest.mark.parametrize(
    ("state", "has_pr", "expected"),
    [
        (ReviewState(), False, CallPlan("review", 1, LIGHT_MODEL)),
        (ReviewState(calls=1), False, CallPlan("review", 2, HEAVY_MODEL)),
        (ReviewState(calls=2), False, CallPlan("review", 3, HEAVY_MODEL)),
        (ReviewState(calls=1), True, CallPlan("review", 2, LIGHT_MODEL)),
        (
            ReviewState(round=2, calls=1),
            False,
            CallPlan("review", 2, LIGHT_MODEL),
        ),
        (
            ReviewState(calls=3, findings=FINDINGS),
            False,
            CallPlan("verify", 4, LIGHT_MODEL),
        ),
    ],
)
def test_plan_call(
    state: ReviewState, has_pr: bool, expected: CallPlan
) -> None:
    assert plan_call(state, has_pr) == expected


@pytest.mark.parametrize(
    "state",
    [
        ReviewState(calls=3),
        ReviewState(calls=3, verify_used=True, findings=FINDINGS),
    ],
)
def test_plan_call_budget_spent(state: ReviewState) -> None:
    with pytest.raises(BudgetSpent):
        plan_call(state, has_pr=False)


@pytest.mark.parametrize(
    ("new_round", "expected"),
    [
        (False, ReviewState(calls=3, findings=FINDINGS)),
        (True, ReviewState(round=2)),
    ],
)
def test_load_state(
    tmp_path: Path, new_round: bool, expected: ReviewState
) -> None:
    path = tmp_path / "state.json"
    save_state(path, ReviewState(calls=3, findings=FINDINGS))
    assert load_state(path, new_round) == expected


def test_load_state_without_file(tmp_path: Path) -> None:
    assert (
        load_state(tmp_path / "missing.json", new_round=False) == ReviewState()
    )
