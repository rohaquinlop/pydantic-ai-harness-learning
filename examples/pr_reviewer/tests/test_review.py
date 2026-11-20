from pathlib import Path
from typing import get_args

import pytest
from pr_reviewer.bundle import build_bundle, run
from pr_reviewer.models import Current, Findings, ReviewOutcome
from pr_reviewer.review import Engine, review
from pr_reviewer.state import BudgetSpent, load_state, state_path

from examples.pr_reviewer.evals.cases import commit
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
    assert all(o.plan.model.startswith("function:") for o, _ in calls)
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


def test_empty_diff_is_current_without_a_model_call(demo_repo: Path) -> None:
    script = Script([])
    outcome = review(demo_repo, "HEAD", None, None, False, script.model())

    assert outcome.output == Current(sha=head(demo_repo))
    assert script.prompts == []
    state = load_state(state_path(demo_repo), new_round=False)
    assert (state.calls, state.findings) == (0, [])


def test_policy_base_is_the_target_tip(demo_repo: Path) -> None:
    run(demo_repo, "git", "switch", "-q", "main")
    commit(demo_repo, {"NEW.md": "Rule added after the branch.\n"}, "rule")
    run(demo_repo, "git", "switch", "-q", "feat/x")

    outcome, _ = review_once(demo_repo, final("Findings", finding("NEW.md")))

    assert isinstance(outcome.output, Findings)


def test_diff_ignores_color_and_prefix_config(
    demo_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = {"color.ui": "always", "diff.noprefix": "true"}
    monkeypatch.setenv("GIT_CONFIG_COUNT", str(len(config)))
    for i, (key, value) in enumerate(config.items()):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{i}", key)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{i}", value)

    diff = build_bundle(demo_repo, "main", None, None, []).diff

    assert diff.startswith("diff --git a/")
    assert "\x1b" not in diff
