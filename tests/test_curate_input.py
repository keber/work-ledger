import json
import unittest

from tests.curatefixtures import LEDGER_AT, NOW, curate_ledger, thread
from tests.digestfixtures import previous
from work_ledger.curate_input import (MAX_CHARS, MAX_THREADS, build_input, input_text,
                                      previous_snapshot, select_threads, thread_facts)

ALLOWED = {"id", "title", "project", "effectiveState", "firstAt", "lastAt", "sessionCount",
           "gitActions", "lastRecap", "lastAsk"}


def ids(threads):
    return [t["id"] for t in threads]


class SelectThreadsTest(unittest.TestCase):
    def test_last_seven_days_from_ledger_generated_at(self):
        led = curate_ledger([thread("in", last_at="2026-11-06T09:00:00+00:00"),
                             thread("edge", last_at="2026-11-05T08:55:00+00:00"),
                             thread("out", last_at="2026-11-05T08:54:59+00:00")])
        self.assertEqual(ids(select_threads(led, None, NOW)), ["in", "edge"])

    def test_old_threads_that_changed_state_since_the_snapshot(self):
        old = "2026-09-01T10:00:00+00:00"
        led = curate_ledger([thread("changed", "stale", last_at=old),
                             thread("same", "stale", last_at=old),
                             thread("new", "stale", last_at=old)])
        snapshot = {"changed": "open", "same": "stale"}
        self.assertEqual(ids(select_threads(led, snapshot, NOW)), ["changed"])
        self.assertEqual(ids(select_threads(led, None, NOW)), [])

    def test_discarded_and_other_domains_are_excluded(self):
        led = curate_ledger([thread("d", "discarded"), thread("p", domain="personal"),
                             thread("w")])
        self.assertEqual(ids(select_threads(led, {"d": "open"}, NOW)), ["w"])

    def test_most_recent_first_and_unknown_dates_are_not_recent(self):
        led = curate_ledger([thread("a", last_at="2026-11-08T10:00:00+00:00"),
                             thread("b", last_at="2026-11-11T10:00:00+00:00"),
                             thread("none", last_at=None)])
        self.assertEqual(ids(select_threads(led, None, NOW)), ["b", "a"])

    def test_unparseable_ledger_date_falls_back_to_now(self):
        led = curate_ledger([thread("a")], generated_at="garbage")
        self.assertEqual(ids(select_threads(led, None, NOW)), ["a"])


class FactsTest(unittest.TestCase):
    def test_only_allowed_fields(self):
        t = thread("a", title="Pipeline", recap="Hecho", ask="¿Sigo?", commits=2, sessions=3)
        facts = thread_facts(t, {"p-app": "app"})
        self.assertEqual(set(facts), ALLOWED)
        self.assertEqual(facts["project"], "app")
        self.assertEqual(facts["gitActions"], {"commit": 2, "push": 0, "merge": 0,
                                               "pr-create": 0})
        self.assertEqual((facts["lastRecap"], facts["lastAsk"]), ("Hecho", "¿Sigo?"))
        self.assertEqual(facts["sessionCount"], 3)
        text = json.dumps(facts)
        for secret in ("s-a", "dir:C:/w", "secret prompt", "private note"):
            self.assertNotIn(secret, text)

    def test_missing_resume_and_actions(self):
        t = thread("a")
        t["resume"], t["gitActions"] = None, None
        facts = thread_facts(t, {})
        self.assertIsNone(facts["lastRecap"])
        self.assertIsNone(facts["project"])
        self.assertEqual(facts["gitActions"], {})


class BuildInputTest(unittest.TestCase):
    def facts(self, n, recap=""):
        return [thread_facts(thread(f"t{i}", recap=recap), {}) for i in range(n)]

    def test_shape(self):
        data, dropped = build_input(self.facts(2), "team", 2, LEDGER_AT)
        self.assertEqual(dropped, 0)
        self.assertEqual(data["audience"], "team")
        self.assertEqual(data["maxPieces"], 2)
        self.assertEqual(data["domain"], "work")
        self.assertEqual(data["periodDays"], 7)
        self.assertEqual(data["ledgerGeneratedAt"], LEDGER_AT)
        self.assertEqual(ids(data["threads"]), ["t0", "t1"])

    def test_thread_cap(self):
        self.assertEqual(MAX_THREADS, 60)
        data, dropped = build_input(self.facts(65), "team", 2, LEDGER_AT)
        self.assertEqual(len(data["threads"]), 60)
        self.assertEqual(dropped, 5)
        self.assertEqual(data["threads"][-1]["id"], "t59")

    def test_character_cap_drops_from_the_oldest(self):
        self.assertEqual(MAX_CHARS, 40_000)
        data, dropped = build_input(self.facts(30, recap="x" * 2000), "team", 2, LEDGER_AT)
        self.assertGreater(dropped, 0)
        self.assertEqual(len(data["threads"]) + dropped, 30)
        self.assertLessEqual(len(input_text(data)), MAX_CHARS)
        self.assertEqual(data["threads"][0]["id"], "t0")

    def test_input_text_is_json(self):
        data, _ = build_input(self.facts(1, recap="Señal"), "public", 1, LEDGER_AT)
        self.assertEqual(json.loads(input_text(data)), data)
        self.assertIn("Señal", input_text(data))


class PreviousSnapshotTest(unittest.TestCase):
    def test_latest_of_another_ledger_is_the_previous_digest(self):
        led = curate_ledger([])
        latest = previous({"a": "open"})
        self.assertEqual(previous_snapshot(led, latest, None),
                         ({"a": "open"}, latest["generatedAt"]))

    def test_latest_of_this_ledger_falls_back_to_the_rotated_previous(self):
        led = curate_ledger([])
        latest = previous({"a": "stale"})
        latest["ledgerGeneratedAt"] = LEDGER_AT
        older = previous({"a": "open"}, generated_at="2026-11-05T09:00:00+00:00")
        self.assertEqual(previous_snapshot(led, latest, older),
                         ({"a": "open"}, "2026-11-05T09:00:00+00:00"))
        self.assertEqual(previous_snapshot(led, latest, None), (None, None))

    def test_no_digest(self):
        self.assertEqual(previous_snapshot(curate_ledger([]), None, None), (None, None))


if __name__ == "__main__":
    unittest.main()
