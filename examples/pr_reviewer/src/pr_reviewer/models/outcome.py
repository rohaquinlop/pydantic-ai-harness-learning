from dataclasses import dataclass

from pydantic_ai.usage import RunUsage

from pr_reviewer.models.output import ReviewResult
from pr_reviewer.models.state import CallPlan


@dataclass(frozen=True)
class ReviewOutcome:
    plan: CallPlan
    output: ReviewResult
    usage: RunUsage
    retries: tuple[str, ...] = ()
