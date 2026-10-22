# Dataset card: streamreceipt-authored-v1

Date authored: 2026-10-22. License: MIT with this repository.

The benchmark defines 13 synthetic SSE transcripts in `src/streamreceipt/benchmark.py`. Two are safe protocol controls. Eleven are explicit mutations of terminal markers, finish reasons, tool JSON, metadata, lifecycle order and usage fields. Labels are `dispatch_allowed`, `blocked` or `inconclusive`, assigned from the design spec. The test runner and baseline are deterministic; no seed is needed to generate these fixed cases.

No vendor request, user data, prompt, model completion, or third-party fixture is included. Provider names in the fixtures identify protocol shapes, not measured services. No train, validation or test split exists because this is a small conformance regression corpus rather than a learned benchmark. The cases are implementation-aligned, so 13/13 correctness does not estimate sensitivity, specificity, or performance on independent streams. Potential missing classes include multimodal events, gateway transformations, retries, novel SDK event types and different provider versions.
