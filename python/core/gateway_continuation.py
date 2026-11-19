"""Join interrupted Responses streams without replaying actions or changing the client-visible turn."""

import math
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime

from core.gateway_store import MAX_RESOURCE


class ProtocolError(ValueError):
    def __init__(self, message, status=400, code="invalid_request_error"):
        super().__init__(message)
        self.status, self.code = status, code


class QuotaLimit(ProtocolError):
    def __init__(self, code, delay, deployment_limited=False):
        super().__init__("上游额度受限", 429, code)
        self.delay = delay
        self.deployment_limited = deployment_limited


def quota_limit(error, headers=None, status=None):
    if not isinstance(error, dict) or status not in (None, 429, "429"):
        return None
    code = str(error.get("code") or error.get("type") or error.get("reason") or "").lower()
    if not code and status in (429, "429"):
        code = "429"
    if code not in {
        "usage_limit_reached",
        "rate_limit_exceeded",
        "rate_limit_error",
        "too_many_requests",
        "deployment_rate_limit_exceeded",
        "429",
    }:
        return None
    headers = {str(k).lower(): v for k, v in headers.items()} if isinstance(headers, Mapping) else {}
    seconds = []

    def duration(value, scale: float = 1, offset: float = 0):
        try:
            n = float(value) * scale - offset
            if math.isfinite(n):
                seconds.append(max(0, n))
        except (ValueError, TypeError, OverflowError):
            pass

    retry = headers.get("retry-after")
    duration(retry)
    if isinstance(retry, str) and not seconds:
        try:
            duration(parsedate_to_datetime(retry).timestamp(), offset=time.time())
        except (ValueError, TypeError, OSError, OverflowError):
            pass
    duration(headers.get("retry-after-ms"), 0.001)
    duration(error.get("retry_after"))
    duration(error.get("resets_in_seconds"))
    duration(error.get("resets_at"), offset=time.time())
    scope = str(error.get("scope") or "").lower()
    deployment = scope == "deployment" or (
        not scope
        and (
            code == "deployment_rate_limit_exceeded"
            or any(
                str(headers.get("x-ratelimit-remaining-" + k, "")) == "0"
                and headers.get("x-ratelimit-limit-" + k)
                for k in ("requests", "tokens")
            )
        )
    )
    return QuotaLimit(code, max(seconds) if seconds else None, deployment)


def replay_item(item):
    item = dict(item)
    if item.get("type") in ("message", "reasoning", "function_call", "custom_tool_call"):
        item.pop("id", None)
    return item


def add_usage(previous, reported):
    combined = dict(previous)
    for key, value in (reported or {}).items():
        if type(value) is int:
            combined[key] = previous.get(key, 0) + value
        elif isinstance(value, dict):
            combined[key] = add_usage(previous.get(key, {}), value)
    return combined


class TextJoin:
    """Delay only a possible verbatim echo at the seam, including an echo split over several frames."""

    def __init__(self, prefix):
        self.prefix = prefix
        self.tail = prefix[-2048:]
        self.pending = ""
        self.head = 0
        self.decided = not prefix
        self.skipped = 0

    def feed(self, delta, final=False):
        if self.decided:
            return delta
        if not final and not self.pending and self.prefix.startswith(delta, self.head):
            self.head += len(delta)
            return ""
        value = self.prefix[: self.head] + self.pending + delta
        self.head = 0
        if not final and value in self.tail:
            self.pending = value
            return ""
        if value.startswith(self.prefix):
            self.skipped = len(self.prefix)
        else:
            # Short coincidental matches commonly occur in punctuation, code and prose.
            for n in range(min(len(value), len(self.tail)), 1, -1):
                overlap = value[:n]
                if self.tail.endswith(overlap) and (
                    n >= 4 or any("\u3400" <= c <= "\u9fff" for c in overlap)
                ):
                    self.skipped = n
                    break
        self.decided = True
        self.pending = ""
        return value[self.skipped :]


class AnswerStream:
    def __init__(self, wire):
        self.model = wire.get("model", "")
        self.response = {}
        self.done = {}
        self.open = {}
        self.text = []
        self.text_size = 0
        self.part_started = False
        self.sequence = -1
        self.resuming = False
        self.closers = []
        text = wire.get("text") or {}
        output_format = (text.get("format") or {}) if isinstance(text, dict) else None
        self.safe = isinstance(output_format, dict) and output_format.get("type", "text") == "text"
        # Hosted actions may have side effects before their first observable event.
        if any(
            t.get("type") in ("mcp", "computer", "computer_use_preview")
            for t in wire.get("tools") or []
            if isinstance(t, dict)
        ):
            self.safe = False

    def current_message(self):
        if len(self.open) == 1:
            index, item = next(iter(self.open.items()))
            if item.get("type") == "message" and item.get("role", "assistant") == "assistant":
                return index, item
        return None

    def can_resume(self, failure):
        reported = (failure.get("response") or {}).get("output") or []
        return (
            self.safe
            and (not self.open or self.current_message() is not None)
            and all(
                isinstance(item, dict) and item.get("type") in ("message", "reasoning") for item in reported
            )
        )

    def continuing_input(self, wire):
        items = [replay_item(value) for _, value in sorted(self.done.items())]
        partial = "".join(self.text)
        if partial:
            message = {"role": "assistant", "content": partial}
            current = self.current_message()
            if current and current[1].get("phase"):
                message["phase"] = current[1]["phase"]
            items.append(message)
        if not items:
            return wire
        if partial or any(item.get("type") == "message" for item in items):
            items.append(
                {
                    "role": "user",
                    "content": "Continue your interrupted answer at the first missing "
                    "character. Preserve its language and formatting. Do not repeat text already written.",
                }
            )
        return {**wire, "input": [*wire["input"], *items]}

    def deliver(self, event):
        kind = event.get("type", "")
        index = event.get("output_index", 0)
        item = event.get("item") or {}
        if self.resuming:
            self.sequence += 1
            event = {**event, "sequence_number": self.sequence}
        else:
            self.sequence = max(self.sequence + 1, event.get("sequence_number", 0))
        if kind in ("response.created", "response.in_progress"):
            self.response = event.get("response") or self.response
        if kind == "response.output_item.added":
            self.open[index] = item
        if kind == "response.content_part.added":
            self.part_started = True
        if kind == "response.output_text.delta":
            if index not in self.open:
                self.open[index] = {"id": event.get("item_id"), "type": "message", "role": "assistant"}
            self.part_started = True
            delta = event["delta"]
            self.text_size += len(delta)
            if self.text_size <= MAX_RESOURCE:
                self.text.append(delta)
            else:
                self.safe = False
        if kind == "response.output_item.done":
            self.done[index] = item
            self.open.pop(index, None)
            if item.get("type") == "message":
                self.text.clear()
                self.text_size = 0
                self.part_started = False
        if (
            item
            and item.get("type") not in ("message", "reasoning")
            or "_call" in kind
            or "refusal" in kind
            or "annotation" in kind
            or event.get("content_index", 0) != 0
        ):
            self.safe = False
        return event

    def publish(self, event):
        kind = event.get("type")
        current = self.current_message()
        if (
            current
            and self.safe
            and event.get("output_index") == current[0]
            and kind
            in ("response.output_text.done", "response.content_part.done", "response.output_item.done")
        ):
            self.closers.append(event)
            return []
        return [*self.flush(), self.deliver(event)]

    def flush(self):
        events = [self.deliver(e) for e in self.closers]
        self.closers.clear()
        return events


class Attempt:
    """Translate a fresh upstream response to the open downstream response and output item."""

    def __init__(self, state):
        self.state = state
        self.response_id = state.response.get("id")
        self.current = state.current_message()
        self.prefix = "".join(state.text)
        self.join = TextJoin(self.prefix)
        self.offset = max(state.done, default=-1) + 1
        self.prior = dict(state.done)
        self.before_text = self.current is not None
        self.merged_index = None
        self.received = 0
        self.merged_item = None
        self.hidden = set()

    def _text_delta(self, delta):
        index, item = self.current
        return {
            "type": "response.output_text.delta",
            "item_id": item.get("id"),
            "output_index": index,
            "content_index": 0,
            "delta": delta,
            "logprobs": [],
        }

    def _finish_prefix(self, text=None):
        index, item = self.current
        text = self.prefix if text is None else text
        part = {"type": "output_text", "text": text, "annotations": []}
        complete = {**item, "status": "completed", "content": [part]}
        common = {"output_index": index, "content_index": 0, "item_id": item.get("id")}
        return [
            {"type": "response.output_text.done", **common, "text": text, "logprobs": []},
            {"type": "response.content_part.done", **common, "part": part},
            {"type": "response.output_item.done", "output_index": index, "item": complete},
        ]

    def translate(self, event):
        if not self.state.resuming:
            return [event]
        if self.response_id and "response_id" in event:
            event = {**event, "response_id": self.response_id}
        kind = event.get("type", "")
        response = event.get("response")
        if kind == "response.created" and self.response_id:
            return []
        if isinstance(response, dict):
            response = {**response, "id": self.response_id or response.get("id")}
            extra = []
            if kind == "response.completed":
                output = dict(self.prior)
                actual = response.get("output") or []
                # Some upstreams omit item.done and include the complete message only in the terminal snapshot.
                if (
                    self.current
                    and self.merged_item is None
                    and (self.before_text or self.merged_index is not None)
                ):
                    n = self.merged_index
                    if n is None:
                        n = next(
                            (i for i, value in enumerate(actual) if value.get("type") == "message"), None
                        )
                    if n is not None:
                        self.merged_index = n
                        self.offset = self.current[0] - n
                        content = actual[n].get("content", []) if n < len(actual) else []
                        full = content[0].get("text", "") if content else ""
                        tail = self.join.feed(full[self.received :], final=True)
                        if tail:
                            extra.append(self._text_delta(tail))
                        merged = "".join(self.state.text) + tail
                        closed = self._finish_prefix(merged)
                        self.merged_item = closed[-1]["item"]
                        already_closed = {e["type"] for e in self.state.closers}
                        extra.extend(e for e in closed if e["type"] not in already_closed)
                    else:
                        extra.extend(self._finish_prefix())
                        output[self.current[0]] = extra[-1]["item"]
                        self.offset = self.current[0] + 1
                for n, item in enumerate(actual):
                    if n in self.hidden or (self.merged_index is not None and n < self.merged_index):
                        continue
                    output[n + self.offset] = item
                output.update(self.state.done)
                if self.merged_item is not None:
                    output[self.current[0]] = self.merged_item
                response["output"] = [value for _, value in sorted(output.items())]
            return [*extra, {**event, "response": response}]
        if not kind.startswith("response.") or "output_index" not in event:
            return [event]
        n = event["output_index"]
        item = event.get("item") or {}
        if n in self.hidden:
            return []
        if self.before_text:
            if item.get("type") == "reasoning" or "reasoning" in kind:
                self.hidden.add(n)
                return []
            self.before_text = False
            self.offset = self.current[0] - n
            if item.get("type", "message") != "message":
                self.offset += 1
                closed = self._finish_prefix()
                self.prior[self.current[0]] = closed[-1]["item"]
                return [*closed, {**event, "output_index": n + self.offset}]
            self.merged_index = n
        mapped = {**event, "output_index": n + self.offset}
        if n != self.merged_index:
            return [mapped]
        index, original = self.current
        mapped["output_index"] = index
        if "item_id" in mapped:
            mapped["item_id"] = original.get("id")
        if kind == "response.output_item.added" or (
            kind == "response.content_part.added" and self.state.part_started
        ):
            return []
        if kind == "response.output_text.delta":
            self.received += len(event["delta"])
            delta = self.join.feed(event["delta"])
            return [{**mapped, "delta": delta}] if delta else []
        if kind in ("response.output_text.done", "response.content_part.done", "response.output_item.done"):
            text = event.get("text")
            if kind == "response.content_part.done":
                text = event["part"].get("text")
            if kind == "response.output_item.done":
                content = item.get("content") or []
                text = content[0].get("text") if content else None
            if not isinstance(text, str):
                return [mapped]
            tail = self.join.feed(text[self.received :], final=True)
            self.received = max(len(text), self.received)
            merged = self.prefix + text[self.join.skipped :]
            if kind == "response.output_text.done":
                mapped["text"] = merged
            elif kind == "response.content_part.done":
                mapped["part"] = {**event["part"], "text": merged}
            else:
                self.merged_item = {
                    **item,
                    "id": original.get("id"),
                    "content": [{**content[0], "text": merged}],
                }
                mapped["item"] = self.merged_item
            return [self._text_delta(tail), mapped] if tail else [mapped]
        return [mapped]
