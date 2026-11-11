"""Group sessions into fork families by shared message uuids, with a best-effort parent.

A fork copies its parent's history keeping the original uuids and timestamps, so start
times cannot tell parent from child; the first message after the shared part can.
"""

from collections import defaultdict

from .sessions_parse import parse_timestamp


def _uuids(session):
    return {u for u, _ in session.get("messages") or ()}


def _first_own(session, shared):
    """Timestamp string of the first message in file order whose uuid is not shared."""
    for uuid, ts in session.get("messages") or ():
        if uuid not in shared:
            return ts
    return None


def _earlier(a_value, b_value, a_id, b_id):
    if a_value is None or b_value is None or a_value == b_value:
        return None
    return a_id if a_value < b_value else b_id


def pair_parent(a, b, shared=None):
    """sessionId of the parent of the pair, or None when it cannot be told.

    Earliest first non-shared message wins; a side without one, or equal times, falls back
    to the earlier transcript creation time; still tied -> None.
    """
    shared = _uuids(a) & _uuids(b) if shared is None else shared
    a_id, b_id = a["sessionId"], b["sessionId"]
    by_divergence = _earlier(parse_timestamp(_first_own(a, shared)),
                             parse_timestamp(_first_own(b, shared)), a_id, b_id)
    return by_divergence or _earlier(a.get("created"), b.get("created"), a_id, b_id)


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def detect_forks(sessions):
    """Map sessionId -> fork info, or None for a session that shares no message uuid."""
    by_id = {s["sessionId"]: s for s in sessions}
    uuid_sets = {sid: _uuids(s) for sid, s in by_id.items()}
    links = _UnionFind()
    owner = {}
    for sid in sorted(by_id):
        links.find(sid)
        for uuid in uuid_sets[sid]:
            if uuid in owner:
                links.union(owner[uuid], sid)
            else:
                owner[uuid] = sid

    families = defaultdict(list)
    for sid in by_id:
        families[links.find(sid)].append(sid)

    forks = {}
    for members in families.values():
        family_id = min(members)
        if len(members) == 1:
            forks[family_id] = None
            continue
        for sid in members:
            others = sorted(m for m in members if m != sid)
            shared = {m: uuid_sets[sid] & uuid_sets[m] for m in others}
            best = sorted(others, key=lambda m: (-len(shared[m]), m))[0]
            is_parent = len(shared[best]) and pair_parent(by_id[sid], by_id[best], shared[best]) == best
            forks[sid] = {
                "familyId": family_id,
                "members": others,
                "sharedMessages": len(shared[best]),
                "parent": best if is_parent else None,
                "divergedAt": _first_own(by_id[sid], shared[best]),
            }
    return forks
