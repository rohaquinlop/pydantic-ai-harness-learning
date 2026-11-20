from pathlib import Path

from pr_reviewer.bundle import run

from ui_qa_reviewer.models import QABundle

FRONTEND_GLOBS = (
    "*.html",
    "*.css",
    "*.scss",
    "*.js",
    "*.jsx",
    "*.ts",
    "*.tsx",
    "*.vue",
    "*.svelte",
)
DIFF_FLAGS = (
    "--no-ext-diff",
    "--no-color",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)


def build_bundle(repo: Path, base_ref: str, task: str) -> QABundle:
    """The frontend part of the `merge-base...HEAD` diff."""
    head_sha = run(repo, "git", "rev-parse", "HEAD").strip()
    base_sha = run(repo, "git", "merge-base", base_ref, "HEAD").strip()
    span = (f"{base_sha}...{head_sha}", "--", *FRONTEND_GLOBS)
    names = run(repo, "git", "diff", "--name-only", "-z", *span)
    return QABundle(
        task=task,
        head_sha=head_sha,
        diff=run(repo, "git", "diff", *DIFF_FLAGS, *span),
        changed_files=[n for n in names.split("\0") if n],
    )
