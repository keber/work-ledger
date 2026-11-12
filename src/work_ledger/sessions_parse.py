"""Parse one Claude Code transcript (JSONL) into facts. Pure: no filesystem besides the read.

Only bounded fields are kept: no message text, tool output or file content.
"""

import json
import posixpath
import re
from collections import Counter
from datetime import datetime, timezone

TITLE_SOURCES = ("custom-title", "agent-name", "ai-title")  # highest precedence first
TITLE_FIELDS = {"custom-title": "customTitle", "agent-name": "agentName", "ai-title": "aiTitle"}
WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
               "NotebookEdit": "notebook_path"}
SHELL_TOOLS = ("Bash", "PowerShell")
WRAP_UP_TOOL = "mcp__ccd_turn__wrap_up"
SUMMARY_SUFFIX = "mem_session_summary"
GIT_ACTIONS = ("commit", "push", "merge", "pr-create")
RECAP_MAX = 300
PROMPT_MAX = 200
DETACHED_BRANCH = "HEAD"

# Regex detection over the raw command text. Known limits: a command inside a quoted string
# (`echo "git push"`) still matches; a git invoked by full path (`C:\...\git.exe push`) or an
# alias does not; `git merge --abort` counts as a merge.
_BOUNDARY = r"(?<![\w./\\-])"
_ARG = r"""(?:"[^"]*"|'[^']*'|\S+)"""
_GIT_OPT = rf"(?:-[Cc]\s+{_ARG}|--[\w-]+(?:={_ARG})?|-[A-Za-z])"
_PATTERNS = (
    (re.compile(rf"{_BOUNDARY}git(?:\.exe)?(?:\s+{_GIT_OPT})*\s+(commit|push|merge)(?![\w-])"),
     None),
    (re.compile(rf"{_BOUNDARY}gh(?:\.exe)?\s+pr\s+create(?![\w-])"), "pr-create"),
    (re.compile(rf"{_BOUNDARY}az(?:\.cmd)?\s+repos\s+pr\s+create(?![\w-])"), "pr-create"),
)
_DRIVE = re.compile(r"^[A-Za-z]:/")
_GIT_BASH_DRIVE = re.compile(r"^/([A-Za-z])(?:/(.*))?$")


def drive_path(path):
    """Git Bash `/<letter>/...` as `<LETTER>:/...`; any other value is returned unchanged.

    Only a single-letter first segment is a drive, so `/home/x` or `/tmp` are kept.
    """
    if not isinstance(path, str):
        return path
    m = _GIT_BASH_DRIVE.match(path)
    if not m:
        return path
    return f"{m.group(1).upper()}:/{m.group(2) or ''}"


def normalize_path(path, cwd=None):
    """Absolute forward-slash path; relative paths are joined to cwd when known."""
    if not isinstance(path, str) or not path:
        return None
    p = path.replace("\\", "/")
    if not (_DRIVE.match(p) or p.startswith("/")) and isinstance(cwd, str) and cwd:
        p = cwd.replace("\\", "/").rstrip("/") + "/" + p
    p = posixpath.normpath(p)
    if _DRIVE.match(p):
        p = p[0].upper() + p[1:]
    return p


def normalize_session_path(path, cwd=None):
    """normalize_path plus the Git Bash drive form (`/c/x` -> `C:/x`), for transcript paths."""
    return drive_path(normalize_path(path, cwd))


def detect_git_actions(command):
    """Git actions in a shell command, in order of appearance."""
    if not isinstance(command, str):
        return []
    found = []
    for pattern, action in _PATTERNS:
        for m in pattern.finditer(command):
            found.append((m.start(), action or m.group(1)))
    return [action for _, action in sorted(found)]


def _truncate(value, limit):
    return value[:limit] if isinstance(value, str) else None


def parse_timestamp(ts):
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _counted(counter, key):
    return [{key: k, "count": n} for k, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]


def _content(record):
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _is_user_message(record):
    if record.get("isMeta"):
        return False
    content = _content(record)
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(isinstance(i, dict) and i.get("type") != "tool_result" for i in content)
    return False


class _Facts:
    def __init__(self):
        self.titles = {}
        self.first = self.last = None  # (datetime, original string)
        self.user_messages = 0
        self.assistant_ids = set()
        self.assistant_anonymous = 0
        self.cwds = Counter()
        self.branches = Counter()
        self.entrypoints = Counter()  # "sdk-cli" marks a headless `claude -p` run
        self.no_branch = 0
        self.relocated = None
        self.writes = Counter()
        self.actions = {a: {"count": 0, "lastAt": None} for a in GIT_ACTIONS}
        self.recap = self.ask = None
        self.summary_saved = False
        self.ended_with_question = False
        self.last_prompt = None
        self.messages = []  # [uuid, timestamp] in file order, for fork detection
        self.malformed = 0

    def add(self, record):
        kind = record.get("type")
        if kind in TITLE_FIELDS:
            value = record.get(TITLE_FIELDS[kind])
            if isinstance(value, str) and value.strip():
                self.titles[kind] = value
            return
        if kind == "relocated":
            self.relocated = normalize_session_path(record.get("relocatedCwd")) or self.relocated
            return
        if kind == "last-prompt":
            self.last_prompt = _truncate(record.get("lastPrompt"), PROMPT_MAX) or self.last_prompt
            return
        if kind not in ("user", "assistant", "system"):
            return
        self._common(record)
        if kind == "user" and _is_user_message(record):
            self.user_messages += 1
        elif kind == "assistant":
            self._assistant(record)

    def _common(self, record):
        ts = record.get("timestamp")
        when = parse_timestamp(ts)
        if when:
            if self.first is None or when < self.first[0]:
                self.first = (when, ts)
            if self.last is None or when > self.last[0]:
                self.last = (when, ts)
        if isinstance(record.get("uuid"), str):
            self.messages.append([record["uuid"], ts if isinstance(ts, str) else None])
        cwd = normalize_session_path(record.get("cwd"))
        if cwd:
            self.cwds[cwd] += 1
        entrypoint = record.get("entrypoint")
        if isinstance(entrypoint, str) and entrypoint:
            self.entrypoints[entrypoint] += 1
        branch = record.get("gitBranch")
        # Transcripts record "HEAD" when not on a branch (detached).
        if isinstance(branch, str) and branch and branch != DETACHED_BRANCH:
            self.branches[branch] += 1
        else:
            self.no_branch += 1

    def _assistant(self, record):
        message = record.get("message")
        msg_id = message.get("id") if isinstance(message, dict) else None
        if isinstance(msg_id, str):
            self.assistant_ids.add(msg_id)
        else:
            self.assistant_anonymous += 1
        content = _content(record)
        if not isinstance(content, list):
            return
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text = item["text"].rstrip()
                if text:
                    self.ended_with_question = text.endswith("?")
            elif item.get("type") == "tool_use":
                self._tool(item.get("name"), item.get("input"), record)

    def _tool(self, name, tool_input, record):
        if not isinstance(name, str):
            return
        if name.endswith(SUMMARY_SUFFIX):
            self.summary_saved = True
        if not isinstance(tool_input, dict):
            return
        if name in WRITE_TOOLS:
            path = normalize_session_path(tool_input.get(WRITE_TOOLS[name]), record.get("cwd"))
            if path:
                self.writes[path] += 1
        elif name in SHELL_TOOLS:
            for action in detect_git_actions(tool_input.get("command")):
                entry = self.actions[action]
                entry["count"] += 1
                if isinstance(record.get("timestamp"), str):
                    entry["lastAt"] = record["timestamp"]
        elif name == WRAP_UP_TOOL:
            self.recap = _truncate(tool_input.get("recap"), RECAP_MAX)
            self.ask = _truncate(tool_input.get("ask"), RECAP_MAX)

    def result(self):
        source = next((s for s in TITLE_SOURCES if s in self.titles), None)
        return {
            "title": self.titles.get(source),
            "titleSource": source,
            "firstAt": self.first[1] if self.first else None,
            "lastAt": self.last[1] if self.last else None,
            "userMessages": self.user_messages,
            "assistantMessages": len(self.assistant_ids) + self.assistant_anonymous,
            "cwds": _counted(self.cwds, "path"),
            "relocatedCwd": self.relocated,
            "gitBranches": _counted(self.branches, "name"),
            "detachedOrNoBranchCount": self.no_branch,
            "writes": _counted(self.writes, "path"),
            "gitActions": self.actions,
            "closure": {"lastRecap": self.recap, "lastAsk": self.ask,
                        "sessionSummarySaved": self.summary_saved,
                        "endedWithQuestion": self.ended_with_question},
            "lastPrompt": self.last_prompt,
            "entrypoint": self.entrypoints.most_common(1)[0][0] if self.entrypoints else None,
            "malformedLines": self.malformed,
            "messages": self.messages,
        }


def parse_lines(lines):
    """Facts from an iterable of JSONL lines, consumed one at a time."""
    facts = _Facts()
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            facts.malformed += 1
            continue
        if not isinstance(record, dict):
            facts.malformed += 1
            continue
        facts.add(record)
    return facts.result()


def parse_transcript(path):
    """Stream a transcript file line by line. Raises OSError if it cannot be read."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return parse_lines(fh)
