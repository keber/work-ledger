import json
import os
import tempfile
import unittest

from tests.threadfixtures import NOW, br, inventory, repo, session, sessions_report, wt
from work_ledger.threads_build import build_ledger
from work_ledger.threads_report import render_ledger_markdown, write_ledger

INV = inventory(repo("C:/r/app", [wt("C:/r/app", "main", is_main=True),
                                  wt("C:/r/app/.wt/f", "feat/x", risk="unpushed",
                                     notOnRemote=2)],
                     [br("old", risk="safe"),
                      br("ancient", risk="modified",
                         lastCommit={"date": "2026-01-01T10:00:00+00:00", "subject": "x",
                                     "isOwn": True})]),
                repo("C:/r/team", [wt("C:/r/team", "main", is_main=True, risk="unpushed",
                                      notOnRemote=4)]))


def ledger():
    return build_ledger(INV, sessions_report(
        session("s1", "2026-11-03T10:00:00Z", cwd="C:/r/app/.wt/f", title="Fix | pipes",
                recap="R" * 200),
        session("s2", "2026-10-01T10:00:00Z", anchor="C:/notes/plan", recap="Closed.")),
        None, generated_at=NOW)


class MarkdownTest(unittest.TestCase):
    def test_sections_in_state_order_and_thread_lines(self):
        md = render_ledger_markdown(ledger())
        self.assertLess(md.index("## at-risk"), md.index("## likely-done"))
        self.assertNotIn("## open", md)
        self.assertIn("Fix \\| pipes", md)
        self.assertIn("git:app#feat/x", md)
        self.assertIn("2026-11-03 (1d idle)", md)
        self.assertIn("unpushed, 2 not on remote", md)
        self.assertIn("1 session", md)
        self.assertIn("R" * 120, md)
        self.assertNotIn("R" * 121, md)
        self.assertIn("dir:plan", md)

    def test_projects_at_risk_section_comes_first(self):
        md = render_ledger_markdown(ledger())
        self.assertLess(md.index("## Projects at risk"), md.index("## at-risk"))
        section = md[md.index("## Projects at risk"):md.index("## at-risk")]
        self.assertIn("**team**", section)
        self.assertIn("main worktree: unpushed, 4 not on remote", section)
        self.assertIn("0 at-risk threads", section)
        self.assertIn("**app**", section)
        self.assertIn("2 at-risk threads", section)
        self.assertNotIn("plan", section)

    def test_no_projects_at_risk(self):
        data = ledger()
        data["projects"] = [p for p in data["projects"] if not p["atRisk"]]
        md = render_ledger_markdown(data)
        self.assertIn("## Projects at risk\n\n- none", md)

    def test_thread_lines_prefixed_with_project_name(self):
        md = render_ledger_markdown(ledger())
        self.assertIn("- app · **Fix \\| pipes**", md)
        self.assertIn("- plan · **plan**", md)

    def test_at_risk_split_into_recent_and_older(self):
        md = render_ledger_markdown(ledger())
        at_risk = md[md.index("## at-risk"):md.index("## likely-done")]
        recent = at_risk.index("### recent")
        older = at_risk.index("### older than 30 days")
        self.assertLess(recent, at_risk.index("Fix \\| pipes"))
        self.assertLess(at_risk.index("Fix \\| pipes"), older)
        self.assertLess(older, at_risk.index("app · ancient"))

    def test_inventory_only_lines_not_prefixed_again(self):
        md = render_ledger_markdown(ledger())
        self.assertIn("- **app · ancient**", md)
        self.assertNotIn("app · **app · ancient**", md)

    def test_warnings_listed(self):
        data = ledger()
        data["warnings"] = ["merge: unknown thread id abc"]
        self.assertIn("unknown thread id abc", render_ledger_markdown(data))


class WriteTest(unittest.TestCase):
    def test_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_ledger(ledger(), os.path.join(tmp, "out"))
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertTrue(os.path.isfile(md_path))
        self.assertTrue(json_path.endswith("ledger.json"))
        self.assertTrue(md_path.endswith("ledger.md"))
        self.assertEqual(data["schemaVersion"], 2)


if __name__ == "__main__":
    unittest.main()
