"""Bounded SSE parsing and provider-specific tool completion checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

MAX_BYTES = 1_048_576
MAX_EVENTS = 10_000
MAX_TOOLS = 64
MAX_ARGUMENT_BYTES = 65_536


class StreamError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StreamError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _parse_json(data: str, code: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_unique_object)
    except StreamError:
        raise
    except (ValueError, RecursionError) as exc:
        raise StreamError(code) from exc


@dataclass(frozen=True)
class Event:
    name: str | None
    data: str


def parse_sse(source: str) -> list[Event]:
    events: list[Event] = []
    data: list[str] = []
    name: str | None = None

    def flush() -> None:
        nonlocal data, name
        if data:
            events.append(Event(name, "\n".join(data)))
            if len(events) > MAX_EVENTS:
                raise StreamError("EVENT_LIMIT")
        data, name = [], None

    for line in source.splitlines():
        if not line:
            flush()
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "data":
                data.append(value)
            elif field == "event":
                name = value
            elif field not in ("id", "retry"):
                raise StreamError("UNKNOWN_SSE_FIELD")
    flush()
    if not events:
        raise StreamError("EMPTY_STREAM")
    return events


def _object(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StreamError(code)
    return value


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _usage_openai(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    p = value.get("prompt_tokens")
    c = value.get("completion_tokens")
    t = value.get("total_tokens")
    return all(_nonnegative_int(x) for x in (p, c, t)) and p + c == t


def _usage_anthropic(value: Any, key: str) -> int | None:
    if not isinstance(value, dict):
        return None
    result = value.get(key)
    return result if _nonnegative_int(result) else None


def _tool_json(raw: str) -> None:
    if len(raw.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise StreamError("ARGUMENT_LIMIT")
    _object(_parse_json(raw, "INVALID_TOOL_JSON"), "TOOL_ARGUMENT_NOT_OBJECT")


def _openai(events: list[Event]) -> tuple[list[str], int, str, bool]:
    findings: list[str] = []
    tools: dict[int, dict[str, str]] = {}
    finish: str | None = None
    done = False
    usage = False
    response_id: str | None = None

    for event in events:
        if done:
            findings.append("EVENT_AFTER_DONE")
            break
        if event.name not in (None, "message"):
            findings.append("UNKNOWN_EVENT_TYPE")
            continue
        if event.data == "[DONE]":
            done = True
            continue
        try:
            chunk = _object(_parse_json(event.data, "INVALID_EVENT_JSON"), "INVALID_EVENT_SHAPE")
            ident = chunk.get("id")
            if not isinstance(ident, str) or not ident:
                raise StreamError("MISSING_RESPONSE_ID")
            if response_id is None:
                response_id = ident
            elif ident != response_id:
                raise StreamError("RESPONSE_ID_CHANGED")
            choices = chunk.get("choices")
            if not isinstance(choices, list):
                raise StreamError("INVALID_CHOICES")
            if "usage" in chunk and chunk["usage"] is not None:
                if not _usage_openai(chunk["usage"]):
                    raise StreamError("INVALID_USAGE")
                if usage:
                    raise StreamError("DUPLICATE_USAGE")
                usage = True
            for choice in choices:
                item = _object(choice, "INVALID_CHOICE")
                if item.get("index") != 0:
                    raise StreamError("UNSUPPORTED_CHOICE_INDEX")
                reason = item.get("finish_reason")
                if reason is not None:
                    if finish is not None:
                        raise StreamError("DUPLICATE_FINISH")
                    if not isinstance(reason, str):
                        raise StreamError("INVALID_FINISH")
                    finish = reason
                delta = _object(item.get("delta", {}), "INVALID_DELTA")
                calls = delta.get("tool_calls", [])
                if not isinstance(calls, list):
                    raise StreamError("INVALID_TOOL_CALLS")
                if finish is not None and calls:
                    raise StreamError("TOOL_AFTER_FINISH")
                for call in calls:
                    call = _object(call, "INVALID_TOOL_CALL")
                    index = call.get("index")
                    if not _nonnegative_int(index) or index >= MAX_TOOLS:
                        raise StreamError("TOOL_INDEX_LIMIT")
                    state = tools.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    for field, value in (
                        ("id", call.get("id")),
                        ("name", _object(call.get("function", {}), "INVALID_FUNCTION").get("name")),
                    ):
                        if value is not None:
                            if not isinstance(value, str) or not value:
                                raise StreamError("INVALID_TOOL_METADATA")
                            if state[field] and state[field] != value:
                                raise StreamError("TOOL_METADATA_CONFLICT")
                            state[field] = value
                    args = call.get("function", {}).get("arguments", "")
                    if not isinstance(args, str):
                        raise StreamError("INVALID_ARGUMENT_DELTA")
                    state["arguments"] += args
                    if len(state["arguments"].encode("utf-8")) > MAX_ARGUMENT_BYTES:
                        raise StreamError("ARGUMENT_LIMIT")
        except StreamError as exc:
            findings.append(exc.code)
            break

    if not done:
        findings.append("MISSING_DONE")
    if finish is None:
        findings.append("MISSING_FINISH")
    elif tools and finish != "tool_calls":
        findings.append("UNSAFE_FINISH")
    if not tools:
        findings.append("NO_CLIENT_TOOLS")
    if len({s["id"] for s in tools.values()}) != len(tools):
        findings.append("DUPLICATE_TOOL_ID")
    for state in tools.values():
        if not state["id"] or not state["name"]:
            findings.append("MISSING_TOOL_METADATA")
        try:
            _tool_json(state["arguments"])
        except StreamError as exc:
            findings.append(exc.code)
    return findings, len(tools), finish or "unobserved", usage


def _anthropic(events: list[Event]) -> tuple[list[str], int, str, bool]:
    findings: list[str] = []
    started = False
    stopped = False
    finish: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    blocks: dict[int, dict[str, Any]] = {}
    ids: set[str] = set()

    for event in events:
        try:
            payload = _object(_parse_json(event.data, "INVALID_EVENT_JSON"), "INVALID_EVENT_SHAPE")
            kind = payload.get("type")
            if event.name != kind:
                raise StreamError("EVENT_TYPE_MISMATCH")
            if stopped:
                raise StreamError("EVENT_AFTER_STOP")
            if kind == "ping":
                continue
            if kind == "error":
                raise StreamError("PROVIDER_ERROR")
            if kind == "message_start":
                if started:
                    raise StreamError("DUPLICATE_START")
                started = True
                message = _object(payload.get("message"), "INVALID_MESSAGE")
                input_tokens = _usage_anthropic(message.get("usage"), "input_tokens")
            elif not started:
                raise StreamError("MISSING_START")
            elif kind == "content_block_start":
                if finish is not None:
                    raise StreamError("BLOCK_AFTER_FINISH")
                index = payload.get("index")
                if not _nonnegative_int(index) or index >= MAX_TOOLS:
                    raise StreamError("BLOCK_INDEX_LIMIT")
                if index in blocks:
                    raise StreamError("DUPLICATE_BLOCK")
                block = _object(payload.get("content_block"), "INVALID_BLOCK")
                block_type = block.get("type")
                if block_type not in ("tool_use", "text", "thinking", "redacted_thinking"):
                    raise StreamError("UNKNOWN_BLOCK_TYPE")
                state = {"type": block_type, "closed": False, "arguments": ""}
                if block_type == "tool_use":
                    ident, name = block.get("id"), block.get("name")
                    if (
                        not isinstance(ident, str)
                        or not ident
                        or not isinstance(name, str)
                        or not name
                    ):
                        raise StreamError("MISSING_TOOL_METADATA")
                    if ident in ids:
                        raise StreamError("DUPLICATE_TOOL_ID")
                    ids.add(ident)
                    initial = block.get("input", {})
                    if initial != {}:
                        raise StreamError("UNSUPPORTED_INITIAL_INPUT")
                blocks[index] = state
            elif kind == "content_block_delta":
                if finish is not None:
                    raise StreamError("BLOCK_AFTER_FINISH")
                index = payload.get("index")
                if not _nonnegative_int(index) or index not in blocks or blocks[index]["closed"]:
                    raise StreamError("DELTA_OUTSIDE_BLOCK")
                delta = _object(payload.get("delta"), "INVALID_DELTA")
                if delta.get("type") == "input_json_delta":
                    if blocks[index]["type"] != "tool_use":
                        raise StreamError("TOOL_DELTA_WRONG_BLOCK")
                    part = delta.get("partial_json")
                    if not isinstance(part, str):
                        raise StreamError("INVALID_ARGUMENT_DELTA")
                    blocks[index]["arguments"] += part
                    if len(blocks[index]["arguments"].encode("utf-8")) > MAX_ARGUMENT_BYTES:
                        raise StreamError("ARGUMENT_LIMIT")
                elif delta.get("type") not in ("text_delta", "thinking_delta", "signature_delta"):
                    raise StreamError("UNKNOWN_DELTA_TYPE")
            elif kind == "content_block_stop":
                if finish is not None:
                    raise StreamError("BLOCK_AFTER_FINISH")
                index = payload.get("index")
                if not _nonnegative_int(index) or index not in blocks or blocks[index]["closed"]:
                    raise StreamError("INVALID_BLOCK_STOP")
                blocks[index]["closed"] = True
            elif kind == "message_delta":
                if any(not b["closed"] for b in blocks.values()):
                    raise StreamError("OPEN_BLOCK_AT_FINISH")
                delta = _object(payload.get("delta"), "INVALID_DELTA")
                reason = delta.get("stop_reason")
                if reason is not None:
                    if finish is not None:
                        raise StreamError("DUPLICATE_FINISH")
                    if not isinstance(reason, str):
                        raise StreamError("INVALID_FINISH")
                    finish = reason
                current = _usage_anthropic(payload.get("usage"), "output_tokens")
                if current is not None:
                    if output_tokens is not None and current < output_tokens:
                        raise StreamError("USAGE_DECREASED")
                    output_tokens = current
            elif kind == "message_stop":
                if finish is None:
                    raise StreamError("MISSING_FINISH")
                stopped = True
            else:
                raise StreamError("UNKNOWN_EVENT_TYPE")
        except StreamError as exc:
            findings.append(exc.code)
            break

    if not started:
        findings.append("MISSING_START")
    if not stopped:
        findings.append("MISSING_MESSAGE_STOP")
    if finish is None:
        findings.append("MISSING_FINISH")
    tools = [b for b in blocks.values() if b["type"] == "tool_use"]
    if not tools:
        findings.append("NO_CLIENT_TOOLS")
    elif finish is not None and finish != "tool_use":
        findings.append("UNSAFE_FINISH")
    for block in tools:
        if not block["closed"]:
            findings.append("OPEN_TOOL_BLOCK")
        try:
            _tool_json(block["arguments"] or "{}")
        except StreamError as exc:
            findings.append(exc.code)
    return (
        findings,
        len(tools),
        finish or "unobserved",
        input_tokens is not None and output_tokens is not None,
    )


BLOCKING = {
    "ARGUMENT_LIMIT",
    "BLOCK_AFTER_FINISH",
    "BLOCK_INDEX_LIMIT",
    "DELTA_OUTSIDE_BLOCK",
    "DUPLICATE_BLOCK",
    "DUPLICATE_FINISH",
    "DUPLICATE_JSON_KEY",
    "DUPLICATE_START",
    "DUPLICATE_TOOL_ID",
    "DUPLICATE_USAGE",
    "EVENT_AFTER_DONE",
    "EVENT_AFTER_STOP",
    "EVENT_TYPE_MISMATCH",
    "INVALID_ARGUMENT_DELTA",
    "INVALID_BLOCK",
    "INVALID_BLOCK_STOP",
    "INVALID_CHOICE",
    "INVALID_CHOICES",
    "INVALID_DELTA",
    "INVALID_EVENT_JSON",
    "INVALID_EVENT_SHAPE",
    "INVALID_FINISH",
    "INVALID_FUNCTION",
    "INVALID_MESSAGE",
    "INVALID_TOOL_CALL",
    "INVALID_TOOL_CALLS",
    "INVALID_TOOL_JSON",
    "INVALID_TOOL_METADATA",
    "INVALID_USAGE",
    "MISSING_RESPONSE_ID",
    "MISSING_TOOL_METADATA",
    "OPEN_BLOCK_AT_FINISH",
    "OPEN_TOOL_BLOCK",
    "PROVIDER_ERROR",
    "RESPONSE_ID_CHANGED",
    "TOOL_AFTER_FINISH",
    "TOOL_ARGUMENT_NOT_OBJECT",
    "TOOL_DELTA_WRONG_BLOCK",
    "TOOL_INDEX_LIMIT",
    "TOOL_METADATA_CONFLICT",
    "UNSAFE_FINISH",
    "UNSUPPORTED_CHOICE_INDEX",
    "UNSUPPORTED_INITIAL_INPUT",
    "USAGE_DECREASED",
}


def audit(source: str, provider: str, *, require_usage: bool = False) -> dict[str, Any]:
    if provider not in ("openai-chat", "anthropic-messages"):
        raise ValueError("provider must be openai-chat or anthropic-messages")
    size = len(source.encode("utf-8"))
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    try:
        if size > MAX_BYTES:
            raise StreamError("TRANSCRIPT_LIMIT")
        events = parse_sse(source)
        findings, tool_count, finish, usage = (
            _openai(events) if provider == "openai-chat" else _anthropic(events)
        )
        event_count = len(events)
    except StreamError as exc:
        findings, tool_count, finish, usage, event_count = [exc.code], 0, "unobserved", False, 0
    if require_usage and not usage:
        findings.append("USAGE_UNOBSERVED")
    findings = sorted(set(findings))
    verdict = (
        "blocked"
        if any(f in BLOCKING or f.endswith("_LIMIT") for f in findings)
        else ("inconclusive" if findings else "dispatch_allowed")
    )
    return {
        "schema_version": 1,
        "provider": provider,
        "transcript_sha256": digest,
        "bytes": size,
        "events": event_count,
        "tool_count": tool_count,
        "finish_reason": finish,
        "usage_observed": usage,
        "usage_required": require_usage,
        "verdict": verdict,
        "findings": findings,
    }
