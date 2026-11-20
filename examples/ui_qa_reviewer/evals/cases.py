import threading
from collections.abc import Generator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import BaseModel
from pydantic_evals import Case

from examples.pr_reviewer.evals.cases import RepoCase

DEMO = Path(__file__).parent.parent / "demo"
TASK = "Add the sign-up page."
BASE = {"README.md": "Sign-up demo.\n"}


class PlantedBug(BaseModel):
    name: str
    categories: frozenset[str]


def demo_files() -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(DEMO.iterdir())}


def planted_files() -> dict[str, str]:
    """The demo with two bugs a desktop browser can see."""
    files = demo_files()
    files["index.html"] = files["index.html"].replace(
        '<label for="email">Email</label>\n        ', ""
    )
    files["app.js"] = files["app.js"].replace(
        'getElementById("message")', 'getElementById("msg")'
    )
    return files


MISSING_LABEL = PlantedBug(
    name="missing_label", categories=frozenset({"accessibility"})
)
SUBMIT_ERROR = PlantedBug(
    name="submit_error", categories=frozenset({"functional", "console"})
)

CASES = [
    Case(
        name="clean",
        inputs=RepoCase(task=TASK, base=BASE, head=demo_files()),
        metadata=[],
    ),
    Case(
        name="planted",
        inputs=RepoCase(task=TASK, base=BASE, head=planted_files()),
        metadata=[MISSING_LABEL, SUBMIT_ERROR],
    ),
]


@contextmanager
def serve(directory: Path) -> Generator[str]:
    """Serve `directory` on a free loopback port, and yield its URL."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/"
        finally:
            server.shutdown()
