import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from work_ledger.report import build_report, render_markdown, write_reports


def wt(path, risk, is_main=False, **extra):
    item = {"path": path, "branch": "b", "head": "abc", "detached": False, "exists": True,
            "locked": False, "prunable": False, "isMain": is_main,
            "dirty": {"staged": 0, "unstaged": 0, "untracked": 0, "ignoredUntracked": 0},
            "upstream": None, "upstreamGone": False, "ahead": None, "behind": None,
            "notOnRemote": 0, "merged": True,
            "lastCommit": {"date": "2026-11-01T10:00:00+00:00", "subject": "s", "isOwn": True},
            "error": None, "risk": risk}
    item.update(extra)
    return item


def br(name, risk, **extra):
    item = {"name": name, "upstream": None, "upstreamGone": False, "ahead": None,
            "behind": None, "notOnRemote": 0, "merged": False,
            "lastCommit": {"date": None, "subject": "x", "isOwn": True},
            "error": None, "risk": risk}
    item.update(extra)
    return item


def repo(path, risk, worktrees=(), branches=(), error=None):
    return {"path": path, "commonDir": path + "/.git", "defaultBranch": "main",
            "hasRemotes": False, "lastFetch": None, "error": error, "risk": risk,
            "worktrees": list(worktrees), "branches": list(branches)}


NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


class BuildReportTest(unittest.TestCase):
    def setUp(self):
        self.repos = [
            repo("C:/r/safe", "main", [wt("C:/r/safe", "main", True)]),
            repo("C:/r/hot", "modified",
                 [wt("C:/r/hot", "modified", True)],
                 [br("f", "unpushed"), br("g", "safe"), br("h", "pushed"), br("i", "untracked")]),
            repo("C:/r/bad", "unknown", error="fatal: boom"),
        ]
        self.report = build_report(self.repos, ["C:/r"], generated_at=NOW)

    def test_versioned_envelope(self):
        self.assertEqual(self.report["schemaVersion"], 2)
        self.assertEqual(self.report["generatedAt"], "2026-11-04T12:00:00+00:00")
        self.assertEqual(self.report["roots"], ["C:/r"])

    def test_repos_sorted_worst_first(self):
        self.assertEqual([r["path"] for r in self.report["repos"]],
                         ["C:/r/hot", "C:/r/bad", "C:/r/safe"])

    def test_summary_counts_items_and_failed_repos(self):
        summary = self.report["summary"]
        self.assertEqual(summary["repos"], 3)
        self.assertEqual(list(summary["risks"]), ["modified", "unpushed", "untracked", "unknown",
                                                  "missing", "pushed", "main", "safe"])
        self.assertEqual(summary["risks"]["modified"], 1)
        self.assertEqual(summary["risks"]["unpushed"], 1)
        self.assertEqual(summary["risks"]["untracked"], 1)
        self.assertEqual(summary["risks"]["pushed"], 1)
        self.assertEqual(summary["risks"]["safe"], 1)
        self.assertEqual(summary["risks"]["main"], 1)
        self.assertEqual(summary["risks"]["unknown"], 1)  # the failed repo
        self.assertEqual(summary["risks"]["missing"], 0)

    def test_records_ignore_untracked_prefixes(self):
        report = build_report([], [], generated_at=NOW, ignore_untracked=[".atl/", "ref/"])
        self.assertEqual(report["ignoreUntracked"], [".atl/", "ref/"])

    def test_json_serializable(self):
        json.dumps(self.report)


class MarkdownTest(unittest.TestCase):
    def test_contains_summary_and_repos_in_order(self):
        report = build_report([
            repo("C:/r/a", "main", [wt("C:/r/a", "main", True)]),
            repo("C:/r/b", "unpushed", [wt("C:/r/b", "main", True)], [br("feat", "unpushed")]),
            repo("C:/r/c", "unknown", error="fatal: boom"),
        ], ["C:/r"], generated_at=NOW)
        md = render_markdown(report)
        self.assertIn("# Git inventory", md)
        self.assertIn("| unpushed | 1 |", md)
        self.assertLess(md.index("## C:/r/b"), md.index("## C:/r/c"))
        self.assertLess(md.index("## C:/r/c"), md.index("## C:/r/a"))
        self.assertIn("fatal: boom", md)
        self.assertIn("feat", md)
        self.assertIn("(main)", md)

    def test_new_risk_values_in_summary(self):
        md = render_markdown(build_report([], [], generated_at=NOW))
        for risk in ("modified", "untracked", "pushed"):
            self.assertIn(f"| {risk} | 0 |", md)
        self.assertNotIn("uncommitted", md)
        self.assertNotIn("unmerged", md)

    def test_non_own_items_tagged_others(self):
        theirs = {"date": None, "subject": "theirs", "isOwn": False}
        unset = {"date": None, "subject": "unset", "isOwn": None}
        report = build_report([repo("C:/r/a", "pushed",
                                    [wt("C:/r/a-wt", "pushed", lastCommit=theirs)],
                                    [br("team", "pushed", lastCommit=theirs),
                                     br("mine", "safe"), br("anon", "safe", lastCommit=unset)])],
                              [], generated_at=NOW)
        md = render_markdown(report)
        lines = md.splitlines()
        self.assertIn("[others]", next(l for l in lines if "C:/r/a-wt" in l and l.startswith("|")))
        self.assertIn("[others]", next(l for l in lines if "| team" in l))
        self.assertNotIn("[others]", next(l for l in lines if "| mine" in l))
        self.assertNotIn("[others]", next(l for l in lines if "| anon" in l))

    def test_not_on_remote_shown_when_positive(self):
        report = build_report([repo("C:/r/a", "unpushed", [],
                                    [br("ahead", "unpushed", notOnRemote=3), br("even", "safe")])],
                              [], generated_at=NOW)
        lines = render_markdown(report).splitlines()
        self.assertIn("not on remote", "\n".join(lines))
        self.assertIn("3", next(l for l in lines if "| ahead" in l).split("|")[3])
        self.assertNotIn("0", next(l for l in lines if "| even" in l).split("|")[3])

    def test_ignored_untracked_shown_in_dirty(self):
        d = {"staged": 0, "unstaged": 0, "untracked": 1, "ignoredUntracked": 2}
        report = build_report([repo("C:/r/a", "untracked", [wt("C:/r/a", "untracked", True, dirty=d)])],
                              [], generated_at=NOW)
        self.assertIn("0/0/1 (+2 ignored)", render_markdown(report))

    def test_pipes_in_subject_are_escaped(self):
        item = wt("C:/r/a", "main", True, lastCommit={"date": None, "subject": "a | b"})
        md = render_markdown(build_report([repo("C:/r/a", "main", [item])], [], generated_at=NOW))
        self.assertIn("a \\| b", md)


class WriteReportsTest(unittest.TestCase):
    def test_writes_json_and_markdown(self):
        report = build_report([], [], generated_at=NOW)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nested", "out")
            json_path, md_path = write_reports(report, out)
            with open(json_path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["schemaVersion"], 2)
            self.assertTrue(json_path.endswith("git-inventory.json"))
            self.assertTrue(md_path.endswith("git-inventory.md"))
            self.assertTrue(os.path.isfile(md_path))


if __name__ == "__main__":
    unittest.main()
