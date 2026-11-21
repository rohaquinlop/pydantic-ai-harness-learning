import sys
from pathlib import Path

import pytest
from incident_triager import main
from incident_triager.agent import triager

from examples.incident_triager.tests.helpers import final, hypothesis
from examples.pr_reviewer.tests.helpers import Script


def run_cli(bundle: Path, turns: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["incident-triager", "--bundle", str(bundle)]
    )
    with triager.override(model=Script(turns).model()):
        main()


def test_prints_hypotheses_and_usage(
    incident: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    turns = [
        [("list_deploys", {})],
        [final(hypothesis("code_change", "deploy:d-10"))],
        [final(hypothesis("code_change", "deploy:d-102"))],
    ]
    run_cli(incident, turns, monkeypatch)
    out = capsys.readouterr().out
    assert "1. [code_change, high] suspected code_change" in out
    assert "   - deploy:d-102: seen" in out
    assert "retry: final_result: No tool printed these refs" in out
    assert "tool calls: 1" in out
    assert "usage: " in out


def test_fails_cleanly_after_output_retries(
    incident: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = [final(hypothesis("code_change", "deploy:d-10"))]
    with pytest.raises(SystemExit, match="triage failed") as e:
        run_cli(incident, [[("list_deploys", {})]] + [bad] * 4, monkeypatch)
    assert "retry: final_result: No tool printed" in str(e.value)


def test_rejects_a_dir_without_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit):
        run_cli(tmp_path, [], monkeypatch)
