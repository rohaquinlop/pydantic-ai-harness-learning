import json
from pathlib import Path

import pytest
from pydantic_ai import models

from examples.incident_triager.evals.cases import BAD_DEPLOY, build_bundle

models.ALLOW_MODEL_REQUESTS = False

ODD_LOG = (
    "2026-11-20T09:59:00 ERROR naive timestamp\n"
    "garbage line without a timestamp\n"
    f"2026-11-20T10:01:00Z ERROR {'x' * 400}\n"
)


@pytest.fixture(scope="session")
def incident(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The bad_deploy eval bundle. Read-only, so one per session."""
    return build_bundle(BAD_DEPLOY, tmp_path_factory.mktemp("i") / "bundle")


@pytest.fixture
def odd(tmp_path: Path) -> Path:
    """A bundle with naive and bad timestamps, a long line, and no repo/."""
    alert = {"title": "odd", "fired_at": "2026-11-20T10:00:00+00:00"}
    (tmp_path / "alert.json").write_text(json.dumps(alert))
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "app.log").write_text(ODD_LOG)
    return tmp_path
