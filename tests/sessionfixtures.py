"""Builders for synthetic Claude Code transcript lines (observed format, 2026-11-04)."""

import itertools
import json
import os

_ids = itertools.count(1)


def _uuid():
    return f"u-{next(_ids):06d}"


def msg(kind, content, ts="2026-11-01T10:00:00.000Z", uuid=None, cwd="C:\\work\\app",
        branch="main", **extra):
    record = {"type": kind, "sessionId": "s", "uuid": uuid or _uuid(), "parentUuid": None,
              "timestamp": ts, "cwd": cwd, "gitBranch": branch, "isSidechain": False,
              "message": {"role": kind, "content": content}}
    record.update(extra)
    return record


def user(text="hello", **kw):
    return msg("user", text, **kw)


def tool_result(**kw):
    return msg("user", [{"type": "tool_result", "tool_use_id": "t", "content": "secret output"}],
               **kw)


def assistant_text(text, **kw):
    return msg("assistant", [{"type": "text", "text": text}], **kw)


def tool(name, tool_input, **kw):
    return msg("assistant", [{"type": "tool_use", "id": "t", "name": name, "input": tool_input}],
               **kw)


def meta(kind, **fields):
    return {"type": kind, "sessionId": "s", **fields}


def lines(*records):
    return [json.dumps(r) if isinstance(r, dict) else r for r in records]


def write_jsonl(path, *records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for line in lines(*records):
            fh.write(line + "\n")
    return path
