# Terminal Gantt visualization

`pydantic_squads.visualization` draws execution spans as a Gantt chart in the terminal, using only the standard library. Português: [gantt_visualization.pt-BR.md](gantt_visualization.pt-BR.md).

```
Agent                     Timeline                                                    Duration
                          0μs        25.0ms     50.0ms      75.0ms     100.0ms

 growth_pm
✓ agent_run              █████████████████████████████████████████████████████           114.0ms
✓   model_call           ███                                                               6.5ms
✓   tool:consult_hx         █████████████████████████████████████                         80.2ms

 nx
✓ agent_run                       █████████████████████████████████████████████████      106.7ms
⟳   model_call                    ██                                                       5.6ms
✓   tool:search_notes               ████████████████                                      36.0ms

────────────────────────────────────────────────────────────────────────────────────────────────────
Summary
  • Total spans: 6
  • Total duration: 126.7ms
  • Status: ✓ 5 | ⟳ 1
```

## Quick start

```python
from pydantic_squads import SpanCollector, TerminalGantt, track_span
```

### Manual spans

Times are in milliseconds.

```python
with SpanCollector() as collector:
    collector.record_with_offset("model_call", "growth_pm", 0, 6.519)  # name, agent, offset_ms, duration_ms
    collector.record_with_offset("tool:consult_hx", "growth_pm", 6.519, 80.222)
    collector.record_with_offset("model_call", "nx", 20, 5.586, status="retry")
collector.render_gantt()
```

### Automatic collection

```python
collector = SpanCollector()

with collector.span("model_call", agent="growth_pm"):
    ...  # a raising block is recorded as "error"

@track_span(collector, "growth_pm", "model_call")  # sync or async; name defaults to the function name
async def call_model(): ...

collector.render_gantt(width=100)
```

### From a product squad run

`ProductSquad.gantt()` draws the current cycle from memory, with or without a `trace_dir`:

```python
squad.review("A fake-door landing page for route sharing")
squad.gantt(width=120).print()
```

```
 squad
✓ request                       ███████████████████████████████████████████████████████████████      410.8ms
✓   triage                      ██████████                                                            58.5ms
✓   fan_out                              ██████████████████████████████                              173.0ms
✓   synthesis                                                          ██████████                     58.6ms
✓   rebuttal                                                                      ███████████         63.6ms
✓   synthesis                                                                                ████     59.0ms

 growth_pm
✓     agent_run                          ██████████████████████████████                              169.6ms

 pm_product
✓     agent_run                          ██████████████████████████████                              169.6ms
```

(Abridged: the real chart also has the Facilitator's, HX's and the other PM's rows, and the model and tool calls inside each run.) The `squad` rows are the request and its steps, drawn first as the outline of the rest. Each role's runs are on that role's rows, indented under the step they belong to, so the PMs' opinions show as bars that overlap under `fan_out`. A cycle recorded to a file draws the same chart with `TerminalGantt.from_jsonl`. See [ADR 0014](adr/0014-request-steps-in-the-trace-and-a-live-gantt.md). `examples/committee_gantt.py` runs a whole round on a fake model and prints its chart.

## API

**`TerminalGantt(width=120, show_ms=True, use_colors=True)`**

- `add_span(name, start_ms, duration_ms, agent=None, status="ok")`: `status` is `ok`, `retry`, `error` or `awaiting_approval`.
- `add_spans_from_trace({"spans": [{"name", "start", "duration", "agent", "status"}]})`.
- `TerminalGantt.from_jsonl(path, **kwargs)`: builds a chart from a trace file (`Span` lines), indenting child spans.
- `TerminalGantt.from_records(records, **kwargs)`: the same from span records already in memory (dicts with `span_id`, `parent_span_id`, `operation`, `started_at`, `duration_ms`, `agent`, `status`).
- `collapse_gaps_ms` (constructor): idle stretches longer than this shrink to it, so a cycle resumed hours later stays readable. The time axis is then compressed, not real.
- `render()` returns a string; `print()` prints it.

**`SpanCollector`**

- `record(name, agent, start_time, end_time, status="ok")`: absolute times in seconds (`time.time()`).
- `record_with_offset(name, agent, start_offset_ms, duration_ms, status="ok")`: only inside the `with` block.
- `span(name, agent=None, status="ok")`: context manager that times its block.
- `to_gantt(**kwargs)` returns a `TerminalGantt` (extra kwargs go to its constructor); `render_gantt(**kwargs)` prints it.

**`track_span(collector, agent=None, name=None)`**: decorator recording each call as a span.

**`create_gantt_from_pydantic_trace(obj)`**: builds a chart from any object exposing `spans` (items with `name`, `start_ms`, `duration_ms`, `agent`, `status`) or `_model_extra['spans']`. A plain Pydantic AI run result has neither; build the spans yourself first.

## Agent colors

| Agent | Color |
|---|---|
| `squad` (a request and its steps) | gray |
| `facilitator` | white |
| `growth_pm`, `pm_growth` | purple |
| `pm_product` | teal |
| `pm_marketing` | pink |
| `nx` | green |
| `hx` | cyan |
| `product_owner`, `po` | yellow |
| `designer`, `design` | blue |
| `social_media` | orange |
| `social` | magenta |

Other agents are cyan. The `squad` group is drawn first and the others follow in name order. A span with status `retry` is yellow, `error` is red and `awaiting_approval` (⏸) is magenta, whatever the agent. The map is `TerminalGantt.AGENT_COLORS`.

## Troubleshooting

- No colors, or escape codes in a log: `TerminalGantt(use_colors=False)`.
- Terminal too narrow: `TerminalGantt(width=80)`.
- Short spans next to a long one show as a single block: the chart scales to the total duration, so each bar is at least one character wide.

Runnable examples are in `examples/gantt_example.py`, `examples/gantt_from_trace.py` (`python examples/gantt_from_trace.py TRACE.jsonl`) and `examples/committee_gantt.py` (needs the `ai` extra); tests are in `tests/test_gantt_terminal.py`.
