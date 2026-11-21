from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "code_change", "config_change", "dependency", "capacity", "resource_leak"
]
Source = Literal["alert", "log", "metric", "deploy", "commit"]


@dataclass
class TriageDeps:
    bundle: Path


class Evidence(BaseModel):
    source: Source
    ref: str = Field(
        description=(
            "A ref exactly as a tool printed it: `alert`, "
            "`logs/api.log:120`, `metric:db_pool_wait_ms`, `deploy:d-102`, "
            "or `commit:a1b2c3d`."
        )
    )
    detail: str = Field(description="What this evidence shows, in one line.")


class Hypothesis(BaseModel):
    cause: str = Field(description="The suspected root cause, in one line.")
    category: Category
    confidence: Literal["high", "medium", "low"]
    evidence: list[Evidence] = Field(min_length=1)
    check: str = Field(
        min_length=10,
        description="The cheapest check that proves or refutes this cause.",
    )
    refuted_if: str = Field(
        min_length=10,
        description="The result of the check that rules this cause out.",
    )


class Triage(BaseModel):
    """Root-cause hypotheses, most likely first."""

    summary: str = Field(description="What happened, in one or two lines.")
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)
