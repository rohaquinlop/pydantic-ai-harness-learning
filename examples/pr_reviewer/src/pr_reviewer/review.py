from pathlib import Path
from typing import Literal

from pydantic_ai import AgentRunResult, UsageLimits
from pydantic_ai.models import Model

from pr_reviewer.agent import build_prompt, reviewer
from pr_reviewer.bundle import build_bundle, policy_base
from pr_reviewer.github import post_review, read_pr_state, review_payload
from pr_reviewer.harness_agent import harness_reviewer, policy_workspace
from pr_reviewer.models import Current, ReviewDeps, ReviewOutcome, ReviewResult
from pr_reviewer.state import (
    load_state,
    plan_call,
    save_state,
    start_round,
    state_path,
)
from pr_reviewer.tools import changed_files

REQUEST_LIMIT = 30

Engine = Literal["custom", "harness"]


def run_reviewer(
    engine: Engine, prompt: str, model: Model | str, deps: ReviewDeps
) -> AgentRunResult[ReviewResult]:
    """One fresh agent run. The harness agent gets the policy base as its workspace."""
    limits = UsageLimits(request_limit=REQUEST_LIMIT)
    if engine == "harness":
        return harness_reviewer.run_sync(
            prompt,
            model=model,
            deps=deps,
            usage_limits=limits,
            capabilities=[policy_workspace(deps)],
        )
    return reviewer.run_sync(
        prompt, model=model, deps=deps, usage_limits=limits
    )


def review(
    repo: Path,
    base_ref: str,
    task: str | None,
    pr: str | None,
    new_round: bool,
    model: Model | str | None = None,
    engine: Engine = "custom",
    post: bool = False,
) -> ReviewOutcome:
    """Run the next review call of this branch's round, with a fresh agent run.

    With `post`, the budget lives in the PR's bot reviews and the result is posted there.
    """
    target = pr if post else None
    path = state_path(repo)
    state = (
        start_round(read_pr_state(repo, target), new_round)
        if target
        else load_state(path, new_round)
    )
    plan = plan_call(state, has_pr=pr is not None)
    bundle = build_bundle(repo, base_ref, task, pr, state.findings)

    reserved = (
        {"verify_used": True}
        if plan.kind == "verify"
        else {"calls": plan.number}
    )
    state = state.model_copy(update=reserved)
    save_state(path, state)

    with policy_base(repo, bundle.base_sha) as base:
        deps = ReviewDeps(base, bundle.head_sha, changed_files(bundle.diff))
        result = run_reviewer(
            engine,
            build_prompt(bundle, verify=plan.kind == "verify"),
            model or plan.model,
            deps,
        )

    findings = (
        [] if isinstance(result.output, Current) else result.output.findings
    )
    state = state.model_copy(update={"findings": findings})
    save_state(path, state)
    outcome = ReviewOutcome(plan, result.output, result.usage)
    if target:
        payload = review_payload(outcome, state, bundle.head_sha, bundle.diff)
        post_review(repo, target, payload)
    return outcome
