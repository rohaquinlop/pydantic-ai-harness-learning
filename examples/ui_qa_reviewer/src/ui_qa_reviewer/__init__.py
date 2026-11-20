import argparse
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_ai.exceptions import AgentRunError

from ui_qa_reviewer.models import QAPassed
from ui_qa_reviewer.review import review


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a QA review of the UI changes on the current branch against a preview."
    )
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--base", required=True, help="Target branch ref, such as origin/main."
    )
    parser.add_argument(
        "--url", required=True, help="Preview URL of this branch's build."
    )
    parser.add_argument("--task", required=True, help="The task contract.")
    parser.add_argument("--model", help="Default: the Sonnet model.")
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme not in ("http", "https") or not url.hostname:
        parser.error("--url must be an http or https URL with a host")

    try:
        outcome = review(args.repo, args.base, args.url, args.task, args.model)
    except AgentRunError as e:
        raise SystemExit(f"QA reviewer failed: {e}") from e
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"{' '.join(e.cmd)} failed: {e.stderr.strip()}") from e

    if isinstance(outcome.output, QAPassed):
        print(f"passed at {outcome.output.sha}")
        for page in outcome.output.checked:
            print(f"  checked: {page}")
    else:
        for f in outcome.output.findings:
            print(f"[{f.severity}][{f.category}] {f.url} — {f.actual}")
            print(f"  expected: {f.expected}")
            for n, step in enumerate(f.steps, 1):
                print(f"  {n}. {step}")
            if f.file:
                print(f"  likely file: {f.file}")
    print(f"\nusage: {outcome.usage}")
