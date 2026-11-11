import unittest

from tests.threadfixtures import overrides
from work_ledger.threads_inputs import InputError
from work_ledger.threads_overrides import apply_merges, override_states, parse_overrides


def group(key, *sids):
    return {"key": key, "kind": "dir", "origin": "sessions",
            "sessions": [{"sessionId": s} for s in sids], "item": None}


class ParseTest(unittest.TestCase):
    def test_missing_overrides_are_empty(self):
        self.assertEqual(parse_overrides(None), {"threads": {}, "merge": []})

    def test_unknown_schema_version_is_an_error(self):
        with self.assertRaises(InputError) as ctx:
            parse_overrides({"schemaVersion": 9, "threads": {}})
        self.assertIn("schemaVersion 9", str(ctx.exception))

    def test_bad_shape_is_an_error(self):
        for bad in ({"schemaVersion": 1, "threads": []}, {"schemaVersion": 1, "merge": {}}, []):
            with self.assertRaises(InputError):
                parse_overrides(bad)


class MergeTest(unittest.TestCase):
    def test_from_sessions_move_into_target_and_from_disappears(self):
        groups = {"a": group("dir:A", "s1"), "b": group("dir:B", "s2"), "c": group("dir:C", "s3")}
        merged, warnings = apply_merges(groups, [{"into": "a", "from": ["b", "c"]}])
        self.assertEqual(list(merged), ["a"])
        self.assertEqual([s["sessionId"] for s in merged["a"]["sessions"]], ["s1", "s2", "s3"])
        self.assertEqual(merged["a"]["key"], "dir:A")
        self.assertEqual(warnings, [])
        self.assertEqual(len(groups["a"]["sessions"]), 1)  # input untouched

    def test_unknown_ids_are_warnings(self):
        groups = {"a": group("dir:A", "s1"), "b": group("dir:B", "s2")}
        merged, warnings = apply_merges(groups, [{"into": "a", "from": ["zzz", "b"]},
                                                 {"into": "nope", "from": ["a"]}])
        self.assertEqual(list(merged), ["a"])
        self.assertEqual(len(merged["a"]["sessions"]), 2)
        self.assertEqual(len(warnings), 2)
        self.assertIn("zzz", warnings[0])
        self.assertIn("nope", warnings[1])

    def test_merge_into_self_is_ignored(self):
        groups = {"a": group("dir:A", "s1")}
        merged, warnings = apply_merges(groups, [{"into": "a", "from": ["a"]}])
        self.assertEqual(len(merged["a"]["sessions"]), 1)
        self.assertEqual(len(warnings), 1)

    def test_inventory_thread_receiving_sessions_becomes_session_backed(self):
        inv = dict(group("git:C:/r#x"), origin="inventory", sessions=[])
        merged, _ = apply_merges({"i": inv, "a": group("dir:A", "s1")},
                                 [{"into": "i", "from": ["a"]}])
        self.assertEqual(merged["i"]["origin"], "sessions")


class OverrideStatesTest(unittest.TestCase):
    def test_states_and_notes(self):
        data = parse_overrides(overrides({"a": {"state": "paused", "note": "later"},
                                          "b": {"note": "only a note"}}))
        states, warnings = override_states(["a", "b", "c"], data)
        self.assertEqual(states["a"], ("paused", "later"))
        self.assertEqual(states["b"], (None, "only a note"))
        self.assertNotIn("c", states)
        self.assertEqual(warnings, [])

    def test_unknown_thread_and_bad_state_warn(self):
        data = parse_overrides(overrides({"gone": {"state": "done"}, "a": {"state": "finished"}}))
        states, warnings = override_states(["a"], data)
        self.assertEqual(states["a"], (None, None))
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("gone" in w for w in warnings))
        self.assertTrue(any("finished" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
