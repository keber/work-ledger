"""Live, read-only git state of one project folder, for `context`.

Never fetches, checks out or writes: only the commands in READ_ONLY_COMMANDS run, through
the shared runner (no shell, timeout, sanitized env, no optional locks). Remote-tracking
refs may therefore be stale. No author names or emails are read.
"""

import os

from .collect import DEFAULT_IGNORE_UNTRACKED, CollectError, default_branch, parse_status
from .gitcmd import GitError, run_git

READ_ONLY_COMMANDS = ("rev-parse", "symbolic-ref", "status", "rev-list", "log", "for-each-ref")
RECENT_COMMITS = 10
BRANCH_LIMIT = 15
BRANCH_SCAN = 50  # most recent local branches checked against the default branch
HEADS = "refs/heads/"


def _state(path, status, **extra):
    base = {"path": path, "status": status, "error": None, "branch": None,
            "defaultBranch": None, "dirty": None, "notOnRemote": None,
            "headNotOnRemote": None, "recentCommits": [], "unmergedBranches": [],
            "moreUnmergedBranches": 0}
    base.update(extra)
    return base


def _git(run, path, *args, ok=(0,)):
    result = run(path, *args)
    if result.code not in ok:
        detail = result.stderr.strip() or f"exit {result.code}"
        raise CollectError(f"git {args[0]}: {detail}")
    return result


def _count(run, path, *args):
    return int(_git(run, path, "rev-list", "--count", *args).stdout.strip() or 0)


def _recent(run, path, limit):
    out = _git(run, path, "log", f"-n{limit}", "--format=%cI%x00%s", "HEAD").stdout
    commits = []
    for line in out.splitlines():
        date, _, subject = line.partition("\0")
        commits.append({"date": date or None, "subject": subject})
    return commits


def _unmerged(run, path, default_ref, current, limit):
    """([branch], count beyond limit): local branches with commits not in the default branch."""
    if default_ref is None:
        return [], 0
    fmt = "%(refname)%00%(committerdate:iso-strict)%00%(subject)"
    out = _git(run, path, "for-each-ref", "--sort=-committerdate", f"--format={fmt}",
               "refs/heads").stdout
    found = []
    for line in out.splitlines()[:BRANCH_SCAN]:
        parts = line.split("\0")
        if len(parts) != 3 or parts[0] == default_ref:
            continue
        ref, date, subject = parts
        ahead = _count(run, path, f"{default_ref}..{ref}")
        if ahead:
            name = ref.removeprefix(HEADS)
            found.append({"name": name, "ahead": ahead, "current": name == current,
                          "lastCommit": {"date": date or None, "subject": subject}})
    return found[:limit], max(0, len(found) - limit)


def live_git(path, run=run_git, recent=RECENT_COMMITS, branch_limit=BRANCH_LIMIT):
    """State dict with `status` ok, missing, not-a-repo or error. Never raises for git."""
    if not path or not os.path.isdir(path):
        return _state(path, "missing")
    try:
        inside = run(path, "rev-parse", "--is-inside-work-tree")
        if inside.code != 0 or inside.stdout.strip() != "true":
            return _state(path, "not-a-repo")
        head = _git(run, path, "symbolic-ref", "--quiet", "--short", "HEAD", ok=(0, 1))
        branch = head.stdout.strip() if head.code == 0 else None
        dirty = parse_status(_git(run, path, "status", "--porcelain=v1", "-z").stdout,
                             DEFAULT_IGNORE_UNTRACKED)
        default_name, default_ref = default_branch(path)
        branches, more = _unmerged(run, path, default_ref, branch, branch_limit)
        return _state(path, "ok", branch=branch, defaultBranch=default_name, dirty=dirty,
                      notOnRemote=_count(run, path, "--branches", "--not", "--remotes"),
                      headNotOnRemote=_count(run, path, "HEAD", "--not", "--remotes"),
                      recentCommits=_recent(run, path, recent),
                      unmergedBranches=branches, moreUnmergedBranches=more)
    except (CollectError, GitError, ValueError, OSError) as exc:
        return _state(path, "error", error=str(exc))
