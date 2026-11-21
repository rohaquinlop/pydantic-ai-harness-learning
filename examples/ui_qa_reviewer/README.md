# ui_qa_reviewer

A QA reviewer for the UI changes in a PR, built with pydantic-ai. It gets the PR's frontend diff and a preview URL of the PR's build, opens the preview in a real Chromium browser, tests the changed screens like a user, and returns QA findings or `passed at <sha>`.

## Steps

1. Structured output: `QAFindings | QAPassed` as `output_type`. Each `QAFinding` has the page URL, a category (`functional`, `accessibility`, `console`, `visual`, `content`), a severity, steps to reproduce, expected and actual results, and an optional likely file.
2. Browser as a capability: the harness `PlaywrightBrowser` gives the agent `navigate`, `snapshot`, `click`, `type_text`, `screenshot`, `console_messages`, `network_requests`, and more. `screenshot` and `navigate` return the PNG as image content, so a vision model sees the page. `ToolBudgets(total=40)` caps the tool calls, and `WrapUpAtLimits` asks for a final answer at the last allowed request (`UsageLimits(request_limit=40)`).
3. Egress: the browser reaches only the preview host. `EgressPolicy(allowed_domains=[host], allowlist_reach=<every request kind>)` refuses navigation, frames, data requests, and subresources to any other host, so a PR page cannot make the browser load other sites. Private addresses are refused, except when the preview host is loopback (`localhost`, `127.0.0.1`), so a local dev server works. The policy matches hosts, not ports, so on a loopback preview the page can still reach other local services on that host.
4. Output validator: `check_result` raises `ModelRetry` when a finding's URL is not on the preview origin (scheme, host, and port), when `QAPassed.sha` is not the head SHA, or when the agent returns `QAPassed` without an image in its history. pydantic-ai sends a tool's `ToolReturn.content` as a `UserPromptPart` next to the `ToolReturnPart`, so the validator reads `ctx.messages` for a `navigate` or `screenshot` return with an image part in the same request. A failed screenshot returns an error string with no image, so it does not count. `output_retries=3`.
5. Bundle: the diff is `merge-base...HEAD`, limited to frontend files (`*.html`, `*.css`, `*.scss`, `*.js`, `*.jsx`, `*.ts`, `*.tsx`, `*.vue`, `*.svelte`). It reuses `run()` from `pr_reviewer.bundle`. A change with no frontend files returns `QAPassed` without a model call.
6. Offline tests: `models.ALLOW_MODEL_REQUESTS = False`, the scripted `FunctionModel` from `pr_reviewer`'s tests, and a stub browser (`tests/helpers.py`) that returns images in the same shape as `PlaywrightBrowser`. No Chromium is needed. Run `uv run pytest` from the repo root.
7. Evals: `demo/` is a small sign-up page. `evals/cases.py` has a clean case and a case with two planted bugs (the email field has no label, and submit throws a `TypeError`, so the thank-you message never shows). Each case is a tiny git repo, served with `http.server` on a free loopback port as the preview. `FindsPlantedBugs` checks recall per bug by category, and `CleanPasses` checks the clean case. Run it with a real model:

    ```bash
    uv run -m examples.ui_qa_reviewer.evals.review_evals --repeat 3
    ```

## Limits

- No responsive checks. `PlaywrightBrowser` has no tool to change the viewport, so the agent checks the default desktop size only.
- The preview must be on a public host or on loopback. Other private addresses (LAN, VPC) are refused.
- The diff filter matches file extensions at any depth, so built or vendored files (`dist/`, `vendor/`) that are committed enter the prompt.
- No GitHub posting, review budget, or CI workflow. `pr_reviewer` shows those.

## Setup

Chromium is a separate download:

```bash
uv run playwright install chromium
```

## Run

Commit your change first. The reviewer reads `HEAD`, not the working tree. Start the branch's frontend (a dev server or a deployed preview), then:

```bash
export ANTHROPIC_API_KEY=...
```

```bash
git fetch && uv run ui-qa-reviewer --base origin/main --url http://localhost:5173 --task "<task contract>"
```

The default model is `anthropic:claude-sonnet-5-5`, because the agent reads screenshots and drives many browser steps. Use `--model` for another model with vision and tool use. For example, DeepSeek's `deepseek-flash` accepts images:

```bash
export DEEPSEEK_API_KEY=...
```

```bash
uv run ui-qa-reviewer --base origin/main --url http://localhost:5173 --task "<task contract>" --model deepseek:deepseek-flash
```

The evals take the same flag:

```bash
uv run -m examples.ui_qa_reviewer.evals.review_evals --model deepseek:deepseek-flash
```

To try it on the demo page, serve it in one terminal:

```bash
uv run -m http.server -d examples/ui_qa_reviewer/demo 8000
```
