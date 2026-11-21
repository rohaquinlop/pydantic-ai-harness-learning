# AGENTS.md

Examples, experiments, and learnings with pydantic-ai. Each example is a uv workspace member under `examples/<name>/`.

## Layout

- `examples/<name>/src/<name>/`: the package. Each package has a CLI entry point in `[project.scripts]`.
- `examples/<name>/tests/`: offline tests. Shared helpers live in `tests/helpers.py` and are imported as `examples.<name>.tests.helpers`.
- `examples/<name>/evals/`: `cases.py` (planted-bug cases) and `review_evals.py` (a `pydantic_evals.Dataset`). Evals call real models.
- `examples/<name>/README.md`: what the example shows and how to run it. Keep it current when behavior or flags change.
- `.github/workflows/pr-review.yml`: runs `pr-reviewer` on a PR when a `pr-reviewer: run` or `pr-reviewer: new round` label is added.

## Docs

- pydantic-ai, the harness, and pydantic-evals change fast. Read the docs before you use or change an API. Do not answer from memory.
- Index: `https://pydantic.dev/docs/ai/llms.txt`. Each page has a Markdown version at `<page URL>/index.md`.

## Tooling

- Use `uv` for everything. Never call `python`, `pip`, or `python -m venv` directly.
- Python 3.13. Install with `uv sync`.
- Add a dependency to the example that needs it (`uv add --package <name> <pkg>`), not to the root. Dev tools go in the root `dev` group.

## Checks

Run all of them from the repo root before you say a change is done:

```bash
uv run pytest
```

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

- The type checker is `ty`. Ignore pyright and mypy diagnostics.
- Line length is 80, for code and docstrings.

## Tests

- Tests are offline. Each `conftest.py` sets `models.ALLOW_MODEL_REQUESTS = False`. Never remove it, and never make a test call a real model.
- Use the scripted `FunctionModel` in `tests/helpers.py` or `TestModel`. `pr_reviewer` has module-level agents, so swap the model with `agent.override(model=...)`. `ui_qa_reviewer` builds its agent with `build_agent(...)`, so pass `model=` to the run. `RepoContext` makes streamed requests, so a `FunctionModel` for the harness engine needs a `stream_function`.
- `ui_qa_reviewer` tests use a stub browser. They do not need Chromium.
- Use `pytest.mark.parametrize` for near-identical cases. Put shared setup in fixtures or `helpers.py`. Do not copy setup between tests.
- Use `pathlib`. Tests must not depend on POSIX-only behavior.
- The docs suggest `inline-snapshot` for long assertions and `dirty-equals` for large data structures. They are not installed. Ask before you add them to the `dev` group.

## API keys and `.env`

- Put API keys in `.env` at the repo root. It is git-ignored. Never commit it, print it, or copy a key into code, docs, or logs.
- The code does not load `.env`. Pass it to `uv run` with `--env-file .env`.
- Keys by provider:
  - `ANTHROPIC_API_KEY`: the default models (`anthropic:claude-*`).
  - `DEEPSEEK_API_KEY`: `deepseek:*` models.
  - `GH_TOKEN`: only for `pr-reviewer --pr` / `--post`. `gh auth login` also works.
- Before a live run, check that the key for the chosen model is set. Check presence only, never the value:

```bash
uv run --env-file .env python -c "import os; print({k: bool(os.environ.get(k)) for k in ('ANTHROPIC_API_KEY', 'DEEPSEEK_API_KEY')})"
```

- If the key is missing, stop. Tell the user which key to add to `.env`. Do not retry with another provider unless the user asks.

## Evals

- Evals call real models and cost money. Run them only when the user asks. Start with `--repeat 1`.
- Run them from the repo root as modules, with `.env`:

```bash
uv run --env-file .env -m examples.pr_reviewer.evals.review_evals --model deepseek:deepseek-chat
```

```bash
uv run --env-file .env -m examples.ui_qa_reviewer.evals.review_evals --model deepseek:deepseek-flash
```

```bash
uv run --env-file .env -m examples.incident_triager.evals.review_evals --model deepseek:deepseek-chat
```

- Flags:
  - `--model`: default is Haiku for `pr_reviewer`, and Sonnet for `ui_qa_reviewer` and `incident_triager`.
  - `--repeat N`: runs per case.
  - `--max-concurrency N`: default 2.
  - `--engine custom|harness`: `pr_reviewer` only. Compare the two engines with the same model and `--repeat`.
- `ui_qa_reviewer` evals need Chromium once: `uv run playwright install chromium`. The cases serve the demo on a free loopback port.
- `ui_qa_reviewer` needs a model with vision and tool use.
- Report the eval table as printed. Do not claim a model or engine is better from one run.

## Debugging a run

- Reproduce the problem in one run: same prompt, deps, model, and settings.
- Read what the model saw: `result.all_messages()` after the run, or `capture_run_messages()` when the run raises. Check the instructions and tool descriptions first, then each tool call and its return.
- Pin the problem in a test: put the recorded responses in a `FunctionModel` and assert on the fix.
- These fail with no error. Check them when a run or eval looks wrong:
  - The run stopped early: `UsageLimitExceeded`. The examples use `request_limit=30` (`pr_reviewer`) and `request_limit=40` (`ui_qa_reviewer`).
  - The answer is cut off: finish reason `length`.
  - The model refused: finish reason `content_filter`.
  - A setting had no effect: settings a model does not support (for example `temperature`) are skipped silently.
  - `cost` is `None`: `genai-prices` has no price for the model.
  - A different model answered: with a fallback model, check `failed_attempts`.

### Retries

- Retries happen at many layers, and the budgets do not share. Read `https://pydantic.dev/docs/ai/core-concepts/retries/index.md` before you change one.
- Transport and provider SDK retries re-send the same HTTP request. The agent does not see them, and they multiply each other.
- Tool retries and output retries ask the model to fix its answer. `ModelRetry` from a tool or an output validator uses this budget, and each retry adds a message to the history. The agents here set `retries={"tools": 3}`, plus `"output": 3` in `ui_qa_reviewer`.

### Logfire

- Logfire records each run, model request, and tool call as a trace. `pydantic-evals` sends experiment results to it too.
- It is not set up in this repo. Ask before you add it.
- Setup:
  - Add the `logfire` extra to `pydantic-ai-slim` in the example, and `pydantic-evals[logfire]` to the `dev` group.
  - Run `uvx logfire-cli auth`, then `uvx logfire-cli init`. `init` writes a `.logfire/` directory. Add it to `.gitignore`.
  - Call `logfire.configure()` and `logfire.instrument_pydantic_ai()` in the entry point, before the first run.

## CLIs

- `pr-reviewer` and `ui-qa-reviewer` read `HEAD`, not the working tree. Commit first.
- Run `git fetch` before you pass `--base origin/main`.

```bash
uv run --env-file .env pr-reviewer --repo . --base origin/main --task "<task contract>"
```

```bash
uv run --env-file .env ui-qa-reviewer --base origin/main --url http://localhost:5173 --task "<task contract>"
```

- `pr-reviewer` keeps its call budget in `.git/pr-reviewer/<branch>.json`. Use `--new-round` to reset it.
- `--post` writes to a GitHub PR. Ask before you use it.

## Add an example

1. `uv init --package --name <name> examples/<name>`
2. Add `<name>` to `dependencies` and `[tool.uv.sources]` in the root `pyproject.toml`.
3. `uv sync`
4. Add a `tests/conftest.py` that sets `models.ALLOW_MODEL_REQUESTS = False`.
5. Add a row to the table in the root `README.md`.

## Git

- Conventional commits, scoped to the example: `feat(pr_reviewer): ...`, `docs(ui_qa_reviewer): ...`.
- Small, logical commits. Never stage `.env`, caches, or scratch files such as `PR_DESCRIPTION.md`.
