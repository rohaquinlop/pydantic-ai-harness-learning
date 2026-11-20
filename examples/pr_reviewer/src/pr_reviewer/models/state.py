from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from pr_reviewer.models.output import Finding


class ReviewState(BaseModel):
    """The review budget of one branch. Lives in the git dir, so it is never committed."""

    round: int = 1
    calls: int = 0
    verify_used: bool = False
    findings: list[Finding] = []


@dataclass(frozen=True)
class CallPlan:
    kind: Literal["review", "verify"]
    number: int
    model: str
