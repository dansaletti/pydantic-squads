"""Run the product squad on a local Claude Code install instead of an API key.

Needs the optional `ai` extra (`pydantic-ai-slim`) and the `claude` CLI on
`PATH`, logged in (`claude` then `/login`). See ADR 0008.

`ClaudeCodeModel` is a Pydantic AI `Model` that sends each model request to
`claude -p` as a one-shot, tool-less call and asks for a JSON envelope back
(`--json-schema`): either text, or calls to the tools Pydantic AI offered.
The tools themselves still run in Python, inside Pydantic AI, so the
squad's permissions, approvals and output validators work unchanged; Claude
Code only plays the part of the model.

By default the subprocess runs without `ANTHROPIC_API_KEY` or
`ANTHROPIC_AUTH_TOKEN` in its environment, so Claude Code falls back to the
logged-in account (e.g. a Pro or Max subscription) instead of billing an API
key. That login is meant for your own, local use: Anthropic does not allow
third-party products to offer claude.ai login or its rate limits to their
users, so never ship this backend as part of a product.
"""

import asyncio
import json
import os
import re
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic_ai.messages import (
    InstructionPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage

MODEL_PREFIX = "claude-code"
"""`ProductSquad(model="claude-code")` or `model="claude-code:<model>"` selects this backend."""

_API_CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

ENVELOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "A plain-text reply. Empty when you only call tools."},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
        },
    },
    "required": ["text", "tool_calls"],
}

Runner = Callable[[list[str], str, dict[str, str], str, float], Awaitable["ProcessResult"]]
"""Runs `argv` with `stdin` text, `env` and `cwd`, within `timeout` seconds."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ClaudeCodeError(RuntimeError):
    """`claude -p` failed, timed out, or answered with something that isn't its JSON result."""


async def run_process(argv: list[str], stdin: str, env: dict[str, str], cwd: str, timeout: float) -> ProcessResult:
    """The default `Runner`: an asyncio subprocess, killed on timeout."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ClaudeCodeError(f"claude did not answer within {timeout:g}s") from None
    assert proc.returncode is not None  # communicate() waited for the process to exit
    return ProcessResult(proc.returncode, stdout.decode(), stderr.decode())


def _tool_line(tool: ToolDefinition) -> str:
    schema = json.dumps(tool.parameters_json_schema, ensure_ascii=False)
    description = tool.description or "(no description)"
    return f"### {tool.name}\n{description}\nArguments JSON schema: {schema}"


_NATIVE_CALL_HINT = (
    '- If invoking a function fails with "No such tool available", you invoked it as a tool of this '
    "session. Nothing is broken: put that same call in `tool_calls` of your JSON answer instead."
)


def _protocol(params: ModelRequestParameters) -> str:
    lines = [
        "# Response protocol",
        "",
        "You are the model behind an agent. Your only way to act is your structured JSON answer "
        '{"text": string, "tool_calls": [{"name": string, "arguments": object}]}. '
        "The functions listed below are run by the agent, outside this session: they are not tools "
        "you can invoke directly, and that is expected. To run them, list them in `tool_calls`; the "
        "agent runs them and the next turn shows their results as `[tool result ...]`. Never say a "
        "function is unavailable and never make up its result.",
        _NATIVE_CALL_HINT,
        "- To run functions, list the calls in `tool_calls` (several at once if they are independent) "
        "and wait for their results. `arguments` must match the function's JSON schema.",
    ]
    if params.allow_text_output:
        lines.append("- To reply to the user directly, put your reply in `text` and leave `tool_calls` empty.")
    else:
        lines.append("- A text-only answer is not accepted: finish by calling one of the output functions.")
    if params.function_tools:
        lines += ["", "## Functions", *(_tool_line(t) for t in params.function_tools)]
    if params.output_tools:
        lines += [
            "",
            "## Output functions",
            "Call exactly one of these, alone, in `tool_calls` to deliver your final answer.",
            *(_tool_line(t) for t in params.output_tools),
        ]
    return "\n".join(lines)


def _user_text(part: UserPromptPart) -> str:
    if isinstance(part.content, str):
        return part.content
    return "\n".join(item if isinstance(item, str) else f"[unsupported {type(item).__name__} omitted]" for item in part.content)


def render_system_prompt(instructions: str | None, messages: Sequence[ModelMessage], params: ModelRequestParameters) -> str:
    """The `--system-prompt` for one request: the agent's system prompts and instructions, then the protocol."""
    sections = [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, SystemPromptPart)
    ]
    if instructions:
        sections.append(instructions)
    sections.append(_protocol(params))
    return "\n\n".join(sections)


def render_transcript(messages: Sequence[ModelMessage]) -> str:
    """The conversation so far as plain text, sent to `claude -p` on stdin."""
    blocks: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    blocks.append(f"[user]\n{_user_text(part)}")
                elif isinstance(part, ToolReturnPart):
                    blocks.append(f"[tool result {part.tool_name} id={part.tool_call_id}]\n{part.model_response_str()}")
                elif isinstance(part, RetryPromptPart):
                    target = f" {part.tool_name} id={part.tool_call_id}" if part.tool_name else ""
                    blocks.append(f"[retry{target}]\n{part.model_response()}")
        else:
            for part in message.parts:
                if isinstance(part, TextPart) and part.content:
                    blocks.append(f"[assistant]\n{part.content}")
                elif isinstance(part, ToolCallPart):
                    args = json.dumps(part.args_as_dict(), ensure_ascii=False)
                    blocks.append(f"[assistant tool call {part.tool_name} id={part.tool_call_id}]\n{args}")
    blocks.append("Reply to the last turn above, following the response protocol.")
    return "\n\n".join(blocks)


_NO_CALL_CORRECTION = (
    "[retry]\nYour last answer had no `tool_calls`, but a text-only answer is not accepted here. "
    "List the function calls you need in `tool_calls`, or call an output function to finish."
)

_UNAVAILABLE_CORRECTION = (
    "[retry]\nYour last answer said functions are unavailable. They are available: \"No such tool "
    'available" only means you invoked them as tools of this session. Put the same calls in '
    "`tool_calls` of your JSON answer; the agent runs them. Do not answer without their results."
)

# What Claude Code answers when the model invokes a listed function as a native tool.
_NO_SUCH_TOOL_RE = re.compile(r"no such tool", re.IGNORECASE)
_UNAVAILABLE_RE = re.compile(
    r"unavailable|not available|indispon[ií]ve(?:l|is)|n[ãa]o est[áa]o? dispon[ií]ve", re.IGNORECASE
)


def _claims_tool_unavailable(text: str, params: ModelRequestParameters) -> bool:
    """Whether a text-only answer says the offered functions can't be used (the model tried a native tool).

    The CLI's own error is enough; a looser wording only counts next to a function's name.
    """
    if not params.function_tools:
        return False
    if _NO_SUCH_TOOL_RE.search(text):
        return True
    return bool(_UNAVAILABLE_RE.search(text)) and any(tool.name in text for tool in params.function_tools)


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _envelope(result: dict[str, Any]) -> dict[str, Any] | None:
    structured = result.get("structured_output")
    if isinstance(structured, dict):
        return structured
    text = str(result.get("result") or "").strip()
    match = _FENCE_RE.match(text)
    try:
        parsed = json.loads(match.group(1) if match else text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_result(stdout: str) -> tuple[list[ModelResponsePart], RequestUsage]:
    """Turn `claude -p --output-format json` output into response parts and usage."""
    try:
        result = json.loads(stdout)
    except ValueError:
        raise ClaudeCodeError(f"claude did not print a JSON result: {stdout[:500]!r}") from None
    if not isinstance(result, dict):
        raise ClaudeCodeError(f"claude did not print a JSON object: {stdout[:500]!r}")
    if result.get("is_error") or result.get("subtype", "success") != "success":
        raise ClaudeCodeError(f"claude reported an error: {result.get('result') or result.get('subtype')}")

    usage_data = result.get("usage") or {}
    cache_read = int(usage_data.get("cache_read_input_tokens") or 0)
    cache_write = int(usage_data.get("cache_creation_input_tokens") or 0)
    usage = RequestUsage(
        # The CLI counts cached input apart (nearly all of the prompt, leaving `input_tokens` at a
        # handful); Pydantic AI's `input_tokens` is the whole prompt, cached or not.
        input_tokens=int(usage_data.get("input_tokens") or 0) + cache_read + cache_write,
        output_tokens=int(usage_data.get("output_tokens") or 0),
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    cost = result.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        # At API list prices: what the call would cost on a key, not a charge on a subscription.
        usage.cost = Decimal(str(cost))

    envelope = _envelope(result)
    if envelope is None:
        # Not the protocol: hand the text to Pydantic AI, which retries when text isn't a valid output.
        return [TextPart(content=str(result.get("result") or ""))], usage

    parts: list[ModelResponsePart] = []
    text = envelope.get("text")
    if isinstance(text, str) and text.strip():
        parts.append(TextPart(content=text))
    for call in envelope.get("tool_calls") or []:
        if not isinstance(call, dict) or not isinstance(call.get("name"), str):
            continue
        args = call.get("arguments")
        parts.append(
            ToolCallPart(
                tool_name=call["name"],
                args=args if isinstance(args, dict) else {},
                tool_call_id=f"cc_{uuid.uuid4().hex}",
            )
        )
    if not parts:
        parts.append(TextPart(content=""))
    return parts, usage


class ClaudeCodeModel(Model):
    """A Pydantic AI model backed by the local `claude` CLI and its logged-in account.

    `model_name` is passed to `claude --model` (e.g. `"sonnet"`, `"opus"`);
    `None` keeps Claude Code's own default. `use_subscription=True` (the
    default) removes API credentials from the subprocess environment so the
    login is used; set it to `False` to let Claude Code use them.
    `extra_args` are appended to every `claude` call. `cwd` is where the CLI
    runs: by default a fresh empty directory per call, so no project
    `CLAUDE.md`, hooks or `.mcp.json` leak into the squad's context.

    When an agent only accepts a tool call (a structured output such as a
    `Bet`) and the answer has none, or when a text answer claims one of the
    offered functions is unavailable (the model reached for a native Claude
    Code tool), the request is repeated up to `protocol_retries` times with
    a correction, before Pydantic AI's own output retries are spent on it.
    A text answer that still claims so after that raises `ClaudeCodeError`
    instead of passing as a reply.

    Usage is what the CLI reports for the call, corrections included:
    `input_tokens` is the whole prompt (cached tokens too) and `cost` is
    Claude Code's own `total_cost_usd`, an estimate at API list prices
    that a subscription is not actually charged.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        executable: str = "claude",
        use_subscription: bool = True,
        timeout: float = 600.0,
        extra_args: Sequence[str] = (),
        cwd: str | Path | None = None,
        protocol_retries: int = 1,
        runner: Runner = run_process,
        settings: ModelSettings | None = None,
    ) -> None:
        super().__init__(settings=settings)
        self._model_name = model_name
        self.executable = executable
        self.use_subscription = use_subscription
        self.timeout = timeout
        self.extra_args = list(extra_args)
        self.cwd = Path(cwd) if cwd is not None else None
        self.protocol_retries = protocol_retries
        self._runner = runner

    @property
    def model_name(self) -> str:
        return self._model_name or "default"

    @property
    def system(self) -> str:
        return MODEL_PREFIX

    def argv(self, system_prompt_file: str) -> list[str]:
        """The `claude` command line for one request."""
        argv = [
            self.executable,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--system-prompt-file",
            system_prompt_file,
            "--json-schema",
            json.dumps(ENVELOPE_SCHEMA),
        ]
        if self._model_name:
            argv += ["--model", self._model_name]
        return argv + self.extra_args

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.use_subscription:
            for var in _API_CREDENTIAL_VARS:
                env.pop(var, None)
        return env

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        model_settings, params = self.prepare_request(model_settings, model_request_parameters)
        instruction_parts = self._get_instruction_parts(messages, params)
        instructions = InstructionPart.join(instruction_parts) if instruction_parts else None
        system_prompt = render_system_prompt(instructions, messages, params)
        transcript = render_transcript(messages)

        total = RequestUsage()
        for attempt in range(self.protocol_retries + 1):
            parts, usage = await self._call(system_prompt, transcript)
            total.incr(usage)
            if any(isinstance(part, ToolCallPart) for part in parts):
                break
            text = "\n".join(part.content for part in parts if isinstance(part, TextPart))
            unavailable = params.allow_text_output and _claims_tool_unavailable(text, params)
            if attempt == self.protocol_retries:
                if unavailable:
                    # Never hand this back as a reply: it reads fine but ignored every function.
                    raise ClaudeCodeError(
                        "the model answered that a function is unavailable instead of calling it "
                        f"through `tool_calls`: {text[:300]!r}"
                    )
                break
            if not params.allow_text_output:
                transcript += "\n\n" + _NO_CALL_CORRECTION
            elif unavailable:
                transcript += "\n\n" + _UNAVAILABLE_CORRECTION
            else:
                break
        return ModelResponse(parts=parts, usage=total, model_name=self.model_name, provider_name=MODEL_PREFIX)

    async def _call(self, system_prompt: str, transcript: str) -> tuple[list[ModelResponsePart], RequestUsage]:
        with tempfile.TemporaryDirectory(prefix="pydantic-squads-") as tmp:
            prompt_file = Path(tmp) / "system-prompt.md"
            prompt_file.write_text(system_prompt, encoding="utf-8")
            cwd = str(self.cwd) if self.cwd is not None else tmp
            try:
                result = await self._runner(self.argv(str(prompt_file)), transcript, self.env(), cwd, self.timeout)
            except FileNotFoundError:
                raise ClaudeCodeError(
                    f"'{self.executable}' not found: install Claude Code and log in with `claude`"
                ) from None
        if result.returncode != 0 and not result.stdout.strip():
            raise ClaudeCodeError(f"claude exited with {result.returncode}: {result.stderr.strip()[:500]}")
        return parse_result(result.stdout)


def resolve_model(model: Any) -> Any:
    """Turn `"claude-code"` / `"claude-code:<model>"` into a `ClaudeCodeModel`; pass anything else through."""
    if isinstance(model, str) and (model == MODEL_PREFIX or model.startswith(f"{MODEL_PREFIX}:")):
        _, _, name = model.partition(":")
        return ClaudeCodeModel(name or None)
    return model
