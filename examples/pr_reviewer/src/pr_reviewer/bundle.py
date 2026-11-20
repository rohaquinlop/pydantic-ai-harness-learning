import json
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from pr_reviewer.models import Bundle, Finding


def run(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        args, cwd=repo, check=True, capture_output=True, text=True, input=stdin
    ).stdout


def _pr_discussion(repo: Path, pr: str) -> tuple[str, str]:
    data = json.loads(
        run(
            repo,
            "gh",
            "pr",
            "view",
            pr,
            "--json",
            "title,body,comments,reviews",
        )
    )
    task = f"{data['title']}\n\n{data['body']}"
    entries = [
        f"[{(c.get('author') or {}).get('login', 'unknown')}] {c['body']}"
        for c in data["comments"] + data["reviews"]
        if c["body"]
    ]
    return task, "\n\n".join(entries)


def build_bundle(
    repo: Path,
    base_ref: str,
    task: str | None,
    pr: str | None,
    prior_findings: list[Finding],
) -> Bundle:
    head_sha = run(repo, "git", "rev-parse", "HEAD").strip()
    base_sha = run(repo, "git", "merge-base", base_ref, "HEAD").strip()
    policy_sha = run(repo, "git", "rev-parse", f"{base_ref}^{{commit}}").strip()
    pr_task, discussion = _pr_discussion(repo, pr) if pr else (None, None)
    return Bundle(
        task=task or pr_task or "(none given)",
        base_sha=base_sha,
        policy_sha=policy_sha,
        head_sha=head_sha,
        diff=run(
            repo,
            "git",
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            f"{base_sha}...{head_sha}",
        ),
        pr_discussion=discussion,
        prior_findings=prior_findings,
    )


@contextmanager
def policy_base(repo: Path, sha: str) -> Generator[Path]:
    """A clean, detached worktree of the target branch at `sha`, removed on exit."""
    with tempfile.TemporaryDirectory(prefix="pr-reviewer-") as tmp:
        path = Path(tmp) / "policy-base"
        run(repo, "git", "worktree", "add", "--detach", str(path), sha)
        try:
            yield path
        finally:
            run(repo, "git", "worktree", "remove", "--force", str(path))
