"""Deterministic check that keeps internal details out of external (public) pieces. Pure.

`violations` returns rule names only, never the matched text, so a rejection can be
recorded without copying what it was meant to keep out. Passing the check is not proof
of safety: every public piece still needs the user's approval.
"""

import re
import unicodedata

# Neutral built-in default: company terms come from the config (`[curation] company_terms`).
DEFAULT_COMPANY_TERMS = ()
DENYLIST_NAME = "curation-denylist.txt"
RULES = ("project-name", "company", "email", "url", "path", "ip-address", "ticket-id",
         "denylist")
# Auto-derived names shorter than this (alphanumeric characters) are ignored: names like
# `qa` or `a` would reject most Spanish text.
MIN_NAME_CHARS = 3

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?|ftp|file)://|\bwww\.", re.IGNORECASE)
_PATH = re.compile(
    r"\b[a-z]:[\\/]"                       # C:\ or C:/
    r"|\\\\[\w.$-]+\\"                     # \\server\share
    r"|~[\\/]"                             # ~/ or ~\
    r"|(?<![\w.:/])/(?:[\w.-]+/)+[\w.-]*"  # /home/user/x (two or more segments)
    r"|[\w.-]+\\[\w.-]+",                  # src\work_ledger
    re.IGNORECASE)
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
                 r"|\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b", re.IGNORECASE)
# #123, AB#123, and Jira-style keys (ABC-123, uppercase only, so `covid-19` prose passes).
_TICKET = re.compile(r"#\d+|\b[A-Z][A-Z0-9]{1,9}-\d{2,}\b")
# PBI 123, Bug #9, tarea 12 (any case).
_TICKET_WORDS = re.compile(r"\b(?:pbi|bug|task|tarea|issue|ticket|us|wi)\s*#?\s*\d+\b",
                           re.IGNORECASE)


def fold(text):
    """Lowercase, accents removed (`Acmé` -> `acme`)."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _tokens(term):
    return re.findall(r"[a-z0-9]+", fold(term))


def _name_pattern(term):
    """Whole-word match that treats `-`, `_`, `.`, spaces (or nothing) as one separator."""
    tokens = _tokens(term)
    if sum(len(t) for t in tokens) < MIN_NAME_CHARS:
        return None
    body = r"[\W_]*".join(re.escape(t) for t in tokens)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def _substring_pattern(term):
    """Substring match, separators optional; for terms the user chose (company, denylist)."""
    tokens = _tokens(term)
    if not tokens:
        return None
    return re.compile(r"[\W_]*".join(re.escape(t) for t in tokens))


def _any(patterns, folded):
    return any(p.search(folded) for p in patterns if p is not None)


def violations(texts, names=(), company=DEFAULT_COMPANY_TERMS, denylist=()):
    """Sorted (rule order) names of the rules any of `texts` breaks; [] when clean."""
    raw = "\n".join(str(t) for t in texts if t is not None)
    folded = fold(raw)
    found = set()
    if _any([_name_pattern(n) for n in names], folded):
        found.add("project-name")
    if _any([_substring_pattern(c) for c in company], folded):
        found.add("company")
    if _EMAIL.search(raw):
        found.add("email")
    if _URL.search(raw):
        found.add("url")
    if _PATH.search(raw):
        found.add("path")
    if _IP.search(raw):
        found.add("ip-address")
    if _TICKET.search(raw) or _TICKET_WORDS.search(raw):
        found.add("ticket-id")
    if _any([_substring_pattern(d) for d in denylist], folded):
        found.add("denylist")
    return [r for r in RULES if r in found]


def parse_denylist(text):
    """One term per line; blank lines and lines starting with `#` are skipped."""
    terms = []
    for line in text.splitlines():
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append(term)
    return terms


def _last_segment(path):
    if not isinstance(path, str):
        return None
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return parts[-1] if parts else None


def internal_names(ledger, inventory=None):
    """Project, repo and worktree folder names from the ledger and the inventory, sorted."""
    paths, names = [], []
    for p in (ledger or {}).get("projects") or []:
        if not isinstance(p, dict):
            continue
        names.append(p.get("name"))
        paths.append(p.get("path"))
        paths.append((p.get("git") or {}).get("worktreePath"))
    for t in (ledger or {}).get("threads") or []:
        git = (t or {}).get("git") or {}
        paths += [git.get("repo"), git.get("worktreePath")]
    for r in (inventory or {}).get("repos") or []:
        if not isinstance(r, dict):
            continue
        paths.append(r.get("path"))
        paths += [(w or {}).get("path") for w in r.get("worktrees") or []]
    names += [_last_segment(p) for p in paths]
    unique = {}
    for name in names:
        if isinstance(name, str) and name.strip():
            unique.setdefault(name.strip().lower(), name.strip())
    return sorted(unique.values(), key=str.lower)
