from pathlib import Path

import pytest
from pydantic_ai import models

from examples.pr_reviewer.evals.cases import RepoCase, build_repo

models.ALLOW_MODEL_REQUESTS = False

BASE = {"README.md": "demo\n", "app.py": "x = 1\n"}


def _repo(tmp_path: Path, head: dict[str, str]) -> Path:
    case = RepoCase(task="Add the sign-up page.", base=BASE, head=head)
    return build_repo(case, tmp_path / "repo")


@pytest.fixture
def ui_repo(tmp_path: Path) -> Path:
    return _repo(tmp_path, {"index.html": "<h1>Hi</h1>\n", "app.py": "x = 2\n"})


@pytest.fixture
def backend_repo(tmp_path: Path) -> Path:
    return _repo(tmp_path, {"app.py": "x = 2\n"})
