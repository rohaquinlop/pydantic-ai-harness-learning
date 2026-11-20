from pathlib import Path

from pr_reviewer.bundle import run
from pr_reviewer.models import CallPlan, ReviewState

MAX_REVIEWS = 3
LIGHT_MODEL = "anthropic:claude-haiku-5-5"
HEAVY_MODEL = "anthropic:claude-opus-5-5"


class BudgetSpent(Exception):
    pass


def plan_call(state: ReviewState, has_pr: bool) -> CallPlan:
    """Pick the next call, shepherd-style.

    Round 1 before a PR exists: light model on call 1, heavy model on calls 2-3. Every
    other call, and the verify call that checks fixes to the last findings, uses the
    light model.
    """
    if state.calls < MAX_REVIEWS:
        number = state.calls + 1
        heavy = number > 1 and state.round == 1 and not has_pr
        return CallPlan("review", number, HEAVY_MODEL if heavy else LIGHT_MODEL)
    if not state.verify_used and state.findings:
        return CallPlan("verify", MAX_REVIEWS + 1, LIGHT_MODEL)
    raise BudgetSpent(
        f"Review budget of round {state.round} is spent. Fix the findings and accept "
        "the tree, or start a new round with --new-round."
    )


def state_path(repo: Path) -> Path:
    git_dir = Path(run(repo, "git", "rev-parse", "--absolute-git-dir").strip())
    branch = run(repo, "git", "rev-parse", "--abbrev-ref", "HEAD").strip()
    return git_dir / "pr-reviewer" / f"{branch.replace('/', '__')}.json"


def start_round(state: ReviewState, new_round: bool) -> ReviewState:
    return ReviewState(round=state.round + 1) if new_round else state


def load_state(path: Path, new_round: bool) -> ReviewState:
    state = (
        ReviewState.model_validate_json(path.read_text())
        if path.exists()
        else ReviewState()
    )
    return start_round(state, new_round)


def save_state(path: Path, state: ReviewState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2))
