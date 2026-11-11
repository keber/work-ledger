import unittest

from work_ledger.sessions_forks import detect_forks, pair_parent


def t(minute):
    return f"2026-11-01T10:{minute:02d}:00Z"


def s(sid, messages, created=None):
    """messages: list of (uuid, minute) in file order."""
    return {"sessionId": sid, "messages": [[u, t(m) if m is not None else None] for u, m in messages],
            "created": created}


# Real forks copy the parent's history with the original uuids AND timestamps.
HISTORY = [("a", 0), ("b", 1), ("c", 2)]


class PairParentTest(unittest.TestCase):
    def test_earliest_first_non_shared_message_is_parent(self):
        parent = s("p", HISTORY + [("p1", 5)])
        child = s("c", HISTORY + [("c1", 9)])
        self.assertEqual(pair_parent(parent, child), "p")
        self.assertEqual(pair_parent(child, parent), "p")

    def test_tie_broken_by_creation_time(self):
        a = s("a", HISTORY + [("a1", 5)], created=200.0)
        b = s("b", HISTORY + [("b1", 5)], created=100.0)
        self.assertEqual(pair_parent(a, b), "b")

    def test_no_divergence_on_one_side_falls_back_to_creation_time(self):
        prefix = s("prefix", HISTORY, created=100.0)
        longer = s("longer", HISTORY + [("x", 5)], created=300.0)
        self.assertEqual(pair_parent(prefix, longer), "prefix")

    def test_full_tie_is_unknown(self):
        a = s("a", HISTORY + [("a1", 5)], created=100.0)
        b = s("b", HISTORY + [("b1", 5)], created=100.0)
        self.assertIsNone(pair_parent(a, b))
        self.assertIsNone(pair_parent(s("x", HISTORY + [("x1", 5)]), s("y", HISTORY + [("y1", 5)])))


class DetectForksTest(unittest.TestCase):
    def test_alone_is_null(self):
        forks = detect_forks([s("a", [("a", 0)]), s("b", [("b", 0)]), s("empty", [])])
        self.assertEqual(forks, {"a": None, "b": None, "empty": None})

    def test_pair_with_identical_first_timestamp(self):
        forks = detect_forks([s("p", HISTORY + [("p1", 5)]), s("c", HISTORY + [("c1", 9)])])
        self.assertEqual(forks["c"], {"familyId": "c", "members": ["p"], "sharedMessages": 3,
                                      "parent": "p", "divergedAt": t(9)})
        self.assertEqual(forks["p"], {"familyId": "c", "members": ["c"], "sharedMessages": 3,
                                      "parent": None, "divergedAt": t(5)})

    def test_family_of_three_is_transitive(self):
        root = s("root", HISTORY + [("r1", 3)])
        mid = s("mid", HISTORY + [("m1", 4), ("m2", 5), ("m3", 6)])
        leaf = s("leaf", HISTORY + [("m1", 4), ("m2", 5), ("l1", 8)])
        forks = detect_forks([root, mid, leaf])
        self.assertEqual({f["familyId"] for f in forks.values()}, {"leaf"})
        self.assertEqual(forks["root"]["members"], ["leaf", "mid"])
        self.assertEqual(forks["leaf"]["parent"], "mid")
        self.assertEqual(forks["leaf"]["sharedMessages"], 5)
        self.assertEqual(forks["leaf"]["divergedAt"], t(8))
        self.assertEqual(forks["mid"]["parent"], None)  # shares most with leaf, which is its child
        self.assertIsNone(forks["root"]["parent"])

    def test_linked_through_a_middle_member_only(self):
        # x and z share nothing directly; both share with y.
        forks = detect_forks([s("x", [("1", 0), ("x1", 2)]), s("y", [("1", 0), ("2", 1)]),
                              s("z", [("2", 1), ("z1", 3)])])
        self.assertEqual(forks["x"]["members"], ["y", "z"])
        self.assertEqual(forks["z"]["familyId"], "x")

    def test_no_non_shared_message_has_null_diverged_at(self):
        forks = detect_forks([s("prefix", HISTORY, created=1.0),
                              s("longer", HISTORY + [("x", 5)], created=2.0)])
        self.assertIsNone(forks["prefix"]["divergedAt"])
        self.assertEqual(forks["longer"]["parent"], "prefix")


if __name__ == "__main__":
    unittest.main()
