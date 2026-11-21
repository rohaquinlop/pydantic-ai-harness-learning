from typing import Any

from incident_triager.models import Category

from examples.pr_reviewer.tests.helpers import Call

FINAL = "final_result"


def hypothesis(category: Category, *refs: str) -> dict[str, Any]:
    return {
        "cause": f"suspected {category}",
        "category": category,
        "confidence": "high",
        "evidence": [
            {"source": "deploy", "ref": ref, "detail": "seen"} for ref in refs
        ],
        "check": "compare error start with the deploy time",
        "refuted_if": "errors started before the deploy",
    }


def final(*hypotheses: dict[str, Any]) -> Call:
    return (FINAL, {"summary": "incident", "hypotheses": list(hypotheses)})
