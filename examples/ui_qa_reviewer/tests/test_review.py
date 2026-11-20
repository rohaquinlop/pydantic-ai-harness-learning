from pathlib import Path

from pr_reviewer.bundle import run
from ui_qa_reviewer.models import QAFindings, QAPassed
from ui_qa_reviewer.review import NO_CHANGES, review

from examples.pr_reviewer.tests.helpers import Script
from examples.ui_qa_reviewer.tests.helpers import (
    NAVIGATE,
    PREVIEW,
    issue,
    stub_browser,
)


def test_review_runs_agent_on_frontend_diff(ui_repo: Path) -> None:
    script = Script([[NAVIGATE], [issue()]])
    calls: list[str] = []

    outcome = review(
        ui_repo,
        "main",
        PREVIEW,
        "Add the sign-up page.",
        script.model(),
        stub_browser(calls=calls),
    )

    assert isinstance(outcome.output, QAFindings)
    assert calls == [f"navigate {PREVIEW}/"]
    assert outcome.usage.requests == 2
    assert "b/index.html" in script.prompts[0]
    assert "app.py" not in script.prompts[0]


def test_empty_frontend_diff_skips_model(backend_repo: Path) -> None:
    outcome = review(backend_repo, "main", PREVIEW, "Bump x.")

    head = run(backend_repo, "git", "rev-parse", "HEAD").strip()
    assert outcome.output == QAPassed(sha=head, checked=[NO_CHANGES])
    assert outcome.usage.requests == 0
