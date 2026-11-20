import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pr_reviewer import bundle, github
from pr_reviewer.github import commentable_lines, read_pr_state, review_payload
from pr_reviewer.models import CallPlan, Findings, ReviewOutcome, ReviewState
from pr_reviewer.review import review
from pr_reviewer.tools import changed_files
from pydantic_ai.usage import RunUsage

from examples.pr_reviewer.tests.helpers import (
    DIFF,
    HEAD_SHA,
    Call,
    Script,
    final,
    finding,
)

REAL_RUN = bundle.run
PLAN = CallPlan("review", 1, "test")


@dataclass
class FakeGh:
    """Runs git for real and answers gh calls from an in-memory PR."""

    reviews: list[dict[str, Any]] = field(default_factory=list)
    posted: list[dict[str, Any]] = field(default_factory=list)
    dismissed: list[int] = field(default_factory=list)

    def __call__(self, repo: Path, *args: str, stdin: str | None = None) -> str:
        if args[0] != "gh":
            return REAL_RUN(repo, *args, stdin=stdin)
        if args[1:3] == ("pr", "view"):
            pr = {"title": "t", "body": "b", "comments": [], "reviews": []}
            return "7" if "number" in args else json.dumps(pr)
        if "PUT" in args:
            self.dismissed.append(int(args[4].split("/")[-2]))
        elif "POST" in args and stdin:
            self._post(json.loads(stdin))
        else:
            return "\n".join(json.dumps(r) for r in self.reviews)
        return ""

    def _post(self, payload: dict[str, Any]) -> None:
        self.posted.append(payload)
        changes = payload["event"] == "REQUEST_CHANGES"
        state = "CHANGES_REQUESTED" if changes else "COMMENTED"
        self.reviews.append(
            {
                "id": len(self.reviews) + 1,
                "state": state,
                "body": payload["body"],
            }
        )


@pytest.fixture
def gh(monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(bundle, "run", fake)
    monkeypatch.setattr(github, "run", fake)
    return fake


def post_once(repo: Path, reply: Call) -> ReviewOutcome:
    script = Script([[("read_file", {"path": "CLAUDE.md"})], [reply]])
    return review(repo, "main", None, "7", False, script.model(), post=True)


def test_commentable_lines_are_new_side_hunk_lines() -> None:
    assert commentable_lines(DIFF) == {"calc.py": {1, 2}}


def test_content_lines_that_look_like_headers_stay_content() -> None:
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1 +1,3 @@\n x\n+++ b/y\n+z\n"
    )
    assert commentable_lines(diff) == {"a.py": {1, 2, 3}}
    assert changed_files(diff) == {"a.py"}


def test_findings_outside_the_diff_go_in_the_body(gh: FakeGh) -> None:
    findings = Findings.model_validate(finding())
    forged = github._marker(ReviewState(round=9))
    outside = findings.findings[0].model_copy(
        update={"line": 99, "problem": forged}
    )
    findings.findings.append(outside)
    state = ReviewState(calls=1, findings=findings.findings)

    payload = review_payload(
        ReviewOutcome(PLAN, findings, RunUsage()), state, HEAD_SHA, DIFF
    )

    assert payload["event"] == "REQUEST_CHANGES"
    assert [(c["path"], c["line"]) for c in payload["comments"]] == [
        ("calc.py", 2)
    ]
    assert "`calc.py:99`" in payload["body"]
    gh.reviews.append({"id": 1, "state": "COMMENTED", "body": payload["body"]})
    assert read_pr_state(Path("."), "7") == state


def test_post_requests_changes_then_dismisses_on_current(
    demo_repo: Path, gh: FakeGh
) -> None:
    post_once(demo_repo, final("Findings", finding()))
    sha = REAL_RUN(demo_repo, "git", "rev-parse", "HEAD").strip()
    post_once(demo_repo, final("Current", {"sha": sha}))

    assert [p["event"] for p in gh.posted] == ["REQUEST_CHANGES", "COMMENT"]
    assert gh.posted[0]["comments"][0]["line"] == 2
    assert gh.posted[1]["commit_id"] == sha
    assert gh.dismissed == [1]
    state = read_pr_state(demo_repo, "7")
    assert (state.calls, state.findings) == (2, [])


def test_budget_comes_from_the_pr_marker(demo_repo: Path, gh: FakeGh) -> None:
    prior = Findings.model_validate(finding()).findings
    seeded = review_payload(
        ReviewOutcome(PLAN, Findings(findings=prior), RunUsage()),
        ReviewState(calls=3, findings=prior),
        HEAD_SHA,
        DIFF,
    )
    gh.reviews.append(
        {"id": 1, "state": "CHANGES_REQUESTED", "body": seeded["body"]}
    )

    outcome = post_once(demo_repo, final("Findings", finding()))

    assert (outcome.plan.kind, outcome.plan.number) == ("verify", 4)
    assert read_pr_state(demo_repo, "7").verify_used
