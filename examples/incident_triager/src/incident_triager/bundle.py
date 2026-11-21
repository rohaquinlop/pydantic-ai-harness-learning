import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LogLine:
    ref: str
    text: str
    ts: datetime | None


@dataclass(frozen=True)
class MetricRow:
    ts: datetime
    metric: str
    value: float


def parse_ts(text: str) -> datetime:
    """Parse an ISO timestamp. A naive value is taken as UTC."""
    ts = datetime.fromisoformat(text.strip())
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _line_ts(text: str) -> datetime | None:
    """The line's leading timestamp, `2026-11-20T09:00:00Z` or
    `2026-11-20 09:00:00`. A date with no time is not a timestamp."""
    parts = text.split(" ", 2)
    stamp = parts[0]
    if "T" not in stamp:
        if len(parts) < 2:
            return None
        stamp = f"{stamp}T{parts[1]}"
    try:
        return parse_ts(stamp)
    except ValueError:
        return None


def logs_dir(bundle: Path) -> Path:
    return (bundle / "logs").resolve()


def log_files(bundle: Path, file_glob: str) -> list[Path]:
    """Log files that match `file_glob`, sorted. Matches outside logs/ drop."""
    root = logs_dir(bundle)
    matches = {p.resolve() for p in root.glob(file_glob)}
    return sorted(p for p in matches if p.is_relative_to(root) and p.is_file())


def log_ref(bundle: Path, path: Path) -> str:
    return path.relative_to(bundle.resolve()).as_posix()


def read_lines(bundle: Path, path: Path) -> list[LogLine]:
    ref = log_ref(bundle, path)
    return [
        LogLine(f"{ref}:{n}", text, _line_ts(text))
        for n, text in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        )
    ]


class BundleError(Exception):
    """A bundle file the tools cannot read. The run stops: the data is wrong,
    not the model's call."""


DEPLOY_KEYS = (
    "id",
    "at",
    "service",
    "kind",
    "version",
    "commit",
    "description",
)


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise BundleError(f"{path.name}: {e}") from e


def load_alert(bundle: Path) -> dict[str, Any]:
    alert = _json(bundle / "alert.json")
    if not isinstance(alert, dict):
        raise BundleError("alert.json: expected a JSON object")
    return alert


def _check_deploy(n: int, deploy: Any) -> None:
    if not isinstance(deploy, dict):
        raise BundleError(f"deploys.json item {n}: expected an object")
    if missing := [k for k in DEPLOY_KEYS if k not in deploy]:
        raise BundleError(f"deploys.json item {n}: missing {missing}")
    try:
        parse_ts(deploy["at"])
    except (TypeError, ValueError) as e:
        raise BundleError(f"deploys.json item {n}: bad at: {e}") from e


def load_deploys(bundle: Path) -> list[dict[str, Any]]:
    path = bundle / "deploys.json"
    deploys = _json(path) if path.is_file() else []
    if not isinstance(deploys, list):
        raise BundleError("deploys.json: expected a JSON list")
    for n, deploy in enumerate(deploys):
        _check_deploy(n, deploy)
    return deploys


def load_metrics(bundle: Path) -> list[MetricRow]:
    path = bundle / "metrics.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        try:
            return [
                MetricRow(
                    parse_ts(r["timestamp"]), r["metric"], float(r["value"])
                )
                for r in csv.DictReader(f)
            ]
        except (KeyError, TypeError, ValueError) as e:
            raise BundleError(f"metrics.csv: {e!r}") from e
