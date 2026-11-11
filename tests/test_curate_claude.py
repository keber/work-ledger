import json
import os
import subprocess
import tempfile
import unittest

from work_ledger.curate_claude import (MODEL, NPM_NATIVE_PARTS, TIMEOUT_SECONDS, ClaudeError,
                                       build_argv, claude_port, parse_envelope,
                                       resolve_claude)

SCHEMA = '{"type":"object"}'


def envelope(**fields):
    base = {"type": "result", "subtype": "success", "is_error": False}
    base.update(fields)
    return json.dumps(base)


class ArgvTest(unittest.TestCase):
    def test_flags_exactly_as_the_spec(self):
        argv = build_argv("C:/bin/claude.exe", "SYSTEM\nPROMPT", SCHEMA)
        self.assertEqual(argv, ["C:/bin/claude.exe", "-p", "--model", "claude-opus-5-5",
                                "--output-format", "json", "--json-schema", SCHEMA,
                                "--tools", "", "--strict-mcp-config", "--restricted",
                                "--no-session-persistence", "--system-prompt",
                                "SYSTEM\nPROMPT"])
        self.assertEqual(MODEL, "claude-opus-5-5")
        self.assertNotIn("--bare", argv)


def native_beside(wrapper_dir):
    """Create the npm layout's native binary next to a wrapper dir; returns its path."""
    path = os.path.join(wrapper_dir, *NPM_NATIVE_PARTS)
    os.makedirs(os.path.dirname(path))
    with open(path, "wb") as fh:
        fh.write(b"")
    return path


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.npm = os.path.join(self.tmp.name, "npm")
        os.makedirs(self.npm)
        self.wrapper = os.path.join(self.npm, "claude.cmd")

    def test_layout_constant(self):
        self.assertEqual(NPM_NATIVE_PARTS,
                         ("node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe"))

    def test_explicit_path_wins(self):
        self.assertEqual(resolve_claude("D:/x/claude.exe", which=lambda n: "C:/other"),
                         "D:/x/claude.exe")

    def test_native_exe_on_path_is_preferred_over_the_wrapper(self):
        found = {"claude.exe": "C:/bin/claude.exe", "claude": self.wrapper}
        self.assertEqual(resolve_claude(None, which=found.get), "C:/bin/claude.exe")

    def test_plain_lookup_when_no_exe_on_path(self):
        found = {"claude": "/usr/local/bin/claude"}
        self.assertEqual(resolve_claude(None, which=found.get), "/usr/local/bin/claude")

    def test_not_found(self):
        with self.assertRaises(ClaudeError) as ctx:
            resolve_claude(None, which=lambda n: None)
        self.assertIn("--claude", str(ctx.exception))

    def test_wrapper_on_path_resolves_to_the_sibling_native_binary(self):
        native = native_beside(self.npm)
        found = {"claude": self.wrapper}
        self.assertEqual(resolve_claude(None, which=found.get), native)

    def test_explicit_wrapper_resolves_too(self):
        native = native_beside(self.npm)
        for name in ("claude.cmd", "CLAUDE.BAT"):
            self.assertEqual(resolve_claude(os.path.join(self.npm, name)), native)

    def test_wrapper_without_native_binary_is_refused(self):
        for name in ("claude.cmd", "CLAUDE.BAT"):
            with self.assertRaises(ClaudeError) as ctx:
                resolve_claude(os.path.join(self.npm, name))
            self.assertIn("batch", str(ctx.exception))
            self.assertIn("--claude", str(ctx.exception))
        with self.assertRaises(ClaudeError):
            resolve_claude(None, which={"claude": self.wrapper}.get)

    def test_a_directory_at_the_native_path_is_not_a_binary(self):
        os.makedirs(os.path.join(self.npm, *NPM_NATIVE_PARTS))
        with self.assertRaises(ClaudeError):
            resolve_claude(self.wrapper)


class EnvelopeTest(unittest.TestCase):
    def test_structured_output_field(self):
        reply = parse_envelope(envelope(structured_output={"pieces": []}, result="text"))
        self.assertEqual(reply.output, {"pieces": []})
        self.assertEqual(reply.warnings, [])

    def test_result_object_or_json_string_with_a_warning(self):
        for result in ({"pieces": []}, '{"pieces": []}', '```json\n{"pieces": []}\n```'):
            reply = parse_envelope(envelope(result=result))
            self.assertEqual(reply.output, {"pieces": []})
            self.assertIn("structured_output", reply.warnings[0])

    def test_missing_is_error_is_a_warning(self):
        reply = parse_envelope(json.dumps({"structured_output": {"pieces": []}}))
        self.assertEqual(reply.output, {"pieces": []})
        self.assertIn("is_error", reply.warnings[0])

    def test_is_error(self):
        with self.assertRaises(ClaudeError) as ctx:
            parse_envelope(envelope(is_error=True, subtype="error_max_turns", result="boom"))
        self.assertIn("is_error", str(ctx.exception))
        self.assertIn("error_max_turns", str(ctx.exception))

    def test_message_array_uses_the_last_result(self):
        stdout = json.dumps([{"type": "system"},
                             {"type": "result", "is_error": False,
                              "structured_output": {"pieces": []}}])
        self.assertEqual(parse_envelope(stdout).output, {"pieces": []})

    def test_invalid_envelopes(self):
        cases = [("", "empty"), ("not json", "not valid JSON"), ("[1, 2]", "no result"),
                 ("3", "unexpected"), (envelope(), "no structured result"),
                 (envelope(result="plain prose"), "not valid JSON"),
                 (envelope(result="[1]"), "not a JSON object"),
                 (envelope(structured_output=[1]), "not a JSON object")]
        for stdout, fragment in cases:
            with self.subTest(stdout=stdout):
                with self.assertRaises(ClaudeError) as ctx:
                    parse_envelope(stdout)
                self.assertIn(fragment, str(ctx.exception))


class FakeRun:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


def done(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


class PortTest(unittest.TestCase):
    def test_runs_without_shell_with_input_on_stdin(self):
        run = FakeRun(done(stdout=envelope(structured_output={"pieces": []})))
        reply = claude_port("C:/bin/claude.exe", run=run)("PROMPT", SCHEMA, '{"threads": []}')
        self.assertEqual(reply.output, {"pieces": []})
        args, kwargs = run.calls[0]
        self.assertEqual(args, build_argv("C:/bin/claude.exe", "PROMPT", SCHEMA))
        self.assertEqual(kwargs["input"], '{"threads": []}')
        self.assertEqual(kwargs["timeout"], TIMEOUT_SECONDS)
        self.assertEqual(TIMEOUT_SECONDS, 300)
        self.assertFalse(kwargs.get("shell"))
        self.assertFalse(kwargs.get("check"))
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertTrue(os.path.isabs(kwargs["cwd"]))
        self.assertFalse(os.path.exists(kwargs["cwd"]), "temp cwd is removed after the call")

    def test_nonzero_exit(self):
        run = FakeRun(done(2, stdout="", stderr="auth failed\n"))
        with self.assertRaises(ClaudeError) as ctx:
            claude_port("claude.exe", run=run)("P", SCHEMA, "{}")
        self.assertIn("exit code 2", str(ctx.exception))
        self.assertIn("auth failed", str(ctx.exception))

    def test_nonzero_exit_with_error_envelope(self):
        run = FakeRun(done(1, stdout=envelope(is_error=True, result="quota")))
        with self.assertRaises(ClaudeError) as ctx:
            claude_port("claude.exe", run=run)("P", SCHEMA, "{}")
        self.assertIn("quota", str(ctx.exception))

    def test_timeout(self):
        run = FakeRun(error=subprocess.TimeoutExpired(["claude"], 300))
        with self.assertRaises(ClaudeError) as ctx:
            claude_port("claude.exe", run=run)("P", SCHEMA, "{}")
        self.assertIn("timed out after 300 s", str(ctx.exception))

    def test_cannot_start(self):
        run = FakeRun(error=FileNotFoundError("nope"))
        with self.assertRaises(ClaudeError) as ctx:
            claude_port("claude.exe", run=run)("P", SCHEMA, "{}")
        self.assertIn("cannot start claude", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
