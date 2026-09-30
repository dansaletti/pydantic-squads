# pydantic-squads

[English](README.md)

Squads de agentes declarativas e validadas, sobre o [Pydantic AI](https://ai.pydantic.dev).

> Estágio inicial (pré-alpha). A API vai mudar. Sem afiliação com o time do Pydantic.

A maioria dos frameworks multiagentes foca em como os agentes *executam*. O `pydantic-squads` foca em como uma squad é *definida*: quem é cada agente, o que ele não deve fazer, com quem fala, onde pode escrever e o que entrega para quem. As definições são modelos Pydantic comuns, validados na criação e testáveis sem chamar um LLM.

## Conceitos

- **Role (papel)**: missão, responsabilidades, fora do escopo, princípios, modo de interação, com quem fala, ferramentas e permissões do agente. As instruções de sistema são geradas a partir desses dados, então existe uma única fonte da verdade.
- **Modos de interação**: `conversational` (fala com o humano), `delegate` (chamado por outro agente como ferramenta), `task` (recebe um contrato, entrega um contrato).
- **Squad**: composição de papéis, validada na criação.
  - **Invariantes** valem para qualquer squad: ids únicos, nenhuma referência a papel inexistente, `human` é reservado e não existe permissão de apagar.
  - **Políticas** são opinativas e substituíveis. As padrões: exatamente um papel conversacional, e só ele fala com o humano.
- **Permissões**: padrões glob sobre a base de conhecimento para leitura, escrita e escrita com aprovação humana.
- **Skills**: o `skills` de um papel nomeia as [Agent Skills](https://agentskills.io/home) que ele pode carregar, e `scripts` (`never`/`approval`/`free`) define como ele pode rodar os scripts que vêm junto. Ligar isso a um agente de verdade fica em `pydantic_squads.product` (veja abaixo).

## Papéis em português

Use o template `PT_BR` para que os rótulos das instruções fiquem em português:

```python
from pydantic_squads import PT_BR, Squad
squad = Squad(name="Produto", roles=[...], template=PT_BR)
```

## Squad de produto

`pydantic_squads.product` traz uma squad pronta — Growth PM, pesquisador(a)
de HX, Product Owner — com contratos de handoff tipados (veja a ADR 0003).
Projetos consumidores só fornecem uma base de conhecimento; papéis e
contratos são fixos.

```python
from pydantic_squads.product import build_product_squad

squad = build_product_squad(language="pt-BR")  # ou "en"
print(squad.instructions_for("growth_pm"))
```

### Rodando de verdade (extra `ai`)

`pip install "pydantic-squads[ai]"` (apoiado no [pydantic-ai-slim](https://ai.pydantic.dev),
não no pacote `pydantic-ai` completo) monta a squad em agentes de verdade: o
`ProductSquad` conversa com o Growth PM, que pode consultar a HX (achados
citados, validados contra a base de conhecimento) e escrever notas dentro
das suas `Permissions`. Uma escrita num caminho `write_with_approval` pausa
a execução e devolve um `DeferredToolRequests` em vez de quebrar, para que
um humano decida antes de qualquer escrita. A própria HX não pode pedir
aprovação — veja a [ADR 0004](docs/adr/0004-hx-cannot-request-write-approval.md).

```python
from pydantic_ai import DeferredToolRequests

from pydantic_squads.product import MarkdownKnowledgeBase, Revision
from pydantic_squads.product.assembly import ProductSquad

kb = MarkdownKnowledgeBase("./vault")  # uma pasta de notas .md estilo Obsidian
squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="Ferramenta B2B para pequenas empresas de logística. Persona principal: gestor de despacho.",
)

resposta = squad.chat("Estamos perdendo usuários no cadastro, o que sabemos?")
print(resposta)  # o Growth PM pode consultar a HX antes de responder

# Quando a conversa já tiver o suficiente:
bet = squad.close_bet()
if isinstance(bet, DeferredToolRequests):
    ...  # resolva bet.approvals, depois squad.close_bet(deferred_tool_results=...)

# Um humano revisa `bet` fora da biblioteca. Só repasse depois de aprovado:
resultado = squad.submit_bet(bet)

# Se o Product Owner devolver o bet, o Growth PM o revisa e submit_bet
# devolve uma Revision (a nova Bet mais o SendBack do PO) em vez de
# reenviá-la automaticamente — um humano vê o motivo e então aprova a
# revisão antes que ela chegue ao Product Owner.
while isinstance(resultado, Revision):
    print(resultado.send_back.reason, resultado.send_back.questions)
    ...  # um humano revisa resultado.bet antes de reenviá-la
    resultado = squad.submit_bet(resultado.bet)

# resultado agora é um Backlog (ou um DeferredToolRequests, se a própria
# revisão precisou de aprovação de escrita).
```

### Skills (extra `skills`)

Cada papel pode carregar [Agent Skills](https://agentskills.io/home) —
pacotes `SKILL.md` com `references/`, `assets/` e `scripts/` — restritas ao
seu próprio `Role.skills`; o Growth PM, a HX e o Product Owner já trazem
uma cada (`prioritization`, `evidence-classification`, `user-stories`), e um
projeto pode adicionar as suas. `pip install "pydantic-squads[skills]"`
traz o [pydantic-ai-skills](https://github.com/dougtrajano/pydantic-ai-skills),
usado em vez do `Skills` embutido do Pydantic AI porque esse só carrega as
instruções do `SKILL.md`, não os arquivos que ele referencia — veja a
[ADR 0005](docs/adr/0005-pydantic-ai-skills-for-bundled-files.md).

```python
squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="...",
    skills_dirs=["./skills"],  # complementa as da biblioteca; omita para nenhuma
)
```

Um papel nunca enxerga uma skill que não declarou, mesmo vinda do mesmo
diretório. `Role.scripts` (padrão `"approval"`) governa `run_skill_script`
do mesmo jeito que `write_with_approval` governa uma escrita de nota:
`"never"` remove a ferramenta, `"approval"` a adia como um
`DeferredToolRequests`, `"free"` roda sem pedir aprovação. Ler os arquivos
de uma skill com `read_skill_resource` é sempre livre.

## Observabilidade

Veja a [ADR 0006](docs/adr/0006-observability-and-checkpointing.md). Um
ciclo é um arco conversa → `Bet` → `Backlog`. Passe `trace_dir` para o
`ProductSquad` para registrar cada chamada como spans (agente, chamadas de
modelo/ferramenta, tokens, custo real, status) em
`{trace_dir}/{cycle_id}.jsonl`, um arquivo append-only por ciclo — incluindo
os próprios spans da HX, aninhados sob o span da tool `consult_hx` do Growth
PM. Um `cycle_id` estável é gerado de qualquer forma, já que também é
gravado no frontmatter da nota de cada Bet fechado
(`squad/bets/<bet_version_id>.md`, junto com `schema_version` e, numa
revisão, `previous_bet_version_id`).

```python
from pydantic_ai import UsageLimits

squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="...",
    usage_limits=UsageLimits(request_limit=20),  # None (padrão) é ilimitado
    trace_dir="./traces",
)
```

Retome uma conversa passada e continue com `chat()`:

```python
squad = ProductSquad(kb, model="openai:gpt-4o", context="...", trace_dir="./traces")
squad.resume(cycle_id)
squad.chat("...")
```

### Visualizador de trace local (extra `observability`)

`pip install "pydantic-squads[ai,observability]"` adiciona uma CLI baseada em `rich`:

```bash
pydantic-squads trace <cycle_id> --trace-dir ./traces --budget-tokens 20000
```

Ela imprime uma timeline por span, duração/tokens/custo por agente, e sinaliza:
spans lentos, retries da HX causados por uma fonte que não existe na base de
conhecimento, devoluções do Product Owner, aprovações humanas pendentes, e
tokens de entrada acima de `--budget-tokens` (verificado por ciclo e por span).

### Exportação OpenTelemetry / Logfire (extra `otel`, desligado por padrão)

`pip install "pydantic-squads[ai,otel]"` adiciona uma ativação explícita:

```python
from pydantic_squads.product.otel import enable_otel

enable_otel(send_to_logfire=True)  # ou False, para exportar para seu próprio coletor OTel
```

> **Aviso:** isso envia o conteúdo completo das conversas — mensagens do
> usuário, respostas do modelo, argumentos de chamadas de ferramenta,
> incluindo o conteúdo das notas da base de conhecimento — para qualquer
> backend OpenTelemetry configurado. Vem desligado por padrão e precisa ser
> ativado explicitamente; revise o que esse backend armazena e quem tem
> acesso antes. É independente do trace local em JSONL/CLI acima, que nunca
> sai da máquina local.

Veja o roadmap em [docs/roadmap.md](docs/roadmap.md).

## Desenvolvimento

```bash
uv sync  # adicione --extra ai para tests/test_product_assembly.py e tests/test_product_observability.py,
         # --extra skills para tests/test_product_skills.py,
         # --extra observability para tests/test_cli.py, --extra otel para tests/test_product_otel.py
uv run pytest
```

## Licença

MIT
