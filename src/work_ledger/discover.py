"""Find git repos under roots and deduplicate them by common dir."""

import os
from dataclasses import dataclass

from .gitcmd import GitError, run_git

MAX_DEPTH = 2
SKIP_DIRS = {".git", "node_modules"}


@dataclass(frozen=True)
class RepoRef:
    main_path: str
    common_dir: str | None
    error: str | None = None


def to_posix(path):
    return os.path.abspath(path).replace("\\", "/")


def _key(path):
    return os.path.normcase(os.path.realpath(path))


def _candidates(root, max_depth):
    """Yield directories containing a .git entry, from depth 0 to max_depth."""
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        if os.path.lexists(os.path.join(current, ".git")):
            yield current
        if depth >= max_depth:
            continue
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir and entry.name not in SKIP_DIRS:
                stack.append((entry.path, depth + 1))


def main_worktree_path(path, common_dir):
    """Path of the main working tree: first entry of `git worktree list`."""
    result = run_git(path, "worktree", "list", "--porcelain")
    if result.code == 0:
        first = result.stdout.split("\n\n", 1)[0].splitlines()
        if first and first[0].startswith("worktree ") and "bare" not in first[1:]:
            return to_posix(first[0][len("worktree "):])
    return to_posix(common_dir)


def _resolve(path):
    try:
        result = run_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if result.code != 0:
            return RepoRef(to_posix(path), None, result.stderr.strip() or f"git exit {result.code}")
        common_dir = to_posix(result.stdout.strip())
        return RepoRef(main_worktree_path(path, common_dir), common_dir)
    except GitError as exc:
        return RepoRef(to_posix(path), None, str(exc))


def discover(roots, max_depth=MAX_DEPTH):
    """Return one RepoRef per distinct repo found under the given roots."""
    seen = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for candidate in _candidates(os.path.abspath(root), max_depth):
            ref = _resolve(candidate)
            key = _key(ref.common_dir) if ref.common_dir else ("error", _key(candidate))
            seen.setdefault(key, ref)
    return sorted(seen.values(), key=lambda r: r.main_path.lower())
