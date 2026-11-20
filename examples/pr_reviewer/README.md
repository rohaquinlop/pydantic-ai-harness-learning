# pr_reviewer

A fresh, read-only PR reviewer built with pydantic-ai. It follows the reviewer in shepherd: it gets one diff and a clean checkout of the target branch, and returns findings or `current at <sha>`.

## Steps

1. Structured output: `Findings | Current` as `output_type`.
2. Deps and tools: `ReviewDeps(policy_base)` and read-only `read_file`, `glob`, `grep` scoped to the policy base.
3. Output validator: `@reviewer.output_validator` raises `ModelRetry` when `Current.sha` is not the head SHA, or a finding names a file that is not in the diff or the policy base.
4. Bundle and review loop: each run builds a bundle from git (and `gh` with `--pr`), checks out the target branch tip as a temporary worktree (the policy base: rules and code), diffs `merge-base...HEAD`, and runs one fresh agent call. Each round has 3 review calls plus 1 verify call. In round 1 before a PR exists, call 1 uses Haiku and calls 2-3 use Opus. Every other call uses Haiku. Each call has a `UsageLimits(request_limit=30)`. The state lives in `.git/pr-reviewer/<branch>.json`. An empty diff returns `Current` without a model call, and does not spend a call. The budget check still runs first, so a spent budget raises an error even for an empty diff.
5. Offline tests: `models.ALLOW_MODEL_REQUESTS = False`, a scripted `FunctionModel` (`tests/helpers.py`) for tools, validator, and the review loop on a temp git repo, and `TestModel` with `reviewer.override(model=...)`. Run `uv run pytest` from the repo root.
6. Evals: `evals/cases.py` holds tiny repos with one planted bug each (plus one clean change). `evals/review_evals.py` is a `pydantic_evals.Dataset` with three evaluators: `FindsPlantedBug` (recall), `CleanIsCurrent`, and `ExtraFindings` (findings that miss the planted bug). Run it with a real model:

    ```bash
    uv run -m examples.pr_reviewer.evals.review_evals --repeat 3
    ```

    Add `--model anthropic:claude-opus-5-5` to compare models.

7. Harness variant: `--engine harness` runs `harness_reviewer` (`harness_agent.py`). It has the same instructions, output type, and validator, but uses `pydantic-ai-harness` capabilities instead of the hand-written tools:

    | Hand-written (`--engine custom`)                                  | Harness (`--engine harness`)                                                                                  |
    | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
    | `read_file`, `glob`, `grep` in `tools.py`                         | `FileSystem(read_only=True, tools=READ_TOOLS)` on a per-run `LocalWorkspace(policy_base, read_only=True)`     |
    | The instructions tell the model to read `CLAUDE.md` / `AGENTS.md` | `RepoContext` loads them into the instructions, and adds nested ones when the model reads into that directory |
    | `UsageLimits` raises `UsageLimitExceeded`                         | `WrapUpAtLimits` asks for a final answer at the last allowed request                                          |
    | No budget per tool                                                | `ToolBudgets(total=40, refuse_repeats=...)`                                                                   |

    `RepoContext` makes streamed requests, so a scripted `FunctionModel` needs a `stream_function` (see `tests/helpers.py`). Compare the two with the evals:

    ```bash
    uv run -m examples.pr_reviewer.evals.review_evals --engine custom --repeat 3
    ```

    ```bash
    uv run -m examples.pr_reviewer.evals.review_evals --engine harness --repeat 3
    ```

8. GitHub integration: `--post` (needs `--pr`) posts the result as one PR review (`github.py`), and `.github/workflows/pr-review.yml` runs it on a PR after a maintainer approves the run.
    - Approval gate: a review runs only when someone adds the `pr-reviewer: run` label (or `pr-reviewer: new round`, which also resets the budget). Only people with triage access or more can add labels. The first step removes the label, so each run needs a new approval, and pushes alone never spend tokens. The run reviews the head SHA at the time of the label, so a push made after the approval is not reviewed.
    - `Findings` → `REQUEST_CHANGES` with one inline comment per finding. A finding on a line that the diff does not show goes in the review body, because GitHub rejects inline comments there.
    - `Current` → a `COMMENT` with `current at <sha>`. `GITHUB_TOKEN` cannot approve unless a repo setting allows it.
    - After each post, the bot's earlier change requests are dismissed. If the post fails, the old change request stays.
    - The review budget lives in a hidden, base64-encoded `<!-- pr-reviewer-state: ... -->` marker in the newest bot review, because the runner's `.git/` is lost after each job. Only reviews by `github-actions[bot]` (`BOT_LOGIN`) count, so a PR author cannot forge the state.
    - Setup: add the `ANTHROPIC_API_KEY` repo secret, and create the two labels:

        ```bash
        gh label create "pr-reviewer: run" --description "Approve one pr-reviewer run"
        ```

        ```bash
        gh label create "pr-reviewer: new round" --description "Approve one pr-reviewer run with a new budget round"
        ```
    - To use another model, set the `PR_REVIEWER_MODEL` repo variable (for example `deepseek:deepseek-chat`) and add that provider's key as a secret. The workflow passes `DEEPSEEK_API_KEY`. For other providers, add their key to the `env` of the Review step.
    - The PR's code is never installed or run. The workflow checks out the base branch into `tool/` and installs pr-reviewer from there, and checks out the PR head into `repo/` only as git data for the diff. So a PR that changes pr-reviewer is reviewed by the base branch's version. Both checkouts drop the token after the clone (`persist-credentials: false`).
    - The workflow uses `--engine harness`. On a large PR, the custom engine can reach the request limit and fail, but `WrapUpAtLimits` asks for a final answer at the last allowed request.
    - The workflow uses `pull_request`, so PRs from forks get no review: they get no secrets.
    - If the job fails during the agent run, the call is not counted, because the state is posted only with the result.

## Run

Commit your change first. The reviewer reads `HEAD`, not the working tree.

```bash
export ANTHROPIC_API_KEY=...
```

```bash
git fetch && uv run pr-reviewer --repo <repo> --base origin/main --task "<task contract>"
```

Fix the findings, commit, and run it again for the next call. Use `--pr <N>` to read the task and discussion from a PR, and `--new-round` to reset the budget.

### Other providers

The default models are Claude models. To use another provider, pass `--model` to the CLI or to the evals. The `openai` extra is installed, so DeepSeek works:

```bash
export DEEPSEEK_API_KEY=...
```

```bash
uv run -m examples.pr_reviewer.evals.review_evals --model deepseek:deepseek-chat
```

For other providers, add their extra to `pydantic-ai-slim` in `pyproject.toml`.

`--model test` runs offline, but `TestModel` invents the file name `a`, so the output validator rejects it and the run fails. Offline tests with a scripted `FunctionModel` come in step 5.
