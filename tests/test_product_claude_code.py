import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")

from pydantic import BaseModel
from pydantic_ai import Agent, models as pydantic_ai_models
from pydantic_ai.messages import (
    BinaryContent,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

from pydantic_squads.product.assembly import ProductSquad
from pydantic_squads.product.claude_code import (
    ClaudeCodeError,
    ClaudeCodeModel,
    ProcessResult,
    parse_result,
    render_system_prompt,
    render_transcript,
    resolve_model,
    run_process,
)
from pydantic_squads.product.knowledge import MarkdownKnowledgeBase

pydantic_ai_models.ALLOW_MODEL_REQUESTS = False


def _stdout(envelope: dict | None = None, **extra) -> str:
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": json.dumps(envelope) if envelope is not None else "",
        "structured_output": envelope,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 2,
        },
    }
    result.update(extra)
    return json.dumps(result)


class FakeRunner:
    """Replays canned `claude -p` outputs and records every call."""

    def __init__(self, *outputs: str, returncode: int = 0, stderr: str = "") -> None:
        self.outputs = list(outputs)
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[dict] = []

    async def __call__(self, argv, stdin, env, cwd, timeout):
        system_prompt = Path(argv[argv.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")
        self.calls.append(dict(argv=argv, stdin=stdin, env=env, cwd=cwd, timeout=timeout, system=system_prompt))
        return ProcessResult(self.returncode, self.outputs.pop(0), self.stderr)


class City(BaseModel):
    name: str
    population_millions: float


def _city_agent(runner: FakeRunner, **kwargs) -> Agent:
    agent = Agent(ClaudeCodeModel("sonnet", runner=runner, **kwargs), output_type=City, system_prompt="Be brief.")

    @agent.tool_plain
    def lookup_population(city: str) -> float:
        """Return a city's population in millions."""
        return 12.4

    return agent


def test_agent_runs_tools_and_structured_output_through_the_cli():
    """A tool call and an output-tool call round-trip through the JSON envelope."""
    runner = FakeRunner(
        _stdout({"text": "", "tool_calls": [{"name": "lookup_population", "arguments": {"city": "SP"}}]}),
        _stdout({"text": "", "tool_calls": [{"name": "final_result", "arguments": {"name": "SP", "population_millions": 12.4}}]}),
    )
    result = _city_agent(runner).run_sync("Population of SP?")
    assert result.output == City(name="SP", population_millions=12.4)
    assert "[tool result lookup_population" in runner.calls[1]["stdin"]
    assert "12.4" in runner.calls[1]["stdin"]
    assert "Be brief." in runner.calls[0]["system"]
    assert "### lookup_population" in runner.calls[0]["system"]
    assert "## Output functions" in runner.calls[0]["system"]
    assert "text-only answer is not accepted" in runner.calls[0]["system"]
    assert result.usage.input_tokens == 20


def test_text_output_agent_gets_plain_reply():
    """An agent that accepts text gets the envelope's `text` as its output."""
    runner = FakeRunner(_stdout({"text": "Hello!", "tool_calls": []}))
    agent = Agent(ClaudeCodeModel(runner=runner))
    assert agent.run_sync("Hi").output == "Hello!"
    assert "reply to the user directly" in runner.calls[0]["system"]
    assert "## Functions" not in runner.calls[0]["system"]


def test_missing_call_is_corrected_before_pydantic_ai_retries():
    """A tool-only agent whose answer has no call is asked again with a correction."""
    runner = FakeRunner(
        _stdout({"text": "SP has 12 million people.", "tool_calls": []}),
        _stdout({"text": "", "tool_calls": [{"name": "final_result", "arguments": {"name": "SP", "population_millions": 12.0}}]}),
    )
    result = _city_agent(runner).run_sync("Population of SP?")
    assert result.output.population_millions == 12.0
    assert len(runner.calls) == 2
    assert "Your last answer had no `tool_calls`" in runner.calls[1]["stdin"]
    assert result.usage.input_tokens == 20  # both CLI calls are counted


def test_protocol_retries_zero_returns_the_text_as_is():
    """With `protocol_retries=0` the text answer goes straight back to Pydantic AI."""
    runner = FakeRunner(_stdout({"text": "no call", "tool_calls": []}))
    model = ClaudeCodeModel(runner=runner, protocol_retries=0)
    params = ModelRequestParameters(
        output_tools=[ToolDefinition(name="final_result", parameters_json_schema={"type": "object"})],
        output_mode="tool",
        allow_text_output=False,
    )
    response = asyncio.run(model.request([ModelRequest(parts=[UserPromptPart("hi")])], None, params))
    assert response.parts == [TextPart(content="no call")]
    assert response.provider_name == "claude-code"
    assert len(runner.calls) == 1


def test_argv_disables_native_tools_and_picks_model():
    """The CLI runs tool-less, without session files, with the chosen model and extra args."""
    argv = ClaudeCodeModel("opus", extra_args=["--effort", "high"]).argv("/tmp/sp.md")
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--system-prompt-file") + 1] == "/tmp/sp.md"
    assert json.loads(argv[argv.index("--json-schema") + 1])["required"] == ["text", "tool_calls"]
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[-2:] == ["--effort", "high"]
    assert "--model" not in ClaudeCodeModel().argv("x")


def test_env_drops_api_credentials_only_for_subscription(monkeypatch):
    """API credentials are removed so the CLI falls back to the logged-in account."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    assert "ANTHROPIC_API_KEY" not in ClaudeCodeModel().env()
    assert "ANTHROPIC_AUTH_TOKEN" not in ClaudeCodeModel().env()
    assert ClaudeCodeModel(use_subscription=False).env()["ANTHROPIC_API_KEY"] == "sk-test"


def test_cwd_defaults_to_a_fresh_directory_and_can_be_set(tmp_path):
    """Each call runs in an empty temp dir unless `cwd` is given."""
    runner = FakeRunner(_stdout({"text": "a", "tool_calls": []}), _stdout({"text": "b", "tool_calls": []}))
    Agent(ClaudeCodeModel(runner=runner)).run_sync("hi")
    Agent(ClaudeCodeModel(runner=runner, cwd=tmp_path)).run_sync("hi")
    assert runner.calls[0]["cwd"] != str(tmp_path)
    assert "pydantic-squads-" in runner.calls[0]["cwd"]
    assert runner.calls[1]["cwd"] == str(tmp_path)


def test_model_name_and_system():
    """The model reports its CLI model name, or `default`, under the `claude-code` system."""
    assert ClaudeCodeModel("sonnet").model_name == "sonnet"
    assert ClaudeCodeModel().model_name == "default"
    assert ClaudeCodeModel().system == "claude-code"


def test_nonzero_exit_without_output_raises():
    """A CLI failure with nothing on stdout surfaces stderr."""
    runner = FakeRunner("", returncode=1, stderr="Invalid API key")
    with pytest.raises(ClaudeCodeError, match="exited with 1: Invalid API key"):
        Agent(ClaudeCodeModel(runner=runner)).run_sync("hi")


def test_missing_executable_raises_a_helpful_error():
    """A missing `claude` binary says to install and log in."""
    model = ClaudeCodeModel(executable="definitely-not-a-real-claude-binary")
    with pytest.raises(ClaudeCodeError, match="not found: install Claude Code"):
        Agent(model).run_sync("hi")


def test_run_process_runs_a_real_subprocess(tmp_path):
    """The default runner passes stdin, env and cwd to the process."""
    script = "import os,sys; print(sys.stdin.read() + os.environ['X'] + os.getcwd())"
    result = asyncio.run(run_process([sys.executable, "-c", script], "in-", {**os.environ, "X": "env-"}, str(tmp_path), 30))
    assert result.returncode == 0
    assert result.stdout.strip() == f"in-env-{tmp_path}"


def test_run_process_times_out():
    """A process slower than the timeout is killed."""
    with pytest.raises(ClaudeCodeError, match="did not answer within"):
        asyncio.run(run_process([sys.executable, "-c", "import time; time.sleep(5)"], "", dict(os.environ), ".", 0.2))


def test_parse_result_reads_usage_and_tool_calls():
    """Usage maps to Pydantic AI fields; malformed calls are skipped and bad args become `{}`."""
    parts, usage = parse_result(
        _stdout(
            {
                "text": "thinking aloud",
                "tool_calls": [
                    {"name": "a", "arguments": {"x": 1}},
                    {"name": "b", "arguments": "oops"},
                    {"arguments": {}},
                    "junk",
                ],
            }
        )
    )
    assert isinstance(parts[0], TextPart) and parts[0].content == "thinking aloud"
    assert [(p.tool_name, p.args) for p in parts[1:]] == [("a", {"x": 1}), ("b", {})]
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens) == (10, 5, 3, 2)


def test_parse_result_falls_back_to_the_result_text():
    """Without `structured_output`, the `result` text is parsed, fenced or not."""
    fenced = '```json\n{"text": "hi", "tool_calls": []}\n```'
    parts, _ = parse_result(json.dumps({"subtype": "success", "result": fenced}))
    assert parts == [TextPart(content="hi")]
    parts, usage = parse_result(json.dumps({"subtype": "success", "result": "plain words"}))
    assert parts == [TextPart(content="plain words")]
    assert usage.input_tokens == 0
    parts, _ = parse_result(json.dumps({"subtype": "success", "result": "[1, 2]"}))
    assert parts == [TextPart(content="[1, 2]")]


def test_parse_result_empty_envelope_is_empty_text():
    """An envelope with neither text nor calls is an empty text part."""
    parts, _ = parse_result(_stdout({"text": " ", "tool_calls": []}))
    assert parts == [TextPart(content="")]


@pytest.mark.parametrize(
    "stdout, message",
    [
        ("not json", "did not print a JSON result"),
        ("[1]", "did not print a JSON object"),
        (json.dumps({"is_error": True, "result": "Not logged in"}), "reported an error: Not logged in"),
        (json.dumps({"subtype": "error_max_turns"}), "reported an error: error_max_turns"),
    ],
)
def test_parse_result_errors(stdout, message):
    """Anything that isn't a successful JSON result raises `ClaudeCodeError`."""
    with pytest.raises(ClaudeCodeError, match=message):
        parse_result(stdout)


def test_render_transcript_covers_every_part_kind():
    """User text, files, tool calls/results, retries and assistant text all reach the transcript."""
    messages = [
        ModelRequest(parts=[SystemPromptPart("sys"), UserPromptPart(["look", BinaryContent(b"x", media_type="image/png")])]),
        ModelResponse(parts=[ThinkingPart("hmm"), TextPart(""), TextPart("on it"), ToolCallPart("search", {"q": "a"}, tool_call_id="t1")]),
        ModelRequest(
            parts=[
                ToolReturnPart("search", ["n1"], tool_call_id="t1"),
                RetryPromptPart("bad args", tool_name="search", tool_call_id="t2"),
                RetryPromptPart("plain text not allowed"),
            ]
        ),
    ]
    transcript = render_transcript(messages)
    assert "[user]\nlook\n[unsupported BinaryContent omitted]" in transcript
    assert "hmm" not in transcript and "sys" not in transcript
    assert "[assistant]\non it" in transcript
    assert '[assistant tool call search id=t1]\n{"q": "a"}' in transcript
    assert '[tool result search id=t1]\n["n1"]' in transcript
    assert "[retry search id=t2]\nbad args" in transcript
    assert "[retry]\nValidation feedback:\nplain text not allowed" in transcript
    assert transcript.endswith("following the response protocol.")


def test_render_system_prompt_joins_system_parts_instructions_and_protocol():
    """System prompts come first, then instructions, then the protocol; tools without a description are marked."""
    params = ModelRequestParameters(function_tools=[ToolDefinition(name="t", parameters_json_schema={"type": "object"})])
    prompt = render_system_prompt("do X", [ModelRequest(parts=[SystemPromptPart("role")]), ModelResponse(parts=[])], params)
    assert prompt.index("role") < prompt.index("do X") < prompt.index("# Response protocol")
    assert "### t\n(no description)" in prompt
    assert "## Output functions" not in prompt


def test_agent_instructions_reach_the_system_prompt():
    """`Agent(instructions=...)` ends up in the system prompt file."""
    runner = FakeRunner(_stdout({"text": "ok", "tool_calls": []}))
    Agent(ClaudeCodeModel(runner=runner), instructions="Speak Portuguese.").run_sync("oi")
    assert "Speak Portuguese." in runner.calls[0]["system"]


def test_resolve_model_strings():
    """`claude-code[:name]` becomes a `ClaudeCodeModel`; anything else passes through."""
    assert isinstance(resolve_model("claude-code"), ClaudeCodeModel)
    assert resolve_model("claude-code").model_name == "default"
    assert resolve_model("claude-code:opus").model_name == "opus"
    assert resolve_model("anthropic:claude-sonnet-4-5") == "anthropic:claude-sonnet-4-5"
    sentinel = object()
    assert resolve_model(sentinel) is sentinel


def test_product_squad_accepts_the_claude_code_model_string(tmp_path):
    """`ProductSquad(model="claude-code:sonnet")` builds every agent on Claude Code."""
    squad = ProductSquad(MarkdownKnowledgeBase(tmp_path), model="claude-code:sonnet", context="ctx")
    for agent in (squad._growth_pm, squad._hx, squad._po, squad._designer):
        assert isinstance(agent.model, ClaudeCodeModel)
        assert agent.model.model_name == "sonnet"


def test_unavailable_function_claim_is_corrected_for_a_text_agent():
    """A text answer saying an offered function is unavailable is asked again with a correction."""
    runner = FakeRunner(
        _stdout({"text": "The search failed with \"No such tool available\".", "tool_calls": []}),
        _stdout({"text": "", "tool_calls": [{"name": "lookup_population", "arguments": {"city": "SP"}}]}),
        _stdout({"text": "12.4 milhões", "tool_calls": []}),
    )
    agent = Agent(ClaudeCodeModel(runner=runner))

    @agent.tool_plain
    def lookup_population(city: str) -> float:
        """Return a city's population in millions."""
        return 12.4

    assert agent.run_sync("Population of SP?").output == "12.4 milhões"
    assert "said functions are unavailable" in runner.calls[1]["stdin"]
    assert "No such tool available" in runner.calls[0]["system"]


def test_text_answer_mentioning_a_function_without_a_claim_is_kept():
    """A text answer that names a function but doesn't call it unavailable is returned as is."""
    runner = FakeRunner(_stdout({"text": "I used lookup_population: 12.4 million.", "tool_calls": []}))
    agent = Agent(ClaudeCodeModel(runner=runner))

    @agent.tool_plain
    def lookup_population(city: str) -> float:
        """Return a city's population in millions."""
        return 12.4

    assert agent.run_sync("Population of SP?").output == "I used lookup_population: 12.4 million."
    assert len(runner.calls) == 1


def test_persistent_unavailable_claim_raises_instead_of_passing_as_a_reply():
    """A text answer that still calls a function unavailable after the correction raises ClaudeCodeError."""
    claim = _stdout({"text": "lookup_population returned: No such tool available.", "tool_calls": []})
    runner = FakeRunner(claim, claim)
    agent = Agent(ClaudeCodeModel(runner=runner))

    @agent.tool_plain
    def lookup_population(city: str) -> float:
        """Return a city's population in millions."""
        return 12.4

    with pytest.raises(ClaudeCodeError, match="unavailable instead of calling it"):
        agent.run_sync("Population of SP?")
    assert len(runner.calls) == 2


def test_unavailable_wording_counts_only_next_to_a_function_name():
    """Without the CLI's own error, "unavailable" triggers the correction only when a function is named."""
    runner = FakeRunner(
        _stdout({"text": "Population data is unavailable for that year.", "tool_calls": []}),
        _stdout({"text": "A ferramenta lookup_population está indisponível.", "tool_calls": []}),
        _stdout({"text": "12.4", "tool_calls": []}),
    )
    agent = Agent(ClaudeCodeModel(runner=runner))

    @agent.tool_plain
    def lookup_population(city: str) -> float:
        """Return a city's population in millions."""
        return 12.4

    assert agent.run_sync("Population of SP in 1500?").output == "Population data is unavailable for that year."
    assert agent.run_sync("Population of SP?").output == "12.4"
    assert len(runner.calls) == 3


def test_no_such_tool_in_a_reply_is_kept_when_no_function_is_offered():
    """An agent without functions can talk about a missing tool without being corrected."""
    runner = FakeRunner(_stdout({"text": "The error says: No such tool available.", "tool_calls": []}))
    assert Agent(ClaudeCodeModel(runner=runner)).run_sync("What does it say?").output.startswith("The error")
    assert len(runner.calls) == 1
