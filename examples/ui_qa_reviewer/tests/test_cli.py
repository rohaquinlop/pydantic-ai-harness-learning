import pytest
from ui_qa_reviewer import main


@pytest.mark.parametrize(
    "url",
    ["localhost:5173", "ftp://h/", "http:///x", "http://h:bad/", "http://[::1"],
)
def test_rejects_bad_url(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    argv = ["ui-qa-reviewer", "--base", "main", "--url", url, "--task", "t"]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
