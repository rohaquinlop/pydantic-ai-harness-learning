from pathlib import Path

from pydantic_ai import UsageLimits
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from ui_qa_reviewer.agent import build_agent, build_prompt
from ui_qa_reviewer.bundle import build_bundle
from ui_qa_reviewer.models import QADeps, QAOutcome, QAPassed

REQUEST_LIMIT = 40
NO_CHANGES = "(no frontend changes)"


def review(
    repo: Path,
    base_ref: str,
    preview_url: str,
    task: str,
    model: Model | str | None = None,
    browser: AbstractCapability[QADeps] | None = None,
) -> QAOutcome:
    bundle = build_bundle(repo, base_ref, task)
    if not bundle.changed_files:
        passed = QAPassed(sha=bundle.head_sha, checked=[NO_CHANGES])
        return QAOutcome(passed, RunUsage())
    result = build_agent(preview_url, browser).run_sync(
        build_prompt(bundle, preview_url),
        model=model,
        deps=QADeps(preview_url, bundle.head_sha),
        usage_limits=UsageLimits(request_limit=REQUEST_LIMIT),
    )
    return QAOutcome(result.output, result.usage)
