"""Resolve the root of each written path on disk and pick a session's write anchor."""

import os
import posixpath
import tempfile
from collections import Counter

from .sessions_parse import normalize_path

# Matches the long and the 8.3 short form (JOHNDO~1) of the Windows user temp dir alike.
TEMP_MARKER = "/appdata/local/temp/"


def default_claude_home():
    return normalize_path(os.path.join(os.path.expanduser("~"), ".claude"))


def default_temp_root():
    return normalize_path(tempfile.gettempdir())


def is_temp_path(path, temp_root):
    """True when path is under temp_root or contains /AppData/Local/Temp/, ignoring case."""
    p = (normalize_path(path) or "").lower()
    if not p:
        return False
    root = (normalize_path(temp_root) or "").lower().rstrip("/")
    if root and (p == root or p.startswith(root + "/")):
        return True
    return TEMP_MARKER in p + "/"


def _key(path):
    return path.lower() if os.name == "nt" else path


class AnchorResolver:
    """Root of a path, first match wins: nearest `.git` ancestor, ~/.claude/<a>/<b>, parent dir.

    `.git` lookups are memoized per directory for the lifetime of the resolver (one scan).
    `is_temp(path)` decides which writes are scratch files left out of the write anchor.
    """

    def __init__(self, claude_home, lexists=os.path.lexists, is_temp=None):
        self.claude_home = normalize_path(claude_home).rstrip("/")
        self._lexists = lexists
        if is_temp is None:
            temp_root = default_temp_root()
            is_temp = lambda path: is_temp_path(path, temp_root)  # noqa: E731
        self._is_temp = is_temp
        self._repo_of_dir = {}

    def _repo_root(self, directory):
        visited = []
        current = directory
        found = None
        while current:
            if current in self._repo_of_dir:
                found = self._repo_of_dir[current]
                break
            visited.append(current)
            if self._lexists(current + "/.git" if not current.endswith("/") else current + ".git"):
                found = current
                break
            parent = posixpath.dirname(current)
            if parent == current:
                break
            current = parent
        for d in visited:
            self._repo_of_dir[d] = found
        return found

    def _claude_root(self, path):
        home = _key(self.claude_home) + "/"
        if not _key(path).startswith(home):
            return None
        below = path[len(home):].split("/")[:-1]  # directory components only
        return "/".join([self.claude_home, *below[:2]])

    def root(self, path):
        p = normalize_path(path)
        parent = posixpath.dirname(p)
        return self._repo_root(parent) or self._claude_root(p) or parent

    def write_anchor(self, writes):
        """{path, share} of the root holding most non-temp writes, or None without any."""
        roots = Counter()
        for w in writes:
            if not self._is_temp(w["path"]):
                roots[self.root(w["path"])] += w["count"]
        total = sum(roots.values())
        if not total:
            return None
        path, count = sorted(roots.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        return {"path": path, "share": round(count / total, 3)}
