"""Risk classification of worktrees and branches. Pure functions, no git."""

# Worst first. "main" marks a main working tree whose state would otherwise be
# "safe" or "pushed": it is never a removal candidate.
RISK_ORDER = ("modified", "unpushed", "untracked", "unknown", "missing", "pushed", "main", "safe")


def classify(facts):
    """Return exactly one risk for a worktree or branch facts dict. First match wins."""
    if facts.get("exists") is False:
        return "missing"
    if facts.get("error"):
        return "unknown"

    dirty = facts.get("dirty", {"staged": 0, "unstaged": 0, "untracked": 0})
    if dirty is None:
        return "unknown"
    if dirty.get("staged", 0) > 0 or dirty.get("unstaged", 0) > 0:
        return "modified"

    not_on_remote = facts.get("notOnRemote")
    if not_on_remote is not None and not_on_remote > 0:
        return "unpushed"
    if dirty.get("untracked", 0) > 0:
        return "untracked"
    if not_on_remote is None:
        return "unknown"

    # Clean and nothing unpushed: only now is the merge state (and therefore the
    # default branch) needed.
    merged = facts.get("merged")
    if merged is None:
        return "unknown"
    if facts.get("isMain"):
        return "main"
    return "safe" if merged else "pushed"


def worst(risks):
    """Return the worst risk in an iterable, or None when empty."""
    present = [r for r in risks if r in RISK_ORDER]
    if not present:
        return None
    return min(present, key=RISK_ORDER.index)
