"""Synthetic inventory, sessions and overrides dicts for the thread builder."""

from datetime import datetime, timezone

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
NO_ACTIONS = {a: {"count": 0, "lastAt": None} for a in ("commit", "push", "merge", "pr-create")}
CLEAN = {"staged": 0, "unstaged": 0, "untracked": 0, "ignoredUntracked": 0}


def session(sid, last_at="2026-11-03T10:00:00Z", anchor=None, cwd="C:/scratch", first_at=None,
            branch=None, title=None, recap=None, ask=None, prompt=None, fork=None, actions=None,
            relocated=None):
    return {"sessionId": sid, "transcriptPath": f"/p/{sid}.jsonl", "projectDir": "p",
            "title": title, "titleSource": "ai-title" if title else None,
            "firstAt": first_at or last_at, "lastAt": last_at,
            "userMessages": 1, "assistantMessages": 1, "subagentTranscripts": 0,
            "cwds": [{"path": cwd, "count": 3}] if cwd else [], "relocatedCwd": relocated,
            "gitBranches": [{"name": branch, "count": 3}] if branch else [],
            "detachedOrNoBranchCount": 0, "writes": [],
            "gitActions": actions or {k: dict(v) for k, v in NO_ACTIONS.items()},
            "closure": {"lastRecap": recap, "lastAsk": ask, "sessionSummarySaved": False,
                        "endedWithQuestion": False},
            "lastPrompt": prompt, "malformedLines": 0,
            "writeAnchor": {"path": anchor, "share": 1.0} if anchor else None, "fork": fork}


def fork(family, members, shared, parent=None):
    return {"familyId": family, "members": members, "sharedMessages": shared, "parent": parent,
            "divergedAt": None}


def wt(path, branch="main", risk="main", is_main=False, detached=False, **extra):
    item = {"path": path, "branch": None if detached else branch, "head": "abc123",
            "detached": detached, "exists": True, "locked": False, "prunable": False,
            "isMain": is_main, "dirty": dict(CLEAN), "upstream": None, "upstreamGone": False,
            "ahead": None, "behind": None, "notOnRemote": 0, "merged": False,
            "lastCommit": {"date": "2026-10-01T10:00:00+00:00", "subject": "s", "isOwn": True},
            "error": None, "risk": risk}
    item.update(extra)
    return item


def br(name, risk="safe", **extra):
    item = {"name": name, "upstream": None, "upstreamGone": False, "ahead": None, "behind": None,
            "notOnRemote": 0, "merged": True,
            "lastCommit": {"date": "2026-09-01T10:00:00+00:00", "subject": "x", "isOwn": True},
            "error": None, "risk": risk}
    item.update(extra)
    return item


def repo(path, worktrees=(), branches=()):
    return {"path": path, "commonDir": path + "/.git", "defaultBranch": "main",
            "hasRemotes": True, "lastFetch": None, "error": None, "risk": "main",
            "worktrees": list(worktrees), "branches": list(branches)}


def inventory(*repos, generated_at="2026-11-04T11:00:00+00:00"):
    return {"schemaVersion": 2, "generatedAt": generated_at, "roots": ["C:/r"],
            "ignoreUntracked": [], "summary": {}, "repos": list(repos)}


def sessions_report(*sessions, version=3, generated_at="2026-11-04T11:30:00+00:00"):
    return {"schemaVersion": version, "generatedAt": generated_at, "sourceRoot": "/src",
            "stats": {}, "sessions": list(sessions)}


def overrides(threads=None, merge=None):
    return {"schemaVersion": 1, "threads": threads or {}, "merge": merge or []}
