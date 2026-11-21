from pathlib import Path

import pytest
from incident_triager.grounding import cites
from incident_triager.triage import triage
from pydantic_ai.exceptions import UnexpectedModelBehavior

from examples.incident_triager.tests.helpers import final, hypothesis
from examples.pr_reviewer.tests.helpers import Call, Script

DEPLOYS: Call = ("list_deploys", {})
ALERT: Call = ("read_alert", {})
GROUNDED = final(hypothesis("code_change", "deploy:d-102"))
MISFILED = {"source": "log", "ref": "deploy:d-102", "detail": "seen"}


@pytest.mark.parametrize(
    ("text", "ref", "expected"),
    [
        ("deploy:d-102 at 11:00", "deploy:d-102", True),
        ("deploy:d-102 at 11:00", "deploy:d-10", False),
        ("logs/api.log:120: ERROR", "logs/api.log:12", False),
        ("logs/api.log:120: ERROR", "logs/api.log:120", True),
        ("logs/payments.log:7: WARN", "logs/payments.log", True),
        ("metric:memory_mb_max\n", "metric:memory_mb", False),
        ("see commit:adfe765.", "commit:adfe765", True),
        ("logs/api.log.1:3: x", "logs/api.log", False),
        ("xdeploy:d-1 ", "deploy:d-1", False),
    ],
)
def test_cites_matches_whole_refs(text: str, ref: str, expected: bool) -> None:
    assert cites(text, ref) is expected


@pytest.mark.parametrize(
    ("turns", "retry"),
    [
        pytest.param([[ALERT, DEPLOYS], [GROUNDED]], "", id="grounded"),
        pytest.param(
            [
                [DEPLOYS],
                [final(hypothesis("code_change", "deploy:d-10"))],
                [GROUNDED],
            ],
            "deploy:d-10.",
            id="prefix-of-a-printed-ref",
        ),
        pytest.param(
            [
                [DEPLOYS],
                [final(hypothesis("code_change", "alert"))],
                [GROUNDED],
            ],
            "refs in this run: alert.",
            id="alert-without-read-alert",
        ),
        pytest.param(
            [
                [DEPLOYS],
                [
                    final(
                        hypothesis("code_change", "deploy:d-102", "deploy:d-9")
                    )
                ],
                [GROUNDED],
            ],
            "deploy:d-9.",
            id="one-bad-ref-of-two",
        ),
        pytest.param(
            [
                [DEPLOYS],
                [final({**hypothesis("code_change"), "evidence": [MISFILED]})],
                [GROUNDED],
            ],
            "does not fit source 'log'",
            id="source-does-not-fit-ref",
        ),
        *(
            pytest.param(
                [
                    [echo, DEPLOYS],
                    [final(hypothesis("code_change", "deploy:d-999"))],
                    [GROUNDED],
                ],
                "deploy:d-999.",
                id=f"ref-only-in-{echo[0]}-args",
            )
            for echo in (
                ("count_logs", {"pattern": "deploy:d-999"}),
                ("read_log", {"file": "deploy:d-999"}),
            )
        ),
    ],
)
def test_validator_grounds_every_ref(
    incident: Path, turns: list[list[Call]], retry: str
) -> None:
    outcome = triage(incident, Script(turns).model())
    assert outcome.output.hypotheses[0].evidence[0].ref == "deploy:d-102"
    assert outcome.tool_calls == len(turns[0])
    assert [retry in r for r in outcome.retries] == ([True] if retry else [])


def test_retry_text_does_not_ground_a_ref(incident: Path) -> None:
    """The validator's retry names the bad ref; that must not count as a
    tool printing it."""
    bad = final(hypothesis("code_change", "deploy:d-10"))
    turns = [[DEPLOYS]] + [[bad]] * 4
    with pytest.raises(UnexpectedModelBehavior, match="output"):
        triage(incident, Script(turns).model())
