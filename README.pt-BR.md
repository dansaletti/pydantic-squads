# pydantic-squads

[English](README.md)

Squads de agentes declarativas e validadas, sobre o [Pydantic AI](https://ai.pydantic.dev).

> Estágio inicial (pré-alpha): o core declarativo e a squad de produto pronta já rodam, mas a API vai mudar. Sem afiliação com o time do Pydantic.

A maioria dos frameworks multiagentes foca em como os agentes *executam*. O `pydantic-squads` foca em como uma squad é *definida*: quem é cada agente, o que ele não deve fazer, com quem fala, onde pode escrever e o que entrega para quem. As definições são modelos Pydantic comuns, validados na criação e testáveis sem chamar um LLM.

A biblioteca também traz uma [squad de produto](#squad-de-produto) pronta que roda de ponta a ponta sobre o Pydantic AI: de uma conversa com o fundador até um bet, um backlog de histórias e um protótipo HTML navegável.

## Instalação

Ainda não está no PyPI; instale a partir do GitHub. Requer Python 3.10+.

```bash
pip install "pydantic-squads @ git+https://github.com/dansaletti/pydantic-squads"
```

O core depende só do `pydantic`. Extras opcionais, combinados como
`"pydantic-squads[ai,skills] @ git+https://github.com/dansaletti/pydantic-squads"`:

| Extra | Adiciona |
|-------|----------|
| `ai` | Roda a squad de produto como agentes Pydantic AI de verdade (`pydantic-ai-slim`) |
| `skills` | Agent Skills por papel (`pydantic-ai-skills`) |
| `observability` | O visualizador local `pydantic-squads trace` (`rich`); use junto com `ai` |
| `otel` | Exportação opcional para OpenTelemetry / Logfire (`logfire`); use junto com `ai` |

## Conceitos

- **Role (papel)**: missão, responsabilidades, fora do escopo, princípios, modo de interação, com quem fala, ferramentas e permissões do agente. As instruções de sistema são geradas a partir desses dados, então existe uma única fonte da verdade.
- **Modos de interação**: `conversational` (fala com o humano), `delegate` (chamado por outro agente como ferramenta), `task` (recebe um contrato, entrega um contrato).
- **Squad**: composição de papéis, validada na criação.
  - **Invariantes** valem para qualquer squad: ids únicos, nenhuma referência a papel inexistente, `human` é reservado e não existe permissão de apagar.
  - **Políticas** são opinativas e substituíveis. As padrões: exatamente um papel conversacional, e só ele fala com o humano.
- **Permissões**: padrões glob sobre a base de conhecimento para leitura, escrita e escrita com aprovação humana.
- **Skills**: o `skills` de um papel nomeia as [Agent Skills](https://agentskills.io/home) que ele pode carregar, e `scripts` (`never`/`approval`/`free`) define como ele pode rodar os scripts que vêm junto. Ligar isso a um agente de verdade fica em `pydantic_squads.product` (veja abaixo).

## Visão rápida

```python
from pydantic_squads import HUMAN, InteractionMode, Role, Squad

lead = Role(
    id="lead",
    name="Líder",
    mission="Ajudar o humano a decidir o que fazer a seguir.",
    responsibilities=["Discutir opções com o humano", "Delegar pesquisa"],
    out_of_scope=["Tomar a decisão final"],
    mode=InteractionMode.CONVERSATIONAL,
    talks_to=[HUMAN, "researcher"],
    delivers="Uma decisão aprovada.",
)
# ... defina "researcher" com mode=InteractionMode.DELEGATE

squad = Squad(name="Produto", roles=[lead, researcher])
print(squad.instructions_for("lead"))
```

Papéis escritos em outro idioma podem usar um `PromptTemplate` correspondente (o `PT_BR` já vem embutido):

```python
from pydantic_squads import PT_BR, Squad
squad = Squad(name="Produto", roles=[...], template=PT_BR)
```

## Squad de produto

`pydantic_squads.product` traz uma squad pronta — Growth PM, pesquisador(a)
de HX, Product Owner, Designer — com contratos de handoff tipados (veja a
ADR 0003). O fluxo é conversa → `Bet` → `Backlog` → `Prototype`.
Projetos consumidores só fornecem uma base de conhecimento; papéis e
contratos são fixos.

```python
from pydantic_squads.product import build_product_squad

squad = build_product_squad(language="pt-BR")  # ou "en"
print(squad.instructions_for("growth_pm"))
```

### Rodando de verdade (extra `ai`)

O extra `ai` (veja [Instalação](#instalação); apoiado no
[pydantic-ai-slim](https://ai.pydantic.dev), não no pacote `pydantic-ai`
completo) monta a squad em agentes de verdade: o
`ProductSquad` conversa com o Growth PM, que pode consultar a HX (achados
citados, validados contra a base de conhecimento) e escrever notas dentro
das suas `Permissions`. Uma escrita num caminho `write_with_approval` pausa
a execução e devolve um `DeferredToolRequests` em vez de quebrar, para que
um humano decida antes de qualquer escrita. A própria HX não pode pedir
aprovação — veja a [ADR 0004](docs/adr/0004-hx-cannot-request-write-approval.md).
Passe `language="pt-BR"` para ter os rótulos das instruções em português
(padrão `"en"`).

```python
from pydantic_ai import DeferredToolRequests

from pydantic_squads.product import MarkdownKnowledgeBase, Revision
from pydantic_squads.product.assembly import ProductSquad

kb = MarkdownKnowledgeBase("./vault")  # uma pasta de notas .md estilo Obsidian
squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="Ferramenta B2B para pequenas empresas de logística. Persona principal: gestor de despacho.",
    language="pt-BR",
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

### Rodando no seu login do Claude Code (sem API key)

Se você tem o [Claude Code](https://code.claude.com) instalado e logado
(`claude`, depois `/login`), a squad pode rodar nesse login em vez de uma API
key: passe `model="claude-code"` (o modelo padrão do Claude Code) ou
`model="claude-code:sonnet"` / `"claude-code:opus"`. Cada requisição de agente
vira uma chamada `claude -p` sem ferramentas; as tools, permissões,
aprovações e validadores da squad continuam rodando em Python, sem mudança
(ADR 0008).

```python
import os

squad = ProductSquad(
    kb,
    model=os.environ.get("SQUAD_MODEL", "claude-code:sonnet"),  # ou "anthropic:claude-sonnet-4-5"
    context="...",
)
```

O `ANTHROPIC_API_KEY` é removido do ambiente da CLI para que o login seja
usado; para mais controle, monte o modelo você mesmo:
`ClaudeCodeModel("sonnet", timeout=900, extra_args=[...])` de
`pydantic_squads.product.claude_code`.

> **Só para uso local e pessoal.** A Anthropic não permite que produtos de
> terceiros ofereçam o login do claude.ai ou os limites dele aos seus
> usuários. Use este backend para rodar a squad para você; o que for
> entregue a outras pessoas usa API key. Ele também é mais lento que a API
> (um processo da CLI por requisição), consome os limites de uso do seu
> plano e funciona melhor com Sonnet ou Opus: modelos pequenos seguem o
> protocolo de chamada de ferramentas com menos confiabilidade.

### Desenhando

O Product Owner marca cada história com `needs_design` (obrigatório, sem
padrão). `design()` entrega o backlog ao Designer, que transforma cada
história que precisa de design num protótipo HTML autocontido e
mobile-first em `squad/design/<cycle_id>/`, consultando a HX sobre as
usuárias no caminho. Um gate determinístico confere que toda história
desse tipo aparece em alguma tela antes de aceitar o protótipo. Veja a
[ADR 0007](docs/adr/0007-designer-role.md).

```python
from pydantic_squads.product import Prototype

desenho = squad.design(resultado)  # None se nenhuma história precisar de design
if isinstance(desenho, DeferredToolRequests):
    # Na primeira vez, o Designer propõe um design system; escrever em
    # design-system/** espera a sua aprovação.
    desenho = squad.design(deferred_tool_results=desenho.build_results(approve_all=True))

if isinstance(desenho, Prototype):
    print(desenho.html_path)  # abra no navegador
    for p in desenho.founder_questions:  # também em questions.md, ao lado do HTML
        print(p.question, "— padrão:", p.suggested_default)
    # Marca, tom e posicionamento são decisão sua: as chaves são o texto das
    # perguntas, e as sem resposta mantêm o padrão sugerido pelo Designer.
    desenho = squad.design(resultado, answers={"Qual tom?": "Amigável, informal"})
```

Uma história ambígua demais para virar tela volta como um `SendBack` para
você, não automaticamente para o Product Owner.

### Skills (extra `skills`)

Cada papel pode carregar [Agent Skills](https://agentskills.io/home) —
pacotes `SKILL.md` com `references/`, `assets/` e `scripts/` — restritas ao
seu próprio `Role.skills`; cada papel já traz uma (`prioritization`,
`evidence-classification`, `user-stories`, `prototyping`), o Product
Owner traz também `story-mapping`, o Designer traz `impeccable` (adaptada
do [impeccable](https://github.com/pbakaus/impeccable), Apache-2.0), o Growth PM
traz também doze skills de growth marketing do
[marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT,
veja `src/pydantic_squads/product/skills/THIRD_PARTY_NOTICE.md`), e um
projeto pode adicionar as suas. O extra `skills`
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
ciclo é um arco conversa → `Bet` → `Backlog` → `Prototype`. Passe `trace_dir` para o
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

Retome uma conversa passada e continue com `chat()`. O `cycle_id` é o nome
do arquivo de trace (`{trace_dir}/<cycle_id>.jsonl`) e também aparece no
frontmatter das notas de Bet do ciclo. O ciclo atual fica em
`squad.cycle_id` (`None` até a primeira chamada iniciar um ciclo):

```python
squad = ProductSquad(kb, model="openai:gpt-4o", context="...", trace_dir="./traces")
squad.resume(cycle_id)
squad.chat("...")
```

### Visualizador de trace local (extra `observability`)

Os extras `ai` e `observability` adicionam uma CLI baseada em `rich`:

```bash
pydantic-squads trace <cycle_id> --trace-dir ./traces --budget-tokens 20000
```

Ela imprime uma timeline por span, duração/tokens/custo por agente, e sinaliza:
spans lentos, retries da HX causados por uma fonte que não existe na base de
conhecimento, devoluções do Product Owner, aprovações humanas pendentes, e
tokens de entrada acima de `--budget-tokens` (verificado por ciclo e por span).
`--trace-dir` usa `$PYDANTIC_SQUADS_TRACE_DIR` por padrão, ou `traces`;
`--slow-threshold-ms` define o que conta como lento (padrão 5000).

### Exportação OpenTelemetry / Logfire (extra `otel`, desligado por padrão)

Os extras `ai` e `otel` adicionam uma ativação explícita:

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

## Roadmap

Veja [docs/roadmap.md](docs/roadmap.md).

## Relacionados

O [pydantic-team](https://github.com/Etiqa/pydantic-team) oferece padrões de time em runtime (hierárquico, colaborativo) para o Pydantic AI. Os dois são complementares: os papéis montados pelo `pydantic-squads` são agentes Pydantic AI comuns.

## Desenvolvimento

```bash
uv sync  # adicione --extra ai para tests/test_product_assembly.py e tests/test_product_observability.py,
         # --extra skills para tests/test_product_skills.py,
         # --extra observability para tests/test_cli.py, --extra otel para tests/test_product_otel.py
uv run pytest
uv run pytest --cov=pydantic_squads --cov-report=term-missing  # a cobertura fica em 100%
```

As regras do projeto para contribuidores e agentes de código (ADRs,
convenções de teste, quais módulos podem importar o quê) estão no
[AGENTS.md](AGENTS.md).

## Licença

MIT
