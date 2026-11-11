import unittest

from tests.digestfixtures import LEDGER_AT, git, ledger, previous, project, thread
from work_ledger.digest_build import RECAP_PREVIEW, build_digest


class AtRiskRecentTest(unittest.TestCase):
    def test_lists_recent_at_risk_threads_with_git_facts(self):
        d = build_digest(ledger([
            thread("a", "at-risk", title="Fix", days=3, git=git("unpushed", 2)),
            thread("b", "at-risk", days=40, git=git("modified")),
            thread("c", "open", days=1)]))
        self.assertEqual(d["atRiskRecent"], [
            {"id": "a", "title": "Fix", "project": "app", "daysIdle": 3, "risk": "unpushed",
             "notOnRemote": 2}])

    def test_keeps_ledger_order(self):
        d = build_digest(ledger([thread("x", "at-risk", days=5, git=git()),
                                 thread("y", "at-risk", days=2, git=git())]))
        self.assertEqual([t["id"] for t in d["atRiskRecent"]], ["x", "y"])

    def test_excluded_override_states(self):
        threads = [thread(t, "at-risk", git=git(), override=o)
                   for t, o in (("d", "done"), ("x", "discarded"), ("p", "paused"))]
        self.assertEqual(build_digest(ledger(threads))["atRiskRecent"], [])

    def test_unknown_project_name(self):
        d = build_digest(ledger([thread("a", "at-risk", project="nope", git=git())]))
        self.assertIsNone(d["atRiskRecent"][0]["project"])


class NoBackupTest(unittest.TestCase):
    def test_projects_and_threads_with_commits_on_no_remote(self):
        d = build_digest(ledger(
            [thread("a", "at-risk", git=git("unpushed", 3)),
             thread("b", "open", git=git("safe", 0)),
             thread("c", "done", override="done", git=git("unpushed", 1))],
            [project("p-app", "app", risk="unpushed", not_on_remote=4),
             project("p-x", "x", risk="safe"), project("p-dir", "notes", risk=None)]))
        nb = d["noBackup"]
        self.assertEqual(nb["projects"], [{"id": "p-app", "name": "app", "risk": "unpushed",
                                           "notOnRemote": 4}])
        # Overrides do not hide unbacked commits.
        self.assertEqual([(t["id"], t["notOnRemote"]) for t in nb["threads"]],
                         [("a", 3), ("c", 1)])
        self.assertEqual(nb["total"], 8)

    def test_thread_on_the_main_worktree_branch_is_not_counted_twice(self):
        d = build_digest(ledger(
            [thread("a", "at-risk", git=git("unpushed", 4, repo="C:/r/app", branch="main"))],
            [project("p-app", "app", risk="unpushed", not_on_remote=4)]))
        self.assertEqual(d["noBackup"]["threads"], [])
        self.assertEqual(d["noBackup"]["total"], 4)

    def test_missing_counts_are_zero(self):
        d = build_digest(ledger([thread("a", "at-risk", git=git(not_on_remote=None))],
                                [project("p-app", "app", not_on_remote=None)]))
        self.assertEqual(d["noBackup"], {"projects": [], "threads": [], "total": 0})


class GoingColdTest(unittest.TestCase):
    def test_open_or_active_idle_seven_days_or_more(self):
        d = build_digest(ledger([
            thread("a", "open", days=7, lead="s-a", recap="R" * 200, ask="Merge it?"),
            thread("b", "active", override="active", days=12, lead="s-b"),
            thread("c", "open", days=6, lead="s-c"),
            thread("d", "stale", days=40, lead="s-d"),
            thread("e", "open", days=None, lead="s-e")]))
        cold = d["goingCold"]
        self.assertEqual([t["id"] for t in cold], ["a", "b"])
        self.assertEqual(cold[0]["recap"], "R" * RECAP_PREVIEW)
        self.assertEqual(RECAP_PREVIEW, 160)
        self.assertEqual(cold[0]["ask"], "Merge it?")
        self.assertEqual(cold[0]["resume"], "claude --resume s-a")
        self.assertEqual(cold[1]["state"], "active")
        self.assertIsNone(cold[1]["recap"])

    def test_thread_without_lead_has_no_resume_command(self):
        d = build_digest(ledger([thread("a", "open", days=9)]))
        self.assertIsNone(d["goingCold"][0]["resume"])

    def test_excluded_override_states(self):
        d = build_digest(ledger([thread("a", "open", days=9, override="paused")]))
        self.assertEqual(d["goingCold"], [])


class WentStaleTest(unittest.TestCase):
    def test_stale_now_and_not_stale_or_absent_before(self):
        d = build_digest(ledger([
            thread("a", "stale", days=31), thread("b", "stale", days=50),
            thread("c", "stale", days=35), thread("d", "open")]),
            previous({"a": "open", "b": "stale", "d": "open"}))
        self.assertEqual([(t["id"], t["title"], t["project"]) for t in d["wentStale"]],
                         [("a", "Thread a", "app"), ("c", "Thread c", "app")])

    def test_no_previous_snapshot_means_no_comparison(self):
        d = build_digest(ledger([thread("a", "stale", days=31)]))
        self.assertIsNone(d["wentStale"])
        self.assertIsNone(d["previousGeneratedAt"])

    def test_excluded_override_states(self):
        d = build_digest(ledger([thread("a", "stale", days=31, override="discarded")]),
                         previous({}))
        self.assertEqual(d["wentStale"], [])


class CountsTest(unittest.TestCase):
    def test_older_at_risk_per_project(self):
        d = build_digest(ledger(
            [thread("a", "at-risk", days=40, git=git()),
             thread("b", "at-risk", days=90, git=git()),
             thread("c", "at-risk", days=50, project="p-x", git=git()),
             thread("d", "at-risk", days=2, git=git())],
            [project("p-app", "app"), project("p-x", "x")]))
        self.assertEqual(d["olderAtRisk"], [{"projectId": "p-app", "project": "app", "count": 2},
                                            {"projectId": "p-x", "project": "x", "count": 1}])

    def test_state_totals_with_change_since_previous(self):
        d = build_digest(ledger([thread("a", "at-risk", git=git()), thread("b", "open"),
                                 thread("c", "open"), thread("e", "custom")]),
                         previous({"a": "open", "b": "open", "z": "stale"}))
        self.assertEqual(d["states"], [
            {"state": "at-risk", "count": 1, "change": 1},
            {"state": "open", "count": 2, "change": 0},
            {"state": "stale", "count": 0, "change": -1},
            {"state": "custom", "count": 1, "change": 1}])

    def test_state_totals_without_previous_have_no_change(self):
        d = build_digest(ledger([thread("b", "open")]))
        self.assertEqual(d["states"], [{"state": "open", "count": 1, "change": None}])

    def test_counts_and_snapshot(self):
        d = build_digest(ledger(
            [thread("a", "at-risk", git=git("unpushed", 2)), thread("b", "open", days=8),
             thread("c", "done", override="done")],
            [project("p-app", "app", not_on_remote=1)]))
        self.assertEqual(d["counts"], {"atRiskRecent": 1, "goingCold": 1,
                                       "notOnRemoteCommits": 3, "wentStale": None,
                                       "effectiveStates": {"at-risk": 1, "open": 1, "done": 1}})
        self.assertEqual(d["snapshot"], {"a": "at-risk", "b": "open", "c": "done"})
        self.assertEqual(d["ledgerGeneratedAt"], LEDGER_AT)

    def test_previous_without_snapshot_counts_as_no_previous(self):
        d = build_digest(ledger([thread("a", "stale", days=31)]), {"schemaVersion": 1})
        self.assertIsNone(d["wentStale"])

    def test_pure_does_not_mutate_inputs(self):
        led = ledger([thread("a", "open", days=9, recap="r")])
        prev = previous({"a": "open"})
        before = (repr(led), repr(prev))
        build_digest(led, prev)
        self.assertEqual((repr(led), repr(prev)), before)


if __name__ == "__main__":
    unittest.main()
