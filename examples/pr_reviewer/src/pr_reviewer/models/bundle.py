from pydantic import BaseModel

from pr_reviewer.models.output import Finding


class Bundle(BaseModel):
    """Everything one review call sees, built from git and gh, never from a chat."""

    task: str
    base_sha: str
    head_sha: str
    diff: str
    pr_discussion: str | None = None
    prior_findings: list[Finding] = []
