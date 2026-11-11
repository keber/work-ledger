"""Render the weekly digest as Markdown and read/write `out/digest/latest.json`."""

import json
import os

from .discover import to_posix
from .report import _cell
from .threads_inputs import InputError, check_schema, load_json
from .threads_state import RECENT_DAYS

SCHEMA_VERSION = 1
LATEST_NAME = "latest.json"
# The latest.json a run replaced. Curation reads it to compare against the digest before.
PREVIOUS_NAME = "previous.json"
NAME_SEPARATOR = " · "


class DigestFileError(Exception):
    """The previous latest.json is unreadable or has an unsupported shape."""


def _name(item):
    title = f"**{_cell(item.get('title'))}**"
    project = item.get("project")
    return f"{_cell(project)}{NAME_SEPARATOR}{title}" if project else title


def _risk_text(risk, not_on_remote):
    text = risk or "-"
    return f"{text}, {not_on_remote} not on remote" if not_on_remote else text


def _idle(days):
    return f"{days}d idle" if days is not None else "idle unknown"


def _or_none(lines):
    return lines or ["- none"]


def _at_risk(digest):
    items = digest["atRiskRecent"]
    lines = [f"- {_name(t)} | {_idle(t['daysIdle'])} | "
             f"git: {_risk_text(t['risk'], t['notOnRemote'])}" for t in items]
    return ["", f"## At risk, recent ({len(items)})", ""] + _or_none(lines)


def _no_backup(digest):
    nb = digest["noBackup"]
    lines = [f"- **{_cell(p['name'])}** main worktree: {_risk_text(p['risk'], p['notOnRemote'])}"
             for p in nb["projects"]]
    lines += [f"- {_name(t)} | {t['notOnRemote']} not on remote" for t in nb["threads"]]
    return ["", f"## No backup ({nb['total']} commits on no remote)", ""] + _or_none(lines)


def _code(text):
    return "`" + text.replace("`", "") + "`"


def _going_cold(digest):
    items = digest["goingCold"]
    lines = []
    for t in items:
        lines.append(f"- {_name(t)} | {t['state']}, {_idle(t['daysIdle'])}")
        if t.get("recap"):
            lines.append(f"  - Recap: {_cell(t['recap'])}")
        if t.get("ask"):
            lines.append(f"  - Ask: {_cell(t['ask'])}")
        if t.get("resume"):
            lines.append(f"  - Resume: {_code(t['resume'])}")
    return ["", f"## Going cold ({len(items)})", ""] + _or_none(lines)


def _went_stale(digest):
    items = digest["wentStale"]
    if items is None:
        return ["", "## Went stale this week", "", "- No previous digest to compare."]
    return ["", f"## Went stale this week ({len(items)})", ""] + \
        _or_none([f"- {_name(t)}" for t in items])


def _change(value):
    if value is None:
        return "-"
    return f"+{value}" if value > 0 else str(value)


def _counts(digest):
    lines = ["", "## Counts", "", f"Older at-risk threads ({RECENT_DAYS}+ days idle), per project:",
             ""]
    lines += _or_none([f"- {_cell(o['project'])}: {o['count']}" for o in digest["olderAtRisk"]])
    lines += ["", "Threads per effective state, change since the previous digest:", ""]
    if not digest["states"]:
        return lines + ["- no threads"]
    lines += ["| State | Threads | Change |", "|---|---|---|"]
    return lines + [f"| {s['state']} | {s['count']} | {_change(s['change'])} |"
                    for s in digest["states"]]


def render_digest_markdown(digest, date):
    previous = digest.get("previousGeneratedAt")
    against = f"previous digest {previous}" if previous else \
        "first digest, no previous snapshot"
    lines = [f"# Weekly digest {date}", "",
             f"Ledger generated {digest['ledgerGeneratedAt']}; {against}.",
             "Threads marked done, discarded or paused are left out of the lists, "
             "not out of the backup check."]
    for section in (_at_risk, _no_backup, _going_cold, _went_stale, _counts):
        lines += section(digest)
    return "\n".join(lines) + "\n"


def latest_record(digest, generated_at, md_path):
    return {"schemaVersion": SCHEMA_VERSION, "generatedAt": generated_at.isoformat(),
            "ledgerGeneratedAt": digest["ledgerGeneratedAt"], "path": md_path,
            "counts": digest["counts"], "snapshot": digest["snapshot"]}


def _write_text(path, text):
    """Write through a temp file and replace, so a failed write keeps the old file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_digest(digest, digest_dir, generated_at, date):
    """Write `<date>.md`, keep the old `latest.json` as `previous.json`, write `latest.json`.

    Same-day runs overwrite. Returns the Markdown and latest.json paths.
    """
    os.makedirs(digest_dir, exist_ok=True)
    md_path = os.path.join(digest_dir, f"{date}.md")
    latest_path = os.path.join(digest_dir, LATEST_NAME)
    _write_text(md_path, render_digest_markdown(digest, date))
    if os.path.isfile(latest_path):
        with open(latest_path, encoding="utf-8") as fh:
            _write_text(os.path.join(digest_dir, PREVIOUS_NAME), fh.read())
    record = latest_record(digest, generated_at, to_posix(md_path))
    _write_text(latest_path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return md_path, latest_path


def load_latest(path):
    """Validated latest.json dict. Raises DigestFileError."""
    try:
        data = check_schema(load_json(path, "digest"), "digest", (SCHEMA_VERSION,))
    except InputError as exc:
        raise DigestFileError(str(exc)) from None
    if not isinstance(data.get("snapshot"), dict) or not isinstance(data.get("counts"), dict):
        raise DigestFileError(f"digest: missing snapshot or counts: {path}")
    if not isinstance(data.get("path"), str) or not data["path"]:
        raise DigestFileError(f"digest: missing Markdown path: {path}")
    return data


def load_previous(path):
    """Previous latest.json, or None when there is none yet. Raises DigestFileError."""
    if not os.path.exists(path):
        return None
    return load_latest(path)
