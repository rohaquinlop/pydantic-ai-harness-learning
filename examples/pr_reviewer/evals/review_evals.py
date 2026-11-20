import argparse
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from pr_reviewer.models import Current, Finding, ReviewResult
from pr_reviewer.review import Engine, review
from pydantic_ai.models import Model
from pydantic_evals import Dataset
from pydantic_evals.evaluators import (
    EvaluationReason,
    Evaluator,
    EvaluatorContext,
)
from pydantic_evals.reporting import EvaluationReport

from examples.pr_reviewer.evals.cases import (
    CASES,
    PlantedBug,
    RepoCase,
    build_repo,
)

Ctx = EvaluatorContext[RepoCase, ReviewResult, PlantedBug]


def _hits(finding: Finding, bug: PlantedBug | None) -> bool:
    return (
        bug is not None
        and finding.file == bug.file
        and bug.first_line <= finding.line <= bug.last_line
    )


def _findings(output: ReviewResult) -> list[Finding]:
    return [] if isinstance(output, Current) else output.findings


@dataclass
class FindsPlantedBug(Evaluator[RepoCase, ReviewResult, PlantedBug]):
    """Recall: a finding points at the planted bug. Skipped on clean cases."""

    def evaluate(self, ctx: Ctx) -> dict[str, bool]:
        if ctx.metadata is None:
            return {}
        return {
            "finds_bug": any(
                _hits(f, ctx.metadata) for f in _findings(ctx.output)
            )
        }


@dataclass
class CleanIsCurrent(Evaluator[RepoCase, ReviewResult, PlantedBug]):
    """A clean change gets `current at <sha>`. Skipped on cases with a bug."""

    def evaluate(self, ctx: Ctx) -> dict[str, EvaluationReason]:
        if ctx.metadata is not None:
            return {}
        current = isinstance(ctx.output, Current)
        return {
            "clean_is_current": EvaluationReason(
                current, None if current else "had findings"
            )
        }


@dataclass
class ExtraFindings(Evaluator[RepoCase, ReviewResult, PlantedBug]):
    """Findings that do not point at the planted bug: noise, or real issues we did not plant."""

    def evaluate(self, ctx: Ctx) -> int:
        return sum(not _hits(f, ctx.metadata) for f in _findings(ctx.output))


dataset = Dataset[RepoCase, ReviewResult, PlantedBug](
    name="pr_reviewer",
    cases=CASES,
    evaluators=[FindsPlantedBug(), CleanIsCurrent(), ExtraFindings()],
)


def make_task(
    model: Model | str | None, engine: Engine
) -> Callable[[RepoCase], ReviewResult]:
    """One fresh repo and one round-1 review call per case."""

    def review_case(case: RepoCase) -> ReviewResult:
        with tempfile.TemporaryDirectory(prefix="pr-reviewer-eval-") as tmp:
            repo = build_repo(case, Path(tmp) / "repo")
            return review(
                repo, "main", case.task, None, False, model, engine
            ).output

    return review_case


def run_evals(
    model: Model | str | None,
    engine: Engine = "custom",
    repeat: int = 1,
    max_concurrency: int = 2,
) -> EvaluationReport[RepoCase, ReviewResult, PlantedBug]:
    return dataset.evaluate_sync(
        make_task(model, engine),
        task_name=f"pr_reviewer[{engine}]",
        repeat=repeat,
        max_concurrency=max_concurrency,
        progress=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the PR reviewer on planted bugs."
    )
    parser.add_argument(
        "--model", help="Default: the first-call model (Haiku)."
    )
    parser.add_argument("--engine", choices=get_args(Engine), default="custom")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per case.")
    parser.add_argument("--max-concurrency", type=int, default=2)
    args = parser.parse_args()
    report = run_evals(
        args.model, args.engine, args.repeat, args.max_concurrency
    )
    report.print(
        include_input=False, include_output=True, include_durations=True
    )


if __name__ == "__main__":
    main()
