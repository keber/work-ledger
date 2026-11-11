"""Build the versioned inventory report and render it as JSON and Markdown."""

import json
import os
from datetime import datetime, timezone

from .classify import RISK_ORDER

SCHEMA_VERSION = 2
JSON_NAME = "git-inventory.json"
MD_NAME = "git-inventory.md"


def _rank(risk):
    return RISK_ORDER.index(risk) if risk in RISK_ORDER else RISK_ORDER.index("unknown")


def _items(repo):
    return repo["worktrees"] + repo["branches"]


def build_report(repos, roots, generated_at=None, ignore_untracked=()):
    generated_at = generated_at or datetime.now(timezone.utc)
    ordered = sorted(repos, key=lambda r: (_rank(r["risk"]), r["path"].lower()))
    counts = {risk: 0 for risk in RISK_ORDER}
    for repo in ordered:
        items = _items(repo)
        if repo.get("error") and not items:
            counts["unknown"] += 1
        for item in items:
            counts[item["risk"] if item["risk"] in counts else "unknown"] += 1
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at.isoformat(),
        "roots": list(roots),
        "ignoreUntracked": list(ignore_untracked),
        "summary": {"repos": len(ordered), "risks": counts},
        "repos": ordered,
    }


def _cell(value):
    if value is None:
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _sync(item):
    if item.get("upstreamGone"):
        return f"{item['upstream']} (gone)"
    if not item.get("upstream"):
        return "none"
    return f"{item['upstream']} +{item['ahead']}/-{item['behind']}"


def _dirty(item):
    d = item.get("dirty")
    if d is None:
        return "-"
    text = f"{d['staged']}/{d['unstaged']}/{d['untracked']}"
    ignored = d.get("ignoredUntracked") or 0
    return text + (f" (+{ignored} ignored)" if ignored else "")


def _not_on_remote(item):
    value = item.get("notOnRemote")
    if value is None:
        return "-"
    return str(value) if value > 0 else ""


def _others(item):
    """Tag items whose last commit is by someone else (isOwn False, not null)."""
    return " [others]" if (item.get("lastCommit") or {}).get("isOwn") is False else ""


def _commit(item):
    c = item.get("lastCommit") or {}
    date = (c.get("date") or "")[:10]
    return _cell(f"{date} {c.get('subject', '')}".strip() or None)


def render_markdown(report):
    lines = [
        "# Git inventory",
        "",
        f"Generated {report['generatedAt']} from {', '.join(report['roots']) or '-'}.",
        "Remote refs are not fetched; see last fetch per repo.",
        "`[others]`: last commit authored by someone else. "
        "Not on remote: commits on no remote-tracking ref.",
        "",
        "## Summary",
        "",
        f"Repos: {report['summary']['repos']}",
        "",
        "| risk | count |",
        "|---|---|",
    ]
    lines += [f"| {risk} | {count} |" for risk, count in report["summary"]["risks"].items()]

    for repo in report["repos"]:
        lines += ["", f"## {repo['path']}", ""]
        lines.append(
            f"Risk: **{repo['risk']}** | default branch: {_cell(repo['defaultBranch'])} | "
            f"remotes: {_cell(repo['hasRemotes'])} | last fetch: {_cell(repo['lastFetch'])}"
        )
        if repo.get("error"):
            lines += ["", f"Error: `{_cell(repo['error'])}`"]
        worktrees = sorted(repo["worktrees"], key=lambda w: _rank(w["risk"]))
        if worktrees:
            lines += ["", "| risk | worktree | branch | dirty s/u/?? | not on remote | upstream | "
                      "merged | last commit |",
                      "|---|---|---|---|---|---|---|---|"]
            for w in worktrees:
                name = w["path"] + (" (main)" if w["isMain"] else "")
                branch = w["branch"] or f"detached {(w['head'] or '')[:8]}"
                flags = "".join(f" [{f}]" for f in ("locked", "prunable") if w.get(f)) + _others(w)
                risk = w["risk"] + (f" ({_cell(w['error'])})" if w.get("error") else "")
                lines.append(f"| {risk} | {_cell(name)}{flags} | {_cell(branch)} | {_dirty(w)} | "
                             f"{_not_on_remote(w)} | {_cell(_sync(w))} | {_cell(w['merged'])} | "
                             f"{_commit(w)} |")
        branches = sorted(repo["branches"], key=lambda b: (_rank(b["risk"]), b["name"]))
        if branches:
            lines += ["", "| risk | branch (not checked out) | not on remote | upstream | merged | "
                      "last commit |",
                      "|---|---|---|---|---|---|"]
            for b in branches:
                risk = b["risk"] + (f" ({_cell(b['error'])})" if b.get("error") else "")
                lines.append(f"| {risk} | {_cell(b['name'])}{_others(b)} | {_not_on_remote(b)} | "
                             f"{_cell(_sync(b))} | {_cell(b['merged'])} | {_commit(b)} |")
    return "\n".join(lines) + "\n"


def write_reports(report, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, JSON_NAME)
    md_path = os.path.join(out_dir, MD_NAME)
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_markdown(report))
    return json_path, md_path
