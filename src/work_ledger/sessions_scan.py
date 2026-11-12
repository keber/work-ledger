"""Scan Claude Code transcripts into session records, with an incremental parse cache.

Read-only on the source tree: the only file written is the cache, outside of it.
"""

import json
import os

from .sessions_anchor import AnchorResolver, default_claude_home
from .sessions_forks import detect_forks
from .sessions_parse import parse_timestamp, parse_transcript

CACHE_VERSION = 4  # 4: entrypoint added; 3: Git Bash drive paths normalized at parse time
CACHE_NAME = os.path.join(".cache", "sessions-cache.json")
_INTERNAL = ("messages",)  # needed for fork detection, never emitted


def _posix(path):
    return os.path.abspath(path).replace("\\", "/")


def _transcripts(source):
    """Yield (project dir name, transcript path) for top-level *.jsonl files only."""
    try:
        projects = [e for e in os.scandir(source) if e.is_dir(follow_symlinks=False)]
    except OSError:
        return
    for project in sorted(projects, key=lambda e: e.name):
        try:
            files = [e for e in os.scandir(project.path)
                     if e.name.endswith(".jsonl") and e.is_file(follow_symlinks=False)]
        except OSError:
            continue
        for entry in sorted(files, key=lambda e: e.name):
            yield project.name, entry.path


def _subagent_count(transcript_path):
    folder = os.path.join(transcript_path[:-len(".jsonl")], "subagents")
    try:
        return sum(1 for e in os.scandir(folder) if e.name.endswith(".jsonl") and e.is_file())
    except OSError:
        return 0


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schemaVersion") != CACHE_VERSION:
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def save_cache(path, files):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"schemaVersion": CACHE_VERSION, "files": files}, fh)
    os.replace(tmp, path)


def _created(st):
    """Transcript creation time: st_birthtime when the OS has it, else st_ctime on Windows."""
    birth = getattr(st, "st_birthtime", None)
    if birth is not None:
        return birth
    return st.st_ctime if os.name == "nt" else None


def _record(session_id, path, project, facts, subagents):
    public = {k: v for k, v in facts.items() if k not in _INTERNAL}
    head = {"sessionId": session_id, "transcriptPath": path, "projectDir": project,
            "title": public.pop("title"), "titleSource": public.pop("titleSource"),
            "firstAt": public.pop("firstAt"), "lastAt": public.pop("lastAt"),
            "userMessages": public.pop("userMessages"),
            "assistantMessages": public.pop("assistantMessages"),
            "subagentTranscripts": subagents}
    return {**head, **public}


def _recency(session):
    when = parse_timestamp(session.get("lastAt"))
    return (when is None, -(when.timestamp()) if when else 0, session["sessionId"])


def scan_sessions(source, cache_path, full=False, claude_home=None, parse=parse_transcript,
                  is_temp=None):
    """Return (sessions, stats). One unreadable transcript never stops the scan.

    The cache holds parse facts only; write anchors are recomputed on every run.
    """
    cache = {} if full else load_cache(cache_path)
    resolver = AnchorResolver(claude_home or default_claude_home(), is_temp=is_temp)
    stats = {"files": 0, "parsed": 0, "cached": 0, "skippedLines": 0, "unreadable": 0,
             "errors": []}
    fresh_cache = {}
    entries = []
    for project, native_path in _transcripts(source):
        path = _posix(native_path)
        stats["files"] += 1
        try:
            st = os.stat(native_path)
            hit = cache.get(path)
            if (isinstance(hit, dict) and hit.get("size") == st.st_size
                    and hit.get("mtimeNs") == st.st_mtime_ns and isinstance(hit.get("facts"), dict)):
                facts = hit["facts"]
                stats["cached"] += 1
            else:
                facts = parse(native_path)
                stats["parsed"] += 1
        except Exception as exc:  # one transcript must never abort the whole run
            stats["unreadable"] += 1
            stats["errors"].append({"path": path, "error": f"{type(exc).__name__}: {exc}"})
            continue
        fresh_cache[path] = {"size": st.st_size, "mtimeNs": st.st_mtime_ns, "facts": facts}
        stats["skippedLines"] += facts.get("malformedLines") or 0
        session_id = os.path.basename(native_path)[:-len(".jsonl")]
        entries.append((session_id, path, project, facts, _subagent_count(native_path),
                        _created(st)))

    forks = detect_forks([{"sessionId": sid, "messages": f.get("messages"), "created": created}
                          for sid, _, _, f, _, created in entries])
    sessions = []
    for session_id, path, project, facts, subagents, _ in entries:
        record = _record(session_id, path, project, facts, subagents)
        record["writeAnchor"] = resolver.write_anchor(record["writes"])
        record["fork"] = forks.get(session_id)
        sessions.append(record)
    sessions.sort(key=_recency)
    save_cache(cache_path, fresh_cache)
    return sessions, stats
