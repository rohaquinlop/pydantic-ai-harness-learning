from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import UsageLimits, capture_run_messages
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    RetryFeedbackPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from incident_triager.agent import triager
from incident_triager.bundle import load_alert
from incident_triager.models import Triage, TriageDeps

REQUEST_LIMIT = 40


@dataclass(frozen=True)
class TriageOutcome:
    output: Triage
    usage: RunUsage
    tool_calls: int
    retries: tuple[str, ...]


def _retry_line(part: ModelRequestPart) -> str | None:
    if isinstance(part, RetryFeedbackPart):
        return f"output: {part.content}"
    if isinstance(part, ToolReturnPart) and part.outcome == "retried":
        return f"{part.tool_name}: {part.content}"
    return None


def retries(messages: list[ModelMessage]) -> tuple[str, ...]:
    return tuple(
        line
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if (line := _retry_line(part))
    )


def tool_calls(messages: list[ModelMessage]) -> int:
    return sum(
        isinstance(part, ToolCallPart)
        and not part.tool_name.startswith("final")
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
    )


def build_prompt(bundle: Path) -> str:
    alert = load_alert(bundle)
    return (
        f"Triage this incident.\nAlert: {alert.get('title', '')}\n"
        f"Fired at: {alert.get('fired_at', '')}"
    )


def triage(bundle: Path, model: Model | str | None = None) -> TriageOutcome:
    """Run one triage on `bundle` with a fresh agent run."""
    with capture_run_messages() as messages:
        try:
            result = triager.run_sync(
                build_prompt(bundle),
                deps=TriageDeps(bundle),
                model=model,
                usage_limits=UsageLimits(request_limit=REQUEST_LIMIT),
            )
        except AgentRunError as e:
            for line in retries(messages):
                e.add_note(f"retry: {line}")
            raise
    history = result.all_messages()
    return TriageOutcome(
        result.output, result.usage, tool_calls(history), retries(history)
    )
