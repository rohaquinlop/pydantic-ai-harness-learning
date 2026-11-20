import re
from collections.abc import Iterator
from pathlib import Path

from pydantic_ai import ModelRetry, RunContext

from pr_reviewer.models import ReviewDeps

MAX_READ_LINES = 400
MAX_GLOB_RESULTS = 200
MAX_GREP_MATCHES = 100
MAX_GREP_FILE_BYTES = 1_000_000


def changed_files(diff: str) -> frozenset[str]:
    files: set[str] = set()
    for line in diff.splitlines():
        if line.startswith(("--- a/", "+++ b/")):
            files.add(line[6:].split("\t")[0])
    return frozenset(files)


def _base(ctx: RunContext[ReviewDeps]) -> Path:
    return ctx.deps.policy_base.resolve()


def _resolve(ctx: RunContext[ReviewDeps], path: str) -> Path:
    base = _base(ctx)
    target = (base / path).resolve()
    if not target.is_relative_to(base):
        raise ModelRetry(
            f"{path} is outside the policy base. Use a path relative to its root."
        )
    return target


def _iter_files(ctx: RunContext[ReviewDeps], pattern: str) -> Iterator[Path]:
    base = _base(ctx)
    for resolved in sorted({p.resolve() for p in base.glob(pattern)}):
        if not resolved.is_relative_to(base) or not resolved.is_file():
            continue
        if ".git" not in resolved.relative_to(base).parts:
            yield resolved


def read_file(
    ctx: RunContext[ReviewDeps],
    path: str,
    start_line: int = 1,
    max_lines: int = MAX_READ_LINES,
) -> str:
    """Read lines of a file in the policy base.

    Args:
        path: Path relative to the policy base root.
        start_line: First line to return, 1-based.
        max_lines: Number of lines to return, at most 400.
    """
    target = _resolve(ctx, path)
    if not target.is_file():
        return (
            f"{path} is not a file in the policy base. Use glob to find files."
        )
    lines = target.read_text(errors="replace").splitlines()
    start = max(start_line, 1)
    chunk = lines[start - 1 : start - 1 + min(max_lines, MAX_READ_LINES)]
    body = "\n".join(f"{n}: {line}" for n, line in enumerate(chunk, start))
    return f"{body}\n[lines {start}-{start + len(chunk) - 1} of {len(lines)}]"


def glob(ctx: RunContext[ReviewDeps], pattern: str) -> list[str]:
    """List files in the policy base that match a glob pattern, such as `**/*.py`.

    Args:
        pattern: Glob pattern relative to the policy base root.
    """
    base = _base(ctx)
    files = [p.relative_to(base).as_posix() for p in _iter_files(ctx, pattern)]
    if len(files) > MAX_GLOB_RESULTS:
        return files[:MAX_GLOB_RESULTS] + [
            f"... {len(files) - MAX_GLOB_RESULTS} more"
        ]
    return files


def grep(
    ctx: RunContext[ReviewDeps], pattern: str, file_glob: str = "**/*"
) -> str:
    """Search file contents in the policy base with a Python regular expression.

    Args:
        pattern: Python regular expression to search for.
        file_glob: Glob pattern that limits which files are searched.
    """
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ModelRetry(f"Invalid regular expression: {e}") from e
    base = _base(ctx)
    matches: list[str] = []
    for p in _iter_files(ctx, file_glob):
        if p.stat().st_size > MAX_GREP_FILE_BYTES:
            continue
        for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if regex.search(line):
                matches.append(f"{p.relative_to(base).as_posix()}:{n}: {line}")
                if len(matches) >= MAX_GREP_MATCHES:
                    return "\n".join(matches) + "\n[match limit reached]"
    return "\n".join(matches) or "no matches"
