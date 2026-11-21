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
    try:
        return parse_ts(text.split(" ", 1)[0])
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


def load_alert(bundle: Path) -> dict[str, Any]:
    return json.loads((bundle / "alert.json").read_text(encoding="utf-8"))


def load_deploys(bundle: Path) -> list[dict[str, Any]]:
    path = bundle / "deploys.json"
    return (
        json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    )


def load_metrics(bundle: Path) -> list[MetricRow]:
    path = bundle / "metrics.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [
            MetricRow(parse_ts(r["timestamp"]), r["metric"], float(r["value"]))
            for r in csv.DictReader(f)
        ]
