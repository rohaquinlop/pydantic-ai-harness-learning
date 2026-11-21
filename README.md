# pydantic-ai learning

Examples, experiments, and learnings with [pydantic-ai](https://pydantic.dev/docs/ai/overview/).

Each example is a uv workspace member under `examples/<name>/`, with its own `pyproject.toml` and `README.md`.

## Examples

| Example | What it shows |
|---|---|
| [pr_reviewer](examples/pr_reviewer/) | A fresh, read-only PR reviewer modeled on shepherd's reviewer: structured output, deps, and tools. |
| [ui_qa_reviewer](examples/ui_qa_reviewer/) | A QA reviewer for a PR's UI changes: a real browser as a capability, image tool returns, egress policy, and a validator that reads the message history. |
| [incident_triager](examples/incident_triager/) | An incident triager over a local bundle of logs, metrics, deploys, and git history: tools that page and aggregate large outputs, a hypothesis-then-check loop, and a validator that only accepts evidence a tool printed. |

## Setup

```bash
uv sync
```

```bash
uv run pytest
```

The other checks:

```bash
uv run ruff check .
```

```bash
uv run ruff format --check .
```

```bash
uv run ty check
```

```bash
uv run complexipy examples
```

Shared test helpers live in `examples/<name>/tests/helpers.py` and are imported as `examples.<name>.tests.helpers`, so names never clash across examples.

## Add an example

1. `uv init --package --name <name> examples/<name>`
2. Add `<name>` to `dependencies` and `[tool.uv.sources]` in the root `pyproject.toml`.
3. `uv sync`
