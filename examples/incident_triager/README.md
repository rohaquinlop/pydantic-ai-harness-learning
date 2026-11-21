# incident_triager

An incident triager built with pydantic-ai. It reads a local incident bundle (the alert, service logs, metrics, deploys, and the service's git history) and returns ranked root-cause hypotheses. Each hypothesis cites evidence that a tool printed and gives the cheapest check that proves or refutes it.

## Steps

1. Bundle: a directory with `alert.json`, `logs/*.log` (one `<ISO timestamp> <LEVEL> <message>` per line), `metrics.csv` (`timestamp,metric,value`), `deploys.json`, and an optional `repo/` git repo. Deploys point at commits in `repo/`. A naive timestamp is taken as UTC.
2. Tools that keep large outputs small. Real logs have thousands of lines, so no tool returns a whole file:
    - `list_sources`: a map of the bundle, with line counts, time ranges, and metric names.
    - `count_logs`: counts matches per file and time bucket. The agent aggregates first, then reads.
    - `search_logs`: 40 matches per page. It cuts each line to 300 characters and prints a `[next cursor: N]` footer.
    - `read_log`: a line range, at most 200 lines.
    - `query_metric`: downsamples to 60 points and says so.
    - `list_deploys`, `git_log`, `git_show`: the deploys, and the commits they point at.
    - Each tool prints refs in one format: `logs/api.log:120`, `metric:memory_mb`, `deploy:d-102`, `commit:a1b2c3d`.
3. Hypothesis-then-check loop: the instructions tell the agent to orient (`read_alert`, `list_sources`), aggregate around the alert time, form 1 to 5 hypotheses, check each with the cheapest tool call, then rank. A deploy near the alert is not proof.
4. Structured output: `Triage` with a summary and ranked `Hypothesis` items. Each item has a category (`code_change`, `config_change`, `dependency`, `capacity`, `resource_leak`), a confidence, evidence refs, a `check`, and a `refuted_if` condition.
5. Grounding validator: `check_grounded` reads `ctx.messages` and raises `ModelRetry` when an evidence ref does not appear in a successful tool return of the same run. Refs match as whole tokens, so `deploy:d-10` does not match `deploy:d-102`. `alert` counts only after a `read_alert` call. A retry message can echo a bad ref, so retried returns never count, and no tool echoes its arguments in a successful return. `retries={"tools": 3, "output": 3}`.
6. Guards: paths stay inside `logs/` and `repo/`. A SHA must be 4 to 40 hex characters, `--since`/`--until` take parsed timestamps, and a pathspec goes after `--`. A bad regex, timestamp, metric, or SHA, or a git error, becomes a `ModelRetry` with a hint. Time-filtered tools skip lines without a timestamp and count them in the footer.
7. Offline tests: `models.ALLOW_MODEL_REQUESTS = False`, the scripted `FunctionModel` from `pr_reviewer`'s tests, and the `bad_deploy` eval bundle as a fixture. Run `uv run pytest` from the repo root.
8. Evals: `evals/cases.py` generates 5 incidents with a planted root cause. Each has thousands of noise log lines and a git repo with dated commits. Every case also has a deploy that did not cause the incident.

    | Case | Planted cause | Wrong lead |
    |---|---|---|
    | `bad_deploy` | a code deploy shrinks the DB pool | an earlier logging deploy |
    | `feature_flag` | a config deploy turns on a flag | a dependency bump |
    | `upstream_outage` | the payment provider returns 503 | a CSS deploy 5 min before the first error |
    | `traffic_spike` | requests per second triple | a log-level config change |
    | `memory_leak` | a template cache that never evicts, deployed 2 days ago | a typo fix 30 min ago |

    `TopHypothesis` checks that the first hypothesis has an accepted category and cites a key ref. `bad_deploy` accepts `code_change` or `config_change`, because its cause is a config value changed in code. `InTopThree` checks the first three. `HypothesisCount` reports how many hypotheses the agent gave.

## Limits

- Grounding checks the ref, not the `detail` text. A model can cite a real ref with an invented detail.
- The bundle is files only. No Loki, Prometheus, or Datadog. A live source would need the same paging and ref format.
- Eval scores depend on one planted cause per case. A real incident can have more than one cause.

## Run

Write an eval case as a bundle, then triage it:

```bash
uv run -m examples.incident_triager.evals.cases memory_leak /tmp/incident
```

```bash
uv run --env-file .env incident-triager --bundle /tmp/incident
```

It prints the hypotheses, each retry, the tool call count, and the usage. The default model is `anthropic:claude-sonnet-5-5`. Use `--model` for another model with tool use, such as `deepseek:deepseek-chat`.

## Evals

The evals call a real model. Start with one run per case:

```bash
uv run --env-file .env -m examples.incident_triager.evals.review_evals --repeat 1
```

Flags: `--model`, `--repeat N`, `--max-concurrency N` (default 2).
