"""Collect read-only git facts for a repo, its worktrees and its local branches."""

import os
from datetime import datetime, timezone

from .classify import classify, worst
from .discover import to_posix
from .gitcmd import GitError, run_git

HEADS = "refs/heads/"
REMOTES = "refs/remotes/"

# Untracked paths under these prefixes (tool folders) are counted apart, in
# dirty.ignoredUntracked, and do not make an item "untracked".
DEFAULT_IGNORE_UNTRACKED = (".atl/", ".tmp/")


class CollectError(Exception):
    pass


def _git(path, *args, ok=(0,)):
    result = run_git(path, *args)
    if result.code not in ok:
        detail = result.stderr.strip() or f"exit {result.code}"
        raise CollectError(f"git {args[0]}: {detail}")
    return result


def _ref_exists(git_dir, ref):
    return _git(git_dir, "rev-parse", "--verify", "--quiet", ref, ok=(0, 1)).code == 0


def default_branch(git_dir):
    """Return (display name, full ref) of the default branch, or (None, None)."""
    result = _git(git_dir, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", ok=(0, 1, 128))
    target = result.stdout.strip()
    if result.code == 0 and target and _ref_exists(git_dir, target):
        return target[len(REMOTES):], target
    for name in ("main", "master"):
        for ref in (HEADS + name, REMOTES + "origin/" + name):
            if _ref_exists(git_dir, ref):
                return ref.removeprefix(HEADS).removeprefix(REMOTES), ref
    return None, None


def _last_fetch(common_dir):
    path = os.path.join(common_dir, "FETCH_HEAD")
    if not os.path.isfile(path):
        return None
    return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()


def parse_worktree_list(raw):
    """Parse `git worktree list --porcelain -z` output into dicts."""
    entries, current = [], None
    for field in raw.split("\0"):
        if not field:
            if current is not None:
                entries.append(current)
                current = None
            continue
        key, _, value = field.partition(" ")
        if key == "worktree":
            current = {"path": value, "head": None, "branch": None, "detached": False,
                       "bare": False, "locked": False, "prunable": False}
        elif current is None:
            continue
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix(HEADS)
        elif key in ("detached", "bare", "locked", "prunable"):
            current[key] = True
    if current is not None:
        entries.append(current)
    return entries


def _is_ignored(path, prefixes):
    path = path.replace("\\", "/")
    return any(path.startswith(prefix) for prefix in prefixes)


def parse_status(raw, ignore_prefixes=()):
    """Count staged, unstaged, untracked and ignored-untracked entries.

    `raw` is `status --porcelain=v1 -z` output. Untracked paths starting with
    one of `ignore_prefixes` (forward slashes; "dir/" also matches the "dir/"
    entry git prints for a wholly untracked folder) count as ignoredUntracked.
    """
    prefixes = tuple(p.replace("\\", "/") for p in ignore_prefixes if p)
    counts = {"staged": 0, "unstaged": 0, "untracked": 0, "ignoredUntracked": 0}
    fields = raw.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 3:
            continue
        x, y = entry[0], entry[1]
        if x == "?" and y == "?":
            key = "ignoredUntracked" if _is_ignored(entry[3:], prefixes) else "untracked"
            counts[key] += 1
            continue
        if x == "!":
            continue
        if x not in " ?":
            counts["staged"] += 1
        if y not in " ?":
            counts["unstaged"] += 1
        if x in "RC":
            i += 1  # rename/copy carries the source path as an extra field
    return counts


def user_email(git_dir):
    """Effective `user.email` for the repo, lowercased, or None when unset."""
    result = _git(git_dir, "config", "--get", "user.email", ok=(0, 1))
    email = result.stdout.strip()
    return email.lower() if result.code == 0 and email else None


def _is_own(author_email, own_email):
    """Compare emails without ever storing the author's address."""
    if own_email is None:
        return None
    return author_email.strip().strip("<>").strip().lower() == own_email


def _branch_refs(git_dir, own_email):
    """Map local branch name -> upstream full ref (or None) and last commit."""
    fmt = ("%(refname)%00%(upstream)%00%(committerdate:iso-strict)%00"
           "%(authoremail)%00%(subject)")
    out = _git(git_dir, "for-each-ref", f"--format={fmt}", "refs/heads").stdout
    refs = {}
    for line in out.splitlines():
        parts = line.split("\0")
        if len(parts) != 5:
            continue
        refname, upstream, date, author, subject = parts
        refs[refname.removeprefix(HEADS)] = {
            "upstreamRef": upstream or None,
            "lastCommit": {"date": date or None, "subject": subject,
                           "isOwn": _is_own(author, own_email)},
        }
    return refs


def _upstream_facts(git_dir, ref, upstream_ref):
    facts = {"upstream": None, "upstreamGone": False, "ahead": None, "behind": None}
    # Only remote-tracking upstreams count as "pushed".
    if not upstream_ref or not upstream_ref.startswith(REMOTES):
        return facts
    facts["upstream"] = upstream_ref[len(REMOTES):]
    if not _ref_exists(git_dir, upstream_ref):
        facts["upstreamGone"] = True
        return facts
    out = _git(git_dir, "rev-list", "--left-right", "--count", f"{ref}...{upstream_ref}").stdout
    ahead, behind = out.split()
    facts["ahead"], facts["behind"] = int(ahead), int(behind)
    return facts


def _merged(git_dir, ref, default_ref):
    if default_ref is None:
        return None
    code = _git(git_dir, "merge-base", "--is-ancestor", ref, default_ref, ok=(0, 1)).code
    return code == 0


def _not_on_remote(git_dir, ref):
    """Commits reachable from ref and from no remote-tracking ref (all, if none)."""
    out = _git(git_dir, "rev-list", "--count", ref, "--not", "--remotes").stdout
    return int(out.strip())


def _last_commit(git_dir, ref, own_email):
    out = _git(git_dir, "log", "-1", "--format=%cI%x00%ae%x00%s", ref).stdout.rstrip("\n")
    date, _, rest = out.partition("\0")
    author, _, subject = rest.partition("\0")
    return {"date": date or None, "subject": subject, "isOwn": _is_own(author, own_email)}


def _ref_facts(git_dir, ref, upstream_ref, default_ref):
    facts = _upstream_facts(git_dir, ref, upstream_ref)
    facts["notOnRemote"] = _not_on_remote(git_dir, ref)
    facts["merged"] = _merged(git_dir, ref, default_ref)
    return facts


def _empty_ref_facts():
    return {"upstream": None, "upstreamGone": False, "ahead": None, "behind": None,
            "notOnRemote": None, "merged": None, "lastCommit": None}


def _collect_worktree(git_dir, entry, is_main, branch_refs, default_ref, ctx):
    path = to_posix(entry["path"])
    item = {
        "path": path,
        "branch": entry["branch"],
        "head": entry["head"],
        "detached": entry["detached"],
        "exists": os.path.isdir(entry["path"]),
        "locked": entry["locked"],
        "prunable": entry["prunable"],
        "isMain": is_main,
        "dirty": None,
        **_empty_ref_facts(),
        "error": None,
    }
    try:
        if item["exists"]:
            raw = _git(entry["path"], "status", "--porcelain=v1", "-z").stdout
            item["dirty"] = parse_status(raw, ctx["ignore"])
        if entry["branch"]:
            ref = HEADS + entry["branch"]
            info = branch_refs.get(entry["branch"], {})
            upstream_ref = info.get("upstreamRef")
        else:
            ref, upstream_ref = entry["head"], None
        if ref and _ref_exists(git_dir, ref):
            item.update(_ref_facts(git_dir, ref, upstream_ref, default_ref))
            item["lastCommit"] = _last_commit(git_dir, ref, ctx["email"])
        elif item["exists"]:
            raise CollectError(f"cannot resolve {ref or 'HEAD'} (unborn branch?)")
    except (CollectError, GitError, ValueError) as exc:
        item["error"] = str(exc)
    item["risk"] = classify(item)
    return item


def _collect_branch(git_dir, name, info, default_ref):
    item = {"name": name, **_empty_ref_facts(), "lastCommit": info["lastCommit"], "error": None}
    try:
        item.update(_ref_facts(git_dir, HEADS + name, info["upstreamRef"], default_ref))
    except (CollectError, GitError, ValueError) as exc:
        item["error"] = str(exc)
    item["risk"] = classify(item)
    return item


def error_repo(ref, message):
    return {
        "path": ref.main_path,
        "commonDir": ref.common_dir,
        "defaultBranch": None,
        "hasRemotes": None,
        "lastFetch": None,
        "error": message,
        "risk": "unknown",
        "worktrees": [],
        "branches": [],
    }


def collect_repo(ref, ignore_untracked=DEFAULT_IGNORE_UNTRACKED):
    """Collect facts for one discovered repo. Never raises for git failures."""
    if ref.error or not ref.common_dir:
        return error_repo(ref, ref.error or "git common dir not found")
    git_dir = ref.common_dir
    try:
        default_name, default_ref = default_branch(git_dir)
        has_remotes = bool(_git(git_dir, "remote").stdout.strip())
        raw = _git(git_dir, "worktree", "list", "--porcelain", "-z").stdout
        own_email = user_email(git_dir)
        branch_refs = _branch_refs(git_dir, own_email)
    except (CollectError, GitError, OSError) as exc:
        return error_repo(ref, str(exc))

    ctx = {"ignore": tuple(ignore_untracked), "email": own_email}
    entries = parse_worktree_list(raw)
    worktrees = []
    for index, entry in enumerate(entries):
        if entry["bare"]:
            continue
        worktrees.append(_collect_worktree(git_dir, entry, index == 0, branch_refs, default_ref, ctx))

    checked_out = {e["branch"] for e in entries if e["branch"]}
    branches = [
        _collect_branch(git_dir, name, info, default_ref)
        for name, info in sorted(branch_refs.items())
        if name not in checked_out
    ]

    risks = [w["risk"] for w in worktrees] + [b["risk"] for b in branches]
    return {
        "path": ref.main_path,
        "commonDir": git_dir,
        "defaultBranch": default_name,
        "hasRemotes": has_remotes,
        "lastFetch": _last_fetch(git_dir),
        "error": None,
        "risk": worst(risks) or "unknown",
        "worktrees": worktrees,
        "branches": branches,
    }
