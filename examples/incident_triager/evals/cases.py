import argparse
import csv
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from incident_triager.models import Category, Triage
from pydantic import BaseModel
from pydantic_evals import Case

START = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
NOISE = (
    "INFO GET /health 200 2ms",
    "INFO GET /api/cart 200 41ms",
    "INFO POST /api/orders 201 88ms",
    "INFO GET /api/products 200 35ms",
)


def at(minutes: float) -> datetime:
    return START + timedelta(minutes=minutes)


class Event(BaseModel):
    """`message` logged every `every_s` seconds from `start` to `end`."""

    start: float
    end: float
    every_s: int
    message: str


class LogSpec(BaseModel):
    noise_every_s: int = 5
    events: list[Event] = []


class Segment(BaseModel):
    """A metric that moves linearly from `a` to `b` between two minutes."""

    start: float
    end: float
    a: float
    b: float


class Commit(BaseModel):
    at: float
    message: str
    files: dict[str, str]


class Deploy(BaseModel):
    id: str
    at: float
    kind: str
    version: str
    commit: int
    description: str


class IncidentCase(BaseModel):
    """An incident bundle. Times are minutes after `START`."""

    service: str
    title: str
    summary: str
    fired_at: float
    window: float = 180
    metric_step: float = 1
    logs: dict[str, LogSpec]
    metrics: dict[str, list[Segment]]
    commits: list[Commit]
    deploys: list[Deploy]


class PlantedCause(BaseModel):
    categories: list[Category]
    key_refs: list[str]


def _log_lines(case: IncidentCase, spec: LogSpec) -> list[str]:
    total = int(case.window * 60)
    lines = [
        (at(s / 60), NOISE[(s // spec.noise_every_s) % len(NOISE)])
        for s in range(0, total, spec.noise_every_s)
    ]
    for e in spec.events:
        lines += [
            (at(s / 60), e.message)
            for s in range(int(e.start * 60), int(e.end * 60), e.every_s)
        ]
    return [f"{ts.isoformat()} {msg}" for ts, msg in sorted(lines)]


def _value(segments: list[Segment], minute: float) -> float:
    s = next(s for s in segments if s.start <= minute <= s.end)
    span = s.end - s.start
    return round(s.a + (s.b - s.a) * (minute - s.start) / span, 1)


def _metric_rows(case: IncidentCase) -> list[list[str]]:
    minutes = [
        i * case.metric_step
        for i in range(int(case.window / case.metric_step) + 1)
    ]
    return [
        [at(m).isoformat(), name, f"{_value(segments, m):g}"]
        for m in minutes
        for name, segments in case.metrics.items()
    ]


def _git(repo: Path, *args: str, when: datetime | None = None) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "eval",
        "GIT_AUTHOR_EMAIL": "eval@example.com",
        "GIT_COMMITTER_NAME": "eval",
        "GIT_COMMITTER_EMAIL": "eval@example.com",
    }
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when.isoformat()
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _build_repo(commits: list[Commit], repo: Path) -> list[str]:
    """Commit each change at its incident time. Returns the short SHAs."""
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    shas = []
    for c in commits:
        for name, content in c.files.items():
            (repo / name).write_text(content, encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", c.message, when=at(c.at))
        shas.append(_git(repo, "rev-parse", "--short", "HEAD"))
    return shas


def build_bundle(case: IncidentCase, bundle: Path) -> Path:
    """Write `case` as an incident bundle in `bundle`, which must not exist."""
    bundle.mkdir(parents=True)
    shas = _build_repo(case.commits, bundle / "repo")
    alert = {
        "title": case.title,
        "service": case.service,
        "fired_at": at(case.fired_at).isoformat(),
        "summary": case.summary,
    }
    (bundle / "alert.json").write_text(
        json.dumps(alert, indent=2), encoding="utf-8"
    )
    deploys = [
        {
            "id": d.id,
            "service": case.service,
            "kind": d.kind,
            "at": at(d.at).isoformat(),
            "version": d.version,
            "commit": shas[d.commit],
            "description": d.description,
        }
        for d in case.deploys
    ]
    (bundle / "deploys.json").write_text(
        json.dumps(deploys, indent=2), encoding="utf-8"
    )
    (bundle / "logs").mkdir()
    for name, spec in case.logs.items():
        text = "\n".join(_log_lines(case, spec)) + "\n"
        (bundle / "logs" / name).write_text(text, encoding="utf-8")
    with (bundle / "metrics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "metric", "value"])
        writer.writerows(_metric_rows(case))
    return bundle


def flat(value: float, end: float = 180) -> list[Segment]:
    return [Segment(start=0, end=end, a=value, b=value)]


def step(
    before: float, after: float, at_min: float, end: float = 180
) -> list[Segment]:
    return [
        Segment(start=0, end=at_min, a=before, b=before),
        Segment(start=at_min, end=end, a=after, b=after),
    ]


DB_BASE = "POOL_SIZE = 20\nPOOL_TIMEOUT_S = 30\n"
APP_BASE = "def handler(request):\n    return checkout(request)\n"
INITIAL = Commit(at=-600, message="Initial import", files={"app.py": APP_BASE})

BAD_DEPLOY = IncidentCase(
    service="checkout",
    title="checkout: 5xx rate above 5%",
    summary="Checkout API returns 5xx on many requests.",
    fired_at=128,
    logs={
        "api.log": LogSpec(
            events=[
                Event(
                    start=122,
                    end=180,
                    every_s=3,
                    message="ERROR TimeoutError: QueuePool limit of size 5 "
                    "overflow 0 reached, connection timed out after 30s",
                )
            ]
        )
    },
    metrics={
        "error_rate_pct": step(0.2, 11.5, 122),
        "db_pool_wait_ms": [
            Segment(start=0, end=121, a=4, b=4),
            Segment(start=121, end=180, a=4, b=2600),
        ],
        "requests_per_s": flat(210),
    },
    commits=[
        Commit(
            at=-600,
            message="Initial import",
            files={"app.py": APP_BASE, "db.py": DB_BASE},
        ),
        Commit(
            at=20,
            message="Add request id to access logs",
            files={"app.py": APP_BASE + "\nLOG_REQUEST_ID = True\n"},
        ),
        Commit(
            at=110,
            message="Reduce DB pool size to save connections",
            files={"db.py": "POOL_SIZE = 5\nPOOL_TIMEOUT_S = 30\n"},
        ),
    ],
    deploys=[
        Deploy(
            id="d-101",
            at=30,
            kind="code",
            version="v2.3.0",
            commit=1,
            description="Add request id to access logs",
        ),
        Deploy(
            id="d-102",
            at=120,
            kind="code",
            version="v2.3.1",
            commit=2,
            description="Reduce DB pool size",
        ),
    ],
)

FEATURE_FLAG = IncidentCase(
    service="pricing",
    title="pricing: error rate above 2%",
    summary="Price lookups fail for some carts.",
    fired_at=136,
    logs={
        "api.log": LogSpec(
            events=[
                Event(
                    start=131,
                    end=180,
                    every_s=4,
                    message="ERROR KeyError: 'currency' in price_for(cart) "
                    "flag=new_pricing",
                )
            ]
        )
    },
    metrics={
        "error_rate_pct": step(0.1, 6.0, 131),
        "latency_p99_ms": flat(140),
        "requests_per_s": flat(320),
    },
    commits=[
        INITIAL,
        Commit(
            at=50,
            message="Bump requests from 2.32.3 to 2.32.4",
            files={"requirements.txt": "requests==2.32.4\n"},
        ),
        Commit(
            at=125,
            message="Turn on new_pricing for all regions",
            files={"flags.yaml": "new_pricing: true\n"},
        ),
    ],
    deploys=[
        Deploy(
            id="d-200",
            at=60,
            kind="code",
            version="v5.1.4",
            commit=1,
            description="Bump requests",
        ),
        Deploy(
            id="d-201",
            at=130,
            kind="config",
            version="flags-88",
            commit=2,
            description="Enable new_pricing flag",
        ),
    ],
)

UPSTREAM = IncidentCase(
    service="checkout",
    title="checkout: order success rate below 90%",
    summary="Orders fail at the payment step.",
    fired_at=146,
    logs={
        "api.log": LogSpec(
            events=[
                Event(
                    start=140,
                    end=180,
                    every_s=5,
                    message="ERROR PaymentError: provider unavailable",
                )
            ]
        ),
        "payments.log": LogSpec(
            noise_every_s=10,
            events=[
                Event(
                    start=140,
                    end=180,
                    every_s=5,
                    message="WARN POST https://api.payprovider.example/v1/"
                    "charges -> 503 Service Unavailable (retry 3/3)",
                )
            ],
        ),
    },
    metrics={
        "error_rate_pct": step(0.2, 9.0, 140),
        "payment_latency_ms": step(310, 30000, 140),
        "requests_per_s": flat(205),
    },
    commits=[
        INITIAL,
        Commit(
            at=125,
            message="Add dark mode styles to the receipt page",
            files={"receipt.css": "body.dark { background: #111; }\n"},
        ),
    ],
    deploys=[
        Deploy(
            id="d-301",
            at=135,
            kind="code",
            version="v2.4.0",
            commit=1,
            description="Receipt page dark mode",
        )
    ],
)

TRAFFIC = IncidentCase(
    service="search",
    title="search: p99 latency above 2s",
    summary="Search is slow for most users.",
    fired_at=142,
    logs={
        "api.log": LogSpec(
            events=[
                Event(
                    start=138,
                    end=180,
                    every_s=2,
                    message="WARN request timed out after 5000ms "
                    "path=/api/search",
                )
            ]
        )
    },
    metrics={
        "requests_per_s": step(300, 950, 135),
        "latency_p99_ms": step(120, 4100, 136),
        "cpu_pct": step(45, 98, 135),
        "error_rate_pct": flat(0.1),
    },
    commits=[
        INITIAL,
        Commit(
            at=80,
            message="Set search-indexer log level to DEBUG",
            files={"logging.yaml": "search_indexer: DEBUG\n"},
        ),
    ],
    deploys=[
        Deploy(
            id="d-401",
            at=90,
            kind="config",
            version="cfg-17",
            commit=1,
            description="Debug logs for search-indexer",
        )
    ],
)

LEAK_WINDOW = 2880
MEMORY_LEAK = IncidentCase(
    service="worker",
    title="worker: pod restarts above 3 in 10 min",
    summary="Worker pods restart again and again.",
    fired_at=2870,
    window=LEAK_WINDOW,
    metric_step=15,
    logs={
        "worker.log": LogSpec(
            noise_every_s=60,
            events=[
                Event(
                    start=2850,
                    end=2880,
                    every_s=120,
                    message="ERROR container worker OOMKilled "
                    "(memory limit 2048Mi)",
                )
            ],
        )
    },
    metrics={
        "memory_mb": [
            Segment(start=0, end=60, a=410, b=410),
            Segment(start=60, end=LEAK_WINDOW, a=410, b=2040),
        ],
        "cpu_pct": flat(35, LEAK_WINDOW),
        "requests_per_s": flat(80, LEAK_WINDOW),
    },
    commits=[
        INITIAL,
        Commit(
            at=45,
            message="Cache parsed templates",
            files={
                "templates.py": "_CACHE = {}\n\n\ndef render(name, ctx):\n"
                "    _CACHE[(name, id(ctx))] = parse(name)\n"
                "    return _CACHE[(name, id(ctx))](ctx)\n"
            },
        ),
        Commit(
            at=2830,
            message="Fix typo in email footer",
            files={"footer.txt": "Thanks for your order.\n"},
        ),
    ],
    deploys=[
        Deploy(
            id="d-501",
            at=60,
            kind="code",
            version="v8.0.0",
            commit=1,
            description="Template cache",
        ),
        Deploy(
            id="d-502",
            at=2840,
            kind="code",
            version="v8.0.1",
            commit=2,
            description="Email footer typo",
        ),
    ],
)

CASES: list[Case[IncidentCase, Triage, PlantedCause]] = [
    Case(
        name="bad_deploy",
        inputs=BAD_DEPLOY,
        metadata=PlantedCause(
            categories=["code_change", "config_change"],
            key_refs=["deploy:d-102"],
        ),
    ),
    Case(
        name="feature_flag",
        inputs=FEATURE_FLAG,
        metadata=PlantedCause(
            categories=["config_change"], key_refs=["deploy:d-201"]
        ),
    ),
    Case(
        name="upstream_outage",
        inputs=UPSTREAM,
        metadata=PlantedCause(
            categories=["dependency"],
            key_refs=["logs/payments.log", "metric:payment_latency_ms"],
        ),
    ),
    Case(
        name="traffic_spike",
        inputs=TRAFFIC,
        metadata=PlantedCause(
            categories=["capacity"], key_refs=["metric:requests_per_s"]
        ),
    ),
    Case(
        name="memory_leak",
        inputs=MEMORY_LEAK,
        metadata=PlantedCause(
            categories=["resource_leak"],
            key_refs=["deploy:d-501", "metric:memory_mb"],
        ),
    ),
]


def main() -> None:
    names = [c.name for c in CASES]
    parser = argparse.ArgumentParser(
        description="Write an eval case as an incident bundle, for a demo run."
    )
    parser.add_argument("case", choices=names)
    parser.add_argument("dir", type=Path, help="Bundle dir. Must not exist.")
    args = parser.parse_args()
    case = next(c for c in CASES if c.name == args.case)
    print(build_bundle(case.inputs, args.dir))


if __name__ == "__main__":
    main()
