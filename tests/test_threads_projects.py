"""Projects and default-branch threads (ledger schemaVersion 2)."""

import unittest

from tests.threadfixtures import (NOW, br, fork, inventory, overrides, repo, session,
                                  sessions_report, wt)
from work_ledger.threads_build import build_ledger
from work_ledger.threads_identity import project_id, thread_id

INV = inventory(
    repo("C:/r/app", [wt("C:/r/app", "main", is_main=True, risk="modified", notOnRemote=2,
                         lastCommit={"date": "2026-10-20T10:00:00+00:00", "subject": "s",
                                     "isOwn": True}),
                      wt("C:/r/app/.wt/feat", "feat/x", risk="unpushed", notOnRemote=3),
                      wt("C:/r/app-agent", detached=True, risk="modified")],
         [br("wip", risk="untracked")]),
    repo("C:/r/quiet", [wt("C:/r/quiet", "main", is_main=True, risk="unpushed", notOnRemote=1,
                           lastCommit={"date": "2026-06-01T10:00:00+00:00", "subject": "q",
                                       "isOwn": True})]),
    repo("C:/r/clean", [wt("C:/r/clean", "main", is_main=True, risk="safe")]),
)


def build(*sessions, inv=INV, ovr=None):
    return build_ledger(inv, sessions_report(*sessions), ovr, generated_at=NOW)


def threads_by_key(ledger):
    return {t["key"]: t for t in ledger["threads"]}


def projects_by_key(ledger):
    return {p["key"]: p for p in ledger["projects"]}


class DefaultBranchThreadTest(unittest.TestCase):
    def test_sessions_on_default_branch_split_per_session(self):
        threads = threads_by_key(build(session("a", cwd="C:/r/app"), session("b", cwd="C:/r/app")))
        self.assertIn("git:C:/r/app#main~session:a", threads)
        self.assertIn("git:C:/r/app#main~session:b", threads)

    def test_fork_family_on_default_branch_is_one_thread(self):
        threads = threads_by_key(build(
            session("p", "2026-11-01T10:00:00Z", cwd="C:/r/app", fork=fork("p", ["c"], 5)),
            session("c", "2026-11-02T10:00:00Z", cwd="C:/r/app", fork=fork("p", ["p"], 5, "p"))))
        t = threads["git:C:/r/app#main~family:p"]
        self.assertEqual(t["sessions"], ["c", "p"])
        self.assertEqual(t["related"], [])

    def test_default_branch_thread_has_project_git_scope_and_ignores_risk(self):
        t = threads_by_key(build(session("a", cwd="C:/r/app")))["git:C:/r/app#main~session:a"]
        self.assertEqual((t["gitScope"], t["git"]), ("project", None))
        # The main worktree is `modified`, but that risk belongs to the project.
        self.assertEqual(t["suggestedState"], "open")

    def test_default_branch_thread_can_be_likely_done_by_recap(self):
        t = threads_by_key(build(session("a", "2026-10-01T10:00:00Z", cwd="C:/r/app",
                                         recap="Done.")))["git:C:/r/app#main~session:a"]
        self.assertEqual(t["suggestedState"], "likely-done")

    def test_feature_and_detached_threads_keep_thread_git(self):
        threads = threads_by_key(build(session("f", cwd="C:/r/app/.wt/feat"),
                                       session("d", cwd="C:/r/app-agent")))
        feat = threads["git:C:/r/app#feat/x"]
        self.assertEqual((feat["gitScope"], feat["git"]["risk"]), ("thread", "unpushed"))
        self.assertEqual(threads["git:C:/r/app@C:/r/app-agent"]["gitScope"], "thread")

    def test_non_git_threads_have_no_git_scope(self):
        threads = threads_by_key(build(session("n", anchor="C:/n"), session("x", cwd="C:/c")))
        self.assertIsNone(threads["dir:C:/n"]["gitScope"])
        self.assertIsNone(threads["session:x"]["gitScope"])

    def test_git_bash_write_anchor_joins_the_repo_thread(self):
        threads = threads_by_key(build(session("g", anchor="/c/r/app/.wt/feat", cwd="/c/x")))
        self.assertEqual(threads["git:C:/r/app#feat/x"]["sessions"], ["g"])


class InventoryOnlyTest(unittest.TestCase):
    def test_at_risk_main_worktree_is_not_a_thread(self):
        keys = set(threads_by_key(build()))
        self.assertEqual(keys, {"git:C:/r/app#feat/x", "git:C:/r/app@C:/r/app-agent",
                                "git:C:/r/app#wip"})

    def test_titles_carry_the_repo_name(self):
        threads = threads_by_key(build())
        self.assertEqual(threads["git:C:/r/app#feat/x"]["title"], "app \u00b7 feat/x")
        self.assertEqual(threads["git:C:/r/app@C:/r/app-agent"]["title"], "app \u00b7 app-agent")

    def test_inventory_only_threads_belong_to_the_repo_project(self):
        ledger = build()
        for t in ledger["threads"]:
            self.assertEqual(t["projectId"], project_id("repo:C:/r/app"))
            self.assertEqual(t["gitScope"], "thread")


class ProjectRecordTest(unittest.TestCase):
    def test_repo_project_fields(self):
        ledger = build(session("a", "2026-11-03T10:00:00Z", cwd="C:/r/app"),
                       session("f", "2026-11-01T10:00:00Z", cwd="C:/r/app/.wt/feat"))
        p = projects_by_key(ledger)["repo:C:/r/app"]
        self.assertEqual(p["id"], project_id("repo:C:/r/app"))
        self.assertEqual((p["kind"], p["name"], p["path"], p["domain"]),
                         ("repo", "app", "C:/r/app", "work"))
        self.assertEqual(p["git"], {
            "defaultBranch": "main", "branch": "main", "worktreePath": "C:/r/app",
            "risk": "modified", "notOnRemote": 2, "dirty": p["git"]["dirty"],
            "lastCommit": {"date": "2026-10-20T10:00:00+00:00", "subject": "s", "isOwn": True}})
        self.assertEqual(p["threadCount"], 4)
        self.assertEqual(sorted(p["threadIds"]), sorted(
            thread_id(k) for k in ("git:C:/r/app#main~session:a", "git:C:/r/app#feat/x",
                                   "git:C:/r/app@C:/r/app-agent", "git:C:/r/app#wip")))
        self.assertEqual(p["sessionCount"], 2)
        self.assertEqual((p["lastAt"], p["daysIdle"], p["recency"]),
                         ("2026-11-03T10:00:00Z", 1, "recent"))
        self.assertTrue(p["atRisk"])

    def test_thread_project_id(self):
        t = threads_by_key(build(session("a", cwd="C:/r/app")))["git:C:/r/app#main~session:a"]
        self.assertEqual(t["projectId"], project_id("repo:C:/r/app"))

    def test_repo_without_sessions_and_at_risk_main_is_a_project_without_threads(self):
        projects = projects_by_key(build())
        p = projects["repo:C:/r/quiet"]
        self.assertEqual((p["threadIds"], p["threadCount"], p["sessionCount"]), ([], 0, 0))
        self.assertEqual(p["lastAt"], "2026-06-01T10:00:00+00:00")
        self.assertEqual((p["daysIdle"], p["recency"]), (156, "old"))
        self.assertTrue(p["atRisk"])
        self.assertEqual((p["git"]["risk"], p["git"]["notOnRemote"]), ("unpushed", 1))
        self.assertNotIn("repo:C:/r/clean", projects)

    def test_dir_and_session_projects(self):
        ledger = build(session("n", anchor="C:/notes/plan", cwd="C:/ClaudeSession"),
                       session("x", cwd="C:/ClaudeSession"),
                       session("y", cwd="C:/ClaudeSession"))
        projects = projects_by_key(ledger)
        plan, cs = projects["dir:C:/notes/plan"], projects["dir:C:/ClaudeSession"]
        self.assertEqual((plan["kind"], plan["name"], plan["path"], plan["git"]),
                         ("dir", "plan", "C:/notes/plan", None))
        self.assertEqual((cs["threadCount"], cs["sessionCount"], cs["name"]),
                         (2, 2, "ClaudeSession"))
        self.assertFalse(cs["atRisk"])
        threads = threads_by_key(ledger)
        self.assertEqual(threads["session:x"]["projectId"], project_id("dir:C:/ClaudeSession"))

    def test_project_at_risk_through_a_thread(self):
        inv = inventory(repo("C:/r/lib", [wt("C:/r/lib", "main", is_main=True, risk="safe"),
                                          wt("C:/r/lib/.wt/b", "b", risk="unpushed")]))
        p = projects_by_key(build(session("s", cwd="C:/r/lib/.wt/b"), inv=inv))["repo:C:/r/lib"]
        self.assertEqual(p["git"]["risk"], "safe")
        self.assertTrue(p["atRisk"])

    def test_project_not_at_risk_when_thread_overridden(self):
        inv = inventory(repo("C:/r/lib", [wt("C:/r/lib", "main", is_main=True, risk="safe"),
                                          wt("C:/r/lib/.wt/b", "b", risk="unpushed")]))
        tid = thread_id("git:C:/r/lib#b")
        ledger = build(session("s", cwd="C:/r/lib/.wt/b"), inv=inv,
                       ovr=overrides({tid: {"state": "paused"}}))
        self.assertFalse(projects_by_key(ledger)["repo:C:/r/lib"]["atRisk"])

    def test_merged_thread_keeps_its_project(self):
        into = thread_id("dir:C:/a")
        gone = thread_id("dir:C:/b")
        ledger = build(session("a", anchor="C:/a"), session("b", anchor="C:/b"),
                       ovr=overrides(merge=[{"into": into, "from": [gone]}]))
        projects = projects_by_key(ledger)
        self.assertNotIn("dir:C:/b", projects)
        self.assertEqual(projects["dir:C:/a"]["sessionCount"], 2)


class RecencyAndOrderTest(unittest.TestCase):
    def test_thread_recency(self):
        threads = threads_by_key(build(session("r", "2026-11-03T10:00:00Z", anchor="C:/r1"),
                                       session("o", "2026-08-01T10:00:00Z", anchor="C:/o1")))
        self.assertEqual(threads["dir:C:/r1"]["recency"], "recent")
        self.assertEqual(threads["dir:C:/o1"]["recency"], "old")

    def test_projects_sorted_at_risk_first_then_last_at_desc(self):
        ledger = build(session("a", "2026-11-03T10:00:00Z", anchor="C:/n1"),
                       session("b", "2026-11-04T10:00:00Z", anchor="C:/n2"))
        self.assertEqual([p["key"] for p in ledger["projects"]],
                         ["repo:C:/r/app", "repo:C:/r/quiet", "dir:C:/n2", "dir:C:/n1"])

    def test_stats_projects(self):
        self.assertEqual(build(session("a", anchor="C:/n1"))["stats"]["projects"], 3)


if __name__ == "__main__":
    unittest.main()
