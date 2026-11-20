import base64
import json
import re
from pathlib import Path
from typing import Any

from pr_reviewer.bundle import run
from pr_reviewer.models import Current, Finding, ReviewOutcome, ReviewState

BOT_LOGIN = "github-actions[bot]"
STATE_MARKER = re.compile(r"<!-- pr-reviewer-state: ([A-Za-z0-9+/=]+) -->")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
REVIEWS = "repos/{owner}/{repo}/pulls/%s/reviews"


def commentable_lines(diff: str) -> dict[str, set[int]]:
    """New-side lines of each file that GitHub accepts inline review comments on."""
    lines: dict[str, set[int]] = {}
    current: set[int] = set()
    number = 0
    in_hunk = False
    for line in diff.splitlines():
        hunk = HUNK.match(line)
        if line.startswith("diff --git "):
            in_hunk = False
        elif not in_hunk and line.startswith("+++ "):
            path = (
                line[6:].split("\t")[0] if line.startswith("+++ b/") else None
            )
            current = lines.setdefault(path, set()) if path else set()
        elif hunk:
            number = int(hunk.group(1))
            in_hunk = True
        elif in_hunk and line.startswith(("+", " ")):
            current.add(number)
            number += 1
    return lines


def _render(f: Finding) -> str:
    text = f"**[{f.rubric}]** {f.problem}\n\n**Fix:** {f.fix}"
    if f.decision_options:
        text += "\n\n**Decision needed:** " + " | ".join(f.decision_options)
    return text


def _marker(state: ReviewState) -> str:
    encoded = base64.b64encode(state.model_dump_json().encode()).decode()
    return f"<!-- pr-reviewer-state: {encoded} -->"


def review_payload(
    outcome: ReviewOutcome, state: ReviewState, head_sha: str, diff: str
) -> dict[str, Any]:
    """One PR review. Findings outside the diff go in the body, because GitHub rejects
    inline comments on lines the diff does not show."""
    plan = outcome.plan
    header = f"pr-reviewer {plan.kind} call {plan.number} ({plan.model})"
    if isinstance(outcome.output, Current):
        body = f"{header}: current at {outcome.output.sha}"
        return {
            "commit_id": head_sha,
            "event": "COMMENT",
            "body": f"{body}\n\n{_marker(state)}",
            "comments": [],
        }
    lines = commentable_lines(diff)
    findings = outcome.output.findings
    inline = [f for f in findings if f.line in lines.get(f.file, set())]
    outside = [
        f"`{f.file}:{f.line}` {_render(f)}" for f in findings if f not in inline
    ]
    return {
        "commit_id": head_sha,
        "event": "REQUEST_CHANGES",
        "body": "\n\n".join([header, *outside, _marker(state)]),
        "comments": [
            {
                "path": f.file,
                "line": f.line,
                "side": "RIGHT",
                "body": _render(f),
            }
            for f in inline
        ],
    }


def _pr_number(repo: Path, pr: str) -> str:
    return run(
        repo, "gh", "pr", "view", pr, "--json", "number", "-q", ".number"
    ).strip()


def _bot_reviews(repo: Path, number: str) -> list[dict[str, Any]]:
    """Reviews by the workflow's bot only, so a PR author cannot forge the state."""
    jq = f'.[] | select(.user.login == "{BOT_LOGIN}") | {{id, state, body}}'
    out = run(repo, "gh", "api", "--paginate", REVIEWS % number, "--jq", jq)
    return [json.loads(line) for line in out.splitlines() if line]


def read_pr_state(repo: Path, pr: str) -> ReviewState:
    """The state saved in the newest bot review of the PR, or a fresh state.

    The last marker of a body wins: findings text comes first and may hold a forged one.
    """
    for review in reversed(_bot_reviews(repo, _pr_number(repo, pr))):
        if markers := STATE_MARKER.findall(review["body"]):
            return ReviewState.model_validate_json(
                base64.b64decode(markers[-1])
            )
    return ReviewState()


def post_review(repo: Path, pr: str, payload: dict[str, Any]) -> None:
    """Dismiss the bot's open change requests, then post the new review."""
    number = _pr_number(repo, pr)
    for review in _bot_reviews(repo, number):
        if review["state"] == "CHANGES_REQUESTED":
            run(
                repo,
                "gh",
                "api",
                "--method",
                "PUT",
                f"{REVIEWS % number}/{review['id']}/dismissals",
                "-f",
                "message=Superseded by a newer pr-reviewer review.",
                "-f",
                "event=DISMISS",
            )
    run(
        repo,
        "gh",
        "api",
        "--method",
        "POST",
        REVIEWS % number,
        "--input",
        "-",
        stdin=json.dumps(payload),
    )
