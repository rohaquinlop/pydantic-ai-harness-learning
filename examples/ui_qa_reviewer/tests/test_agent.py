import pytest
from ui_qa_reviewer.agent import build_prompt, preview_browser
from ui_qa_reviewer.models import QABundle, QAFindings, QAPassed

from examples.pr_reviewer.tests.helpers import Call
from examples.ui_qa_reviewer.tests.helpers import (
    HEAD_SHA,
    NAVIGATE,
    PREVIEW,
    SCREENSHOT,
    issue,
    passed,
    qa_run,
    retries,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000.evil.test/",
        "http://127.0.0.1:9000/",
        "https://127.0.0.1:8000/",
        "http://127.0.0.1:bad/",
    ],
)
def test_rejects_off_origin_finding(url: str) -> None:
    result = qa_run([[issue(url)], [issue(f"{PREVIEW}/signup")]])

    assert isinstance(result.output, QAFindings)
    assert result.output.findings[0].url == f"{PREVIEW}/signup"
    assert any("not on the preview" in r for r in retries(result))


def test_accepts_finding_on_preview() -> None:
    result = qa_run([[issue(f"{PREVIEW}/signup?step=2")]])

    assert isinstance(result.output, QAFindings)
    assert retries(result) == []


@pytest.mark.parametrize(
    ("before", "image"), [([], True), ([[SCREENSHOT]], False)]
)
def test_rejects_pass_without_screenshot(
    before: list[list[Call]], image: bool
) -> None:
    result = qa_run([*before, [passed()], [issue()]], image=image)

    assert isinstance(result.output, QAFindings)
    assert any("not seen the page" in r for r in retries(result))


@pytest.mark.parametrize("tool", [SCREENSHOT, NAVIGATE])
def test_accepts_pass_after_image(tool: Call) -> None:
    result = qa_run([[tool], [passed()]])

    assert result.output == QAPassed(sha=HEAD_SHA, checked=["/ sign-up form"])
    assert retries(result) == []


def test_rejects_wrong_sha() -> None:
    result = qa_run([[SCREENSHOT], [passed("deadbeef")], [passed()]])

    assert isinstance(result.output, QAPassed)
    assert any("candidate head SHA" in r for r in retries(result))


def test_prompt_contents() -> None:
    bundle = QABundle(
        task="Add the sign-up page.",
        head_sha=HEAD_SHA,
        diff="+<h1>Hi</h1>",
        changed_files=["index.html"],
    )

    prompt = build_prompt(bundle, PREVIEW)

    for part in (
        HEAD_SHA,
        PREVIEW,
        "index.html",
        "<task-contract>",
        "+<h1>Hi</h1>",
    ):
        assert part in prompt


@pytest.mark.parametrize(
    ("url", "blocks_private"),
    [
        ("http://localhost:5173", False),
        ("http://127.0.0.1:8000", False),
        ("https://preview.example.com", True),
    ],
)
def test_browser_reaches_only_preview(url: str, blocks_private: bool) -> None:
    policy = preview_browser(url).policy

    assert policy is not None
    assert policy.allowed_domains == [url.split("//")[1].split(":")[0]]
    assert policy.allowlist_reach == {
        "navigation",
        "subframe",
        "data",
        "subresource",
    }
    assert policy.block_private_addresses is blocks_private
