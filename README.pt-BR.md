# pydantic-squads

[English](README.md)

Squads de agentes declarativas e validadas, sobre o [Pydantic AI](https://ai.pydantic.dev).

> Estágio inicial (pré-alpha): o core declarativo e a squad de produto pronta já rodam, mas a API vai mudar. Sem afiliação com o time do Pydantic.

A maioria dos frameworks multiagentes foca em como os agentes *executam*. O `pydantic-squads` foca em como uma squad é *definida*: quem é cada agente, o que ele não deve fazer, com quem fala, onde pode escrever e o que entrega para quem. As definições são modelos Pydantic comuns, validados na criação e testáveis sem chamar um LLM.

A biblioteca também traz uma [squad de produto](#squad-de-produto) pronta que roda de ponta a ponta sobre o Pydantic AI: de uma conversa com um Facilitator neutro, passando por um comitê de PMs e uma única decisão humana, até um backlog de histórias, um protótipo HTML navegável e o conteúdo de lançamento.

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

`pydantic_squads.product` traz uma squad pronta, com contratos de handoff
tipados (veja a ADR 0003 e a [ADR 0013](docs/adr/0013-pm-committee-with-a-single-human-gate.md)). Projetos consumidores só
fornecem uma base de conhecimento; papéis e contratos são fixos.

Chegando agora ao projeto? O [docs/architecture.pt-BR.md](docs/architecture.pt-BR.md)
percorre o fluxo, as fronteiras de cada papel e por que foi feito assim.

| Papel | O que faz |
| --- | --- |
| Facilitator | O único papel que fala com você. Esclarece o pedido, escolhe os PMs a ouvir e consolida o que eles dizem. Não dá parecer |
| Growth PM, Product PM, Marketing PM | O comitê. Cada um dá um `Opinion` do seu ponto de vista: métricas e experimentos, jornadas e escopo, posicionamento e mensagem |
| Pesquisador(a) de HX | Ferramenta de consulta somente leitura sobre a base de conhecimento: achados citados, cada um classificado como evidência, suposição ou lacuna |
| Product Owner | Transforma um `Brief` aprovado num `Backlog`. Não recebe mais nada |
| Designer | Transforma as histórias que precisam de design num `Prototype` em HTML |
| Social Media | Transforma o mesmo `Brief` num `ContentPack`, abaixo do Marketing PM |

O fluxo é conversa → `Triage` → `Opinion`s em paralelo → `Synthesis` → a
sua decisão → `Brief` → `Backlog` → `Prototype`, e o mesmo `Brief` →
`ContentPack`.

```python
from pydantic_squads.product import build_product_squad

squad = build_product_squad(language="pt-BR")  # ou "en"
print(squad.instructions_for("facilitator"))
```

### Rodando de verdade (extra `ai`)

O extra `ai` (veja [Instalação](#instalação); apoiado no
[pydantic-ai-slim](https://ai.pydantic.dev), não no pacote `pydantic-ai`
completo) monta a squad em agentes de verdade.

```python
from pydantic_ai import DeferredToolRequests

from pydantic_squads.product import BriefRejection, MarkdownKnowledgeBase
from pydantic_squads.product.assembly import ProductSquad

kb = MarkdownKnowledgeBase("./vault")  # uma pasta de notas .md estilo Obsidian
squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="Ferramenta B2B para pequenas empresas de logística. Persona principal: gestor de despacho.",
    language="pt-BR",
)

# 1. Converse com o Facilitator até o pedido ficar claro. Ele pode consultar a HX.
resposta = squad.chat("Quero uma landing page fake door para compartilhamento de rotas")
print(resposta)

# 2. Feche a conversa. O Facilitator faz a triagem, os PMs escolhidos dão
#    seus pareceres em paralelo, e você recebe uma Synthesis.
sintese = squad.close_request()
if isinstance(sintese, DeferredToolRequests):
    ...  # resolva, depois squad.close_request(deferred_tool_results=...)

print(sintese.summary)
for divergencia in sintese.divergences:  # onde os PMs discordam, posição por posição
    print(divergencia.topic, divergencia.positions)
for lacuna in sintese.gaps:  # o que a HX disse que a base de conhecimento não sabe
    print(lacuna.gap, lacuna.questions, lacuna.asked_by)
for parecer in sintese.opinions:  # o parecer de cada PM, na íntegra
    print(parecer.role, parecer.confidence, parecer.recommendation)
print(sintese.proposed_brief)

# 3. Decida, uma vez. Escolha um:
sintese = squad.adjust("Troque a métrica por uma taxa de conversão")  # refaz só a síntese
brief = squad.approve("Pode seguir")  # o brief proposto, com a sua decisão carimbada
# squad.reject("Não neste trimestre")  # encerra o pedido, sem brief

# 4. Só um Brief aprovado chega ao Product Owner.
resultado = squad.submit_brief(brief)
if isinstance(resultado, BriefRejection):
    print(resultado.missing_fields, resultado.reason)
# Caso contrário, resultado é um Backlog.
```

`squad.review("...")` leva um pedido direto ao comitê, sem conversa antes.

### Conversando pelo terminal

O `pydantic-squads chat` é esse fluxo inteiro como uma sessão de terminal,
com um modelo de verdade e sem escrever código. Você precisa do
[Claude Code](https://code.claude.com) instalado e logado (`claude`, depois
`/login`) e de uma pasta de notas markdown para servir de base de
conhecimento:

```bash
pip install "pydantic-squads[ai,observability] @ git+https://github.com/dansaletti/pydantic-squads"
pydantic-squads chat CAMINHO/DO/VAULT \
  --context "O que é o seu produto e para quem" \
  --language pt-BR \
  --trace-dir ./traces
```

A partir de um clone deste repo, com o [uv](https://docs.astral.sh/uv/):
`uv run --extra ai --extra observability pydantic-squads chat CAMINHO/DO/VAULT`.

Digite o seu pedido e depois:

| Comando | O que faz |
| --- | --- |
| `/close` | Fecha a conversa e leva o pedido ao comitê |
| `/review TEXTO` | Leva TEXTO direto ao comitê, sem conversa |
| `/approve [NOTAS]`, `/adjust NOTAS`, `/reject MOTIVO` | A sua decisão sobre a síntese |
| `/submit` | Entrega o Brief aprovado ao Product Owner |
| `/content`, `/design` | Pede o conteúdo ao Social Media, ou o protótipo ao Designer |
| `/gantt`, `/cost` | Desenha o ciclo com o custo, ou mostra só o custo por agente |
| `/resume CYCLE_ID` | Continua uma conversa anterior (precisa de `--trace-dir`) |
| `/help`, `/quit` | A lista de comandos; sair, mostrando o custo |

Os comandos são em inglês; `--language pt-BR` faz os agentes responderem em
português. Uma escrita que precisa da sua aprovação é mostrada e espera o
seu sim ou não. Sem opção de modelo, a sessão roda a
[configuração recomendada](#configuração-recomendada) no seu login do
Claude Code, o que consome os limites do seu plano. `--model` aceita
qualquer string de modelo do Pydantic AI, para rodar com API key;
`--pm-model`, `--hx-model` e `--role-model PAPEL=MODELO` mudam papéis
isolados. `--context` também aceita o caminho de um arquivo, e `--skills`
dá aos papéis as skills da biblioteca. Veja a
[ADR 0017](docs/adr/0017-chat-command.md).

O que sustenta isso, por código e não por prompt:

- **O Facilitator é neutro.** O agente da conversa não tem ferramenta que
  alcance um PM, o agente que escreve a síntese não tem ferramenta
  nenhuma, e uma `Synthesis` não tem campo para uma recomendação própria.
- **Os PMs não debatem.** Cada um dá seu parecer numa execução própria, sem
  histórico de mensagens e sem ver os outros. O papel no parecer é
  carimbado pelo runtime, e uma fonte que não seja uma nota da base de
  conhecimento é recusada.
- **No máximo uma réplica.** Se a primeira síntese encontra divergências,
  os PMs citados nelas respondem uma vez e a síntese é refeita. O que
  continuar divergindo fica visível. Não há laço.
- **Você vê o material bruto.** A síntese carrega os pareceres originais na
  íntegra, as réplicas, e cada lacuna que a HX apontou com a pergunta que a
  revelou. O Facilitator agrupa as lacunas que dizem a mesma coisa, e o
  código garante que nenhuma some; `sintese.raw_gaps` tem as lacunas nas
  palavras da HX. Ela também é gravada em
  `squad/committee/<cycle_id>/synthesis-<n>.md`.
- **A decisão é dado.** `approve()` não chama modelo: carimba uma
  `HumanDecision` e grava o `Brief` em `squad/briefs/<brief_id>.md`,
  como Markdown para você ler, com o mesmo brief como dado em
  `<brief_id>.json` ao lado
  ([ADR 0018](docs/adr/0018-notes-are-markdown-for-people.md)). Um
  brief com campo faltando, ou sem decisão aprovada, é rejeitado antes de
  o modelo do Product Owner ser chamado
  ([ADR 0011](docs/adr/0011-brief-is-the-product-owners-only-door.md)).
- **A HX é uma ferramenta de consulta somente leitura.** Cada chamada a
  `consult_hx` é uma execução nova, sem memória da anterior, e ela nunca
  escreve ([ADR 0010](docs/adr/0010-hx-is-a-read-only-query-tool.md)). O
  `ProductSquad` embrulha a base de conhecimento recebida num
  `SerializedKnowledgeBase`, para que as escritas aconteçam uma de cada vez.

O Facilitator pode escrever em `docs/**` e `assumptions/**` com a sua
aprovação. Uma escrita dessas pausa a execução e devolve um
`DeferredToolRequests` em vez de quebrar, para que você decida antes de
qualquer escrita; passe a resolução como `deferred_tool_results` no mesmo
método. Depois de `approve()` ou `reject()`, o próximo `chat()` começa um
pedido novo, com um `cycle_id` novo. Passe `language="pt-BR"` para ter os
rótulos das instruções, e as notas que a squad grava, em português
(padrão `"en"`).

Um pedido ouvido por três PMs custa uma triagem, três pareceres (cada um
com as suas consultas à HX) e uma síntese, mais uma rodada quando eles
divergem. `usage_limits` limita cada execução. Para manter cada chamada
pequena, buscar na base de conhecimento devolve trechos dos melhores
resultados, e o papel lê as notas de que precisa
([ADR 0015](docs/adr/0015-search-returns-excerpts.md)). O que a HX já
respondeu ao Facilitator é entregue aos PMs, para que a mesma pergunta não
seja feita à HX uma vez por PM.

#### Configuração recomendada

Não existe arquivo de configuração: a squad é configurada pelos argumentos
do `ProductSquad`. Os papéis podem rodar em modelos diferentes. `models`
mapeia o id de um papel para o modelo dele, e todo papel não citado usa
`model`
([ADR 0016](docs/adr/0016-shared-evidence-brevity-and-a-model-per-role.md)).

A biblioteca traz uma configuração testada para o Claude Code como preset.
É a que o `pydantic-squads chat` usa por padrão:

```python
from pydantic_squads.product.claude_code import RECOMMENDED_MODEL, RECOMMENDED_ROLE_MODELS

squad = ProductSquad(
    kb,
    model=RECOMMENDED_MODEL,  # "claude-code:sonnet": Facilitator, Product Owner, Designer, Social Media
    models=RECOMMENDED_ROLE_MODELS,  # PMs em "claude-code:sonnet:high", HX em "claude-code:haiku"
    context="...",
)
```

Os PMs, que julgam, rodam no Sonnet com raciocínio estendido; a HX, que
busca e classifica, no Haiku. Num vault real, o mesmo tipo de pedido foi de
uma estimativa de US$ 4,74, antes de tudo isso, para US$ 0,64 com esta
configuração, da conversa ao backlog. É um preset, não um padrão:
`ProductSquad(kb, model=...)` sozinho roda todos os papéis num modelo só.
Para mudar um papel, passe o seu próprio mapa, por exemplo
`models={**RECOMMENDED_ROLE_MODELS, "hx": "claude-code:sonnet"}`.

### Rodando no seu login do Claude Code (sem API key)

Se você tem o [Claude Code](https://code.claude.com) instalado e logado
(`claude`, depois `/login`), a squad pode rodar nesse login em vez de uma API
key: passe `model="claude-code"` (o modelo padrão do Claude Code) ou
`model="claude-code:sonnet"` / `"claude-code:opus"`. Uma terceira parte
define o esforço de raciocínio (`low`, `medium`, `high`, `xhigh`, `max`):
`"claude-code:sonnet:high"` é o Sonnet com raciocínio estendido, que pensa
por mais tempo e custa mais tokens de saída. Cada requisição de agente
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

Os traces deste backend mostram os tokens e o custo que o Claude Code
informa em cada chamada. Os tokens de entrada são o prompt inteiro,
incluindo os que vieram do cache, e o custo é uma estimativa a preço de
tabela da API: serve para comparar ciclos, não é cobrado da sua assinatura.

### Desenhando

O Product Owner marca cada história com `needs_design` (obrigatório, sem
padrão). `design()` entrega o backlog ao Designer, que transforma cada
história que precisa de design num protótipo HTML autocontido e
mobile-first em `squad/design/<cycle_id>/`, consultando a HX sobre as
usuárias e o Marketing PM sobre marca no caminho. Um gate determinístico confere que toda história
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
    # O que chega até você é o que a squad não conseguiu responder: uma lacuna
    # da HX, ou uma dúvida de marca sobre a qual o Marketing PM não achou nada
    # na base de conhecimento. As chaves são o texto das perguntas, e as sem
    # resposta mantêm o padrão sugerido pelo Designer.
    desenho = squad.design(resultado, answers={"Qual tom?": "Amigável, informal"})
```

Uma história ambígua demais para virar tela volta como um `SendBack` para
você, não automaticamente para o Product Owner.

### Escrevendo o conteúdo

O Marketing PM é o dono de posicionamento, tom, marca e naming. Os outros
papéis perguntam a ele por `consult_pm_marketing`, e ele responde com base
na base de conhecimento, com fontes, ou diz que a base não resolve a
questão. Só então uma dúvida de marca chega até você. O Social Media
trabalha abaixo dele: `produce_content()` recebe o mesmo `Brief` aprovado e
escreve a copy da landing page e os posts em `squad/content/<cycle_id>/`.
Veja a [ADR 0012](docs/adr/0012-marketing-pm-owns-brand-and-social-media-executes.md).

```python
from pydantic_squads.product import ContentPack

pacote = squad.produce_content(brief)  # um BriefRejection se o brief não estiver aprovado
if isinstance(pacote, ContentPack):
    for peca in pacote.pieces:
        print(peca.kind, peca.channel, peca.path)  # arquivos na base de conhecimento
    print(pacote.open_questions)  # dúvidas de marca que ninguém soube responder
```

Nada é publicado: revisar e postar o conteúdo fica com você.

### Skills (extra `skills`)

Cada papel pode carregar [Agent Skills](https://agentskills.io/home) —
pacotes `SKILL.md` com `references/`, `assets/` e `scripts/` — restritas ao
seu próprio `Role.skills`; cada papel, menos o Facilitator, já traz uma (`prioritization`, `story-mapping`,
`evidence-classification`, `user-stories`, `prototyping`, `social`), o
Product Owner traz também `story-mapping`, o Designer traz `impeccable` (adaptada
do [impeccable](https://github.com/pbakaus/impeccable), Apache-2.0), o Growth PM,
o Marketing PM e o Social Media dividem doze skills de growth marketing do
[marketingskills](https://github.com/coreyhaines31/marketingskills) (oito,
três e uma; MIT,
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
ciclo é um pedido: a conversa, a rodada do comitê, a decisão, e o backlog,
o protótipo e o conteúdo feitos a partir do brief. Passe `trace_dir` para o
`ProductSquad` para registrar cada chamada como spans (agente, chamadas de
modelo/ferramenta, tokens, custo real, status) em
`{trace_dir}/{cycle_id}.jsonl`, um arquivo append-only por ciclo — incluindo
os próprios spans da HX, aninhados sob o span da tool `consult_hx` do papel
que a consultou, e um span `human_decision` para a sua aprovação ou
rejeição. Um `cycle_id` estável é gerado de qualquer forma, já que também é
gravado no frontmatter das notas de síntese
(`squad/committee/<cycle_id>/`) e da nota do brief
(`squad/briefs/<brief_id>.md`).

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
frontmatter das notas de síntese e de brief do ciclo. O ciclo atual fica em
`squad.cycle_id` (`None` até a primeira chamada iniciar um ciclo):

```python
squad = ProductSquad(kb, model="openai:gpt-4o", context="...", trace_dir="./traces")
squad.resume(cycle_id)
squad.chat("...")
```

`resume()` restaura a conversa do Facilitator. Uma síntese que estava
esperando a sua decisão não é restaurada: chame `close_request()` de novo.
As notas dela de antes continuam na base de conhecimento.

Uma rodada do comitê é gravada como um span `request` com as suas etapas
abaixo (`triage`, `fan_out`, `synthesis`, e `rebuttal` quando os PMs
divergem), cada run de agente dentro da sua etapa. `squad.gantt().print()`
desenha o ciclo atual como um
[Gantt no terminal](docs/gantt_visualization.pt-BR.md) direto da memória,
com ou sem `trace_dir`: os pareceres dos PMs aparecem como barras
sobrepostas sob `fan_out`. Veja a [ADR 0014](docs/adr/0014-request-steps-in-the-trace-and-a-live-gantt.md).

### Visualizador de trace local (extra `observability`)

Os extras `ai` e `observability` adicionam uma CLI baseada em `rich`:

```bash
pydantic-squads trace <cycle_id> --trace-dir ./traces --budget-tokens 20000
```

Ela imprime uma timeline por span, duração/tokens/custo por agente, e sinaliza:
spans lentos, retries da HX causados por uma fonte que não existe na base de
conhecimento, rejeições de brief, devoluções do Designer, aprovações humanas
pendentes, e
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

## Migração

A API ainda muda entre versões, sem aliases de compatibilidade. Cada
quebra é listada aqui.

### 0.2 → 0.3

| Antes | Depois |
| --- | --- |
| `squad/briefs/<brief_id>.md` guardava o `Brief` em JSON: `Brief.model_validate_json(kb.read(path).content)` | O `.md` é Markdown para uma pessoa ler ([ADR 0018](docs/adr/0018-notes-are-markdown-for-people.md)). O dado fica em `squad/briefs/<brief_id>.json`, apontado pelo frontmatter `data` da nota: `BriefRecord.model_validate_json(kb.read(json_path).content).brief` |
| `committee.synthesis_note(synthesis, cycle_id, version)` | `notes.synthesis_note(synthesis, cycle_id, version, language)`, em `pydantic_squads.product.notes` |
| `synthesis-<n>.md`, `decision.md` e `questions.md` tinham texto fixo em inglês, como `- Risk: ...`, `- Asked by: growth_pm` e `- Origin: hx_gap` | Mesmos caminhos e frontmatter. O corpo é diagramado para leitura, chama os papéis pelo nome de exibição (`Growth PM`) e sai no `language` da squad. Não faça parse do corpo |

### 0.1 → 0.2

| Antes | Depois |
| --- | --- |
| A HX tinha `write_note` e podia escrever em `squad/hx/**` | A HX é somente leitura ([ADR 0010](docs/adr/0010-hx-is-a-read-only-query-tool.md)). As notas que já existem em `squad/hx/` continuam legíveis; o que a HX anotaria ela passa a relatar como achados no `HXAnswer` |
| `squad.chat()` falava com o Growth PM | Fala com o Facilitator, que não dá parecer ([ADR 0013](docs/adr/0013-pm-committee-with-a-single-human-gate.md)) |
| `bet = squad.close_bet()` | `sintese = squad.close_request()`, depois `brief = squad.approve()` (ou `adjust(notas)` / `reject(motivo)`) |
| `Bet`, `BetRecord` | Removidos. O artefato de decisão é o `Brief`; as visões dos PMs são `Opinion`s dentro da `Synthesis`. `BriefRecord` substitui `BetRecord` |
| Notas em `squad/bets/<bet_version_id>.md` | `squad/briefs/<brief_id>.md`, mais `squad/committee/<cycle_id>/synthesis-<n>.md` e `decision.md`. As notas de bet antigas continuam legíveis |
| `squad.submit_bet(bet)` | `squad.submit_brief(brief)`, com o `Brief` que `approve()` devolve ([ADR 0011](docs/adr/0011-brief-is-the-product-owners-only-door.md)) |
| `Revision` (o Growth PM revisando um bet devolvido pelo Product Owner) | Removida. `submit_brief()` devolve `Backlog \| BriefRejection`; corrija o brief e envie de novo |
| O `SendBack` do Product Owner | `BriefRejection(missing_fields, reason)`. `SendBack` agora é só do Designer |
| `submit_bet()` podia devolver um `DeferredToolRequests` | `submit_brief()` nunca devolve |
| O trace era uma lista plana de runs de agente | Uma rodada do comitê acrescenta um span `request` com spans de etapa abaixo, todos com `agent="squad"`. O formato do arquivo é o mesmo |
| `Report.po_send_backs`, "Product Owner send-backs" no `pydantic-squads trace` | `Report.brief_rejections`, "Brief rejections" |
| `GROWTH_PM` era conversacional, escrevia notas e falava com o Product Owner | É um papel de tarefa que só lê. As escritas aprovadas em `docs/**` e `assumptions/**` são do Facilitator |
| `HXAnswer.question` era o que a HX escrevesse | É a pergunta de quem consultou, palavra por palavra |
| `build_product_squad()` tinha 4 papéis | Tem 8, nesta ordem: `facilitator`, `growth_pm`, `pm_product`, `pm_marketing`, `hx`, `product_owner`, `designer`, `social_media`. `Span.agent` também aceita os novos ids, e a squad acrescenta a policy `product_owner_has_one_door` |
| `FounderQuestion(origin="positioning", ...)` | Adicione `marketing_question`, a pergunta feita ao Marketing PM. O Designer pergunta a ele antes de perguntar a você ([ADR 0012](docs/adr/0012-marketing-pm-owns-brand-and-social-media-executes.md)) |
| O Growth PM tinha `product-marketing`, `marketing-psychology`, `launch` e `social` | As três primeiras são do Marketing PM, e `social` é do Social Media |
| O Designer listava `product_owner` em `talks_to` | Lista `hx` e `pm_marketing` |
| `ProductSquad(kb).kb is kb` | `ProductSquad(kb).kb` é um `SerializedKnowledgeBase` em volta de `kb`. Para dividir um só escritor entre squads, embrulhe antes com `SerializedKnowledgeBase.wrap(kb)` e passe o wrapper |

## Roadmap

Veja [docs/roadmap.md](docs/roadmap.md).

## Relacionados

O [pydantic-team](https://github.com/Etiqa/pydantic-team) oferece padrões de time em runtime (hierárquico, colaborativo) para o Pydantic AI. Os dois são complementares: os papéis montados pelo `pydantic-squads` são agentes Pydantic AI comuns.

## Desenvolvimento

```bash
uv sync  # adicione --extra ai para tests/test_product_assembly.py, tests/test_product_committee.py,
         # tests/test_product_marketing.py e tests/test_product_observability.py,
         # --extra skills para tests/test_product_skills.py,
         # --extra observability para tests/test_cli.py e tests/test_product_chat.py,
         # --extra otel para tests/test_product_otel.py
uv run pytest
uv run pytest --cov=pydantic_squads --cov-report=term-missing  # a cobertura fica em 100%
```

As regras do projeto para contribuidores e agentes de código (ADRs,
convenções de teste, quais módulos podem importar o quê) estão no
[AGENTS.md](AGENTS.md).

## Licença

MIT
