"""Find hand-written handoff notes in a project folder, for `context`. Read-only, bounded.

Only the folder itself and a few common doc dirs one level down are listed. Directory
junctions, symlinks and reparse-point files are skipped, only files matching known names
are read, and each read stops at READ_LIMIT characters.

A note within HANDOFF_CAP characters is shown whole. A longer one is shown as its title
and leading "read first" block (up to LEAD_CAP) plus a table of contents of every heading
with its line number, so the reader can open the file at the sections that matter. No
section is picked automatically: picking by date chose stale sections on real notes.
"""

import fnmatch
import os
import re
import stat
from datetime import datetime, timezone

PATTERNS = ("agent-next-steps*.md", "next-steps*.md", "handoff*.md", "estado_proyecto.md",
            "status.md")
DOC_DIRS = ("qa", "docs", ".claude")
MAX_FILES = 3
HANDOFF_CAP = 3000
LEAD_CAP = 800
READ_LIMIT = 262144
ELLIPSIS = "..."
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_READ_FIRST = re.compile(r"read first|read me first|important|novedades|leer primero|léeme|"
                         r"leeme|importante", re.IGNORECASE)


def _matches(name):
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, p) for p in PATTERNS)


def _is_reparse(entry):
    """Junction, symlink or other reparse point (Windows); never followed."""
    try:
        if entry.is_junction() or entry.is_symlink():
            return True
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) or 0
    except OSError:
        return True
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _candidates(root):
    folders = [root]
    try:
        folders += [e.path for e in os.scandir(root)
                    if e.name.lower() in DOC_DIRS and not _is_reparse(e)
                    and e.is_dir(follow_symlinks=False)]
    except OSError:
        return
    for folder in folders:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                if _matches(entry.name) and not _is_reparse(entry) \
                        and entry.is_file(follow_symlinks=False):
                    yield entry.path, entry.stat(follow_symlinks=False)
            except OSError:
                continue


def _read_text(path, limit):
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return fh.read(limit)


# ---- excerpt ----

def _headings(lines):
    """[(index, level, heading text)] for headings outside code fences."""
    heads, fenced = [], False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else _HEADING.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    return heads


def _clip(text, limit):
    if len(text) <= limit:
        return text
    return text[:max(0, limit - len(ELLIPSIS))].rstrip() + ELLIPSIS


def _lead_end(heads, line_count):
    """Line index where the lead ends: after the title and a leading read-first section."""
    rest = heads[1:] if heads and heads[0][1] == 1 else heads
    if not rest:
        return line_count
    first = rest[0]
    if _READ_FIRST.search(first[2]):
        return next((i for i, level, _ in rest[1:] if level <= first[1]), line_count)
    return first[0]


def excerpt_note(text, cap=HANDOFF_CAP, lead_cap=LEAD_CAP):
    """(shown text, toc). toc is [{line (1-based), level, heading}] for every heading.

    Within `cap` the text is whole; beyond it, only the title and lead (up to lead_cap).
    """
    lines = text.splitlines()
    heads = _headings(lines)
    toc = [{"line": i + 1, "level": level, "heading": heading} for i, level, heading in heads]
    if len(text) <= cap:
        return text, toc
    lead = "\n".join(lines[:_lead_end(heads, len(lines))]).rstrip()
    return _clip(lead, lead_cap), toc


def find_handoff(root, max_files=MAX_FILES, cap=HANDOFF_CAP):
    """[{path, modifiedAt, bytes, lines, text, truncated, toc}], most recently modified first.

    A missing folder or an unreadable file yields nothing for it; never raises.
    """
    if not root or not os.path.isdir(root):
        return []
    found = sorted(_candidates(root), key=lambda item: (-item[1].st_mtime, item[0]))
    notes = []
    for path, st in found:
        if len(notes) >= max_files:
            break
        try:
            raw = _read_text(path, READ_LIMIT)
        except OSError:
            continue
        text, toc = excerpt_note(raw, cap)
        notes.append({"path": os.path.abspath(path).replace("\\", "/"),
                      "modifiedAt": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                      "bytes": st.st_size, "lines": len(raw.splitlines()), "text": text,
                      "truncated": text != raw, "toc": toc})
    return notes
