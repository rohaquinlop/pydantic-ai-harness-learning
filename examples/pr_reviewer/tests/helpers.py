import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)

HEAD_SHA = "abc123"
CLAUDE_MD = "Rule: guard division by zero.\n"
BASE_CALC = "def ratio(a, b):\n    return a / b if b else 0\n"
HEAD_CALC = "def ratio(a, b):\n    return a / b\n"
DIFF = (
    "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def ratio(a, b):\n"
    "-    return a / b if b else 0\n+    return a / b\n"
)

Call = tuple[str, dict[str, Any]]


def finding(file: str = "calc.py", **fields: Any) -> dict[str, Any]:
    return {
        "findings": [
            {
                "file": file,
                "line": 2,
                "rubric": "correctness",
                "problem": "division by zero",
                "fix": "guard b",
                **fields,
            }
        ]
    }


def final(kind: str, args: dict[str, Any]) -> Call:
    return (f"final_result_{kind}", args)


@dataclass
class Script:
    """A FunctionModel that plays fixed turns and records each run's first prompt.

    It also streams, because the harness `RepoContext` capability makes streamed requests.
    """

    turns: list[list[Call]]
    prompts: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)

    def model(self) -> FunctionModel:
        turns = iter(self.turns)

        def next_calls(
            messages: list[ModelMessage], info: AgentInfo
        ) -> list[Call]:
            self.instructions.append(info.instructions or "")
            if len(messages) == 1:
                self.prompts.extend(
                    str(p.content)
                    for p in messages[0].parts
                    if isinstance(p, UserPromptPart)
                )
            return next(turns)

        def respond(
            messages: list[ModelMessage], info: AgentInfo
        ) -> ModelResponse:
            calls = next_calls(messages, info)
            return ModelResponse(parts=[ToolCallPart(n, a) for n, a in calls])

        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[DeltaToolCalls]:
            for i, (name, args) in enumerate(next_calls(messages, info)):
                yield {i: DeltaToolCall(name, json.dumps(args))}

        return FunctionModel(respond, stream_function=stream)
