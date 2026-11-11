"""Claude Code in headless mode, behind a port.

The port is any callable `(system_prompt, schema_json, input_text) -> ClaudeReply` that
raises ClaudeError on failure. `claude_port` is the real adapter; tests inject fakes and
never run `claude`. Authentication is Claude Code's own (OAuth), so this project handles no
API key.
"""

import json
import os
import shutil
import subprocess
import tempfile
from collections import namedtuple

MODEL = "claude-opus-5-5"
TIMEOUT_SECONDS = 300
DETAIL_CHARS = 500
BATCH_SUFFIXES = (".cmd", ".bat")
# Where the npm package keeps the native binary, relative to the claude.cmd wrapper.
NPM_NATIVE_PARTS = ("node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")

ClaudeReply = namedtuple("ClaudeReply", "output warnings")


class ClaudeError(Exception):
    """The claude call failed: not found, non-zero exit, timeout, or an unusable result."""


def build_argv(executable, system_prompt, schema):
    """argv for one call. No shell; the input goes on stdin."""
    return [executable, "-p", "--model", MODEL, "--output-format", "json",
            "--json-schema", schema, "--tools", "", "--strict-mcp-config", "--restricted",
            "--no-session-persistence", "--system-prompt", system_prompt]


def resolve_claude(path=None, which=None):
    """Executable to run. Raises ClaudeError.

    Order: `path` when given; else `claude.exe` on PATH; else `claude` on PATH. Batch
    wrappers (`claude.cmd` from npm) are never run: Windows runs them through cmd.exe,
    which re-parses the arguments and cannot carry the multi-line system prompt safely.
    A wrapper is replaced by the native binary the npm package installs beside it,
    `<wrapper dir>/node_modules/@anthropic-ai/claude-code/bin/claude.exe`, when it exists.
    """
    which = which or shutil.which
    executable = path or which("claude.exe") or which("claude")
    if not executable:
        raise ClaudeError("claude not found on PATH; pass --claude PATH")
    if os.path.splitext(executable)[1].lower() not in BATCH_SUFFIXES:
        return executable
    native = os.path.join(os.path.dirname(os.path.abspath(executable)), *NPM_NATIVE_PARTS)
    if os.path.isfile(native):
        return native
    raise ClaudeError(f"batch wrapper not supported: {executable}, and no native binary at "
                      f"{native}; pass --claude with the path of the native claude executable")


def _detail(text):
    return (text or "").strip()[:DETAIL_CHARS] or "no output"


def _strip_fence(text):
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3]
        first_newline = stripped.find("\n")
        if first_newline != -1 and not stripped[:first_newline].strip().startswith("{"):
            stripped = stripped[first_newline + 1:]
    return stripped.strip()


def _result_message(data):
    """The result object: the envelope itself, or the last `type: result` of a message list."""
    if isinstance(data, list):
        results = [m for m in data if isinstance(m, dict) and m.get("type") == "result"]
        if not results:
            raise ClaudeError("envelope: no result message in the JSON array")
        return results[-1]
    if not isinstance(data, dict):
        raise ClaudeError("envelope: unexpected JSON value, expected an object")
    return data


def _object(value, where):
    if not isinstance(value, dict):
        raise ClaudeError(f"{where} is not a JSON object")
    return value


def parse_envelope(stdout):
    """ClaudeReply from `--output-format json` stdout. Raises ClaudeError.

    The structured result is read from `structured_output`, else from `result` (an object,
    or a JSON string, optionally fenced). Missing fields that the format usually has are
    reported as warnings, so a format change is visible in the log.
    """
    if not (stdout or "").strip():
        raise ClaudeError("envelope: empty output")
    try:
        data = json.loads(stdout)
    except ValueError:
        raise ClaudeError("envelope: not valid JSON") from None
    message = _result_message(data)
    warnings = []
    if "is_error" not in message:
        warnings.append("envelope: no is_error field; assuming success")
    if message.get("is_error") is True or str(message.get("subtype", "")).startswith("error"):
        detail = message.get("result")
        detail = _detail(detail if isinstance(detail, str) else json.dumps(detail))
        raise ClaudeError(f"is_error set (subtype {message.get('subtype') or '-'}): {detail}")
    if message.get("structured_output") is not None:
        return ClaudeReply(_object(message["structured_output"], "structured_output"),
                           warnings)
    result = message.get("result")
    if result is None:
        raise ClaudeError("envelope: no structured result (looked for structured_output "
                          "and result)")
    warnings.append("envelope: no structured_output field; parsed result instead")
    if isinstance(result, str):
        try:
            result = json.loads(_strip_fence(result))
        except ValueError:
            raise ClaudeError("result: not valid JSON") from None
    return ClaudeReply(_object(result, "result"), warnings)


def claude_port(executable, run=subprocess.run):
    """Port that runs `executable` once per call, in an empty temporary directory."""
    def generate(system_prompt, schema, input_text):
        argv = build_argv(executable, system_prompt, schema)
        try:
            # An empty cwd keeps project instruction files out of the call.
            with tempfile.TemporaryDirectory(prefix="work-ledger-curate-") as cwd:
                result = run(argv, input=input_text, capture_output=True, encoding="utf-8",
                             errors="replace", timeout=TIMEOUT_SECONDS, check=False, cwd=cwd,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise ClaudeError(f"timed out after {TIMEOUT_SECONDS} s") from None
        except OSError as exc:
            raise ClaudeError(f"cannot start claude: {exc}") from None
        if result.returncode != 0:
            try:
                parse_envelope(result.stdout)
            except ClaudeError as exc:
                if "is_error" in str(exc):
                    raise ClaudeError(f"exit code {result.returncode}: {exc}") from None
            raise ClaudeError(f"exit code {result.returncode}: {_detail(result.stderr)}")
        return parse_envelope(result.stdout)
    return generate
