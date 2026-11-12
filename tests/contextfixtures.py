"""Synthetic ledger, sessions index and live git dicts for the `context` command."""

from datetime import datetime, timezone

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
LEDGER_AT = "2026-11-11T09:00:00+00:00"


def thread(tid, project="p-shop", title=None, last_at="2026-11-10T10:00:00Z", first_at=None,
           sessions=None, state="open", recap=None, ask=None, prompt=None, git=None,
           scope=None, days=None):
    sessions = [f"s-{tid}"] if sessions is None else list(sessions)
    return {"id": tid, "key": f"dir:C:/w/{tid}", "kind": "git" if git else "dir",
            "origin": "sessions" if sessions else "inventory", "projectId": project,
            "title": title or f"Thread {tid}", "sessions": sessions,
            "sessionCount": len(sessions), "lead": sessions[0] if sessions else None,
            "resume": ({"lastRecap": recap, "lastAsk": ask, "lastPrompt": prompt}
                       if sessions else None),
            "firstAt": first_at or last_at, "lastAt": last_at, "daysIdle": days,
            "gitScope": scope or ("thread" if git else None), "git": git,
            "suggestedState": state, "state": None, "effectiveState": state, "note": None}


def tgit(branch="feat/x", risk="unpushed", not_on_remote=2, dirty=None, merged=False):
    return {"repo": "C:/r/shop", "branch": branch, "worktreePath": None, "risk": risk,
            "notOnRemote": not_on_remote, "dirty": dirty, "merged": merged, "found": True}


def project(pid, name, path=None, last_at="2026-11-10T10:00:00Z", at_risk=False, kind="repo",
            threads=()):
    path = path or f"C:/r/{name}"
    return {"id": pid, "key": f"{kind}:{path}", "kind": kind, "name": name, "path": path,
            "git": None, "threadIds": list(threads), "threadCount": len(threads),
            "sessionCount": 0, "lastAt": last_at, "daysIdle": None, "atRisk": at_risk}


def ledger(projects, threads, generated_at=LEDGER_AT, sessions_path=None):
    return {"schemaVersion": 2, "generatedAt": generated_at,
            "inputs": {"sessions": {"path": sessions_path, "generatedAt": None}},
            "warnings": [], "stats": {}, "projects": list(projects), "threads": list(threads)}


def git_ok(**extra):
    state = {"path": "C:/r/shop", "status": "ok", "error": None, "branch": "main",
             "defaultBranch": "origin/main",
             "dirty": {"staged": 1, "unstaged": 2, "untracked": 0, "ignoredUntracked": 0},
             "notOnRemote": 3, "headNotOnRemote": 1,
             "recentCommits": [{"date": "2026-11-10T09:00:00+00:00", "subject": "fix: totals"}],
             "unmergedBranches": [{"name": "feat/x", "ahead": 2, "current": False,
                                   "lastCommit": {"date": "2026-11-09T09:00:00+00:00",
                                                  "subject": "wip: export"}}],
             "moreUnmergedBranches": 0}
    state.update(extra)
    return state


def excerpt(*entries, omitted=0, gap=None, error=None):
    return {"entries": [{"at": at, "role": role, "text": text} for at, role, text in entries],
            "total": len(entries) + omitted, "omitted": omitted, "gapAfter": gap,
            "sharedWith": {}, "keys": [(at, role, text) for at, role, text in entries],
            "error": error}


def session_info(path, first_at, last_at, entrypoint="claude-desktop", user_messages=3,
                 prompt=None, assistant_messages=3, title_source="ai-title", fork=None):
    return {"transcriptPath": path, "firstAt": first_at, "lastAt": last_at,
            "entrypoint": entrypoint, "userMessages": user_messages, "lastPrompt": prompt,
            "assistantMessages": assistant_messages, "titleSource": title_source, "fork": fork}


def note(path="C:/r/shop/HANDOFF.md", modified="2026-11-08T10:00:00+00:00", text="Next: run QA",
         truncated=False, toc=None, lines=None):
    return {"path": path, "modifiedAt": modified, "bytes": len(text),
            "lines": lines or len(text.splitlines()), "text": text, "truncated": truncated,
            "toc": toc or []}
