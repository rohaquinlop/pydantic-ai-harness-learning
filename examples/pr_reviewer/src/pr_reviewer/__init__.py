import argparse
import subprocess
from pathlib import Path
from typing import get_args

from pydantic_ai.exceptions import AgentRunError

from pr_reviewer.models import Current
from pr_reviewer.review import Engine, review
from pr_reviewer.state import MAX_REVIEWS, BudgetSpent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the next review call on the current branch with a fresh reviewer agent."
    )
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--base", required=True, help="Target branch ref, such as origin/main."
    )
    parser.add_argument(
        "--task", help="The task contract. Default: the PR title and body."
    )
    parser.add_argument("--pr", help="PR number or URL, read with gh.")
    parser.add_argument(
        "--new-round", action="store_true", help="Reset the review budget."
    )
    parser.add_argument("--model", help="Use this model for every call.")
    parser.add_argument(
        "--engine",
        choices=get_args(Engine),
        default="custom",
        help="custom: hand-written tools. harness: pydantic-ai-harness capabilities.",
    )
    args = parser.parse_args()

    try:
        outcome = review(
            args.repo,
            args.base,
            args.task,
            args.pr,
            args.new_round,
            args.model,
            args.engine,
        )
    except (BudgetSpent, AgentRunError) as e:
        raise SystemExit(f"reviewer failed: {e}") from e
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"{' '.join(e.cmd)} failed: {e.stderr.strip()}") from e

    plan = outcome.plan
    print(
        f"{plan.kind} call {plan.number} of {MAX_REVIEWS} (+1 verify), {plan.model}"
    )
    if isinstance(outcome.output, Current):
        print(f"current at {outcome.output.sha}")
    else:
        for f in outcome.output.findings:
            print(f"{f.file}:{f.line} [{f.rubric}] — {f.problem} — {f.fix}")
            if f.decision_options:
                print(f"  DECISION: {' | '.join(f.decision_options)}")
    print(f"\nusage: {outcome.usage}")
