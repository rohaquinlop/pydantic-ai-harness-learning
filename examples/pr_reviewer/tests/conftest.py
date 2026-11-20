from pathlib import Path

import pytest
from pr_reviewer.models import ReviewDeps
from pr_reviewer.tools import changed_files
from pydantic_ai import models

from examples.pr_reviewer.evals.cases import RepoCase, build_repo
from examples.pr_reviewer.tests.helpers import (
    BASE_CALC,
    CLAUDE_MD,
    DIFF,
    HEAD_CALC,
    HEAD_SHA,
)

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def deps(tmp_path: Path) -> ReviewDeps:
    base = tmp_path / "base"
    base.mkdir()
    (base / "CLAUDE.md").write_text(CLAUDE_MD)
    (base / "calc.py").write_text(BASE_CALC)
    (tmp_path / "outside.txt").write_text("secret\n")
    return ReviewDeps(base, HEAD_SHA, changed_files(DIFF))


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    case = RepoCase(
        task="Simplify ratio()",
        base={"CLAUDE.md": CLAUDE_MD, "calc.py": BASE_CALC},
        head={"calc.py": HEAD_CALC},
    )
    return build_repo(case, tmp_path / "repo", branch="feat/x")
