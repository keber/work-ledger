import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from work_ledger.sessions_report import build_sessions_report, render_sessions_markdown, \
    write_sessions_reports

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
NO_ACTIONS = {a: {"count": 0, "lastAt": None} for a in ("commit", "push", "merge", "pr-create")}


def session(sid, last_at, anchor=None, cwd="C:/w", **extra):
    record = {"sessionId": sid, "transcriptPath": f"/p/{sid}.jsonl", "projectDir": "p",
              "title": None, "titleSource": None, "firstAt": last_at, "lastAt": last_at,
              "userMessages": 1, "assistantMessages": 1, "subagentTranscripts": 0,
              "cwds": [{"path": cwd, "count": 1}] if cwd else [], "relocatedCwd": None,
              "gitBranches": [], "writes": [], "gitActions": dict(NO_ACTIONS),
              "closure": {"lastRecap": None, "lastAsk": None, "sessionSummarySaved": False,
                          "endedWithQuestion": False},
              "lastPrompt": None, "malformedLines": 0,
              "writeAnchor": {"path": anchor, "share": 1.0} if anchor else None, "fork": None}
    record.update(extra)
    return record


STATS = {"files": 3, "parsed": 2, "cached": 1, "skippedLines": 0, "unreadable": 0, "errors": []}


class BuildTest(unittest.TestCase):
    def test_envelope(self):
        report = build_sessions_report([], STATS, "C:/home/.claude/projects", generated_at=NOW)
        self.assertEqual(report["schemaVersion"], 3)
        self.assertEqual(report["generatedAt"], NOW.isoformat())
        self.assertEqual(report["sourceRoot"], "C:/home/.claude/projects")
        self.assertEqual(report["stats"], STATS)
        self.assertEqual(report["sessions"], [])


class MarkdownTest(unittest.TestCase):
    def render(self, sessions):
        return render_sessions_markdown(build_sessions_report(sessions, STATS, "/src", NOW))

    def test_grouped_by_anchor_then_cwd_most_recent_first(self):
        md = self.render([
            session("s-new", "2026-11-03T10:00:00Z", anchor="C:/repo/b"),
            session("s-mid", "2026-11-02T10:00:00Z", anchor=None, cwd="C:/only/cwd"),
            session("s-old", "2026-11-01T10:00:00Z", anchor="C:/repo/a"),
            session("s-a2", "2026-11-02T12:00:00Z", anchor="C:/repo/a"),
            session("s-none", None, anchor=None, cwd=None),
        ])
        order = [md.index(h) for h in ("## C:/repo/b", "## C:/repo/a", "## C:/only/cwd",
                                       "## (unknown)")]
        self.assertEqual(order, sorted(order))
        self.assertLess(md.index("s-a2"), md.index("s-old"))

    def test_session_row_details(self):
        actions = dict(NO_ACTIONS, commit={"count": 2, "lastAt": "t"}, push={"count": 1, "lastAt": "t"})
        md = self.render([session(
            "abcdef1234", "2026-11-03T10:00:00Z", anchor="C:/r", title="Fix | pipes",
            gitBranches=[{"name": "feat/x", "count": 3}], gitActions=actions,
            closure={"lastRecap": "Done.\nAll good", "lastAsk": "Commit?",
                     "sessionSummarySaved": True, "endedWithQuestion": True},
            fork={"familyId": "family-root-id", "members": ["parent-session-id"],
                  "sharedMessages": 12, "parent": "parent-session-id",
                  "divergedAt": "2026-11-03T09:00:00Z"})])
        self.assertIn("Fix \\| pipes", md)
        self.assertIn("feat/x", md)
        self.assertIn("commit 2", md)
        self.assertIn("push 1", md)
        self.assertNotIn("merge 0", md)
        self.assertIn("Done. All good", md)
        self.assertIn("family family-r (2)", md)
        self.assertIn("fork of parent-s", md)
        self.assertIn("summary", md)

    def test_family_without_known_parent(self):
        md = self.render([session("s1", "2026-11-03T10:00:00Z", fork={
            "familyId": "s1", "members": ["s2", "s3"], "sharedMessages": 4, "parent": None,
            "divergedAt": None})])
        self.assertIn("family s1 (3)", md)
        self.assertNotIn("fork of", md)

    def test_untitled_session_uses_short_id(self):
        md = self.render([session("0123456789abcdef", "2026-11-03T10:00:00Z")])
        self.assertIn("(untitled 01234567)", md)


class WriteTest(unittest.TestCase):
    def test_writes_both_files(self):
        report = build_sessions_report([session("s", "2026-11-03T10:00:00Z")], STATS, "/src", NOW)
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_sessions_reports(report, os.path.join(tmp, "out"))
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertTrue(md_path.endswith("sessions.md") and os.path.isfile(md_path))
        self.assertTrue(json_path.endswith("sessions.json"))
        self.assertEqual(data["sessions"][0]["sessionId"], "s")


if __name__ == "__main__":
    unittest.main()
