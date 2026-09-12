# Optional model proposals

Analysis, comparison, checks, deduplication and saved-plan replay need no model.
Only `idiomatize` and named `pattern` proposals use the optional API client.

```sh
pip install "reducio[llm]"
# Set REDUCIO_API_KEY securely in your environment, not in a committed file.
reducio idiomatize . --llm-api openai --model YOUR_MODEL_ID --dry-run
reducio pattern strategy . --llm-api anthropic --model YOUR_MODEL_ID --dry-run
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
llm_timeout_seconds: 60         # total request deadline
llm_max_tokens: 2048
```

Environment overrides: `REDUCIO_LLM_API`, `REDUCIO_MODEL`,
`REDUCIO_LLM_BASE_URL`, `REDUCIO_LLM_TIMEOUT_SECONDS`, `REDUCIO_LLM_MAX_TOKENS`.
Explicit CLI options override environment, then selected YAML, then defaults.
`--llm-base-url` overrides the URL; include the version prefix, not the endpoint.
Defaults are `https://api.openai.com/v1` or `https://api.anthropic.com/v1`.
HTTPS is required except for loopback HTTP. Credentials, query strings and
fragments in URLs are rejected; redirects are not followed.

Tokens are read on each request: `REDUCIO_API_KEY` takes precedence over
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, according to the selected format.
No token is stored in configuration or sessions. Provider error bodies are withheld.
Planning sends source code to the selected endpoint **even with `--dry-run`**.
Do not enable this on sensitive source unless the endpoint is approved for it.

The client supports text-only, non-streaming
[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
(`messages`, `max_completion_tokens`) and
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)
(`system`, `messages`, `max_tokens`). Custom endpoints must implement these fields
and completion markers. Responses API, tool calls, model discovery, automatic
provider switching and retries are not supported. Not every model accepts this
text-only request format. Truncated/refused/empty/malformed replies fail planning.

Missing API/model/token/dependency or request failures produce an incomplete plan
(exit 1). Only explicit `--allow-fallback` permits heuristic/template fallback,
recorded in the saved plan. An unchanged successful reply does not trigger fallback.

## GitHub CI

Normal [CI analysis](GITHUB_CI.md) needs no token. For an explicitly requested
model-planning step in a trusted manual workflow, install `reducio[llm]` and map
a GitHub Actions secret to `REDUCIO_API_KEY` in that step's `env`. Use `--dry-run`
and upload the proposal for review. Never expose secrets to untrusted PR code or
use `pull_request_target` to run it. API usage can incur charges.

## Migration

Removed `LLMRouter`, `ModelTier`, LiteLLM and tier/discovery logic. Library callers
can use `LLMClient(AppConfig(llm_api="openai", model="..."))` and `await complete(...)`.
Remove retired `prefer_local`, `prefer_remote`, `model_tiers`, `tier`,
`REDUCIO_PREFER_LOCAL` and `REDUCIO_PREFER_REMOTE`: these now fail configuration
validation. Ineffective model/preference flags on analyze/deduplicate are removed.
Model IDs are passed unchanged; migrate old provider-prefixed IDs explicitly.
Existing saved plans/results remain readable and replay without an API request.
Session `clear_cache()` remains a compatibility no-op; plans are read from disk.
