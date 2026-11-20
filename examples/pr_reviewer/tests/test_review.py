from pathlib import Path
from typing import get_args

import pytest
from pr_reviewer.bundle import run
from pr_reviewer.models import Current, ReviewOutcome
from pr_reviewer.review import Engine, review
from pr_reviewer.state import BudgetSpent, load_state, state_path

from examples.pr_reviewer.tests.helpers import Call, Script, final, finding

READ_RULES: Call = ("read_file", {"path": "CLAUDE.md"})


def review_once(
    repo: Path, reply: Call, new_round: bool = False, engine: Engine = "custom"
) -> tuple[ReviewOutcome, str]:
    script = Script([[READ_RULES], [reply]])
    outcome = review(
        repo,
        "main",
        "Simplify ratio()",
        None,
        new_round,
        script.model(),
        engine,
    )
    return outcome, script.prompts[0]


def head(repo: Path) -> str:
    return run(repo, "git", "rev-parse", "HEAD").strip()


def test_round_runs_three_reviews_then_verify_then_stops(
    demo_repo: Path,
) -> None:
    calls = [
        review_once(demo_repo, final("Findings", finding())) for _ in range(4)
    ]

    assert [(o.plan.kind, o.plan.number) for o, _ in calls] == [
        ("review", 1),
        ("review", 2),
        ("review", 3),
        ("verify", 4),
    ]
    assert ["<prior-findings>" in p for _, p in calls] == [
        False,
        True,
        True,
        True,
    ]
    assert "verify call" in calls[3][1]
    with pytest.raises(BudgetSpent):
        review_once(demo_repo, final("Findings", finding()))


def test_current_clears_findings_and_new_round_resets(demo_repo: Path) -> None:
    review_once(demo_repo, final("Findings", finding()))
    outcome, prompt = review_once(
        demo_repo, final("Current", {"sha": head(demo_repo)}), new_round=True
    )

    assert outcome.output == Current(sha=head(demo_repo))
    assert "<prior-findings>" not in prompt
    state = load_state(state_path(demo_repo), new_round=False)
    assert (state.round, state.calls, state.findings) == (2, 1, [])


@pytest.mark.parametrize("engine", get_args(Engine))
def test_state_in_git_dir_and_worktree_removed(
    demo_repo: Path, engine: Engine
) -> None:
    outcome, _ = review_once(
        demo_repo, final("Current", {"sha": head(demo_repo)}), engine=engine
    )
    assert outcome.output == Current(sha=head(demo_repo))

    path = state_path(demo_repo)
    assert path.parent.parent.name == ".git"
    assert path.name == "feat__x.json"
    assert len(run(demo_repo, "git", "worktree", "list").splitlines()) == 1
