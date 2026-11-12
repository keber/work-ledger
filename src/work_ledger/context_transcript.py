"""Compact, chronological digest of one transcript, read on demand for `context`.

Unlike the session scan, this keeps message text: user prompts, the assistant's last text
of each turn and wrap-up recaps, each clipped. Tool inputs, tool output and file contents
are never kept. The caller prints the result; nothing here is written to disk.
"""

import json
import os
from collections import Counter, deque

from .sessions_parse import WRAP_UP_TOOL

ENTRY_MAX = 300
HEAD = 3
TAIL = 8
ELLIPSIS = "..."
# Prompts injected by the harness (slash commands, reminders) start with a tag.
_INJECTED_PREFIX = "<"
_SKIP_FLAGS = ("isMeta", "isSidechain", "isCompactSummary")
TRANSCRIPT_SUFFIX = ".jsonl"
OUTSIDE_SOURCE = "excerpts unavailable: path outside sessions source"


def entry_key(entry):
    """Identity of an entry across sessions: a fork copies its parent's entries verbatim."""
    return (entry.get("at"), entry.get("role"), entry.get("text"))


def _real(path):
    return os.path.normcase(os.path.realpath(path))


def is_transcript_path(path, source_root):
    """True when path is a .jsonl file whose real path lies under the real source_root.

    Paths come from sessions.json; this keeps a tampered or stale report from making the
    command open arbitrary files.
    """
    if not isinstance(path, str) or not path or not isinstance(source_root, str)             or not source_root:
        return False
    if not path.lower().endswith(TRANSCRIPT_SUFFIX):
        return False
    real, root = _real(path), _real(source_root)
    try:
        return os.path.commonpath([real, root]) == root and real != root
    except ValueError:  # different drives
        return False


def clip(text, limit=ENTRY_MAX):
    """Whitespace collapsed to single spaces, cut to `limit` chars with a trailing marker."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit - len(ELLIPSIS)].rstrip() + ELLIPSIS


def _skipped(record):
    return any(record.get(flag) for flag in _SKIP_FLAGS)


def _user_text(record):
    """The prompt text of a user record, or None for tool results and injected content."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [i.get("text") for i in content
                 if isinstance(i, dict) and i.get("type") == "text" and isinstance(i.get("text"), str)]
        text = " ".join(parts)
    else:
        return None
    text = text.strip()
    if not text or text.startswith(_INJECTED_PREFIX):
        return None
    return text


def _recap_text(tool_input):
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("recap"), str):
        return None
    text = tool_input["recap"]
    if isinstance(tool_input.get("ask"), str) and tool_input["ask"].strip():
        text += " | ask: " + tool_input["ask"]
    return text


class _Digest:
    def __init__(self, head, tail, limit, seen=None):
        self.head, self.limit = head, limit
        self.seen = seen or {}
        self.shared = Counter()
        self.keys = []
        self.first = []
        self.last = deque(maxlen=tail) if tail > 0 else None
        self.total = 0
        self.pending = None  # (timestamp, text) of the turn's latest assistant text

    def add(self, at, role, text):
        entry = {"at": at, "role": role, "text": clip(text, self.limit)}
        key = entry_key(entry)
        self.keys.append(key)
        if key in self.seen:
            self.shared[self.seen[key]] += 1
            return
        self.total += 1
        if len(self.first) < self.head:
            self.first.append(entry)
        elif self.last is not None:
            self.last.append(entry)

    def flush(self):
        if self.pending:
            self.add(self.pending[0], "assistant", self.pending[1])
        self.pending = None

    def record(self, record):
        kind = record.get("type")
        if kind not in ("user", "assistant") or _skipped(record):
            return
        at = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
        if kind == "user":
            text = _user_text(record)
            if text is not None:
                self.flush()
                self.add(at, "user", text)
            return
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            return
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str) \
                    and item["text"].strip():
                self.pending = (at, item["text"])
            elif item.get("type") == "tool_use" and item.get("name") == WRAP_UP_TOOL:
                recap = _recap_text(item.get("input"))
                if recap:
                    self.pending = None  # text before the wrap-up is not the turn's last word
                    self.add(at, "recap", recap)

    def result(self):
        self.flush()
        tail = list(self.last or [])
        omitted = self.total - len(self.first) - len(tail)
        return {"entries": self.first + tail, "total": self.total, "omitted": omitted,
                "gapAfter": len(self.first) if omitted else None,
                "sharedWith": dict(self.shared), "keys": self.keys}


def excerpt_lines(lines, head=HEAD, tail=TAIL, limit=ENTRY_MAX, seen=None):
    """Digest of JSONL lines: the first `head` and last `tail` entries, oldest first.

    `omitted` entries sit between position `gapAfter` and the next entry. Entries whose
    key is in `seen` ({key: session id}) were already shown for another session: they are
    counted in `sharedWith` ({session id: count}) and take no head or tail slot. `keys`
    lists every entry key, shared or not, for the caller to mark as seen.
    """
    digest = _Digest(head, tail, limit, seen)
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            digest.record(record)
    return digest.result()


def _failed(error):
    return {"entries": [], "total": 0, "omitted": 0, "gapAfter": None, "sharedWith": {},
            "keys": [], "error": error}


def read_excerpt(path, head=HEAD, tail=TAIL, limit=ENTRY_MAX, seen=None, source_root=None):
    """excerpt_lines over a transcript file plus `error`; failures are reported, not raised.

    With `source_root`, a path that is not a .jsonl under it is never opened.
    """
    if source_root is not None and not is_transcript_path(path, source_root):
        return _failed(OUTSIDE_SOURCE)
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            excerpt = excerpt_lines(fh, head, tail, limit, seen)
    except OSError as exc:
        return _failed(f"transcript unreadable: {type(exc).__name__}: {exc}")
    excerpt["error"] = None
    return excerpt
