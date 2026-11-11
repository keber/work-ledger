"""Synthetic ledger (schemaVersion 2) and digest snapshot dicts for the weekly digest."""

from datetime import datetime, timezone

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
LEDGER_AT = "2026-11-06T08:55:00+00:00"


def git(risk="unpushed", not_on_remote=0, repo="C:/r/app", branch="feat/x", worktree=None,
        found=True):
    return {"repo": repo, "branch": branch, "worktreePath": worktree, "risk": risk,
            "notOnRemote": not_on_remote, "dirty": None, "merged": False, "found": found}


def thread(tid, state="open", project="p-app", title=None, days=1, recency=None, git=None,
           override=None, lead=None, recap=None, ask=None, scope=None):
    """Thread record with only the fields the digest reads; state is the effective state."""
    return {"id": tid, "key": f"dir:C:/w/{tid}", "kind": "git" if git else "dir",
            "origin": "sessions", "projectId": project, "title": title or f"Thread {tid}",
            "sessions": [lead] if lead else [], "sessionCount": 1 if lead else 0,
            "lead": lead, "resume": {"lastRecap": recap, "lastAsk": ask, "lastPrompt": None},
            "daysIdle": days,
            "recency": recency or ("recent" if days is not None and days < 30 else "old"),
            "gitScope": scope or ("thread" if git else None), "git": git,
            "suggestedState": state if override is None else "open",
            "state": override, "effectiveState": override or state}


def project(pid, name, risk="main", not_on_remote=0, path=None, branch="main"):
    path = path or f"C:/r/{name}"
    git = None
    if risk is not None:
        git = {"defaultBranch": branch, "branch": branch, "worktreePath": path, "risk": risk,
               "notOnRemote": not_on_remote, "dirty": None, "lastCommit": None}
    return {"id": pid, "key": f"repo:{path}", "kind": "repo" if git else "dir", "name": name,
            "path": path, "git": git, "atRisk": False}


def ledger(threads=(), projects=None, generated_at=LEDGER_AT, version=2):
    projects = [project("p-app", "app")] if projects is None else list(projects)
    return {"schemaVersion": version, "generatedAt": generated_at, "warnings": [],
            "stats": {}, "projects": projects, "threads": list(threads)}


def previous(snapshot, generated_at="2026-10-30T09:00:00+00:00"):
    return {"schemaVersion": 1, "generatedAt": generated_at,
            "ledgerGeneratedAt": "2026-10-30T08:55:00+00:00",
            "path": "C:/o/digest/2026-10-30.md", "counts": {}, "snapshot": dict(snapshot)}
