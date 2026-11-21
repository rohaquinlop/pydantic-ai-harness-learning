import argparse
from pathlib import Path

from pydantic_ai.exceptions import AgentRunError

from incident_triager.bundle import BundleError
from incident_triager.models import Hypothesis
from incident_triager.triage import triage


def _render(rank: int, h: Hypothesis) -> list[str]:
    return [
        f"{rank}. [{h.category}, {h.confidence}] {h.cause}",
        *(f"   - {e.ref}: {e.detail}" for e in h.evidence),
        f"   check: {h.check}",
        f"   refuted if: {h.refuted_if}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Triage an incident bundle into ranked root-cause "
        "hypotheses."
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        required=True,
        help="Directory with alert.json, logs/, metrics.csv, deploys.json, "
        "and an optional repo/.",
    )
    parser.add_argument("--model", help="Default: Sonnet.")
    args = parser.parse_args()
    if not (args.bundle / "alert.json").is_file():
        parser.error(f"{args.bundle} has no alert.json")

    try:
        outcome = triage(args.bundle, args.model)
    except AgentRunError as e:
        lines = [f"triage failed: {e}", *getattr(e, "__notes__", [])]
        raise SystemExit("\n".join(lines)) from e
    except BundleError as e:
        raise SystemExit(f"bad bundle: {e}") from e

    print(outcome.output.summary)
    for rank, h in enumerate(outcome.output.hypotheses, 1):
        print("\n".join(_render(rank, h)))
    for retry in outcome.retries:
        print(f"retry: {retry}")
    print(f"\ntool calls: {outcome.tool_calls}")
    print(f"usage: {outcome.usage}")
