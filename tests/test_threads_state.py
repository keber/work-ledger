import unittest

from tests.threadfixtures import NOW
from work_ledger.threads_state import (STATE_ORDER, days_idle, effective_state, recency,
                                       suggest_state)


def git(risk, found=True):
    return {"risk": risk if found else None, "found": found}


def resume(recap=None, ask=None):
    return {"lastRecap": recap, "lastAsk": ask, "lastPrompt": None}


class DaysIdleTest(unittest.TestCase):
    def test_whole_days(self):
        self.assertEqual(days_idle("2026-11-01T13:00:00Z", NOW), 2)
        self.assertEqual(days_idle("2026-11-04T11:59:00Z", NOW), 0)

    def test_unknown_or_future(self):
        self.assertIsNone(days_idle(None, NOW))
        self.assertIsNone(days_idle("garbage", NOW))
        self.assertEqual(days_idle("2026-11-05T12:00:00Z", NOW), 0)


class SuggestStateTest(unittest.TestCase):
    def state(self, kind="git", g=None, r=None, days=0):
        return suggest_state(kind, g, r, days)[0]

    def test_at_risk_for_each_risk(self):
        for risk in ("modified", "unpushed", "untracked"):
            self.assertEqual(self.state(g=git(risk), days=400), "at-risk", risk)

    def test_pushed_waits_for_merge(self):
        self.assertEqual(self.state(g=git("pushed"), days=400), "waiting-merge")

    def test_safe_is_likely_done(self):
        self.assertEqual(self.state(g=git("safe"), days=400), "likely-done")

    def test_closed_non_git_thread_idle_a_week_is_likely_done(self):
        for kind in ("dir", "session"):
            self.assertEqual(self.state(kind, r=resume("Done."), days=7), "likely-done", kind)

    def test_recap_rule_needs_idle_no_ask_and_non_git(self):
        self.assertEqual(self.state("dir", r=resume("Done."), days=6), "open")
        self.assertEqual(self.state("dir", r=resume("Done.", ask="Commit?"), days=8), "open")
        self.assertEqual(self.state("dir", r=resume(None), days=8), "open")
        self.assertEqual(self.state("dir", r=None, days=8), "open")
        self.assertEqual(self.state("git", g=git("main"), r=resume("Done."), days=8), "open")

    def test_stale_after_30_days(self):
        self.assertEqual(self.state("dir", r=resume(ask="?"), days=30), "stale")
        self.assertEqual(self.state("git", g=git("main"), days=29), "open")

    def test_first_match_wins(self):
        # likely-done (recap) beats stale; at-risk beats everything.
        self.assertEqual(self.state("dir", r=resume("Done."), days=90), "likely-done")
        self.assertEqual(self.state(g=git("modified"), r=resume("Done."), days=90), "at-risk")

    def test_not_found_counts_as_no_risk(self):
        self.assertEqual(self.state(g=git("modified", found=False), days=3), "open")
        self.assertEqual(self.state(g=git("safe", found=False), days=31), "stale")

    def test_git_thread_without_thread_git_uses_recap_rule(self):
        # Default-branch threads (gitScope project) carry no git and ignore git risk.
        self.assertEqual(self.state("git", g=None, r=resume("Done."), days=8), "likely-done")
        self.assertEqual(self.state("git", g=None, r=resume(ask="?"), days=3), "open")

    def test_unknown_idle_is_open(self):
        self.assertEqual(self.state("session", r=resume("Done."), days=None), "open")

    def test_reason_is_given(self):
        state, reason = suggest_state("git", git("unpushed"), None, 2)
        self.assertEqual(state, "at-risk")
        self.assertIn("unpushed", reason)
        self.assertIn("30", suggest_state("dir", None, None, 31)[1])


class RecencyTest(unittest.TestCase):
    def test_recent_below_30_days_else_old(self):
        self.assertEqual(recency(0), "recent")
        self.assertEqual(recency(29), "recent")
        self.assertEqual(recency(30), "old")
        self.assertEqual(recency(None), "old")


class EffectiveStateTest(unittest.TestCase):
    def test_override_wins(self):
        self.assertEqual(effective_state("paused", "at-risk"), "paused")
        self.assertEqual(effective_state(None, "at-risk"), "at-risk")

    def test_order(self):
        self.assertEqual(STATE_ORDER, ("at-risk", "open", "waiting-merge", "active", "paused",
                                       "stale", "likely-done", "done", "discarded"))


if __name__ == "__main__":
    unittest.main()
