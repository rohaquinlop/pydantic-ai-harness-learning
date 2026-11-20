from typing import Literal

from pydantic import BaseModel, Field

Rubric = Literal["scope", "api", "correctness", "tests", "docs", "quality"]


class Finding(BaseModel):
    file: str = Field(
        description="Path of the changed file, as shown in the diff."
    )
    line: int = Field(description="Line number in the new version of the file.")
    rubric: Rubric = Field(
        description="The rubric item this finding falls under."
    )
    problem: str
    fix: str = Field(description="A concrete fix.")
    decision_options: list[str] | None = Field(
        default=None,
        description="Set only when a human must decide. List the options; do not pick one.",
    )


class Findings(BaseModel):
    """Actionable findings, highest rubric level first."""

    findings: list[Finding] = Field(min_length=1)


class Current(BaseModel):
    """The change has no actionable findings."""

    sha: str = Field(description="The candidate head SHA given in the prompt.")


ReviewResult = Findings | Current
