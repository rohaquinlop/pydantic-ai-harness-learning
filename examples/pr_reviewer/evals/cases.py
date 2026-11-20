from pathlib import Path

from pr_reviewer.bundle import run
from pr_reviewer.models import ReviewResult
from pydantic import BaseModel
from pydantic_evals import Case


class RepoCase(BaseModel):
    """A tiny repo: files on main, and the files the candidate commit changes or adds."""

    task: str
    base: dict[str, str]
    head: dict[str, str]


def commit(repo: Path, files: dict[str, str], message: str) -> None:
    for name, content in files.items():
        (repo / name).write_text(content)
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-qm", message)


def build_repo(case: RepoCase, repo: Path, branch: str = "candidate") -> Path:
    """Create `repo` with `case.base` on main and `case.head` committed on `branch`."""
    repo.mkdir()
    run(repo, "git", "init", "-q", "-b", "main")
    run(repo, "git", "config", "user.email", "eval@example.com")
    run(repo, "git", "config", "user.name", "eval")
    commit(repo, case.base, "base")
    run(repo, "git", "switch", "-qc", branch)
    commit(repo, case.head, "candidate")
    return repo


class PlantedBug(BaseModel):
    file: str
    first_line: int
    last_line: int


CALC_GUARDED = "def ratio(a, b):\n    return a / b if b else 0\n"
REPEAT_BASE = "def repeat(text, n=2):\n    return text * n\n"
PAGE = (
    "def page(items, number, size):\n"
    '    """Return page `number` (1-based) of `items`."""\n'
    "    start = (number - 1) * size\n"
    "    return items[start:start + size]\n"
)
CONFIG_BASE = (
    'from pathlib import Path\n\nCACHE_DIR = Path.home() / ".cache" / "app"\n'
)

CASES: list[Case[RepoCase, ReviewResult, PlantedBug]] = [
    Case(
        name="guard_removed",
        inputs=RepoCase(
            task="Simplify ratio().",
            base={
                "CLAUDE.md": "Guard every division by zero.\n",
                "calc.py": CALC_GUARDED,
            },
            head={"calc.py": "def ratio(a, b):\n    return a / b\n"},
        ),
        metadata=PlantedBug(file="calc.py", first_line=1, last_line=2),
    ),
    Case(
        name="off_by_one",
        inputs=RepoCase(
            task="Add page_count(), the number of pages page() can return.",
            base={"pages.py": PAGE},
            head={
                "pages.py": PAGE
                + "\n\ndef page_count(items, size):\n    return len(items) // size\n"
            },
        ),
        metadata=PlantedBug(file="pages.py", first_line=7, last_line=8),
    ),
    Case(
        name="rule_violation",
        inputs=RepoCase(
            task="Add cache_file(name), the path of a file in the cache dir.",
            base={
                "CLAUDE.md": "Use pathlib for paths. Never use os.path.\n",
                "config.py": CONFIG_BASE,
            },
            head={
                "config.py": "import os\n"
                + CONFIG_BASE
                + "\n\ndef cache_file(name):\n    return os.path.join(CACHE_DIR, name)\n"
            },
        ),
        metadata=PlantedBug(file="config.py", first_line=1, last_line=8),
    ),
    Case(
        name="scope_creep",
        inputs=RepoCase(
            task="Rename the parameter n to count in repeat(). Change nothing else.",
            base={"util.py": REPEAT_BASE},
            head={
                "util.py": "def repeat(text, count=3):\n    return text * count\n"
            },
        ),
        metadata=PlantedBug(file="util.py", first_line=1, last_line=1),
    ),
    Case(
        name="clean_docstring",
        inputs=RepoCase(
            task="Add a docstring to ratio().",
            base={"calc.py": CALC_GUARDED},
            head={
                "calc.py": "def ratio(a, b):\n"
                '    """Return a / b, or 0 when b is 0."""\n'
                "    return a / b if b else 0\n"
            },
        ),
    ),
]
