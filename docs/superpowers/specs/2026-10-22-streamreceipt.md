# StreamReceipt 0.1 design spec

Date: 2026-10-22. Approved for this user-requested manual run before implementation.

## User and problem

AI platform engineers test streamed tool calls through SDKs and gateways. A parseable JSON argument is insufficient evidence that the model finished safely or that final usage was observed. Premature EOF, unsafe finish reasons, and malformed tool deltas can be mistaken for a runnable call. The engineer needs a portable offline receipt over a recorded SSE transcript before allowing tool dispatch in a test or CI pipeline.

## Evidence and comparison

| Reference | User and capability | Current evidence, limitation, license, integration |
|---|---|---|
| [OpenAI Chat Completions and Python SDK](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events) | Python developers get chunk assembly, parsed tool events and optional usage. | Official API says interrupted streams may lack final usage. [SDK source](https://github.com/openai/openai-python/blob/main/src/openai/lib/streaming/chat/_completions.py) notes a final snapshot does not itself prove stream finish; [issue 4063](https://github.com/openai/openai-python/issues/4063) reports early-EOF ambiguity with an offline reproduction. Recent release v3.37.0 and 2026-10-22 commit inspected. Apache-2.0. [Contribution guide](https://github.com/openai/openai-python/blob/main/CONTRIBUTING.md) limits PRs to collaborators. Integration: raw Chat Completions SSE or SDK chunk capture. No independent cross-provider dispatch receipt or fixture benchmark is documented. |
| [Anthropic Messages and Python SDK](https://platform.claude.com/docs/en/build-with-claude/streaming) | Claude developers get `message_start`, content-block deltas, `message_delta`, `message_stop` and SDK accumulation. | Docs require parsing partial tool JSON after block stop and state usage is cumulative. [SDK source](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/lib/streaming/_messages.py) assembles stream events; [issue 1265](https://github.com/anthropics/anthropic-sdk-python/issues/1265) reports malformed tool JSON diagnostics. v2.1.0 and 2026-10-21 activity inspected. Apache-2.0; [contribution guide](https://github.com/anthropics/anthropic-sdk-python/blob/main/CONTRIBUTING.md) documents generated code and tests. Integration: raw Messages SSE. No documented cross-provider terminal and usage receipt. |
| [Vercel AI SDK](https://github.com/vercel/ai/blob/main/packages/ai/src/generate-text/stream-text-result.ts) | TypeScript agents stream tool calls and expose finish and usage events. | [Issue 22912](https://github.com/vercel/ai/issues/22912) reproduces pending tool calls after unsafe finish; [issue 23533](https://github.com/vercel/ai/issues/23533) reports a gateway finish-shape mismatch. v7.0.150 and 2026-10-22 activity inspected. Apache-2.0. [Contribution guide](https://github.com/vercel/ai/blob/main/CONTRIBUTING.md) favors precise reproductions and focused issues. Integration: SDK stream parts and provider adapters. It is an application SDK, not an offline two-provider raw SSE conformance checker. |
| [LiteLLM](https://github.com/BerriAI/litellm) | Gateway users normalize providers and costs. | [Issue 36114](https://github.com/BerriAI/litellm/issues/36114) reports stream usage undercounting; [issue 36168](https://github.com/BerriAI/litellm/issues/36168) reports usage lost in a choice-bearing final chunk. v1.106.2 and 2026-10-22 activity inspected. Core MIT, enterprise directory separately licensed; [contributing](https://github.com/BerriAI/litellm/blob/main/CONTRIBUTING.md) requires a CLA and tests. Integration: OpenAI-compatible SSE. No gateway source is copied. |

[Applied ML](https://github.com/eugeneyan/applied-ml) is only a discovery index. Its linked [Amazon data-quality verification paper](https://www.amazon.science/publications/automating-large-scale-data-quality-verification) (2018) supports the general production pattern of declarative constraints and inspectable validation, not a claim about LLM streams or locally reproduced Amazon results.

Local overlap check: `llm-structured-output-fuzzer` checks completed JSON strings, `fallbacklens` checks route contracts and sampled logical spans, and `agenttracecanary` compares OTLP structure. None consumes provider SSE to establish terminal tool-call and usage evidence.

## Chosen gap and original contribution

Build an independent, dependency-free Python CLI that reads captured OpenAI Chat Completions or Anthropic Messages SSE, checks provider-specific terminal order, tool argument assembly, safe stop reason, and usage observation, then emits a content-minimized receipt. This improves correctness and reliability of tool dispatch plus observability of usage without building another SDK, proxy, or model router.

## Scope

- Input: one bounded UTF-8 SSE transcript from a file; explicit provider flag. No live provider calls or SDK credentials.
- OpenAI Chat Completions: choice index 0 only; reconstruct tool calls by tool index; require a compatible `finish_reason`, `[DONE]`, a unique ID and function name, JSON-object arguments, and no conflicting repeated metadata. Treat missing optional usage as `unobserved`; when usage is required, mark the receipt inconclusive.
- Anthropic Messages: require start, ordered content-block lifecycle, `message_delta` stop reason and `message_stop`; assemble `input_json_delta` for client `tool_use` blocks and require JSON-object input. Accept only `tool_use` as a client-tool dispatch stop reason. Track cumulative usage without summing repeated values.
- Never put raw prompt, text, tool name, ID or argument bytes in JSON, HTML or SVG output. Emit stable finding codes, counts and SHA-256 digests for audit linkage.
- Bound transcript size, SSE event count, tool count and argument size. Unknown/new event types become inconclusive where semantic safety cannot be established.
- Include an authored mutation corpus, declared parse-only baseline, deterministic JSON and a generated SVG comparison.

## Acceptance and baseline

- Run every authored case and confirm expected verdicts. Compare with a parse-only baseline that accepts any syntactically valid tool JSON, including missing terminal evidence.
- Unit tests cover normal dual-provider streams, EOF, unsafe finish, malformed JSON, ID conflict, missing usage, duplicate terminal, and malformed SSE.
- Demonstrate a safe control for each provider, a blocked unsafe case for each provider, and an inconclusive missing-usage case.
- Package installs from a wheel without network or third-party runtime packages; lint, tests, exact benchmark regeneration, SVG parse and README no-em-dash check pass.

## Risks, limits and publication

Do not equate a syntactically safe receipt with authorization to run a real tool; application policy and schema validation remain necessary. Raw captured transcripts may contain secrets and must stay outside version control. Synthetic cases show rule behavior, not production sensitivity or provider reliability. This slice does not support OpenAI Responses, Anthropic server tools, multimodal streams, retries within an HTTP request, signed receipts, or live billing reconciliation. Publish as an independent MIT repository after verification. No upstream code or fixtures will be copied and no upstream PR is planned.
