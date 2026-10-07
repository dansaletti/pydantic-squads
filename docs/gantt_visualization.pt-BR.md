# Visualização Gantt no terminal

`pydantic_squads.visualization` desenha spans de execução como um Gantt no terminal, usando só a biblioteca padrão. English: [gantt_visualization.md](gantt_visualization.md).

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

### Spans manuais

Tempos em milissegundos.

```python
with SpanCollector() as collector:
    collector.record_with_offset("model_call", "growth_pm", 0, 6.519)  # name, agent, offset_ms, duration_ms
    collector.record_with_offset("tool:consult_hx", "growth_pm", 6.519, 80.222)
    collector.record_with_offset("model_call", "nx", 20, 5.586, status="retry")
collector.render_gantt()
```

### Coleta automática

```python
collector = SpanCollector()

with collector.span("model_call", agent="growth_pm"):
    ...  # um bloco que levanta exceção vira "error"

@track_span(collector, "growth_pm", "model_call")  # sync ou async; o nome padrão é o da função
async def call_model(): ...

collector.render_gantt(width=100)
```

## API

**`TerminalGantt(width=120, show_ms=True, use_colors=True)`**

- `add_span(name, start_ms, duration_ms, agent=None, status="ok")`: `status` é `ok`, `retry`, `error` ou `awaiting_approval`.
- `add_spans_from_trace({"spans": [{"name", "start", "duration", "agent", "status"}]})`.
- `TerminalGantt.from_jsonl(path, **kwargs)`: monta o gráfico a partir de um arquivo de trace (linhas `Span`), indentando os spans filhos.
- `collapse_gaps_ms` (construtor): trechos ociosos maiores que isso encolhem para esse valor, e um ciclo retomado horas depois continua legível. O eixo de tempo fica comprimido, não real.
- `render()` devolve uma string; `print()` imprime.

**`SpanCollector`**

- `record(name, agent, start_time, end_time, status="ok")`: tempos absolutos em segundos (`time.time()`).
- `record_with_offset(name, agent, start_offset_ms, duration_ms, status="ok")`: só dentro do bloco `with`.
- `span(name, agent=None, status="ok")`: context manager que cronometra o bloco.
- `to_gantt(**kwargs)` devolve um `TerminalGantt` (kwargs extras vão para o construtor); `render_gantt(**kwargs)` imprime.

**`track_span(collector, agent=None, name=None)`**: decorator que registra cada chamada como um span.

**`create_gantt_from_pydantic_trace(obj)`**: monta o gráfico de qualquer objeto que exponha `spans` (itens com `name`, `start_ms`, `duration_ms`, `agent`, `status`) ou `_model_extra['spans']`. O resultado de um run comum do Pydantic AI não tem nenhum dos dois; monte os spans antes.

## Cores por agente

| Agente | Cor |
|---|---|
| `growth_pm`, `pm_growth` | roxo |
| `nx` | verde |
| `hx` | ciano |
| `po` | amarelo |
| `designer`, `design` | azul |
| `social` | magenta |

Outros agentes ficam ciano. Um span `retry` fica amarelo, `error` vermelho e `awaiting_approval` (⏸) magenta, seja qual for o agente. O mapa é `TerminalGantt.AGENT_COLORS`.

## Troubleshooting

- Sem cores, ou códigos de escape num log: `TerminalGantt(use_colors=False)`.
- Terminal estreito: `TerminalGantt(width=80)`.
- Spans curtos ao lado de um longo aparecem como um bloco: o gráfico escala pela duração total, e cada barra tem pelo menos um caractere.

Há exemplos executáveis em `examples/gantt_example.py` e `examples/gantt_from_trace.py` (`python examples/gantt_from_trace.py TRACE.jsonl`); os testes estão em `tests/test_gantt_terminal.py`.
