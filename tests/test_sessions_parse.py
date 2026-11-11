import os
import tempfile
import unittest

from tests.sessionfixtures import (assistant_text, lines, meta, tool, tool_result, user,
                                   write_jsonl)
from work_ledger.sessions_parse import (detect_git_actions, drive_path, normalize_path,
                                        parse_lines, parse_transcript)


def parse(*records):
    return parse_lines(lines(*records))


class TitleTest(unittest.TestCase):
    def test_no_title(self):
        facts = parse(user())
        self.assertIsNone(facts["title"])
        self.assertIsNone(facts["titleSource"])

    def test_ai_title_last_wins(self):
        facts = parse(meta("ai-title", aiTitle="first"), user(), meta("ai-title", aiTitle="second"))
        self.assertEqual((facts["title"], facts["titleSource"]), ("second", "ai-title"))

    def test_agent_name_beats_ai_title(self):
        facts = parse(meta("agent-name", agentName="agent"), meta("ai-title", aiTitle="ai"))
        self.assertEqual((facts["title"], facts["titleSource"]), ("agent", "agent-name"))

    def test_custom_title_beats_all_and_last_wins(self):
        facts = parse(meta("custom-title", customTitle="one"),
                      meta("agent-name", agentName="agent"),
                      meta("custom-title", customTitle="two"),
                      meta("ai-title", aiTitle="ai"))
        self.assertEqual((facts["title"], facts["titleSource"]), ("two", "custom-title"))

    def test_empty_title_value_is_ignored(self):
        facts = parse(meta("ai-title", aiTitle="real"), meta("custom-title", customTitle=""))
        self.assertEqual(facts["titleSource"], "ai-title")


class CountsTest(unittest.TestCase):
    def test_timestamps_and_message_counts(self):
        facts = parse(
            user(ts="2026-11-01T10:05:00.000Z"),
            assistant_text("ok", ts="2026-11-01T10:06:00.000Z"),
            tool_result(ts="2026-11-01T10:07:00.000Z"),
            user(ts="2026-11-01T09:59:00.000Z"),
            meta("ai-title", aiTitle="t"),
        )
        self.assertEqual(facts["firstAt"], "2026-11-01T09:59:00.000Z")
        self.assertEqual(facts["lastAt"], "2026-11-01T10:07:00.000Z")
        # A tool_result line is not a user message.
        self.assertEqual(facts["userMessages"], 2)
        self.assertEqual(facts["assistantMessages"], 1)

    def test_assistant_lines_of_one_message_count_once(self):
        a = assistant_text("part")
        b = tool("Read", {"file_path": "x"})
        a["message"]["id"] = "m1"
        b["message"]["id"] = "m1"
        self.assertEqual(parse(a, b)["assistantMessages"], 1)

    def test_meta_user_lines_are_not_user_messages(self):
        self.assertEqual(parse(user(isMeta=True), user())["userMessages"], 1)

    def test_empty_transcript(self):
        facts = parse()
        self.assertIsNone(facts["firstAt"])
        self.assertEqual(facts["userMessages"], 0)
        self.assertEqual(facts["messages"], [])

    def test_cwds_and_branches_with_counts(self):
        facts = parse(user(cwd="C:\\a", branch="main"), user(cwd="C:\\a", branch="feat"),
                      user(cwd="C:\\b", branch=""), assistant_text("x", cwd="C:\\a", branch=None))
        self.assertEqual(facts["cwds"], [{"path": "C:/a", "count": 3}, {"path": "C:/b", "count": 1}])
        self.assertEqual(facts["gitBranches"],
                         [{"name": "feat", "count": 1}, {"name": "main", "count": 1}])

    def test_relocated_cwd(self):
        self.assertIsNone(parse(user())["relocatedCwd"])
        facts = parse(user(), meta("relocated", relocatedCwd="C:\\new\\place"))
        self.assertEqual(facts["relocatedCwd"], "C:/new/place")

    def test_last_prompt_truncated_to_200(self):
        facts = parse(meta("last-prompt", lastPrompt="old"), meta("last-prompt", lastPrompt="p" * 250))
        self.assertEqual(facts["lastPrompt"], "p" * 200)

    def test_message_uuids_with_timestamps_in_file_order(self):
        facts = parse(meta("ai-title", aiTitle="t"), user(uuid="a1", ts="2026-11-01T10:02:00Z"),
                      assistant_text("x", uuid="a2", ts="2026-11-01T10:01:00Z"))
        self.assertEqual(facts["messages"], [["a1", "2026-11-01T10:02:00Z"],
                                             ["a2", "2026-11-01T10:01:00Z"]])

    def test_head_branch_is_detached_or_no_branch(self):
        facts = parse(user(branch="HEAD"), user(branch="HEAD"), user(branch=""), user(branch=None),
                      user(branch="main"))
        self.assertEqual(facts["gitBranches"], [{"name": "main", "count": 1}])
        self.assertEqual(facts["detachedOrNoBranchCount"], 4)


class GitBashPathTest(unittest.TestCase):
    def test_drive_path(self):
        self.assertEqual(drive_path("/c/Users/x"), "C:/Users/x")
        self.assertEqual(drive_path("/d"), "D:/")
        self.assertEqual(drive_path("/d/"), "D:/")
        self.assertEqual(drive_path("C:/already"), "C:/already")

    def test_only_single_letter_first_segment_is_a_drive(self):
        for path in ("/home/x", "/cc/x", "/tmp", "/", "relative/c", None, ""):
            self.assertEqual(drive_path(path), path, path)

    def test_cwds_writes_and_relocated_are_normalized(self):
        facts = parse(user(cwd="/c/work/app"),
                      tool("Write", {"file_path": "/d/repo/a.py"}, cwd="/c/work/app"),
                      tool("Edit", {"file_path": "src/b.py"}, cwd="/c/work/app"),
                      meta("relocated", relocatedCwd="/e/moved"))
        self.assertEqual(facts["cwds"], [{"path": "C:/work/app", "count": 3}])
        self.assertEqual(facts["writes"], [{"path": "C:/work/app/src/b.py", "count": 1},
                                           {"path": "D:/repo/a.py", "count": 1}])
        self.assertEqual(facts["relocatedCwd"], "E:/moved")

    def test_posix_paths_with_long_first_segment_kept(self):
        facts = parse(user(cwd="/home/me/app"))
        self.assertEqual(facts["cwds"], [{"path": "/home/me/app", "count": 1}])


class MalformedTest(unittest.TestCase):
    def test_malformed_lines_skipped_and_counted(self):
        facts = parse_lines(["{not json", "", "[1, 2]", "null", *lines(user())])
        self.assertEqual(facts["malformedLines"], 3)
        self.assertEqual(facts["userMessages"], 1)

    def test_unknown_types_and_missing_fields_are_tolerated(self):
        facts = parse({"type": "mystery"}, {"type": "user"}, {"type": "assistant", "message": 5},
                      {"type": "assistant", "message": {"content": [7, {"type": "tool_use"}]}})
        self.assertEqual(facts["malformedLines"], 0)
        self.assertEqual(facts["writes"], [])


class WritesTest(unittest.TestCase):
    def test_write_tools_with_backslash_paths(self):
        facts = parse(
            tool("Write", {"file_path": "C:\\work\\app\\a.py", "content": "secret"}),
            tool("Edit", {"file_path": "c:\\work\\app\\a.py", "old_string": "x", "new_string": "y"}),
            tool("MultiEdit", {"file_path": "C:/work/app/b.py", "edits": []}),
            tool("NotebookEdit", {"notebook_path": "C:\\work\\nb.ipynb", "new_source": "s"}),
            tool("Read", {"file_path": "C:\\work\\app\\ignored.py"}),
        )
        self.assertEqual(facts["writes"], [
            {"path": "C:/work/app/a.py", "count": 2},
            {"path": "C:/work/app/b.py", "count": 1},
            {"path": "C:/work/nb.ipynb", "count": 1},
        ])

    def test_relative_path_joined_with_cwd(self):
        facts = parse(tool("Write", {"file_path": "src\\x.py"}, cwd="C:\\work\\app"))
        self.assertEqual(facts["writes"], [{"path": "C:/work/app/src/x.py", "count": 1}])

    def test_no_file_content_is_kept(self):
        facts = parse(tool("Write", {"file_path": "C:\\a.txt", "content": "TOPSECRET"}),
                      tool_result(), user("my private prompt"))
        self.assertNotIn("TOPSECRET", repr(facts))
        self.assertNotIn("secret output", repr(facts))
        self.assertNotIn("my private prompt", repr(facts))


class NormalizePathTest(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(normalize_path("c:\\A\\..\\B\\f.txt"), "C:/B/f.txt")
        self.assertEqual(normalize_path("/home/u/./f"), "/home/u/f")
        self.assertEqual(normalize_path("rel\\f", "D:\\base"), "D:/base/rel/f")
        self.assertIsNone(normalize_path(""))
        self.assertIsNone(normalize_path(None))


class GitActionsTest(unittest.TestCase):
    def test_detects_common_forms(self):
        cases = {
            'git commit -m "x"': ["commit"],
            'git -C "C:\\path with space\\repo" commit -m x': ["commit"],
            "git -C C:/repo commit -am x && git push -u origin feat": ["commit", "push"],
            "git --no-pager -c core.x=y merge main": ["merge"],
            "git.exe push": ["push"],
            "gh pr create --title t --body b": ["pr-create"],
            "az repos pr create --title t": ["pr-create"],
            "cd repo; git add .; git commit -m 'fix'": ["commit"],
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(detect_git_actions(command), expected)

    def test_does_not_match_lookalikes(self):
        for command in ("git merge-base a b", "git commit-tree x", "git log --merges",
                        "gh pr view", "git status", "legit push", "cat .git/commit"):
            with self.subTest(command=command):
                self.assertEqual(detect_git_actions(command), [])

    def test_from_bash_and_powershell_tools_with_last_timestamp(self):
        facts = parse(
            tool("Bash", {"command": "git commit -m a"}, ts="2026-11-01T10:00:00.000Z"),
            tool("PowerShell", {"command": "git commit -m b; git push"}, ts="2026-11-01T11:00:00.000Z"),
            tool("Read", {"command": "git push"}, ts="2026-11-01T12:00:00.000Z"),
        )
        actions = facts["gitActions"]
        self.assertEqual(actions["commit"], {"count": 2, "lastAt": "2026-11-01T11:00:00.000Z"})
        self.assertEqual(actions["push"], {"count": 1, "lastAt": "2026-11-01T11:00:00.000Z"})
        self.assertEqual(actions["merge"], {"count": 0, "lastAt": None})
        self.assertEqual(actions["pr-create"], {"count": 0, "lastAt": None})


class ClosureTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(parse(user())["closure"], {"lastRecap": None, "lastAsk": None,
                                                    "sessionSummarySaved": False,
                                                    "endedWithQuestion": False})

    def test_last_wrap_up_wins_and_recap_truncated(self):
        facts = parse(
            tool("mcp__ccd_turn__wrap_up", {"recap": "old", "ask": "Old?"}),
            tool("mcp__ccd_turn__wrap_up", {"recap": "r" * 400}),
        )
        self.assertEqual(facts["closure"]["lastRecap"], "r" * 300)
        self.assertIsNone(facts["closure"]["lastAsk"])

    def test_ask_kept(self):
        facts = parse(tool("mcp__ccd_turn__wrap_up", {"recap": "done", "ask": "Commit now?"}))
        self.assertEqual(facts["closure"]["lastAsk"], "Commit now?")

    def test_session_summary_detected_by_suffix(self):
        facts = parse(tool("mcp__plugin_engram_engram__mem_session_summary", {"content": "c"}))
        self.assertTrue(facts["closure"]["sessionSummarySaved"])
        facts = parse(tool("mem_session_summary_x", {}))
        self.assertFalse(facts["closure"]["sessionSummarySaved"])

    def test_ended_with_question_uses_last_assistant_text(self):
        self.assertTrue(parse(assistant_text("All done. Shall I commit?  "))["closure"]["endedWithQuestion"])
        facts = parse(assistant_text("Shall I?"), tool("Bash", {"command": "ls"}),
                      assistant_text("Done."))
        self.assertFalse(facts["closure"]["endedWithQuestion"])
        # A trailing tool call does not hide the last text.
        facts = parse(assistant_text("Proceed?"), tool("Bash", {"command": "ls"}))
        self.assertTrue(facts["closure"]["endedWithQuestion"])


class ParseTranscriptTest(unittest.TestCase):
    def test_streams_file_and_tolerates_bad_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(os.path.join(tmp, "s.jsonl"), user(), "{bad")
            with open(path, "ab") as fh:
                fh.write(b"\xff\xfe garbage\n")
            facts = parse_transcript(path)
        self.assertEqual(facts["userMessages"], 1)
        self.assertEqual(facts["malformedLines"], 2)


if __name__ == "__main__":
    unittest.main()
