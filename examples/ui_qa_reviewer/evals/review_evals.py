import argparse
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.models import Model
from pydantic_evals import Dataset
from pydantic_evals.evaluators import (
    EvaluationReason,
    Evaluator,
    EvaluatorContext,
)
from pydantic_evals.reporting import EvaluationReport
from ui_qa_reviewer.models import QAFindings, QAPassed, QAResult
from ui_qa_reviewer.review import review

from examples.pr_reviewer.evals.cases import RepoCase, build_repo
from examples.ui_qa_reviewer.evals.cases import CASES, PlantedBug, serve

Bugs = list[PlantedBug]
Ctx = EvaluatorContext[RepoCase, QAResult, Bugs]


@dataclass
class FindsPlantedBugs(Evaluator[RepoCase, QAResult, Bugs]):
    def evaluate(self, ctx: Ctx) -> dict[str, bool]:
        found = (
            {f.category for f in ctx.output.findings}
            if isinstance(ctx.output, QAFindings)
            else set()
        )
        return {
            bug.name: bool(found & bug.categories) for bug in ctx.metadata or []
        }


@dataclass
class CleanPasses(Evaluator[RepoCase, QAResult, Bugs]):
    """A clean change passes. Skipped on cases with bugs."""

    def evaluate(self, ctx: Ctx) -> dict[str, EvaluationReason]:
        if ctx.metadata:
            return {}
        passed = isinstance(ctx.output, QAPassed)
        return {
            "clean_passes": EvaluationReason(
                passed, None if passed else "had findings"
            )
        }


dataset = Dataset[RepoCase, QAResult, Bugs](
    name="ui_qa_reviewer",
    cases=CASES,
    evaluators=[FindsPlantedBugs(), CleanPasses()],
)


def make_task(model: Model | str | None) -> Callable[[RepoCase], QAResult]:
    """One fresh repo and one QA run per case. Only the head files are served, not `.git/`."""

    def review_case(case: RepoCase) -> QAResult:
        with tempfile.TemporaryDirectory(prefix="ui-qa-eval-") as tmp:
            repo = build_repo(case, Path(tmp) / "repo")
            site = Path(tmp) / "site"
            site.mkdir()
            for name, content in case.head.items():
                (site / name).write_text(content)
            with serve(site) as url:
                return review(repo, "main", url, case.task, model).output

    return review_case


def run_evals(
    model: Model | str | None, repeat: int = 1, max_concurrency: int = 2
) -> EvaluationReport[RepoCase, QAResult, Bugs]:
    return dataset.evaluate_sync(
        make_task(model),
        task_name="ui_qa_reviewer",
        repeat=repeat,
        max_concurrency=max_concurrency,
        progress=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the UI QA reviewer on a demo page with planted bugs."
    )
    parser.add_argument("--model", help="Default: the Sonnet model.")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per case.")
    parser.add_argument("--max-concurrency", type=int, default=2)
    args = parser.parse_args()
    report = run_evals(args.model, args.repeat, args.max_concurrency)
    report.print(
        include_input=False, include_output=True, include_durations=True
    )


if __name__ == "__main__":
    main()
