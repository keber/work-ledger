import json
import unittest

import copy

from tests.contextfixtures import (NOW, excerpt, git_ok, ledger, note, project, session_info,
                                   tgit, thread)
from tests.sessionfixtures import assistant_text, lines, user
from work_ledger.context_build import (SCHEMA_VERSION, automated_sessions, build_overview,
                                       build_query_context, closest_names, fit, git_summary,
                                       match_projects, render_json, render_markdown)
from work_ledger.context_transcript import excerpt_lines


def shop_ledger(sessions_path="C:/o/sessions.json"):
    threads = [
        thread("t-old", title="Old export idea", last_at="2026-09-01T10:00:00Z",
               first_at="2026-08-20T10:00:00Z", state="stale"),
        thread("t-new", title="Invoice totals", last_at="2026-11-10T10:00:00Z",
               first_at="2026-11-01T10:00:00Z", recap="Totals fixed; not pushed.",
               ask="Push?", prompt="si", git=tgit(), sessions=["s-new2", "s-new1"]),
        thread("t-mid", title="Report layout", last_at="2026-11-05T10:00:00Z",
               prompt="please redo the layout of the monthly report table"),
        thread("t-agent1", title="worktree-agent-aa11", last_at="2026-11-08T10:00:00Z",
               sessions=[], state="at-risk", git=tgit("worktree-agent-aa11")),
        thread("t-agent2", title="worktree-agent-bb22", last_at="2026-10-20T10:00:00Z",
               sessions=[], state="likely-done"),
        thread("t-other", project="p-blog", title="Blog post", last_at="2026-10-01T10:00:00Z"),
    ]
    projects = [
        project("p-shop", "Shop_Exportadora", last_at="2026-11-10T10:00:00Z", at_risk=True,
                threads=["t-old", "t-new", "t-mid", "t-agent1", "t-agent2"]),
        project("p-blog", "blog", path="C:/r/personal/blog", last_at="2026-10-01T10:00:00Z",
                threads=["t-other"]),
        project("p-exp", "exportadora-api", last_at="2026-11-09T10:00:00Z"),
    ]
    return ledger(projects, threads, sessions_path=sessions_path)


SESSIONS = {
    "s-new1": session_info("C:/t/s-new1.jsonl", "2026-11-01T10:00:00Z", "2026-11-02T10:00:00Z"),
    "s-new2": session_info("C:/t/s-new2.jsonl", "2026-11-09T10:00:00Z", "2026-11-10T10:00:00Z"),
    "s-t-mid": session_info("C:/t/s-t-mid.jsonl", "2026-11-05T09:00:00Z",
                            "2026-11-05T10:00:00Z"),
}


def reader_for(calls):
    def read(path, seen=None):
        calls.append(path)
        return excerpt(("2026-11-09T10:00:00Z", "user", f"prompt in {path}"),
                       ("2026-11-09T10:05:00Z", "assistant", "answer"))
    return read


def query_ctx(query="shop", ledger_data=None, sessions=SESSIONS, threads=8, transcripts=5,
              calls=None, git=None, reader=None, handoff=None):
    calls = [] if calls is None else calls
    return build_query_context(ledger_data or shop_ledger(), query, NOW,
                               git_reader=git or (lambda path: git_ok(path=path)),
                               sessions_index=sessions,
                               read_excerpt=reader or reader_for(calls),
                               handoff_reader=handoff or (lambda path: []),
                               threads=threads, transcripts=transcripts,
                               ledger_path="C:/o/ledger.json")


class MatchTest(unittest.TestCase):
    def test_name_match_case_insensitive_ordered_by_recent_activity(self):
        names = [p["name"] for p in match_projects(shop_ledger(), "EXPORTADORA")]
        self.assertEqual(names, ["Shop_Exportadora", "exportadora-api"])

    def test_path_match(self):
        self.assertEqual([p["id"] for p in match_projects(shop_ledger(), "personal")], ["p-blog"])

    def test_thread_title_match(self):
        self.assertEqual([p["id"] for p in match_projects(shop_ledger(), "invoice")], ["p-shop"])

    def test_no_match(self):
        self.assertEqual(match_projects(shop_ledger(), "zzz"), [])

    def test_closest_names(self):
        self.assertEqual(closest_names(shop_ledger(), "blgo")[0], "blog")
        self.assertLessEqual(len(closest_names(shop_ledger(), "x")), 5)


class GitSummaryTest(unittest.TestCase):
    def test_thread_git(self):
        text = git_summary(thread("a", git=tgit(dirty={"staged": 0, "unstaged": 1,
                                                       "untracked": 2, "ignoredUntracked": 0})))
        self.assertIn("branch feat/x", text)
        self.assertIn("unpushed", text)
        self.assertIn("2 commits on no remote", text)
        self.assertIn("1 unstaged", text)
        self.assertIn("2 untracked", text)

    def test_project_scope(self):
        self.assertIn("default branch", git_summary(thread("a", scope="project")))

    def test_no_git(self):
        self.assertEqual(git_summary(thread("a")), "no git")


class QueryContextTest(unittest.TestCase):
    def test_header_and_project(self):
        ctx = query_ctx()
        self.assertEqual(ctx["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(ctx["mode"], "query")
        self.assertEqual(ctx["query"], "shop")
        self.assertEqual(ctx["ledger"]["generatedAt"], "2026-11-11T09:00:00+00:00")
        self.assertEqual(ctx["ledger"]["ageHours"], 3.0)
        self.assertEqual([p["name"] for p in ctx["projects"]], ["Shop_Exportadora"])
        proj = ctx["projects"][0]
        self.assertEqual(proj["daysIdle"], 1)
        self.assertEqual(proj["git"]["status"], "ok")
        self.assertEqual(proj["git"]["path"], "C:/r/Shop_Exportadora")

    def test_quiet_threads_are_collapsed(self):
        proj = query_ctx()["projects"][0]
        self.assertEqual(proj["quietThreads"], {"count": 2, "atRisk": 1, "minDaysIdle": 3,
                                                "maxDaysIdle": 22})
        ids = [t["id"] for t in proj["threads"]]
        self.assertEqual(ids, ["t-new", "t-mid", "t-old"])
        self.assertEqual(proj["moreThreads"], 0)

    def test_thread_fields(self):
        t = query_ctx()["projects"][0]["threads"][0]
        self.assertEqual(t["title"], "Invoice totals")
        self.assertEqual(t["state"], "open")
        self.assertEqual(t["firstAt"], "2026-11-01T10:00:00Z")
        self.assertEqual(t["daysIdle"], 1)
        self.assertEqual(t["sessionCount"], 2)
        self.assertIn("branch feat/x", t["git"])
        self.assertEqual(t["lastRecap"], "Totals fixed; not pushed.")
        self.assertEqual(t["lastAsk"], "Push?")
        self.assertIsNone(t["lastPrompt"])  # "si" says nothing
        self.assertEqual(t["resume"], "claude --resume s-new2")

    def test_meaningful_prompt_kept(self):
        t = query_ctx()["projects"][0]["threads"][1]
        self.assertEqual(t["lastPrompt"], "please redo the layout of the monthly report table")

    def test_top_n_threads(self):
        proj = query_ctx(threads=1)["projects"][0]
        self.assertEqual([t["id"] for t in proj["threads"]], ["t-new"])
        self.assertEqual(proj["moreThreads"], 2)

    def test_excerpts_for_top_k_threads_oldest_session_first(self):
        calls = []
        proj = query_ctx(transcripts=1, calls=calls)["projects"][0]
        self.assertEqual(calls, ["C:/t/s-new1.jsonl", "C:/t/s-new2.jsonl"])
        ex = proj["threads"][0]["excerpts"]
        self.assertEqual([e["sessionId"] for e in ex], ["s-new1", "s-new2"])
        self.assertEqual(ex[0]["firstAt"], "2026-11-01T10:00:00Z")
        self.assertEqual(ex[0]["entries"][0]["text"], "prompt in C:/t/s-new1.jsonl")
        self.assertEqual(proj["threads"][1]["excerpts"], [])

    def test_missing_transcript_entry_noted_not_read(self):
        calls = []
        proj = query_ctx(transcripts=3, calls=calls)["projects"][0]
        old = proj["threads"][2]
        self.assertEqual(old["excerpts"], [])
        self.assertNotIn(None, calls)

    def test_sessions_index_unavailable(self):
        ctx = query_ctx(sessions=None)
        self.assertTrue(any("transcript" in n for n in ctx["notes"]))
        self.assertEqual(ctx["projects"][0]["threads"][0]["excerpts"], [])

    def test_several_projects_and_cap(self):
        ctx = query_ctx(query="r/")  # every path matches
        self.assertEqual([p["id"] for p in ctx["projects"]], ["p-shop", "p-exp", "p-blog"])

    def test_more_projects_than_max_are_listed_by_name(self):
        projects = [project(f"p{i}", f"app{i}", last_at=f"2026-11-0{i + 1}T10:00:00Z")
                    for i in range(8)]
        ctx = query_ctx(query="app", ledger_data=ledger(projects, []))
        self.assertEqual(len(ctx["projects"]), 6)
        self.assertEqual(ctx["alsoMatched"], ["app1", "app0"])


class OverviewTest(unittest.TestCase):
    def test_recent_or_at_risk_projects(self):
        data = shop_ledger()
        data["projects"].append(project("p-risk", "old-risky", last_at="2026-01-01T10:00:00Z",
                                        at_risk=True))
        ctx = build_overview(data, NOW, ledger_path="C:/o/ledger.json")
        self.assertEqual(ctx["mode"], "overview")
        names = [p["name"] for p in ctx["projects"]]
        self.assertEqual(names, ["Shop_Exportadora", "exportadora-api", "old-risky"])
        shop = ctx["projects"][0]
        self.assertTrue(shop["atRisk"])
        self.assertEqual(shop["daysIdle"], 1)
        self.assertEqual(shop["latestThread"]["title"], "Invoice totals")
        self.assertEqual(shop["latestThread"]["lastRecap"], "Totals fixed; not pushed.")
        self.assertIsNone(ctx["projects"][1]["latestThread"])


class RenderTest(unittest.TestCase):
    def test_markdown_query(self):
        text = render_markdown(query_ctx(transcripts=1))
        self.assertIn("Shop_Exportadora", text)
        self.assertIn("2026-11-11T09:00:00+00:00", text)
        self.assertIn("This command writes nothing", text)
        self.assertIn("transcript and model context", text)
        self.assertNotIn("never stored", text)
        self.assertIn("Branch: main", text)
        self.assertIn("fix: totals", text)
        self.assertIn("feat/x (2 ahead", text)
        self.assertIn("2 threads without sessions (1 at risk), idle 3-22d", text)
        self.assertIn("Invoice totals", text)
        self.assertIn("`claude --resume s-new2`", text)
        self.assertIn("Totals fixed; not pushed.", text)
        self.assertIn("user: prompt in C:/t/s-new1.jsonl", text)

    def test_markdown_gap_and_errors(self):
        ctx = query_ctx(transcripts=1)
        ex = ctx["projects"][0]["threads"][0]["excerpts"]
        ex[0].update(excerpt(("2026-11-01T10:00:00Z", "user", "a"),
                             ("2026-11-01T11:00:00Z", "user", "b"), omitted=4, gap=1))
        ex[1].update(excerpt(error="excerpts unavailable: path outside sessions source"))
        text = render_markdown(ctx)
        self.assertIn("4 entries omitted", text)
        self.assertIn("excerpts unavailable: path outside sessions source", text)

    def test_markdown_git_states(self):
        for status, phrase in (("missing", "path not found"), ("not-a-repo", "not a git repo"),
                               ("error", "git failed: boom")):
            ctx = query_ctx(git=lambda path, s=status: git_ok(status=s, error="boom"))
            self.assertIn(phrase, render_markdown(ctx))

    def test_markdown_overview(self):
        text = render_markdown(build_overview(shop_ledger(), NOW))
        self.assertIn("Shop_Exportadora", text)
        self.assertIn("AT RISK", text)
        self.assertIn("Invoice totals", text)

    def test_json(self):
        data = json.loads(render_json(query_ctx()))
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["projects"][0]["name"], "Shop_Exportadora")


class FitTest(unittest.TestCase):
    def test_fits_untouched(self):
        ctx = query_ctx()
        text, fitted = fit(ctx, 100000, render_markdown)
        self.assertIsNone(fitted["truncation"])
        self.assertEqual(text, render_markdown(ctx))

    def test_drops_excerpts_first_then_threads(self):
        ctx = query_ctx(transcripts=3)
        full = len(render_markdown(ctx))
        text, fitted = fit(ctx, full - 50, render_markdown)
        self.assertLessEqual(len(text), full - 50)
        trunc = fitted["truncation"]
        self.assertGreaterEqual(trunc["droppedExcerpts"], 1)
        self.assertEqual(trunc["droppedThreads"], 0)
        self.assertIn("truncated", text)
        self.assertIn("transcript excerpt", text)

    def test_drops_threads_and_projects_when_needed(self):
        ctx = query_ctx(query="r/", transcripts=3)
        text, fitted = fit(ctx, 1500, render_markdown)
        self.assertLessEqual(len(text), 1500)
        trunc = fitted["truncation"]
        self.assertGreater(trunc["droppedThreads"] + trunc["droppedProjects"], 0)
        self.assertEqual(len(fitted["projects"]) >= 1, True)

    def test_hard_cut_as_last_resort(self):
        text, fitted = fit(query_ctx(), 300, render_markdown)
        self.assertLessEqual(len(text), 300)
        self.assertTrue(fitted["truncation"]["hardCut"])
        self.assertIn("truncated", text)

    def test_json_never_hard_cut(self):
        text, fitted = fit(query_ctx(), 300, render_json)
        json.loads(text)
        self.assertTrue(fitted["truncation"]["overLimit"])


FORK_SHARED = [user("plan the export", ts="2026-11-01T10:00:00Z"),
               assistant_text("Plan: three steps", ts="2026-11-01T10:01:00Z")]
TRANSCRIPTS = {
    "C:/t/parent.jsonl": lines(*FORK_SHARED, user("step one", ts="2026-11-01T11:00:00Z")),
    "C:/t/fork.jsonl": lines(*FORK_SHARED, user("step two instead", ts="2026-11-02T10:00:00Z")),
}


def real_reader(path, seen=None):
    return excerpt_lines(TRANSCRIPTS[path], seen=seen)


class SharedEntriesTest(unittest.TestCase):
    def fork_ledger(self, same_thread=True):
        sessions = {"s-parent": session_info("C:/t/parent.jsonl", "2026-11-01T10:00:00Z",
                                             "2026-11-01T11:00:00Z"),
                    "s-fork": session_info("C:/t/fork.jsonl", "2026-11-01T10:00:00Z",
                                           "2026-11-02T10:00:00Z")}
        if same_thread:
            threads = [thread("t1", sessions=["s-fork", "s-parent"],
                              last_at="2026-11-02T10:00:00Z")]
        else:
            threads = [thread("t1", sessions=["s-fork"], last_at="2026-11-02T10:00:00Z"),
                       thread("t2", sessions=["s-parent"], last_at="2026-11-01T11:00:00Z")]
        data = ledger([project("p-shop", "shop", threads=[t["id"] for t in threads])], threads)
        return data, sessions

    def test_fork_within_a_thread_shows_shared_entries_once(self):
        data, sessions = self.fork_ledger()
        ctx = query_ctx(ledger_data=data, sessions=sessions, reader=real_reader)
        parent, fork = ctx["projects"][0]["threads"][0]["excerpts"]
        self.assertEqual(parent["sessionId"], "s-parent")
        self.assertEqual(len(parent["entries"]), 3)
        self.assertEqual([e["text"] for e in fork["entries"]], ["step two instead"])
        self.assertEqual(fork["sharedWith"], {"s-parent": 2})
        self.assertNotIn("keys", fork)
        self.assertIn("2 shared entries with session s-parent omitted", render_markdown(ctx))
        json.loads(render_json(ctx))

    def test_fork_across_threads_of_the_project(self):
        data, sessions = self.fork_ledger(same_thread=False)
        ctx = query_ctx(ledger_data=data, sessions=sessions, reader=real_reader)
        first, second = ctx["projects"][0]["threads"]
        self.assertEqual(len(first["excerpts"][0]["entries"]), 3)  # the fork, ranked first
        self.assertEqual([e["text"] for e in second["excerpts"][0]["entries"]], ["step one"])
        self.assertEqual(second["excerpts"][0]["sharedWith"], {"s-fork": 2})


REVIEW_PROMPT = "You are a code reviewer. Review the diff in this repository and report"


class AutomatedTest(unittest.TestCase):
    def automated_ledger(self, entrypoint="sdk-cli", count=4, user_messages=1):
        threads = [thread("t-real", title="Real work", last_at="2026-11-01T10:00:00Z")]
        sessions = {"s-t-real": session_info("C:/t/r.jsonl", "2026-11-01T09:00:00Z",
                                             "2026-11-01T10:00:00Z")}
        for i in range(count):
            sid = f"s-auto{i}"
            threads.append(thread(f"t-auto{i}", title="master",
                                  last_at=f"2026-11-0{i + 2}T10:00:00Z", sessions=[sid]))
            sessions[sid] = session_info(f"C:/t/a{i}.jsonl", f"2026-11-0{i + 2}T09:00:00Z",
                                         f"2026-11-0{i + 2}T10:00:00Z", entrypoint=entrypoint,
                                         user_messages=user_messages, prompt=REVIEW_PROMPT)
        data = ledger([project("p-shop", "shop", threads=[t["id"] for t in threads])], threads)
        return data, sessions

    def test_entrypoint_signal(self):
        data, sessions = self.automated_ledger(count=1)
        auto = automated_sessions(data["threads"], sessions)
        self.assertEqual(auto, {"s-auto0": "entrypoint"})

    def test_repeated_prompt_fallback_needs_four_single_turn_sessions(self):
        data, sessions = self.automated_ledger(entrypoint=None, count=4)
        auto = automated_sessions(data["threads"], sessions)
        self.assertEqual(set(auto), {f"s-auto{i}" for i in range(4)})
        self.assertEqual(set(auto.values()), {"repeated-prompt"})
        data, sessions = self.automated_ledger(entrypoint=None, count=3)
        self.assertEqual(automated_sessions(data["threads"], sessions), {})
        data, sessions = self.automated_ledger(entrypoint=None, count=4, user_messages=2)
        self.assertEqual(automated_sessions(data["threads"], sessions), {})

    def test_repeated_prompt_applies_whatever_the_entrypoint(self):
        data, sessions = self.automated_ledger(entrypoint="cli", count=4)
        auto = automated_sessions(data["threads"], sessions)
        self.assertEqual(set(auto), {f"s-auto{i}" for i in range(4)})
        self.assertEqual(set(auto.values()), {"repeated-prompt"})

    def test_mixed_entrypoints_match_the_prompt_of_a_headless_run(self):
        data, sessions = self.automated_ledger(entrypoint="cli", count=3)
        sessions["s-auto0"]["entrypoint"] = "sdk-cli"
        auto = automated_sessions(data["threads"], sessions)
        self.assertEqual(auto, {"s-auto0": "entrypoint", "s-auto1": "prompt-of-automated",
                                "s-auto2": "prompt-of-automated"})
        proj = query_ctx(ledger_data=data, sessions=sessions)["projects"][0]
        self.assertEqual([t["id"] for t in proj["threads"]], ["t-real"])
        self.assertEqual(proj["automatedRuns"]["signals"],
                         {"entrypoint": 1, "prompt-of-automated": 2})

    def test_headless_prompt_matches_across_projects(self):
        data, sessions = self.automated_ledger(entrypoint="cli", count=2)
        data["threads"][1]["projectId"] = "p-other"
        sessions["s-auto0"]["entrypoint"] = "sdk-cli"
        self.assertEqual(automated_sessions(data["threads"], sessions)["s-auto1"],
                         "prompt-of-automated")

    def test_multi_turn_session_with_an_automated_prompt_is_kept(self):
        data, sessions = self.automated_ledger(entrypoint="cli", count=2)
        sessions["s-auto0"]["entrypoint"] = "sdk-cli"
        sessions["s-auto1"]["userMessages"] = 4
        self.assertNotIn("s-auto1", automated_sessions(data["threads"], sessions))

    def test_interactive_single_turn_session_with_unique_prompt_is_not_collapsed(self):
        data, sessions = self.automated_ledger(entrypoint="claude-desktop", count=1)
        sessions["s-t-real"].update(userMessages=1, lastPrompt="fix the totals bug please")
        self.assertEqual(automated_sessions(data["threads"], sessions), {})
        proj = query_ctx(ledger_data=data, sessions=sessions)["projects"][0]
        self.assertEqual({t["id"] for t in proj["threads"]}, {"t-real", "t-auto0"})
        self.assertIsNone(proj["automatedRuns"])

    def test_automated_threads_collapsed_and_excluded_from_ranking(self):
        data, sessions = self.automated_ledger()
        proj = query_ctx(ledger_data=data, sessions=sessions, threads=1)["projects"][0]
        self.assertEqual([t["id"] for t in proj["threads"]], ["t-real"])
        self.assertEqual(proj["moreThreads"], 0)
        self.assertEqual(proj["automatedRuns"], {"threads": 4, "sessions": 4,
                                                 "lastAt": "2026-11-05T10:00:00Z",
                                                 "signals": {"entrypoint": 4}})
        text = render_markdown(query_ctx(ledger_data=data, sessions=sessions))
        self.assertIn("4 automated runs (entrypoint 4), last on 2026-11-05", text)

    def test_mixed_thread_is_not_automated(self):
        data, sessions = self.automated_ledger(count=1)
        data["threads"][1]["sessions"].append("s-t-real")
        data["threads"][1]["sessionCount"] = 2
        proj = query_ctx(ledger_data=data, sessions=sessions)["projects"][0]
        self.assertIsNone(proj["automatedRuns"])

    def test_no_sessions_index_no_detection(self):
        data, _ = self.automated_ledger()
        proj = query_ctx(ledger_data=data, sessions=None)["projects"][0]
        self.assertIsNone(proj["automatedRuns"])

    def test_overview_skips_automated_latest_thread(self):
        data, sessions = self.automated_ledger()
        ctx = build_overview(data, NOW, sessions_index=sessions)
        self.assertEqual(ctx["projects"][0]["latestThread"]["title"], "Real work")


TEMPLATE = ("Act as a reviewer of the work item below. Check the acceptance criteria, list the "
            "gaps and propose test cases. Work item: ")


class TemplatedPromptTest(unittest.TestCase):
    """Regression: a scheduled job run from a desktop session inherits `claude-desktop`.

    Shape seen on real data: single-turn, one reply, untitled, a templated prompt whose
    variable part starts after ~100 characters, two runs, never run headless.
    """

    def pair(self, overrides=None):
        threads = [thread("t-real", title="Real work", last_at="2026-10-20T10:00:00Z")]
        sessions = {"s-t-real": session_info("C:/t/r.jsonl", "2026-10-20T09:00:00Z",
                                             "2026-10-20T10:00:00Z")}
        for i, item in enumerate(("4711 Export pallets by client", "4802 Fix the invoice totals")):
            sid = f"s-job{i}"
            threads.append(thread(f"t-job{i}", title="master",
                                  last_at=f"2026-10-14T18:3{i}:20Z", sessions=[sid]))
            info = dict(entrypoint="claude-desktop", user_messages=1, assistant_messages=1,
                        title_source=None, prompt=(TEMPLATE + item)[:200])
            info.update((overrides or {}).get(i, {}))
            sessions[sid] = session_info(f"C:/t/j{i}.jsonl", f"2026-10-14T18:3{i}:13Z",
                                         f"2026-10-14T18:3{i}:20Z", **info)
        data = ledger([project("p-shop", "shop", threads=[t["id"] for t in threads])], threads)
        return data, sessions

    def test_untitled_single_reply_pair_with_shared_template_is_automated(self):
        data, sessions = self.pair()
        auto = automated_sessions(data["threads"], sessions)
        self.assertEqual(auto, {"s-job0": "templated-prompt", "s-job1": "templated-prompt"})
        proj = query_ctx(ledger_data=data, sessions=sessions)["projects"][0]
        self.assertEqual([t["id"] for t in proj["threads"]], ["t-real"])
        self.assertEqual(proj["automatedRuns"]["signals"], {"templated-prompt": 2})

    def test_short_templated_prompts_of_a_burst(self):
        short = "Summarize the daily status of the export team for item {}"  # under 100 chars
        data, sessions = self.pair({0: {"prompt": short.format(4711)},
                                    1: {"prompt": short.format(4802)}})
        auto = automated_sessions(data["threads"], sessions)
        self.assertEqual(set(auto.values()), {"templated-prompt"})
        self.assertEqual(len(auto), 2)

    def test_titled_session_is_interactive(self):
        data, sessions = self.pair({1: {"title_source": "ai-title"}})
        self.assertEqual(automated_sessions(data["threads"], sessions), {})

    def test_more_than_one_reply_is_interactive(self):
        data, sessions = self.pair({1: {"assistant_messages": 2}})
        self.assertEqual(automated_sessions(data["threads"], sessions), {})

    def test_forks_share_their_first_prompt_and_are_not_automated(self):
        fork = {"familyId": "f1", "members": ["s-job0", "s-job1"], "sharedMessages": 1,
                "parent": "s-job0", "divergedAt": None}
        data, sessions = self.pair({0: {"fork": fork}, 1: {"fork": fork}})
        self.assertEqual(automated_sessions(data["threads"], sessions), {})

    def test_short_shared_prefix_is_not_a_template(self):
        data, sessions = self.pair({1: {"prompt": TEMPLATE[:20] + " something else entirely, "
                                                    "a different question about the build"}})
        self.assertEqual(automated_sessions(data["threads"], sessions), {})

    def test_single_untitled_quick_question_is_kept(self):
        data, sessions = self.pair()
        del sessions["s-job1"]
        data["threads"] = [t for t in data["threads"] if t["id"] != "t-job1"]
        self.assertEqual(automated_sessions(data["threads"], sessions), {})

    def test_whitespace_differences_do_not_break_the_exact_prompt_match(self):
        data, sessions = self.pair({0: {"entrypoint": "sdk-cli"},
                                      1: {"prompt": TEMPLATE.replace(" ", "  ", 3)
                                          + "4711 Export pallets by client",
                                          "title_source": "ai-title"}})
        sessions["s-job0"]["lastPrompt"] = TEMPLATE + "4711 Export pallets by client"
        auto = automated_sessions(data["threads"], sessions)
        self.assertEqual(auto["s-job1"], "prompt-of-automated")


class HandoffTest(unittest.TestCase):
    def test_notes_listed_with_staleness_flag(self):
        notes = [note("C:/r/shop/qa/NEXT-STEPS.md", "2026-11-10T12:00:00+00:00", "fresh"),
                 note("C:/r/shop/HANDOFF.md", "2026-11-01T10:00:00+00:00", "old plan")]
        calls = []
        proj = query_ctx(handoff=lambda path: calls.append(path) or notes)["projects"][0]
        self.assertEqual(calls, ["C:/r/Shop_Exportadora"])
        fresh, old = proj["handoff"]
        self.assertFalse(fresh["olderThanActivity"])
        self.assertTrue(old["olderThanActivity"])

    def test_render_before_threads(self):
        notes = [note(text="## Next\n- run QA", truncated=True),
                 note("C:/r/shop/STATUS.md", "2026-11-01T10:00:00+00:00", "old")]
        text = render_markdown(query_ctx(handoff=lambda path: notes))
        self.assertIn("### Handoff notes", text)
        self.assertLess(text.index("### Handoff notes"), text.index("### Threads"))
        self.assertIn("C:/r/shop/HANDOFF.md (modified 2026-11-08", text)
        self.assertIn("possibly stale", text)
        self.assertIn("- run QA", text)
        self.assertIn("[note truncated", text)

    def test_truncated_note_shows_lead_toc_and_path(self):
        toc = [{"line": 1, "level": 1, "heading": "Agent next steps"},
               {"line": 40, "level": 2, "heading": "Sprint 15 closed 2026-08-26"},
               {"line": 310, "level": 2, "heading": "4. Pending for the next iteration"},
               {"line": 322, "level": 3, "heading": "4.1 Blockers"}]
        long_note = note("C:/r/shop/qa/AGENT-NEXT-STEPS.md", text="# Agent next steps\n> read me",
                         truncated=True, toc=toc, lines=480)
        long_note["bytes"] = 28000
        text = render_markdown(query_ctx(handoff=lambda path: [long_note]))
        self.assertIn("[note truncated: 28000 bytes, 480 lines; title and lead shown. Read the "
                      "full file: C:/r/shop/qa/AGENT-NEXT-STEPS.md]", text)
        self.assertIn("Contents (line: heading):", text)
        self.assertIn("  - L310 ## 4. Pending for the next iteration", text)
        self.assertIn("    - L322 ### 4.1 Blockers", text)
        self.assertLess(text.index("> read me"), text.index("Contents (line: heading):"))

    def test_whole_note_has_no_toc(self):
        whole = note(text="# S\nall good", toc=[{"line": 1, "level": 1, "heading": "S"}])
        text = render_markdown(query_ctx(handoff=lambda path: [whole]))
        self.assertNotIn("Contents (line: heading):", text)
        self.assertNotIn("note truncated", text)

    def test_long_toc_is_capped(self):
        toc = [{"line": i, "level": 2, "heading": f"h{i}"} for i in range(1, 121)]
        text = render_markdown(query_ctx(handoff=lambda path: [note(truncated=True, toc=toc)]))
        self.assertIn("L80 ## h80", text)
        self.assertNotIn("L81 ## h81", text)
        self.assertIn("... 40 more headings in the file", text)

    def test_shortened_note_is_marked(self):
        notes = [note(text="n" * 3000)]
        ctx = query_ctx(transcripts=0, handoff=lambda path: notes)
        limit = len(render_markdown(ctx)) - 1500
        text, fitted = fit(ctx, limit, render_markdown)
        self.assertTrue(fitted["projects"][0]["handoff"][0]["shortened"])
        self.assertIn("first 800 chars shown, shortened by --max-chars. Read the full file", text)

    def test_drop_order_excerpts_then_handoff_then_threads(self):
        notes = [note(text="n" * 3000)]
        ctx = query_ctx(transcripts=3, handoff=lambda path: notes)
        limit = len(render_markdown(without_excerpts(ctx))) - 1000
        text, fitted = fit(ctx, limit, render_markdown)
        trunc = fitted["truncation"]
        self.assertEqual(trunc["droppedExcerpts"], 3)
        self.assertEqual(trunc["shortenedHandoffNotes"], 1)
        self.assertEqual(trunc["droppedThreads"], 0)
        self.assertTrue(fitted["projects"][0]["handoff"][0]["truncated"])
        self.assertLessEqual(len(text), limit)


def without_excerpts(ctx):
    ctx = copy.deepcopy(ctx)
    for p in ctx["projects"]:
        for t in p["threads"]:
            t["excerpts"] = []
    return ctx


if __name__ == "__main__":
    unittest.main()
