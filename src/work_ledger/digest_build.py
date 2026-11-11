"""Weekly pending-work digest computed from the ledger and the previous snapshot. Pure."""

from collections import Counter

from .threads_state import DONE_IDLE_DAYS, STATE_ORDER

RECAP_PREVIEW = 160
COLD_DAYS = DONE_IDLE_DAYS
COLD_STATES = ("open", "active")
# Override states the user already decided on: never listed as pending work.
EXCLUDED_OVERRIDES = ("done", "discarded", "paused")


def _listed(thread):
    return thread.get("state") not in EXCLUDED_OVERRIDES


def _commits(value):
    return value if isinstance(value, int) and value > 0 else 0


def _at_risk_recent(threads, names):
    return [{"id": t["id"], "title": t.get("title"), "project": names.get(t.get("projectId")),
             "daysIdle": t.get("daysIdle"), "risk": (t.get("git") or {}).get("risk"),
             "notOnRemote": _commits((t.get("git") or {}).get("notOnRemote"))}
            for t in threads
            if _listed(t) and t.get("effectiveState") == "at-risk"
            and t.get("recency") == "recent"]


def _no_backup(threads, projects, names):
    """Unbacked commits on main worktrees and threads. Overrides do not hide them.

    A thread on the same repo and branch as a counted main worktree holds the same
    commits, so it is not counted again.
    """
    listed_projects, counted = [], set()
    for p in projects:
        git = p.get("git") or {}
        n = _commits(git.get("notOnRemote"))
        if n:
            listed_projects.append({"id": p["id"], "name": p.get("name"),
                                    "risk": git.get("risk"), "notOnRemote": n})
            counted.add((p.get("path"), git.get("branch")))
    listed_threads = []
    for t in threads:
        git = t.get("git") or {}
        n = _commits(git.get("notOnRemote"))
        if n and (git.get("repo"), git.get("branch")) not in counted:
            listed_threads.append({"id": t["id"], "title": t.get("title"),
                                   "project": names.get(t.get("projectId")), "notOnRemote": n})
    total = sum(p["notOnRemote"] for p in listed_projects) + \
        sum(t["notOnRemote"] for t in listed_threads)
    return {"projects": listed_projects, "threads": listed_threads, "total": total}


def _going_cold(threads, names):
    cold = []
    for t in threads:
        idle = t.get("daysIdle")
        if not (_listed(t) and t.get("effectiveState") in COLD_STATES
                and idle is not None and idle >= COLD_DAYS):
            continue
        resume = t.get("resume") or {}
        lead = t.get("lead")
        cold.append({"id": t["id"], "title": t.get("title"),
                     "project": names.get(t.get("projectId")),
                     "state": t["effectiveState"], "daysIdle": idle,
                     "recap": (resume.get("lastRecap") or "")[:RECAP_PREVIEW] or None,
                     "ask": resume.get("lastAsk") or None,
                     "resume": f"claude --resume {lead}" if lead else None})
    return cold


def _went_stale(threads, names, before):
    if before is None:
        return None
    return [{"id": t["id"], "title": t.get("title"), "project": names.get(t.get("projectId"))}
            for t in threads
            if _listed(t) and t.get("effectiveState") == "stale"
            and before.get(t["id"]) != "stale"]


def _older_at_risk(threads, names):
    counts = Counter(t.get("projectId") for t in threads
                     if _listed(t) and t.get("effectiveState") == "at-risk"
                     and t.get("recency") != "recent")
    return [{"projectId": pid, "project": names.get(pid), "count": n}
            for pid, n in counts.items()]


def _states(now_counts, before):
    before_counts = Counter(before.values()) if before is not None else Counter()
    present = set(now_counts) | set(before_counts)
    order = [s for s in STATE_ORDER if s in present] + \
        sorted(s for s in present if s not in STATE_ORDER)
    return [{"state": s, "count": now_counts.get(s, 0),
             "change": None if before is None else now_counts.get(s, 0) - before_counts.get(s, 0)}
            for s in order]


def _previous_snapshot(previous):
    snapshot = (previous or {}).get("snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else None


def build_digest(ledger, previous=None):
    """Digest dict from a schemaVersion 2 ledger and the previous latest.json (or None)."""
    threads = ledger.get("threads") or []
    projects = ledger.get("projects") or []
    names = {p["id"]: p.get("name") for p in projects}
    before = _previous_snapshot(previous)

    at_risk = _at_risk_recent(threads, names)
    no_backup = _no_backup(threads, projects, names)
    cold = _going_cold(threads, names)
    stale = _went_stale(threads, names, before)
    snapshot = {t["id"]: t.get("effectiveState") for t in threads}
    now_counts = Counter(snapshot.values())
    return {
        "ledgerGeneratedAt": ledger.get("generatedAt"),
        "previousGeneratedAt": (previous or {}).get("generatedAt") if before is not None else None,
        "atRiskRecent": at_risk,
        "noBackup": no_backup,
        "goingCold": cold,
        "wentStale": stale,
        "olderAtRisk": _older_at_risk(threads, names),
        "states": _states(now_counts, before),
        "counts": {"atRiskRecent": len(at_risk), "goingCold": len(cold),
                   "notOnRemoteCommits": no_backup["total"],
                   "wentStale": None if stale is None else len(stale),
                   "effectiveStates": {s["state"]: s["count"]
                                       for s in _states(now_counts, None) if s["count"]}},
        "snapshot": snapshot,
    }
