"""Build the versioned sessions report and render it as JSON and Markdown."""

import json
import os
from datetime import datetime, timezone

from .report import _cell
from .sessions_parse import GIT_ACTIONS, parse_timestamp

SCHEMA_VERSION = 3  # 3: temp writes excluded from writeAnchor
JSON_NAME = "sessions.json"
MD_NAME = "sessions.md"
UNKNOWN_GROUP = "(unknown)"


def build_sessions_report(sessions, stats, source_root, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at.isoformat(),
        "sourceRoot": source_root,
        "stats": stats,
        "sessions": list(sessions),
    }


def _group(session):
    if session.get("writeAnchor"):
        return session["writeAnchor"]["path"]
    cwds = session.get("cwds") or []
    return cwds[0]["path"] if cwds else UNKNOWN_GROUP


def _recent_key(session):
    when = parse_timestamp(session.get("lastAt"))
    return when.timestamp() if when else float("-inf")


def _title(session):
    return session.get("title") or f"(untitled {session['sessionId'][:8]})"


def _actions(session):
    actions = session.get("gitActions") or {}
    parts = [f"{a} {actions[a]['count']}" for a in GIT_ACTIONS if (actions.get(a) or {}).get("count")]
    return ", ".join(parts) or None


def _closure(session):
    c = session.get("closure") or {}
    parts = []
    if c.get("lastRecap"):
        parts.append(c["lastRecap"])
    if c.get("lastAsk"):
        parts.append(f"ask: {c['lastAsk']}")
    flags = [name for name, on in (("summary", c.get("sessionSummarySaved")),
                                   ("ended with question", c.get("endedWithQuestion"))) if on]
    if flags:
        parts.append(f"[{', '.join(flags)}]")
    return " ".join(parts) or None


def _fork(session):
    fork = session.get("fork")
    if not fork:
        return None
    text = f"family {fork['familyId'][:8]} ({len(fork['members']) + 1})"
    if fork.get("parent"):
        text += f", fork of {fork['parent'][:8]} ({fork['sharedMessages']} shared)"
    return text


def render_sessions_markdown(report):
    stats = report["stats"]
    lines = [
        "# Claude Code sessions",
        "",
        f"Generated {report['generatedAt']} from {report['sourceRoot']}.",
        f"Files: {stats['files']} (parsed {stats['parsed']}, cached {stats['cached']}, "
        f"unreadable {stats['unreadable']}); skipped lines: {stats['skippedLines']}.",
        "Grouped by write anchor (fallback: main cwd), most recent first.",
    ]
    groups = {}
    for session in report["sessions"]:
        groups.setdefault(_group(session), []).append(session)
    ordered = sorted(groups.items(),
                     key=lambda kv: (-max(_recent_key(s) for s in kv[1]), kv[0]))
    for name, sessions in ordered:
        lines += ["", f"## {name}", "",
                  "| last | first | title | branch | git | closure | fork |",
                  "|---|---|---|---|---|---|---|"]
        for s in sorted(sessions, key=lambda s: (-_recent_key(s), s["sessionId"])):
            branches = s.get("gitBranches") or []
            lines.append(
                f"| {_cell((s.get('lastAt') or '')[:16] or None)} "
                f"| {_cell((s.get('firstAt') or '')[:16] or None)} "
                f"| {_cell(_title(s))} | {_cell(branches[0]['name'] if branches else None)} "
                f"| {_cell(_actions(s))} | {_cell(_closure(s))} | {_cell(_fork(s))} |")
    return "\n".join(lines) + "\n"


def write_sessions_reports(report, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, JSON_NAME)
    md_path = os.path.join(out_dir, MD_NAME)
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_sessions_markdown(report))
    return json_path, md_path
