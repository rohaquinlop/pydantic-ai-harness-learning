from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Category = Literal[
    "code_change", "config_change", "dependency", "capacity", "resource_leak"
]
Source = Literal["alert", "log", "metric", "deploy", "commit"]
REF_PREFIXES: dict[str, Source] = {
    "logs/": "log",
    "metric:": "metric",
    "deploy:": "deploy",
    "commit:": "commit",
}


def source_of(ref: str) -> Source | None:
    if ref == "alert":
        return "alert"
    return next(
        (s for prefix, s in REF_PREFIXES.items() if ref.startswith(prefix)),
        None,
    )


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

    @model_validator(mode="after")
    def source_matches_ref(self) -> Self:
        if source_of(self.ref) != self.source:
            raise ValueError(
                f"ref {self.ref!r} does not fit source {self.source!r}. "
                "Use `alert`, `logs/<file>:<line>`, `metric:<name>`, "
                "`deploy:<id>`, or `commit:<sha>`, and the matching source."
            )
        return self


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
