# Optional model proposals

Analysis, comparison, checks, deduplication and saved-plan replay need no model.
Only `idiomatize` and named `pattern` proposals use the optional API client.

```sh
pip install "reducio[llm]"
# Set REDUCIO_API_KEY securely in your environment, not in a committed file.
# Hosted APIs are remote: sending source needs explicit --allow-remote.
reducio idiomatize . --llm-api openai --model YOUR_MODEL_ID --allow-remote --dry-run
reducio pattern strategy . --llm-api anthropic --model YOUR_MODEL_ID --allow-remote --dry-run
# A loopback endpoint (e.g. a local OpenAI-compatible server) needs no consent.
reducio idiomatize . --llm-api openai --model YOUR_MODEL_ID --llm-base-url http://localhost:11434/v1 --dry-run
```

Use the provider's exact model ID, without a routing prefix. PyApp releases bundle
the optional client; it stays inactive until requested. Review proposals before
applying: model output is not verified as behavior-preserving.

## Configuration

Equivalent `.reducio.yaml` (never put the token here):

```yaml
llm_api: openai                 # openai or anthropic; no default selection
model: YOUR_MODEL_ID
llm_base_url: https://api.openai.com/v1
llm_timeout_seconds: 60         # per connect/read/write phase, not a total deadline
llm_max_tokens: 2048
allow_remote: false             # consent to send source to a non-loopback host
```

Environment overrides: `REDUCIO_LLM_API`, `REDUCIO_MODEL`,
`REDUCIO_LLM_BASE_URL`, `REDUCIO_LLM_TIMEOUT_SECONDS`, `REDUCIO_LLM_MAX_TOKENS`,
`REDUCIO_ALLOW_REMOTE` (boolean).
Explicit CLI options override environment, then selected YAML, then defaults.
`--llm-base-url` overrides the URL; include the version prefix, not the endpoint.
Defaults are `https://api.openai.com/v1` or `https://api.anthropic.com/v1`.
HTTPS is required except for loopback HTTP. Credentials, query strings and
fragments in URLs are rejected; redirects are not followed.

Tokens are read on each request: `REDUCIO_API_KEY` takes precedence over
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, according to the selected format.
No token is stored in configuration or sessions. Provider error bodies are withheld.
Planning sends source code to the selected endpoint **even with `--dry-run`**.

## Local-only by default

Source never leaves the machine without consent. Endpoints whose host is
`localhost`, `127.0.0.1` or `::1` are local; every other host, including the
default OpenAI/Anthropic URLs, is refused **before any request** unless you pass
`--allow-remote`, set `REDUCIO_ALLOW_REMOTE=1` or `allow_remote: true`. A refusal
makes the plan incomplete (exit 1); it is not a fallback trigger worth relying on.
Only give consent when the endpoint is approved for that source.

Before planning, reducio prints one stderr line (shown even with `--quiet`) naming
the API format, model, host and whether it is local, allowed or refused. Each saved
plan records, per request attempted, the host, prompt size in bytes and the
SHA-256 of the prompt — never the source, the reply or the token — and plan
previews show them. Prompts are not logged elsewhere.

The client supports text-only, non-streaming
[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
(`messages`, `max_completion_tokens`) and
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)
(`system`, `messages`, `max_tokens`). Custom endpoints must implement these fields
and completion markers. Responses API, tool calls, model discovery, automatic
provider switching and retries are not supported. Not every model accepts this
text-only request format. Truncated/refused/empty/malformed replies fail planning.

`idiomatize` is model-only: without `--llm-api` and `--model` it exits 2 before
scanning. Missing token/dependency or request failures produce an incomplete plan
(exit 1). For `pattern`, only explicit `--allow-fallback` permits template fallback,
recorded in the saved plan. An unchanged successful reply does not trigger fallback.

## GitHub CI

Normal [CI analysis](GITHUB_CI.md) needs no token. For an explicitly requested
model-planning step in a trusted manual workflow, install `reducio[llm]` and map
a GitHub Actions secret to `REDUCIO_API_KEY` in that step's `env`, and pass
`--allow-remote` for a hosted API. Use `--dry-run`
and upload the proposal for review. Never expose secrets to untrusted PR code or
use `pull_request_target` to run it. API usage can incur charges.

Upgrade notes for removed router/tier APIs are in [MIGRATION.md](MIGRATION.md#model-apis).
