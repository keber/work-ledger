"""Apply the user-owned overrides (merges and states) to threads. Pure functions."""

from .threads_inputs import InputError
from .threads_state import OVERRIDE_STATES

SCHEMA_VERSION = 1


def parse_overrides(data):
    """Validated {"threads": {...}, "merge": [...]}; None means no overrides."""
    if data is None:
        return {"threads": {}, "merge": []}
    if not isinstance(data, dict):
        raise InputError("overrides: expected a JSON object")
    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise InputError(f"overrides: unsupported schemaVersion {data.get('schemaVersion')} "
                         f"(supported: {SCHEMA_VERSION})")
    threads = data.get("threads", {})
    merge = data.get("merge", [])
    if not isinstance(threads, dict) or not all(isinstance(v, dict) for v in threads.values()):
        raise InputError("overrides: 'threads' must map thread ids to objects")
    if not isinstance(merge, list) or not all(
            isinstance(m, dict) and isinstance(m.get("from", []), list) for m in merge):
        raise InputError("overrides: 'merge' must be a list of {into, from: [...]}")
    return {"threads": threads, "merge": merge}


def apply_merges(groups, merges):
    """(new groups, warnings). Sessions of `from` move into `into`; `from` groups disappear."""
    result = {tid: dict(g, sessions=list(g["sessions"])) for tid, g in groups.items()}
    warnings = []
    for entry in merges:
        into = entry.get("into")
        if into not in result:
            warnings.append(f"merge: unknown target thread id {into}")
            continue
        for source in entry.get("from") or []:
            if source == into or source not in result:
                warnings.append(f"merge into {into}: unknown or same thread id {source}")
                continue
            result[into]["sessions"] += result.pop(source)["sessions"]
        if result[into]["sessions"]:
            result[into]["origin"] = "sessions"
    return result, warnings


def override_states(thread_ids, overrides):
    """({id: (state, note)}, warnings) for overridden threads that exist."""
    known = set(thread_ids)
    states, warnings = {}, []
    for tid, entry in overrides["threads"].items():
        if tid not in known:
            warnings.append(f"overrides: unknown thread id {tid}")
            continue
        state = entry.get("state")
        if state is not None and state not in OVERRIDE_STATES:
            warnings.append(f"overrides: thread {tid} has unknown state {state!r} (ignored)")
            state = None
        note = entry.get("note")
        states[tid] = (state, note if isinstance(note, str) else None)
    return states, warnings
