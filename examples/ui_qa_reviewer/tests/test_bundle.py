from pathlib import Path

from ui_qa_reviewer.bundle import build_bundle


def test_keeps_only_frontend_files(ui_repo: Path) -> None:
    bundle = build_bundle(ui_repo, "main", "Add the sign-up page.")

    assert bundle.changed_files == ["index.html"]
    assert "b/index.html" in bundle.diff
    assert "app.py" not in bundle.diff
