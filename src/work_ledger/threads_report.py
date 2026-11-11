"""Render the ledger as JSON and Markdown."""

import json
import os

from .report import _cell
from .threads_identity import short_key
from .threads_state import RECENT_DAYS, STATE_ORDER

JSON_NAME = "ledger.json"
MD_NAME = "ledger.md"
RECAP_PREVIEW = 120
NAME_SEPARATOR = " · "


def _activity(item):
    last = (item.get("lastAt") or "")[:10] or "-"
    idle = item.get("daysIdle")
    return f"{last} ({idle}d idle)" if idle is not None else last


def _risk_text(git):
    text = git.get("risk") or "-"
    if git.get("notOnRemote"):
        text += f", {git['notOnRemote']} not on remote"
    return text


def _git(thread):
    git = thread.get("git")
    if not git:
        return "git: project" if thread.get("gitScope") == "project" else "no git"
    if not git.get("found"):
        return "git: not in inventory"
    return f"git: {_risk_text(git)}"


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _line(thread, project_names):
    n = thread["sessionCount"]
    # Inventory-only titles already carry the repo name.
    name = None
    if thread.get("origin") != "inventory":
        name = project_names.get(thread.get("projectId"))
    prefix = f"{_cell(name)}{NAME_SEPARATOR}" if name else ""
    parts = [f"{prefix}**{_cell(thread['title'])}** `{short_key(thread['key'])}`",
             _activity(thread), _git(thread), _plural(n, "session")]
    recap = ((thread.get("resume") or {}).get("lastRecap") or "")[:RECAP_PREVIEW]
    if recap:
        parts.append(_cell(recap))
    return "- " + " | ".join(parts)


def _project_line(project, at_risk_threads):
    git = project.get("git")
    main = f"main worktree: {_risk_text(git)}" if git else "no git"
    return "- " + " | ".join([f"**{_cell(project['name'])}** `{project['key'].split(':', 1)[0]}`",
                              main, _plural(at_risk_threads, "at-risk thread"),
                              _activity(project)])


def _projects_at_risk(ledger):
    at_risk_counts = {}
    for t in ledger["threads"]:
        if t["effectiveState"] == "at-risk":
            at_risk_counts[t.get("projectId")] = at_risk_counts.get(t.get("projectId"), 0) + 1
    lines = ["", "## Projects at risk", ""]
    risky = [p for p in ledger.get("projects") or [] if p.get("atRisk")]
    if not risky:
        return lines + ["- none"]
    return lines + [_project_line(p, at_risk_counts.get(p["id"], 0)) for p in risky]


def _state_section(state, threads, project_names):
    lines = ["", f"## {state}", ""]
    if state != "at-risk":
        return lines + [_line(t, project_names) for t in threads]
    recent = [t for t in threads if t.get("recency") == "recent"]
    older = [t for t in threads if t.get("recency") != "recent"]
    if recent:
        lines += ["### recent", ""] + [_line(t, project_names) for t in recent] + [""]
    if older:
        lines += [f"### older than {RECENT_DAYS} days", ""] + \
            [_line(t, project_names) for t in older] + [""]
    return lines[:-1] if lines[-1] == "" else lines


def render_ledger_markdown(ledger):
    stats = ledger["stats"]
    project_names = {p["id"]: p["name"] for p in ledger.get("projects") or []}
    lines = ["# Work ledger", "",
             f"Generated {ledger['generatedAt']}. Projects: {stats.get('projects', 0)}. "
             f"Threads: {stats['threads']} "
             f"({', '.join(f'{k} {v}' for k, v in stats['kinds'].items())}).",
             "Effective state = override state, else suggested state."]
    lines += _projects_at_risk(ledger)
    if ledger.get("warnings"):
        lines += ["", "## Warnings", ""] + [f"- {_cell(w)}" for w in ledger["warnings"]]
    by_state = {}
    for thread in ledger["threads"]:
        by_state.setdefault(thread["effectiveState"], []).append(thread)
    for state in [s for s in STATE_ORDER if s in by_state] + \
            sorted(s for s in by_state if s not in STATE_ORDER):
        lines += _state_section(state, by_state[state], project_names)
    return "\n".join(lines) + "\n"


def write_ledger(ledger, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, JSON_NAME)
    md_path = os.path.join(out_dir, MD_NAME)
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(ledger, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_ledger_markdown(ledger))
    return json_path, md_path
