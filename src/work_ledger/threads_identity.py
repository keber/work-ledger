"""Resolve sessions and inventory items to work thread and project keys. Pure, over loaded JSON."""

import hashlib
import re

from .sessions_parse import drive_path

# Suffix of default-branch thread keys: `git:<main>#<branch>~family:<id>` or `~session:<id>`.
# `~` cannot appear in a git branch name, so it never collides with a branch.
SCOPE_SEPARATOR = "~"


def thread_id(key):
    """Stable id: first 12 hex characters of SHA-256 of the key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def project_id(key):
    """Stable project id, same rule as thread ids."""
    return thread_id(key)


def _norm(path):
    """Forward slashes, Git Bash drive form converted, no trailing slash."""
    if not isinstance(path, str) or not path:
        return None
    return drive_path(path.replace("\\", "/")).rstrip("/")


def git_key(repo_path, branch, worktree_path):
    return f"git:{repo_path}#{branch}" if branch else f"git:{repo_path}@{worktree_path}"


DEFAULT_REMOTE = "origin"


def short_default_branch(repo):
    """Local name of the repo's default branch.

    The inventory records a remote-tracking name (`origin/master`) when the repo has a
    remote, else a local one (`main`). The first segment is stripped when it names one of the
    repo's remotes (`remotes`, when the inventory has it), otherwise only a leading `origin/`.
    """
    name = repo.get("defaultBranch")
    if not isinstance(name, str) or not name:
        return None
    remotes = repo.get("remotes")
    if not isinstance(remotes, list):
        remotes = [DEFAULT_REMOTE]
    head, sep, rest = name.partition("/")
    return rest if sep and rest and head in remotes else name


def worktree_index(inventory):
    """[(folded path, repo path, worktree, short default branch)] longest path first."""
    entries = []
    for repo in inventory.get("repos") or []:
        default_branch = short_default_branch(repo)
        for wt in repo.get("worktrees") or []:
            folded = (_norm(wt.get("path")) or "").lower()
            if folded:
                entries.append((folded, repo["path"], wt, default_branch))
    entries.sort(key=lambda e: -len(e[0]))
    return entries


def find_worktree(path, index):
    """(repo path, worktree, default branch) of the longest worktree containing path, or None."""
    p = (_norm(path) or "").lower()
    if not p:
        return None
    for folded, repo_path, wt, default_branch in index:
        if p == folded or p.startswith(folded + "/"):
            return repo_path, wt, default_branch
    return None


def cwd_path(session):
    """relocatedCwd, else the most frequent cwd; Git Bash drive form converted."""
    if session.get("relocatedCwd"):
        return drive_path(session["relocatedCwd"])
    cwds = session.get("cwds") or []
    return drive_path(cwds[0]["path"]) if cwds else None


def anchor_path(session):
    anchor = session.get("writeAnchor") or {}
    return drive_path(anchor.get("path")) or cwd_path(session)


def _session_branch(session, wt, index):
    """The session's own branch, trusted only when its cwd is in the anchor worktree.

    Transcripts record the branch of the cwd, which says nothing about another repo the
    session wrote into.
    """
    hit = find_worktree(cwd_path(session), index)
    if not hit or hit[1] is not wt:
        return None
    branches = session.get("gitBranches") or []
    return branches[0]["name"] if branches else None


def _scope_suffix(session):
    """Default-branch thread suffix: the fork family, else the session itself."""
    family = (session.get("fork") or {}).get("familyId")
    if family:
        return f"{SCOPE_SEPARATOR}family:{family}"
    return f"{SCOPE_SEPARATOR}session:{session['sessionId']}"


def resolve_session(session, index):
    """(key, kind) of the thread a session belongs to.

    Work on the repo's default branch is split per fork family or per session: a shared
    trunk says nothing about which piece of work a session was doing.
    """
    path = anchor_path(session)
    hit = find_worktree(path, index)
    if hit:
        repo_path, wt, default_branch = hit
        branch = _session_branch(session, wt, index) or wt.get("branch")
        key = git_key(repo_path, branch, wt["path"])
        if branch and default_branch and branch == default_branch:
            key += _scope_suffix(session)
        return key, "git"
    if (session.get("writeAnchor") or {}).get("path"):
        return f"dir:{path}", "dir"
    return f"session:{session['sessionId']}", "session"


def is_project_scope(key):
    """True for default-branch thread keys, whose git state belongs to the project."""
    if not key.startswith("git:") or "#" not in key:
        return False
    return SCOPE_SEPARATOR in key.split("#", 1)[1]


def project_key(session, key, kind):
    """(project key, project kind) of a thread key; `session` gives the cwd of session threads."""
    if kind == "git":
        return f"repo:{split_git_key(key)[0]}", "repo"
    if kind == "dir":
        return f"dir:{key[len('dir:'):]}", "dir"
    return f"dir:{cwd_path(session) or ''}", "dir"


def inventory_items(inventory):
    """Yield (key, repo path, branch, worktree path, item) for every worktree and branch."""
    for repo in inventory.get("repos") or []:
        for wt in repo.get("worktrees") or []:
            yield (git_key(repo["path"], wt.get("branch"), wt["path"]), repo["path"],
                   wt.get("branch"), wt["path"], wt)
        for br in repo.get("branches") or []:
            yield git_key(repo["path"], br["name"], None), repo["path"], br["name"], None, br


def split_git_key(key):
    """(repo path, branch, worktree path) of a git key; a default-branch suffix is dropped."""
    rest = key[len("git:"):]
    if "#" in rest:
        repo_path, branch = rest.split("#", 1)
        return repo_path, branch.split(SCOPE_SEPARATOR, 1)[0], None
    repo_path, _, worktree_path = rest.partition("@")
    return repo_path, None, worktree_path or None


def last_segment(path):
    return next((p for p in reversed(re.split(r"[/\\]", path or "")) if p), path)


def short_key(key):
    """Key with paths reduced to their last segment and ids to 8 characters, for display."""
    kind, _, rest = key.partition(":")
    if kind == "git":
        repo_path, branch, worktree_path = split_git_key(key)
        tail = f"#{branch}" if branch else f"@{last_segment(worktree_path)}"
        if is_project_scope(key):
            scope, _, ident = key.rsplit(SCOPE_SEPARATOR, 1)[1].partition(":")
            tail += f"{SCOPE_SEPARATOR}{scope}:{ident[:8]}"
        return f"git:{last_segment(repo_path)}{tail}"
    if kind == "session":
        return f"session:{rest[:8]}"
    return f"{kind}:{last_segment(rest)}"
