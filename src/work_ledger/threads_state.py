"""Suggested thread state from git facts and closure signals. Pure functions."""

from .sessions_parse import parse_timestamp

# Display and sort order of effective states, suggested and user ones mixed.
STATE_ORDER = ("at-risk", "open", "waiting-merge", "active", "paused", "stale", "likely-done",
               "done", "discarded")
OVERRIDE_STATES = ("active", "paused", "discarded", "done")
AT_RISK = ("modified", "unpushed", "untracked")
DONE_IDLE_DAYS = 7
STALE_DAYS = 30
RECENT_DAYS = 30


def days_idle(last_at, now):
    """Whole days from last_at to now, never negative; None when last_at is unknown."""
    when = parse_timestamp(last_at)
    if when is None:
        return None
    return max(0, (now - when).days)


def recency(days):
    """`recent` when idle less than RECENT_DAYS, else `old`; unknown idle counts as old."""
    return "recent" if days is not None and days < RECENT_DAYS else "old"


def suggest_state(kind, git, resume, days):
    """(suggestedState, suggestedReason). First match wins; git.found false means no risk.

    The recap rule applies to threads without their own git facts: non-git kinds and
    default-branch threads, whose git state belongs to the project (git is None).
    """
    risk = git.get("risk") if git and git.get("found") else None
    if risk in AT_RISK:
        return "at-risk", f"git risk {risk}"
    if risk == "pushed":
        return "waiting-merge", "pushed, not merged"
    if risk == "safe":
        return "likely-done", "git risk safe (merged or on remote)"
    resume = resume or {}
    if ((kind != "git" or git is None) and resume.get("lastRecap") and not resume.get("lastAsk")
            and days is not None and days >= DONE_IDLE_DAYS):
        return "likely-done", f"wrap-up recap without question, idle {days}d"
    if days is not None and days >= STALE_DAYS:
        return "stale", f"idle {days}d (>= {STALE_DAYS})"
    return "open", "recent activity" if days is not None else "no activity date"


def effective_state(state, suggested):
    return state or suggested
