from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai.usage import RunUsage

QACategory = Literal[
    "functional", "accessibility", "console", "visual", "content"
]
Severity = Literal["blocker", "major", "minor"]


class QAFinding(BaseModel):
    url: str = Field(description="The preview page where the issue shows.")
    category: QACategory
    severity: Severity
    steps: list[str] = Field(
        min_length=1, description="Steps to reproduce, in order."
    )
    expected: str
    actual: str
    file: str | None = Field(
        default=None,
        description="The changed file that likely causes it, if known.",
    )


class QAFindings(BaseModel):
    """QA issues found on the preview, most severe first."""

    findings: list[QAFinding] = Field(min_length=1)


class QAPassed(BaseModel):
    """The changed screens work and look right."""

    sha: str = Field(description="The candidate head SHA given in the prompt.")
    checked: list[str] = Field(
        min_length=1, description="The pages and flows you checked."
    )


QAResult = QAFindings | QAPassed


class QABundle(BaseModel):
    """What one QA run sees, built from git, never from a chat."""

    task: str
    head_sha: str
    diff: str
    changed_files: list[str]


@dataclass
class QADeps:
    preview_url: str
    head_sha: str


@dataclass(frozen=True)
class QAOutcome:
    output: QAResult
    usage: RunUsage
