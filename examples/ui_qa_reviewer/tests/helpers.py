import base64
from typing import Any

from pydantic_ai import AgentRunResult, ToolReturn
from pydantic_ai.capabilities import Toolset
from pydantic_ai.messages import BinaryContent, ModelRequest, ToolReturnPart
from pydantic_ai.toolsets import FunctionToolset
from ui_qa_reviewer.agent import build_agent
from ui_qa_reviewer.models import QADeps, QAResult

from examples.pr_reviewer.tests.helpers import Call, Script, final

PREVIEW = "http://127.0.0.1:8000"
HEAD_SHA = "abc123"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
NAVIGATE: Call = ("navigate", {"url": f"{PREVIEW}/"})
SCREENSHOT: Call = ("screenshot", {})


def _seen(note: str, image: bool) -> str | ToolReturn:
    if not image:
        return "Error: the screenshot is too large."
    return ToolReturn(
        note, content=[BinaryContent(data=PNG, media_type="image/png")]
    )


def stub_browser(
    image: bool = True, calls: list[str] | None = None
) -> Toolset[QADeps]:
    """Stands in for PlaywrightBrowser, with the same image return shape."""
    toolset = FunctionToolset[QADeps]()
    log = calls if calls is not None else []

    @toolset.tool_plain
    def navigate(url: str) -> str | ToolReturn:
        log.append(f"navigate {url}")
        return _seen(f"Opened {url}", image)

    @toolset.tool_plain
    def screenshot() -> str | ToolReturn:
        log.append("screenshot")
        return _seen("Screenshot captured.", image)

    return Toolset(toolset)


def passed(sha: str = HEAD_SHA) -> Call:
    return final("QAPassed", {"sha": sha, "checked": ["/ sign-up form"]})


def issue(url: str = f"{PREVIEW}/") -> Call:
    finding: dict[str, Any] = {
        "url": url,
        "category": "functional",
        "severity": "major",
        "steps": ["Type an email", "Click Sign up"],
        "expected": "A thank-you message",
        "actual": "Nothing happens",
    }
    return final("QAFindings", {"findings": [finding]})


def qa_run(
    turns: list[list[Call]], image: bool = True
) -> AgentRunResult[QAResult]:
    agent = build_agent(PREVIEW, stub_browser(image))
    return agent.run_sync(
        "Check the preview.",
        model=Script(turns).model(),
        deps=QADeps(PREVIEW, HEAD_SHA),
    )


def retries(result: AgentRunResult[QAResult]) -> list[str]:
    """Rejected outputs: the output tool's returns other than the final one."""
    returns = [
        str(p.content)
        for m in result.all_messages()
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart)
        and p.tool_name.startswith("final_result")
    ]
    return returns[:-1]
