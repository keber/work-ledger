"""Join the git inventory and the session facts into projects and work threads. Pure."""

from collections import defaultdict
from datetime import datetime, timezone

from .sessions_parse import GIT_ACTIONS, parse_timestamp
from .threads_identity import (inventory_items, is_project_scope, last_segment, project_id,
                               project_key, resolve_session, split_git_key, thread_id,
                               worktree_index)
from .threads_overrides import apply_merges, override_states, parse_overrides
from .threads_state import (AT_RISK, STATE_ORDER, days_idle, effective_state, recency,
                            suggest_state)

SCHEMA_VERSION = 2
DOMAIN = "work"
KINDS = ("git", "dir", "session")
TITLE_SEPARATOR = " · "


def _when(value):
    when = parse_timestamp(value)
    return when.timestamp() if when else None


def _recency(session):
    when = _when(session.get("lastAt"))
    return (when is None, -(when or 0), session["sessionId"])


def group_sessions(inventory, sessions):
    """{thread id: group} from sessions, plus inventory-only groups for unclaimed risky items.

    Each group carries its project as (project key, project kind). Main worktrees never
    become inventory-only threads: their risk belongs to the project.
    """
    index = worktree_index(inventory)
    groups = {}
    for session in sessions:
        key, kind = resolve_session(session, index)
        group = groups.setdefault(thread_id(key), {
            "key": key, "kind": kind, "origin": "sessions", "sessions": [],
            "project": project_key(session, key, kind)})
        group["sessions"].append(session)
    for key, repo_path, _, _, item in inventory_items(inventory):
        tid = thread_id(key)
        if item.get("isMain") or item.get("risk") not in AT_RISK or tid in groups:
            continue
        groups[tid] = {"key": key, "kind": "git", "origin": "inventory", "sessions": [],
                       "project": (f"repo:{repo_path}", "repo")}
    return groups


def git_facts_index(inventory):
    """{key: git facts} for every worktree and branch in the inventory."""
    facts = {}
    for key, repo_path, branch, worktree_path, item in inventory_items(inventory):
        facts[key] = ({"repo": repo_path, "branch": branch, "worktreePath": worktree_path,
                       "risk": item.get("risk"), "notOnRemote": item.get("notOnRemote"),
                       "dirty": item.get("dirty"), "merged": item.get("merged"), "found": True},
                      item)
    return facts


def _git(key, facts_index):
    if key in facts_index:
        return facts_index[key]
    repo_path, branch, worktree_path = split_git_key(key)
    return ({"repo": repo_path, "branch": branch, "worktreePath": worktree_path, "risk": None,
             "notOnRemote": None, "dirty": None, "merged": None, "found": False}, None)


def _sum_actions(sessions):
    total = {a: {"count": 0, "lastAt": None} for a in GIT_ACTIONS}
    for s in sessions:
        for action, entry in (s.get("gitActions") or {}).items():
            if action not in total or not isinstance(entry, dict):
                continue
            total[action]["count"] += entry.get("count") or 0
            last = entry.get("lastAt")
            if last and (total[action]["lastAt"] is None
                         or (_when(last) or 0) > (_when(total[action]["lastAt"]) or 0)):
                total[action]["lastAt"] = last
    return total


def _extreme(values, pick):
    dated = [(_when(v), v) for v in values if _when(v) is not None]
    return pick(dated)[1] if dated else None


def _title(group, sessions, git):
    if group["origin"] == "inventory":
        repo_path, branch, worktree_path = split_git_key(group["key"])
        return last_segment(repo_path) + TITLE_SEPARATOR + (branch or last_segment(worktree_path))
    titled = next((s["title"] for s in sessions if s.get("title")), None)
    if titled:
        return titled
    branch = (git or {}).get("branch")
    if not branch and group["kind"] == "git":
        branch = split_git_key(group["key"])[1]
    if branch:
        return branch
    rest = group["key"].split(":", 1)[1]
    if group["kind"] == "git":
        rest = split_git_key(group["key"])[2] or rest
    return last_segment(rest)


def _git_scope(group):
    if group["kind"] != "git":
        return None
    return "project" if is_project_scope(group["key"]) else "thread"


def build_thread(tid, group, facts_index, now):
    """Thread record without related, state and effective state."""
    sessions = sorted(group["sessions"], key=_recency)
    lead = sessions[0] if sessions else None
    scope = _git_scope(group)
    git, item = _git(group["key"], facts_index) if scope == "thread" else (None, None)
    if sessions:
        first_at = _extreme([s.get("firstAt") for s in sessions], min)
        last_at = _extreme([s.get("lastAt") for s in sessions], max)
    else:
        # Inventory-only: the last commit is the only activity known.
        first_at, last_at = None, ((item or {}).get("lastCommit") or {}).get("date")
    resume = None
    if lead:
        closure = lead.get("closure") or {}
        resume = {"lastRecap": closure.get("lastRecap"), "lastAsk": closure.get("lastAsk"),
                  "lastPrompt": lead.get("lastPrompt")}
    idle = days_idle(last_at, now)
    # Project-scope threads have git None: the shared trunk's risk is not theirs.
    suggested, reason = suggest_state(group["kind"], git, resume, idle)
    return {
        "id": tid, "key": group["key"], "kind": group["kind"], "origin": group["origin"],
        "projectId": project_id(group["project"][0]),
        "title": _title(group, sessions, git), "domain": DOMAIN,
        "sessions": [s["sessionId"] for s in sessions], "sessionCount": len(sessions),
        "lead": lead["sessionId"] if lead else None, "resume": resume,
        "firstAt": first_at, "lastAt": last_at, "daysIdle": idle, "recency": recency(idle),
        "gitScope": scope, "git": git, "gitActions": _sum_actions(sessions), "related": [],
        "suggestedState": suggested, "suggestedReason": reason,
    }


def related_threads(groups):
    """{thread id: [related]} linking threads whose sessions share a fork family."""
    families = defaultdict(lambda: defaultdict(int))  # family -> thread id -> max shared
    for tid, group in groups.items():
        for s in group["sessions"]:
            fork = s.get("fork")
            if fork and fork.get("familyId"):
                shared = families[fork["familyId"]]
                shared[tid] = max(shared[tid], fork.get("sharedMessages") or 0)
    related = defaultdict(dict)
    for members in families.values():
        top = max(members.values()) if members else 0
        for tid in members:
            for other in members:
                if other != tid:
                    related[tid][other] = max(related[tid].get(other, 0), top)
    return {tid: [{"id": other, "sharedMessages": n, "reason": "fork-family"}
                  for other, n in sorted(links.items())]
            for tid, links in related.items()}


def _main_worktree(repo):
    worktrees = repo.get("worktrees") or []
    return next((w for w in worktrees if w.get("isMain")), None)


def project_git(repo):
    """Main worktree state of a repo project. Only bounded fields; no author emails."""
    main = _main_worktree(repo) or {}
    commit = main.get("lastCommit")
    if isinstance(commit, dict):
        commit = {"date": commit.get("date"), "subject": commit.get("subject"),
                  "isOwn": commit.get("isOwn")}
    return {"defaultBranch": repo.get("defaultBranch"), "branch": main.get("branch"),
            "worktreePath": main.get("path"), "risk": main.get("risk"),
            "notOnRemote": main.get("notOnRemote"), "dirty": main.get("dirty"),
            "lastCommit": commit if isinstance(commit, dict) else None}


def build_projects(project_keys, threads, inventory, now):
    """Project records from {project key: kind} and built threads, sorted at-risk first.

    Repos whose main worktree is at risk become projects even with no threads.
    """
    repos = {r.get("path"): r for r in inventory.get("repos") or []}
    keys = dict(project_keys)
    for path, repo in repos.items():
        if (_main_worktree(repo) or {}).get("risk") in AT_RISK:
            keys.setdefault(f"repo:{path}", "repo")
    by_project = defaultdict(list)
    for t in threads:
        by_project[t["projectId"]].append(t)
    projects = []
    for key, kind in keys.items():
        pid = project_id(key)
        members = by_project.get(pid, [])
        path = key.split(":", 1)[1]
        git = project_git(repos.get(path) or {"defaultBranch": None}) if kind == "repo" else None
        if members:
            last_at = _extreme([t["lastAt"] for t in members], max)
        else:
            last_at = ((git or {}).get("lastCommit") or {}).get("date")
        idle = days_idle(last_at, now)
        at_risk = ((git or {}).get("risk") in AT_RISK
                   or any(t["effectiveState"] == "at-risk" for t in members))
        projects.append({
            "id": pid, "key": key, "kind": kind,
            "name": last_segment(path) or "(no path)", "path": path or None, "domain": DOMAIN,
            "git": git, "threadIds": [t["id"] for t in members], "threadCount": len(members),
            "sessionCount": sum(t["sessionCount"] for t in members),
            "lastAt": last_at, "daysIdle": idle, "recency": recency(idle), "atRisk": at_risk,
        })
    projects.sort(key=_project_sort_key)
    return projects


def _project_sort_key(project):
    when = _when(project["lastAt"])
    return (not project["atRisk"], when is None, -(when or 0), project["key"])


def _sort_key(thread):
    state = thread["effectiveState"]
    when = _when(thread["lastAt"])
    return (STATE_ORDER.index(state) if state in STATE_ORDER else len(STATE_ORDER),
            when is None, -(when or 0), thread["key"])


def _input(path, data):
    return {"path": path, "generatedAt": (data or {}).get("generatedAt")}


def build_ledger(inventory, sessions_report, overrides=None, generated_at=None, inputs=None):
    """Ledger dict. Merges are applied before states; unknown override ids become warnings."""
    now = generated_at or datetime.now(timezone.utc)
    inputs = inputs or {}
    parsed = parse_overrides(overrides)
    groups = group_sessions(inventory, sessions_report.get("sessions") or [])
    groups, warnings = apply_merges(groups, parsed["merge"])
    states, state_warnings = override_states(groups, parsed)
    warnings += state_warnings

    facts_index = git_facts_index(inventory)
    related = related_threads(groups)
    threads = []
    for tid, group in groups.items():
        thread = build_thread(tid, group, facts_index, now)
        thread["related"] = related.get(tid, [])
        state, note = states.get(tid, (None, None))
        thread["state"] = state
        thread["note"] = note
        thread["effectiveState"] = effective_state(state, thread["suggestedState"])
        threads.append(thread)
    threads.sort(key=_sort_key)
    projects = build_projects({g["project"][0]: g["project"][1] for g in groups.values()},
                              threads, inventory, now)

    kinds = {k: 0 for k in KINDS}
    effective = {s: 0 for s in STATE_ORDER}
    for t in threads:
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
        effective[t["effectiveState"]] = effective.get(t["effectiveState"], 0) + 1
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "inputs": {"inventory": _input(inputs.get("inventory"), inventory),
                   "sessions": _input(inputs.get("sessions"), sessions_report),
                   "overrides": {"path": inputs.get("overrides"), "present": overrides is not None}},
        "warnings": warnings,
        "stats": {"projects": len(projects), "threads": len(threads), "kinds": kinds,
                  "effectiveStates": effective},
        "projects": projects,
        "threads": threads,
    }
