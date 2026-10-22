"""Versioned authored protocol mutations and a declared parse-only baseline."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .core import audit


def _openai_events() -> list[dict[str, Any] | str]:
    common = {"id": "demo-1", "object": "chat.completion.chunk", "model": "mock-model"}

    def chunk(delta: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
        return {**common, "choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}

    return [
        chunk({"role": "assistant"}),
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"item":'},
                    }
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"A"}'}}]}),
        chunk({}, "tool_calls"),
        {
            **common,
            "choices": [],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
        },
        "[DONE]",
    ]


def _anthropic_events() -> list[dict[str, Any]]:
    return [
        {"type": "message_start", "message": {"usage": {"input_tokens": 8}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"item":'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '"A"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]


def _sse(events: list[dict[str, Any] | str], provider: str) -> str:
    chunks = []
    for event in events:
        if provider == "anthropic-messages":
            chunks.append("event: " + event["type"] + "\n")
        data = event if isinstance(event, str) else json.dumps(event, separators=(",", ":"))
        chunks.append("data: " + data + "\n\n")
    return "".join(chunks)


def cases() -> list[tuple[str, str, str, str]]:
    """Return (id, provider, transcript, expected verdict) for authored v1 cases."""
    o = _openai_events()
    a = _anthropic_events()
    result = [
        ("openai-safe", "openai-chat", _sse(o, "openai-chat"), "dispatch_allowed"),
        ("anthropic-safe", "anthropic-messages", _sse(a, "anthropic-messages"), "dispatch_allowed"),
    ]
    x = deepcopy(o)
    x.pop()
    result.append(("openai-no-done", "openai-chat", _sse(x, "openai-chat"), "inconclusive"))
    x = deepcopy(o)
    x.pop(3)
    result.append(("openai-no-finish", "openai-chat", _sse(x, "openai-chat"), "inconclusive"))
    x = deepcopy(o)
    x[3]["choices"][0]["finish_reason"] = "length"
    result.append(("openai-length", "openai-chat", _sse(x, "openai-chat"), "blocked"))
    x = deepcopy(o)
    x[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] = '"A"'
    result.append(("openai-bad-json", "openai-chat", _sse(x, "openai-chat"), "blocked"))
    x = deepcopy(o)
    x[2]["choices"][0]["delta"]["tool_calls"][0]["id"] = "call-2"
    result.append(("openai-id-conflict", "openai-chat", _sse(x, "openai-chat"), "blocked"))
    x = deepcopy(o)
    x.pop(4)
    result.append(("openai-no-usage", "openai-chat", _sse(x, "openai-chat"), "inconclusive"))
    x = deepcopy(a)
    x.pop()
    result.append(
        ("anthropic-no-stop", "anthropic-messages", _sse(x, "anthropic-messages"), "inconclusive")
    )
    x = deepcopy(a)
    x[5]["delta"]["stop_reason"] = "max_tokens"
    result.append(
        ("anthropic-max-tokens", "anthropic-messages", _sse(x, "anthropic-messages"), "blocked")
    )
    x = deepcopy(a)
    x.pop(4)
    result.append(
        ("anthropic-open-block", "anthropic-messages", _sse(x, "anthropic-messages"), "blocked")
    )
    x = deepcopy(a)
    x[3]["delta"]["partial_json"] = '"A"'
    result.append(
        ("anthropic-bad-json", "anthropic-messages", _sse(x, "anthropic-messages"), "blocked")
    )
    x = deepcopy(a)
    x[5]["usage"] = {}
    result.append(
        ("anthropic-no-usage", "anthropic-messages", _sse(x, "anthropic-messages"), "inconclusive")
    )
    return result


def _parse_only(transcript: str, provider: str) -> bool:
    """Weak baseline: assemble a single tool JSON, ignore terminal and usage evidence."""
    fragments: list[str] = []
    for line in transcript.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            event = json.loads(line[6:])
        except ValueError:
            return False
        if provider == "openai-chat":
            for choice in event.get("choices", []):
                for call in choice.get("delta", {}).get("tool_calls", []):
                    fragments.append(call.get("function", {}).get("arguments", ""))
        elif event.get("type") == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "input_json_delta":
                fragments.append(delta.get("partial_json", ""))
    try:
        return isinstance(json.loads("".join(fragments)), dict)
    except ValueError:
        return False


def benchmark() -> dict[str, Any]:
    rows = []
    for case_id, provider, transcript, expected in cases():
        report = audit(transcript, provider, require_usage=True)
        baseline_verdict = "dispatch_allowed" if _parse_only(transcript, provider) else "blocked"
        rows.append(
            {
                "id": case_id,
                "provider": provider,
                "expected": expected,
                "actual": report["verdict"],
                "baseline": baseline_verdict,
                "findings": report["findings"],
            }
        )
    return {
        "schema_version": 1,
        "corpus": "streamreceipt-authored-v1",
        "cases": len(rows),
        "streamreceipt_correct": sum(x["actual"] == x["expected"] for x in rows),
        "parse_only_correct": sum(x["baseline"] == x["expected"] for x in rows),
        "rows": rows,
    }


def svg_report(report: dict[str, Any]) -> str:
    total = report["cases"]
    good = report["streamreceipt_correct"]
    base = report["parse_only_correct"]
    width = 720

    def bar(y: int, label: str, score: int, color: str) -> str:
        fill = int(490 * score / total)
        return (
            f'<text x="26" y="{y}" fill="#182436" font-size="18">{escape(label)}</text>'
            f'<rect x="205" y="{y - 17}" width="490" height="25" rx="6" fill="#e8edf4"/>'
            f'<rect x="205" y="{y - 17}" width="{fill}" height="25" rx="6" fill="{color}"/>'
            f'<text x="{min(640, 215 + fill)}" y="{y + 2}" fill="#182436" font-size="15">{score}/{total}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="190" viewBox="0 0 720 190" role="img" aria-label="Authored stream fixture verdict accuracy">'
        '<rect width="720" height="190" fill="#f8fafc"/>'
        '<text x="26" y="34" fill="#182436" font-size="21" font-weight="bold">Stream completion checks</text>'
        + bar(88, "Parse-only", base, "#d68b53")
        + bar(139, "StreamReceipt", good, "#298b78")
        + "</svg>\n"
    )


def write_evidence(directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    report = benchmark()
    (directory / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (directory / "benchmark.svg").write_text(svg_report(report), encoding="utf-8")
    return report
