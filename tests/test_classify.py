import unittest

from work_ledger.classify import RISK_ORDER, classify, worst


def facts(**overrides):
    base = {
        "exists": True,
        "error": None,
        "dirty": {"staged": 0, "unstaged": 0, "untracked": 0, "ignoredUntracked": 0},
        "upstream": None,
        "upstreamGone": False,
        "ahead": None,
        "behind": None,
        "notOnRemote": 0,
        "merged": True,
        "isMain": False,
    }
    base.update(overrides)
    return base


def dirty(**counts):
    base = {"staged": 0, "unstaged": 0, "untracked": 0, "ignoredUntracked": 0}
    base.update(counts)
    return base


class ClassifyTest(unittest.TestCase):
    def test_missing_wins_over_everything(self):
        self.assertEqual(classify(facts(exists=False, error="boom", merged=None)), "missing")

    def test_error_is_unknown(self):
        self.assertEqual(classify(facts(error="fatal: bad")), "unknown")

    def test_staged_or_unstaged_is_modified(self):
        for key in ("staged", "unstaged"):
            f = facts(dirty=dirty(**{key: 1}), notOnRemote=3, merged=False)
            self.assertEqual(classify(f), "modified")

    def test_modified_wins_over_untracked(self):
        self.assertEqual(classify(facts(dirty=dirty(unstaged=1, untracked=2))), "modified")

    def test_not_on_remote_is_unpushed(self):
        self.assertEqual(classify(facts(notOnRemote=2, merged=True)), "unpushed")

    def test_unpushed_wins_over_untracked(self):
        self.assertEqual(classify(facts(dirty=dirty(untracked=1), notOnRemote=1)), "unpushed")

    def test_only_untracked_is_untracked(self):
        self.assertEqual(classify(facts(dirty=dirty(untracked=1))), "untracked")

    def test_ignored_untracked_does_not_count(self):
        self.assertEqual(classify(facts(dirty=dirty(ignoredUntracked=4))), "safe")

    def test_untracked_wins_over_unknown_merge_state(self):
        self.assertEqual(classify(facts(dirty=dirty(untracked=1), merged=None)), "untracked")

    def test_ahead_alone_does_not_decide(self):
        # ahead/behind stay as facts; notOnRemote decides "unpushed".
        f = facts(upstream="origin/x", ahead=2, behind=0, notOnRemote=0)
        self.assertEqual(classify(f), "safe")

    def test_unknown_not_on_remote_is_unknown(self):
        self.assertEqual(classify(facts(notOnRemote=None)), "unknown")

    def test_clean_pushed_not_merged_is_pushed(self):
        f = facts(upstream="origin/x", ahead=0, behind=3, merged=False)
        self.assertEqual(classify(f), "pushed")

    def test_gone_upstream_but_on_remote_is_pushed(self):
        f = facts(upstream="origin/x", upstreamGone=True, merged=False)
        self.assertEqual(classify(f), "pushed")

    def test_clean_pushed_merged_is_safe(self):
        self.assertEqual(classify(facts(upstream="origin/x", ahead=0, behind=0)), "safe")

    def test_unknown_merge_state_when_needed_is_unknown(self):
        self.assertEqual(classify(facts(merged=None)), "unknown")

    def test_unknown_merge_state_not_needed_when_unpushed(self):
        self.assertEqual(classify(facts(merged=None, notOnRemote=1)), "unpushed")

    def test_unknown_dirty_state_is_unknown(self):
        self.assertEqual(classify(facts(dirty=None)), "unknown")

    def test_main_worktree_that_would_be_safe_is_main(self):
        self.assertEqual(classify(facts(isMain=True)), "main")

    def test_main_worktree_that_would_be_pushed_is_main(self):
        self.assertEqual(classify(facts(isMain=True, merged=False)), "main")

    def test_main_worktree_keeps_other_risks(self):
        self.assertEqual(classify(facts(isMain=True, dirty=dirty(staged=1))), "modified")
        self.assertEqual(classify(facts(isMain=True, notOnRemote=1)), "unpushed")
        self.assertEqual(classify(facts(isMain=True, dirty=dirty(untracked=1))), "untracked")
        self.assertEqual(classify(facts(isMain=True, merged=None)), "unknown")


class WorstTest(unittest.TestCase):
    def test_severity_order(self):
        self.assertEqual(RISK_ORDER, ("modified", "unpushed", "untracked", "unknown",
                                      "missing", "pushed", "main", "safe"))

    def test_worst_of_list(self):
        self.assertEqual(worst(["safe", "pushed", "untracked", "unpushed"]), "unpushed")

    def test_worst_of_empty_is_none(self):
        self.assertIsNone(worst([]))


if __name__ == "__main__":
    unittest.main()
