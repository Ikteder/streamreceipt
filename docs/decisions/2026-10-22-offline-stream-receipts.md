# Decision: an offline stream receipt, not another gateway

Date: 2026-10-22

An AI platform engineer needs to know whether a captured model stream reached the terminal boundary that makes a client tool call eligible for further validation. We chose a dependency-free file audit with explicit provider adapters. The alternative of a live gateway would add credential handling, provider costs, retry behavior and operational obligations without improving this specific regression check.

The [comparison in the approved spec](../superpowers/specs/2026-10-22-streamreceipt.md) covers OpenAI Python, Anthropic Python, Vercel AI SDK and LiteLLM, including source, current issue evidence, licenses and contribution constraints. The source protocols are not interchangeable: OpenAI uses a choice finish reason and `[DONE]`, while Anthropic uses block stops, `message_delta` and `message_stop`. The receipt exposes one shared verdict but retains provider-specific rules.

`blocked` means directly observed unsafe evidence. `inconclusive` means the transcript lacks terminal evidence, a recognized tool call, or required usage. `dispatch_allowed` only means the supported protocol checks passed. It is intentionally narrower than authorization or safety certification.

Reports exclude raw content and tool identifiers. SHA-256 is retained to link a receipt to a local transcript, but the digest is not a privacy guarantee for low-entropy data. No provider source code or test fixture was copied. Independent MIT publication is appropriate because the tool spans two protocols and the OpenAI Python contribution guide restricts outside pull requests.
