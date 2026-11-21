import json
import os
import re
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic_ai import ModelRetry, RunContext

from incident_triager.bundle import (
    LogLine,
    MetricRow,
    load_alert,
    load_deploys,
    load_metrics,
    log_files,
    log_ref,
    logs_dir,
    parse_ts,
    read_lines,
)
from incident_triager.models import TriageDeps

PAGE_SIZE = 40
MAX_LINE_CHARS = 300
MAX_READ_LINES = 200
MAX_BUCKETS = 100
MAX_METRIC_POINTS = 60
MAX_SHOW_LINES = 300
MAX_COMMITS = 50
SHA = re.compile(r"[0-9a-f]{4,40}")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NO_REPO = "no git repo: repo/ is missing or git is not installed"


def _bundle(ctx: RunContext[TriageDeps]) -> Path:
    return ctx.deps.bundle.resolve()


def _cut(text: str) -> str:
    if len(text) <= MAX_LINE_CHARS:
        return text
    return f"{text[:MAX_LINE_CHARS]} [+{len(text) - MAX_LINE_CHARS} chars]"


def _regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as e:
        raise ModelRetry(f"Invalid regular expression: {e}") from e


def _ts_arg(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return parse_ts(value)
    except ValueError as e:
        raise ModelRetry(
            f"Invalid timestamp {value!r}. Use ISO 8601, such as "
            "2026-11-20T12:00:00Z."
        ) from e


def _in_window(
    ts: datetime, since: datetime | None, until: datetime | None
) -> bool:
    return (since is None or ts >= since) and (until is None or ts <= until)


def _matches(
    bundle: Path, regex: re.Pattern[str], file_glob: str
) -> list[LogLine]:
    try:
        paths = log_files(bundle, file_glob)
    except (NotImplementedError, ValueError) as e:
        raise ModelRetry(
            f"Invalid file_glob {file_glob!r}: {e}. Use a relative glob "
            "under logs/, such as `*.log`."
        ) from e
    return [
        line
        for path in paths
        for line in read_lines(bundle, path)
        if regex.search(line.text)
    ]


def _windowed(
    lines: list[LogLine], since: datetime | None, until: datetime | None
) -> tuple[list[LogLine], int]:
    kept = [
        line
        for line in lines
        if line.ts is not None and _in_window(line.ts, since, until)
    ]
    skipped = sum(line.ts is None for line in lines)
    return kept, skipped


def _skipped_note(skipped: int) -> list[str]:
    return [f"[skipped {skipped} unparseable lines]"] if skipped else []


def read_alert(ctx: RunContext[TriageDeps]) -> str:
    """Read the alert that opened the incident. Cite it as `alert`."""
    text = json.dumps(load_alert(_bundle(ctx)), indent=2)
    return "\n".join(["alert", *(_cut(x) for x in text.splitlines())])


def list_sources(ctx: RunContext[TriageDeps]) -> str:
    """List what the bundle holds: log files, metrics, deploys, and repo."""
    bundle = _bundle(ctx)
    lines = ["logs:"]
    for path in log_files(bundle, "*.log"):
        stamps = [x.ts for x in read_lines(bundle, path) if x.ts]
        span = (
            f"{min(stamps).isoformat()} to {max(stamps).isoformat()}"
            if stamps
            else "no timestamps"
        )
        lines.append(f"  {log_ref(bundle, path)}: {len(stamps)} lines, {span}")
    counts = Counter(row.metric for row in load_metrics(bundle))
    lines += ["metrics:"] + [
        f"  metric:{name}: {n} points" for name, n in sorted(counts.items())
    ]
    lines.append(f"deploys: {len(load_deploys(bundle))}")
    lines.append(f"repo: {'yes' if _has_repo(bundle) else 'no'}")
    return "\n".join(lines)


def count_logs(
    ctx: RunContext[TriageDeps],
    pattern: str,
    file_glob: str = "*.log",
    bucket_minutes: int = 5,
) -> str:
    """Count log lines that match a regex, per file and time bucket.

    Use it before search_logs to see when and where a pattern starts.

    Args:
        pattern: Python regular expression.
        file_glob: Glob under logs/, such as `api*.log`.
        bucket_minutes: Bucket size in minutes.
    """
    bundle = _bundle(ctx)
    lines, skipped = _windowed(
        _matches(bundle, _regex(pattern), file_glob), None, None
    )
    size = timedelta(minutes=max(bucket_minutes, 1))
    buckets = Counter(
        (EPOCH + (x.ts - EPOCH) // size * size, x.ref.rsplit(":", 1)[0])
        for x in lines
        if x.ts
    )
    rows = [
        f"{start.isoformat()} {file} {n}"
        for (start, file), n in sorted(buckets.items())
    ]
    if len(rows) > MAX_BUCKETS:
        rows = rows[:MAX_BUCKETS] + [
            f"[{len(rows) - MAX_BUCKETS} more buckets: use a larger bucket]"
        ]
    head = f"{len(lines)} matches"
    return "\n".join([head, *rows, *_skipped_note(skipped)])


def search_logs(
    ctx: RunContext[TriageDeps],
    pattern: str,
    file_glob: str = "*.log",
    since: str | None = None,
    until: str | None = None,
    cursor: int = 0,
) -> str:
    """Find log lines that match a regex, one page at a time.

    Args:
        pattern: Python regular expression.
        file_glob: Glob under logs/, such as `api*.log`.
        since: ISO 8601 start of the time window.
        until: ISO 8601 end of the time window.
        cursor: Index of the first match to return. Use the next cursor
            from the previous page.
    """
    lines = _matches(_bundle(ctx), _regex(pattern), file_glob)
    start, end = _ts_arg(since), _ts_arg(until)
    skipped = 0
    if start or end:
        lines, skipped = _windowed(lines, start, end)
    cursor = max(cursor, 0)
    page = lines[cursor : cursor + PAGE_SIZE]
    footer = (
        f"[next cursor: {cursor + PAGE_SIZE} of {len(lines)} matches]"
        if cursor + PAGE_SIZE < len(lines)
        else f"[end: {len(lines)} matches]"
    )
    body = [f"{x.ref}: {_cut(x.text)}" for x in page]
    return "\n".join([*body, footer, *_skipped_note(skipped)])


def read_log(
    ctx: RunContext[TriageDeps],
    file: str,
    start_line: int = 1,
    max_lines: int = 100,
) -> str:
    """Read a range of lines from one log file.

    Args:
        file: Path under logs/, such as `api.log`.
        start_line: First line to return, 1-based.
        max_lines: Number of lines to return, at most 200.
    """
    bundle = _bundle(ctx)
    root = logs_dir(bundle)
    path = (root / file.removeprefix("logs/")).resolve()
    if not path.is_relative_to(root):
        raise ModelRetry(f"{file} is outside logs/. Use a file under logs/.")
    if not path.is_file():
        return "No such log file. Use list_sources to see the files."
    lines = read_lines(bundle, path)
    start = max(start_line, 1)
    count = max(1, min(max_lines, MAX_READ_LINES))
    chunk = lines[start - 1 : start - 1 + count]
    body = [f"{x.ref}: {_cut(x.text)}" for x in chunk]
    return "\n".join([*body, f"[{len(chunk)} of {len(lines)} lines]"])


def _downsample(rows: list[MetricRow]) -> tuple[list[MetricRow], str]:
    if len(rows) <= MAX_METRIC_POINTS:
        return rows, ""
    step = len(rows) / MAX_METRIC_POINTS
    picked = [rows[int(i * step)] for i in range(MAX_METRIC_POINTS)]
    return picked, (
        f"[downsampled {len(rows)} points to {MAX_METRIC_POINTS}: "
        "narrow the window for full detail]"
    )


def query_metric(
    ctx: RunContext[TriageDeps],
    name: str,
    since: str | None = None,
    until: str | None = None,
) -> str:
    """Read one metric over a time window.

    Args:
        name: Metric name, as list_sources prints it, without `metric:`.
        since: ISO 8601 start of the time window.
        until: ISO 8601 end of the time window.
    """
    name = name.removeprefix("metric:")
    rows = load_metrics(_bundle(ctx))
    known = sorted({r.metric for r in rows})
    if name not in known:
        raise ModelRetry(f"Unknown metric {name!r}. Known: {', '.join(known)}")
    start, end = _ts_arg(since), _ts_arg(until)
    picked, note = _downsample(
        [r for r in rows if r.metric == name and _in_window(r.ts, start, end)]
    )
    body = [f"{r.ts.isoformat()} {r.value:g}" for r in picked]
    return "\n".join([f"metric:{name}", *body] + ([note] if note else []))


def list_deploys(
    ctx: RunContext[TriageDeps],
    since: str | None = None,
    until: str | None = None,
) -> str:
    """List code and config deploys in a time window.

    Args:
        since: ISO 8601 start of the time window.
        until: ISO 8601 end of the time window.
    """
    start, end = _ts_arg(since), _ts_arg(until)
    rows = [
        f"deploy:{d['id']} {d['at']} {d['service']} {d['kind']} "
        f"{d['version']} commit:{d['commit']} {d['description']}"
        for d in load_deploys(_bundle(ctx))
        if _in_window(parse_ts(d["at"]), start, end)
    ]
    return "\n".join(_cut(x) for x in rows) or "no deploys in this window"


def _has_repo(bundle: Path) -> bool:
    return (bundle / "repo" / ".git").exists() and bool(shutil.which("git"))


def _git(ctx: RunContext[TriageDeps], *args: str) -> str | None:
    bundle = _bundle(ctx)
    if not _has_repo(bundle):
        return None
    try:
        return subprocess.run(
            ["git", *args],
            cwd=bundle / "repo",
            env={
                **os.environ,
                "GIT_CEILING_DIRECTORIES": str(bundle.resolve()),
            },
            check=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
    except subprocess.CalledProcessError as e:
        raise ModelRetry(f"git failed: {e.stderr.strip()}") from e


def _repo_path(ctx: RunContext[TriageDeps], path: str) -> str:
    repo = (_bundle(ctx) / "repo").resolve()
    target = (repo / path).resolve()
    if not target.is_relative_to(repo):
        raise ModelRetry(f"{path} is outside repo/. Use a path in the repo.")
    return target.relative_to(repo).as_posix()


def git_log(
    ctx: RunContext[TriageDeps],
    since: str | None = None,
    until: str | None = None,
    path: str | None = None,
) -> str:
    """List commits in the service repo, newest first.

    Args:
        since: ISO 8601 start of the time window.
        until: ISO 8601 end of the time window.
        path: Only commits that touch this path in the repo.
    """
    args = [
        "log",
        f"--max-count={MAX_COMMITS + 1}",
        "--format=commit:%h %cI %s",
    ]
    for flag, value in (("since", since), ("until", until)):
        if ts := _ts_arg(value):
            args.append(f"--{flag}={ts.isoformat()}")
    if path:
        args += ["--", _repo_path(ctx, path)]
    out = _git(ctx, *args)
    if out is None:
        return NO_REPO
    lines = [_cut(x) for x in out.splitlines()]
    if not lines:
        return "no commits in this window"
    more = (
        ["[more commits: narrow the window or the path]"]
        if len(lines) > MAX_COMMITS
        else []
    )
    return "\n".join(lines[:MAX_COMMITS] + more)


def git_show(
    ctx: RunContext[TriageDeps], sha: str, max_lines: int = 150
) -> str:
    """Show one commit: message, changed files, and diff.

    Args:
        sha: Commit SHA, as git_log or list_deploys prints it, without
            `commit:`.
        max_lines: Number of lines to return, at most 300.
    """
    sha = sha.removeprefix("commit:")
    if not SHA.fullmatch(sha):
        raise ModelRetry(f"{sha!r} is not a commit SHA. Use 4-40 hex chars.")
    out = _git(
        ctx, "show", "--stat", "--patch", "--format=commit:%h %cI %s", sha, "--"
    )
    if out is None:
        return NO_REPO
    lines = out.splitlines()
    limit = max(1, min(max_lines, MAX_SHOW_LINES))
    more = [f"[{len(lines) - limit} more lines]"] if len(lines) > limit else []
    return "\n".join([_cut(x) for x in lines[:limit]] + more)


TOOLS = [
    read_alert,
    list_sources,
    count_logs,
    search_logs,
    read_log,
    query_metric,
    list_deploys,
    git_log,
    git_show,
]
