import json
import os
import tempfile
import unittest

from tests.sessionfixtures import tool, user, write_jsonl
from work_ledger.sessions_parse import parse_transcript
from work_ledger.sessions_scan import CACHE_VERSION, scan_sessions


class ParseSpy:
    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, path):
        self.calls.append(os.path.basename(path))
        if os.path.basename(path) in self.fail_on:
            raise PermissionError("denied")
        return parse_transcript(path)


class _ScanBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name).replace("\\", "/")
        self.source = self.root + "/projects"
        self.cache = self.root + "/out/.cache/sessions-cache.json"
        self.claude = self.root + "/home/.claude"
        os.makedirs(self.root + "/repo/.git")

    def tearDown(self):
        self._tmp.cleanup()

    def transcript(self, project, sid, *records):
        return write_jsonl(f"{self.source}/{project}/{sid}.jsonl", *records)

    def scan(self, parse=None, full=False):
        # Fixtures live under the system temp dir, which the default filter would drop.
        kwargs = {"parse": parse} if parse else {}
        return scan_sessions(self.source, self.cache, full=full, claude_home=self.claude,
                             is_temp=lambda path: False, **kwargs)


class ScanTest(_ScanBase):
    def test_session_record_shape(self):
        self.transcript("proj", "s1",
                        user(uuid="a", ts="2026-11-01T10:00:00Z"),
                        tool("Write", {"file_path": self.root + "/repo/a.py"}, uuid="b",
                             ts="2026-11-01T10:01:00Z"))
        sessions, stats = self.scan()
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s["sessionId"], "s1")
        self.assertEqual(s["projectDir"], "proj")
        self.assertEqual(s["transcriptPath"], self.source + "/proj/s1.jsonl")
        self.assertEqual(s["writeAnchor"], {"path": self.root + "/repo", "share": 1.0})
        self.assertIsNone(s["fork"])
        self.assertNotIn("forkOf", s)
        self.assertEqual(s["subagentTranscripts"], 0)
        self.assertNotIn("messages", s)
        self.assertEqual(stats["files"], 1)
        self.assertEqual(stats["parsed"], 1)

    def test_subagents_counted_per_parent_not_emitted(self):
        self.transcript("proj", "s1", user())
        self.transcript("proj", "s2", user())
        for name in ("agent-1", "agent-2"):
            write_jsonl(f"{self.source}/proj/s1/subagents/{name}.jsonl", user())
        sessions, stats = self.scan()
        by_id = {s["sessionId"]: s for s in sessions}
        self.assertEqual(set(by_id), {"s1", "s2"})
        self.assertEqual(by_id["s1"]["subagentTranscripts"], 2)
        self.assertEqual(by_id["s2"]["subagentTranscripts"], 0)
        self.assertEqual(stats["files"], 2)

    def test_forks_across_projects(self):
        # Forks copy history with original uuids and timestamps.
        shared = [user(uuid="x1", ts="2026-11-01T10:00:00Z"), user(uuid="x2", ts="2026-11-01T10:01:00Z")]
        self.transcript("p1", "parent", *shared, user(uuid="p", ts="2026-11-01T10:02:00Z"))
        self.transcript("p2", "child", *shared, user(uuid="y", ts="2026-11-02T10:05:00Z"))
        sessions, _ = self.scan()
        by_id = {s["sessionId"]: s for s in sessions}
        self.assertEqual(by_id["child"]["fork"], {"familyId": "child", "members": ["parent"],
                                                  "sharedMessages": 2, "parent": "parent",
                                                  "divergedAt": "2026-11-02T10:05:00Z"})
        self.assertIsNone(by_id["parent"]["fork"]["parent"])

    def test_sorted_most_recent_first(self):
        self.transcript("p", "old", user(ts="2026-10-01T10:00:00Z"))
        self.transcript("p", "new", user(ts="2026-11-01T10:00:00Z"))
        self.transcript("p", "empty")
        sessions, _ = self.scan()
        self.assertEqual([s["sessionId"] for s in sessions], ["new", "old", "empty"])

    def test_skipped_lines_summed(self):
        self.transcript("p", "a", user(), "{bad", "nope")
        self.transcript("p", "b", "{bad")
        _, stats = self.scan()
        self.assertEqual(stats["skippedLines"], 3)

    def test_unreadable_file_does_not_stop_run(self):
        self.transcript("p", "a", user())
        self.transcript("p", "b", user())
        sessions, stats = self.scan(parse=ParseSpy(fail_on={"a.jsonl"}))
        self.assertEqual([s["sessionId"] for s in sessions], ["b"])
        self.assertEqual(stats["unreadable"], 1)
        self.assertEqual(stats["errors"][0]["path"], self.source + "/p/a.jsonl")
        self.assertIn("denied", stats["errors"][0]["error"])

    def test_default_filter_drops_temp_writes(self):
        self.transcript("proj", "s1", tool("Write", {"file_path": self.root + "/repo/a.py"}))
        sessions, _ = scan_sessions(self.source, self.cache, claude_home=self.claude)
        self.assertIsNone(sessions[0]["writeAnchor"])
        self.assertEqual(sessions[0]["writes"][0]["count"], 1)

    def test_missing_source_yields_empty_scan(self):
        sessions, stats = scan_sessions(self.root + "/absent", self.cache, claude_home=self.claude)
        self.assertEqual((sessions, stats["files"]), ([], 0))


class CacheTest(_ScanBase):
    def test_unchanged_file_is_not_reparsed(self):
        self.transcript("p", "a", user(uuid="a1"), tool("Bash", {"command": "git push"}))
        first, _ = self.scan(parse=ParseSpy())
        spy = ParseSpy()
        second, stats = self.scan(parse=spy)
        self.assertEqual(spy.calls, [])
        self.assertEqual((stats["parsed"], stats["cached"]), (0, 1))
        self.assertEqual(first, second)

    def test_changed_file_is_reparsed(self):
        path = self.transcript("p", "a", user())
        self.scan()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(user()) + "\n")
        spy = ParseSpy()
        sessions, stats = self.scan(parse=spy)
        self.assertEqual(spy.calls, ["a.jsonl"])
        self.assertEqual(sessions[0]["userMessages"], 2)
        self.assertEqual(stats["cached"], 0)

    def test_full_bypasses_cache(self):
        self.transcript("p", "a", user())
        self.scan()
        spy = ParseSpy()
        _, stats = self.scan(parse=spy, full=True)
        self.assertEqual(spy.calls, ["a.jsonl"])
        self.assertEqual((stats["parsed"], stats["cached"]), (1, 0))

    def test_corrupt_cache_is_ignored(self):
        self.transcript("p", "a", user())
        os.makedirs(os.path.dirname(self.cache))
        with open(self.cache, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        sessions, stats = self.scan()
        self.assertEqual((len(sessions), stats["parsed"]), (1, 1))

    def test_failed_file_is_retried_next_run(self):
        self.transcript("p", "a", user())
        self.scan(parse=ParseSpy(fail_on={"a.jsonl"}))
        spy = ParseSpy()
        self.scan(parse=spy)
        self.assertEqual(spy.calls, ["a.jsonl"])

    def test_cache_version_is_4_and_older_caches_are_reparsed(self):
        self.assertEqual(CACHE_VERSION, 4)
        self.transcript("p", "a", user())
        self.scan()
        with open(self.cache, encoding="utf-8") as fh:
            cached = json.load(fh)
        self.assertEqual(cached["schemaVersion"], 4)
        cached["schemaVersion"] = 3
        with open(self.cache, "w", encoding="utf-8") as fh:
            json.dump(cached, fh)
        spy = ParseSpy()
        self.scan(parse=spy)
        self.assertEqual(spy.calls, ["a.jsonl"])

    def test_cache_drops_deleted_transcripts(self):
        path = self.transcript("p", "a", user())
        self.transcript("p", "b", user())
        self.scan()
        os.remove(path)
        self.scan()
        with open(self.cache, encoding="utf-8") as fh:
            cached = json.load(fh)
        self.assertEqual(list(cached["files"]), [self.source + "/p/b.jsonl"])


if __name__ == "__main__":
    unittest.main()
