import argparse
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from incident_triager.grounding import cites
from incident_triager.models import Hypothesis, Triage
from incident_triager.triage import triage
from pydantic_ai.models import Model
from pydantic_evals import Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_evals.reporting import EvaluationReport

from examples.incident_triager.evals.cases import (
    CASES,
    IncidentCase,
    PlantedCause,
    build_bundle,
)

Ctx = EvaluatorContext[IncidentCase, Triage, PlantedCause]


def names_cause(h: Hypothesis, cause: PlantedCause) -> bool:
    """An accepted category, and evidence that cites one of the key refs."""
    return h.category in cause.categories and any(
        cites(e.ref, key) for e in h.evidence for key in cause.key_refs
    )


@dataclass
class TopHypothesis(Evaluator[IncidentCase, Triage, PlantedCause]):
    """The first hypothesis names the planted cause."""

    def evaluate(self, ctx: Ctx) -> bool:
        assert ctx.metadata
        return names_cause(ctx.output.hypotheses[0], ctx.metadata)


@dataclass
class InTopThree(Evaluator[IncidentCase, Triage, PlantedCause]):
    """One of the first three hypotheses names the planted cause."""

    def evaluate(self, ctx: Ctx) -> bool:
        assert ctx.metadata
        return any(
            names_cause(h, ctx.metadata) for h in ctx.output.hypotheses[:3]
        )


@dataclass
class HypothesisCount(Evaluator[IncidentCase, Triage, PlantedCause]):
    def evaluate(self, ctx: Ctx) -> int:
        return len(ctx.output.hypotheses)


dataset = Dataset[IncidentCase, Triage, PlantedCause](
    name="incident_triager",
    cases=CASES,
    evaluators=[TopHypothesis(), InTopThree(), HypothesisCount()],
)


def make_task(model: Model | str | None) -> Callable[[IncidentCase], Triage]:
    """One fresh bundle and one triage run per case."""

    def triage_case(case: IncidentCase) -> Triage:
        with tempfile.TemporaryDirectory(prefix="incident-eval-") as tmp:
            bundle = build_bundle(case, Path(tmp) / "bundle")
            return triage(bundle, model).output

    return triage_case


def run_evals(
    model: Model | str | None, repeat: int = 1, max_concurrency: int = 2
) -> EvaluationReport[IncidentCase, Triage, PlantedCause]:
    return dataset.evaluate_sync(
        make_task(model),
        task_name="incident_triager",
        repeat=repeat,
        max_concurrency=max_concurrency,
        progress=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the incident triager on planted root causes."
    )
    parser.add_argument("--model", help="Default: Sonnet.")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per case.")
    parser.add_argument("--max-concurrency", type=int, default=2)
    args = parser.parse_args()
    report = run_evals(args.model, args.repeat, args.max_concurrency)
    report.print(
        include_input=False, include_output=True, include_durations=True
    )


if __name__ == "__main__":
    main()
