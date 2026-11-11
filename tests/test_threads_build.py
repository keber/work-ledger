import unittest

from tests.threadfixtures import (NOW, br, fork, inventory, overrides, repo, session,
                                  sessions_report, wt)
from work_ledger.threads_build import build_ledger
from work_ledger.threads_identity import thread_id

INV = inventory(
    repo("C:/r/app", [wt("C:/r/app", "main", is_main=True),
                      wt("C:/r/app/.wt/feat", "feat/x", risk="unpushed", notOnRemote=3,
                         dirty={"staged": 0, "unstaged": 0, "untracked": 0,
                                "ignoredUntracked": 0}),
                      wt("C:/r/app-agent", detached=True, risk="modified")],
         [br("pushed-one", risk="pushed", merged=False), br("done-one", risk="safe"),
          br("wip", risk="untracked")]),
)


def build(*sessions, inv=INV, ovr=None):
    return build_ledger(inv, sessions_report(*sessions), ovr, generated_at=NOW)


def by_key(ledger):
    return {t["key"]: t for t in ledger["threads"]}


class EnvelopeTest(unittest.TestCase):
    def test_envelope_and_stats(self):
        ledger = build_ledger(INV, sessions_report(session("s1", cwd="C:/r/app")), None,
                              generated_at=NOW,
                              inputs={"inventory": "C:/o/git-inventory.json",
                                      "sessions": "C:/o/sessions.json", "overrides": None})
        self.assertEqual(ledger["schemaVersion"], 2)
        self.assertEqual(ledger["generatedAt"], NOW.isoformat())
        self.assertEqual(ledger["inputs"]["inventory"],
                         {"path": "C:/o/git-inventory.json", "generatedAt": INV["generatedAt"]})
        self.assertEqual(ledger["inputs"]["sessions"]["generatedAt"], "2026-11-04T11:30:00+00:00")
        self.assertEqual(ledger["inputs"]["overrides"], {"path": None, "present": False})
        self.assertEqual(ledger["warnings"], [])
        self.assertEqual(ledger["stats"]["kinds"], {"git": 4, "dir": 0, "session": 0})
        self.assertEqual(ledger["stats"]["effectiveStates"]["at-risk"], 3)
        self.assertEqual(ledger["stats"]["threads"], 4)
        self.assertEqual(ledger["stats"]["projects"], 1)


class InventoryOnlyTest(unittest.TestCase):
    def test_only_at_risk_items_without_sessions(self):
        threads = by_key(build())
        self.assertEqual(set(threads), {"git:C:/r/app#feat/x", "git:C:/r/app@C:/r/app-agent",
                                        "git:C:/r/app#wip"})
        t = threads["git:C:/r/app#wip"]
        self.assertEqual((t["origin"], t["sessions"], t["sessionCount"], t["lead"]),
                         ("inventory", [], 0, None))
        self.assertEqual(t["title"], "app · wip")
        self.assertEqual(t["lastAt"], "2026-09-01T10:00:00+00:00")
        self.assertEqual(t["suggestedState"], "at-risk")

    def test_not_created_when_a_session_resolves_there(self):
        threads = by_key(build(session("s1", cwd="C:/r/app/.wt/feat")))
        t = threads["git:C:/r/app#feat/x"]
        self.assertEqual((t["origin"], t["sessions"]), ("sessions", ["s1"]))
        self.assertEqual(len([k for k in threads if k == "git:C:/r/app#feat/x"]), 1)


class RecordTest(unittest.TestCase):
    def test_identity_fields(self):
        t = by_key(build(session("s1", cwd="C:/r/app")))["git:C:/r/app#main~session:s1"]
        self.assertEqual(t["id"], thread_id("git:C:/r/app#main~session:s1"))
        self.assertEqual((t["kind"], t["origin"], t["domain"]), ("git", "sessions", "work"))

    def test_sessions_sorted_and_lead_resume(self):
        t = by_key(build(
            session("old", "2026-10-01T10:00:00Z", cwd="C:/w", anchor="C:/w", recap="old recap",
                    first_at="2026-09-30T10:00:00Z"),
            session("new", "2026-11-02T10:00:00Z", cwd="C:/w", anchor="C:/w", recap="R",
                    ask="A?", prompt="P")))["dir:C:/w"]
        self.assertEqual(t["sessions"], ["new", "old"])
        self.assertEqual(t["sessionCount"], 2)
        self.assertEqual(t["lead"], "new")
        self.assertEqual(t["resume"], {"lastRecap": "R", "lastAsk": "A?", "lastPrompt": "P"})
        self.assertEqual((t["firstAt"], t["lastAt"]), ("2026-09-30T10:00:00Z",
                                                        "2026-11-02T10:00:00Z"))
        self.assertEqual(t["daysIdle"], 2)

    def test_title_from_most_recent_titled_session(self):
        t = by_key(build(session("a", "2026-11-02T10:00:00Z", cwd="C:/r/app/.wt/feat",
                                 title="Older"),
                         session("b", "2026-11-03T10:00:00Z", cwd="C:/r/app/.wt/feat")))[
            "git:C:/r/app#feat/x"]
        self.assertEqual(t["title"], "Older")

    def test_title_falls_back_to_branch_then_last_segment(self):
        threads = by_key(build(session("a", cwd="C:/r/app"),
                               session("b", anchor="C:/notes/plan"),
                               session("c0ffee", cwd="C:/ClaudeSession"),
                               session("d", cwd="C:/r/app-agent/x")))
        self.assertEqual(threads["git:C:/r/app#main~session:a"]["title"], "main")
        self.assertEqual(threads["dir:C:/notes/plan"]["title"], "plan")
        self.assertEqual(threads["session:c0ffee"]["title"], "c0ffee")
        self.assertEqual(threads["git:C:/r/app@C:/r/app-agent"]["title"], "app-agent")

    def test_git_facts(self):
        g = by_key(build(session("s", cwd="C:/r/app/.wt/feat")))["git:C:/r/app#feat/x"]["git"]
        self.assertEqual(g, {"repo": "C:/r/app", "branch": "feat/x",
                             "worktreePath": "C:/r/app/.wt/feat", "risk": "unpushed",
                             "notOnRemote": 3, "dirty": g["dirty"], "merged": False,
                             "found": True})
        self.assertEqual(g["dirty"]["staged"], 0)

    def test_git_facts_for_branch_and_detached(self):
        threads = by_key(build())
        self.assertIsNone(threads["git:C:/r/app#wip"]["git"]["worktreePath"])
        detached = threads["git:C:/r/app@C:/r/app-agent"]["git"]
        self.assertEqual((detached["branch"], detached["worktreePath"]), (None, "C:/r/app-agent"))

    def test_branch_gone_from_inventory_is_not_found(self):
        t = by_key(build(session("s", cwd="C:/r/app", branch="feat/merged-and-deleted",
                                 last_at="2026-11-03T10:00:00Z")))
        g = t["git:C:/r/app#feat/merged-and-deleted"]["git"]
        self.assertEqual(g, {"repo": "C:/r/app", "branch": "feat/merged-and-deleted",
                             "worktreePath": None, "risk": None, "notOnRemote": None,
                             "dirty": None, "merged": None, "found": False})
        self.assertEqual(t["git:C:/r/app#feat/merged-and-deleted"]["suggestedState"], "open")

    def test_non_git_threads_have_no_git(self):
        self.assertIsNone(by_key(build(session("s", anchor="C:/n")))["dir:C:/n"]["git"])

    def test_git_actions_summed(self):
        a1 = {"commit": {"count": 2, "lastAt": "2026-11-01T10:00:00Z"},
              "push": {"count": 1, "lastAt": "2026-11-01T10:00:00Z"},
              "merge": {"count": 0, "lastAt": None}, "pr-create": {"count": 0, "lastAt": None}}
        a2 = {"commit": {"count": 1, "lastAt": "2026-11-02T10:00:00Z"},
              "push": {"count": 0, "lastAt": None},
              "merge": {"count": 0, "lastAt": None}, "pr-create": {"count": 1, "lastAt": "x"}}
        t = by_key(build(session("a", anchor="C:/n", actions=a1),
                         session("b", anchor="C:/n", actions=a2)))["dir:C:/n"]
        self.assertEqual(t["gitActions"]["commit"], {"count": 3, "lastAt": "2026-11-02T10:00:00Z"})
        self.assertEqual(t["gitActions"]["push"], {"count": 1, "lastAt": "2026-11-01T10:00:00Z"})
        self.assertEqual(t["gitActions"]["merge"], {"count": 0, "lastAt": None})
        self.assertEqual(t["gitActions"]["pr-create"]["count"], 1)


class RelatedTest(unittest.TestCase):
    def test_fork_family_links_other_threads_only(self):
        threads = by_key(build(
            session("p", anchor="C:/a", fork=fork("p", ["c1", "c2"], 5)),
            session("c1", anchor="C:/b", fork=fork("p", ["p", "c2"], 9, parent="p")),
            session("c2", anchor="C:/a", fork=fork("p", ["p", "c1"], 4, parent="p")),
            session("lone", anchor="C:/c")))
        a, b = threads["dir:C:/a"], threads["dir:C:/b"]
        self.assertEqual(a["related"], [{"id": b["id"], "sharedMessages": 9,
                                         "reason": "fork-family"}])
        self.assertEqual(b["related"], [{"id": a["id"], "sharedMessages": 9,
                                         "reason": "fork-family"}])
        self.assertEqual(threads["dir:C:/c"]["related"], [])

    def test_same_thread_family_is_not_related(self):
        threads = by_key(build(session("p", anchor="C:/a", fork=fork("p", ["c"], 5)),
                               session("c", anchor="C:/a", fork=fork("p", ["p"], 5, "p"))))
        self.assertEqual(threads["dir:C:/a"]["related"], [])


class OverridesTest(unittest.TestCase):
    def test_state_note_and_effective_state(self):
        tid = thread_id("dir:C:/n")
        ledger = build(session("s", anchor="C:/n"),
                       ovr=overrides({tid: {"state": "paused", "note": "n"}}))
        t = by_key(ledger)["dir:C:/n"]
        self.assertEqual((t["state"], t["note"], t["suggestedState"], t["effectiveState"]),
                         ("paused", "n", "open", "paused"))
        self.assertEqual(ledger["stats"]["effectiveStates"]["paused"], 1)

    def test_no_override_means_null_state(self):
        t = by_key(build(session("s", anchor="C:/n")))["dir:C:/n"]
        self.assertEqual((t["state"], t["effectiveState"]), (None, "open"))

    def test_merge_applied_before_states(self):
        into, gone = thread_id("dir:C:/a"), thread_id("dir:C:/b")
        ledger = build(
            session("old", "2026-09-01T10:00:00Z", anchor="C:/a", recap="Done."),
            session("new", "2026-11-03T10:00:00Z", anchor="C:/b", ask="Next?"),
            ovr=overrides({gone: {"state": "done"}}, [{"into": into, "from": [gone, "unknown1"]}]))
        threads = by_key(ledger)
        self.assertNotIn("dir:C:/b", threads)
        t = threads["dir:C:/a"]
        self.assertEqual(t["sessions"], ["new", "old"])
        self.assertEqual((t["lead"], t["daysIdle"], t["suggestedState"]), ("new", 1, "open"))
        self.assertEqual(len(ledger["warnings"]), 2)
        self.assertTrue(any("unknown1" in w for w in ledger["warnings"]))
        self.assertTrue(any(gone in w for w in ledger["warnings"]))


class SortTest(unittest.TestCase):
    def test_effective_state_order_then_last_at_desc(self):
        ledger = build(
            session("o1", "2026-11-01T10:00:00Z", anchor="C:/o1"),
            session("o2", "2026-11-03T10:00:00Z", anchor="C:/o2"),
            session("st", "2026-08-01T10:00:00Z", anchor="C:/st"),
            session("ld", "2026-10-01T10:00:00Z", anchor="C:/ld", recap="Done."),
            session("pz", "2026-11-03T10:00:00Z", anchor="C:/pz"),
            ovr=overrides({thread_id("dir:C:/pz"): {"state": "paused"}}))
        order = [(t["effectiveState"], t["key"]) for t in ledger["threads"]]
        self.assertEqual(order, [
            ("at-risk", "git:C:/r/app#feat/x"), ("at-risk", "git:C:/r/app@C:/r/app-agent"),
            ("at-risk", "git:C:/r/app#wip"),
            ("open", "dir:C:/o2"), ("open", "dir:C:/o1"),
            ("paused", "dir:C:/pz"), ("stale", "dir:C:/st"), ("likely-done", "dir:C:/ld")])


if __name__ == "__main__":
    unittest.main()
