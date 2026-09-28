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

`pip install "pydantic-squads[ai]"` monta a squad em agentes [Pydantic
AI](https://ai.pydantic.dev) de verdade: o `ProductSquad` conversa com o
Growth PM, que pode consultar a HX (achados citados, validados contra a
base de conhecimento) e escrever notas dentro das suas `Permissions`. Uma
escrita num caminho `write_with_approval` pausa a execução e devolve um
`DeferredToolRequests` em vez de quebrar, para que um humano decida antes
de qualquer escrita.

```python
from pydantic_ai import DeferredToolRequests

from pydantic_squads.product import MarkdownKnowledgeBase
from pydantic_squads.product.assembly import ProductSquad

kb = MarkdownKnowledgeBase("./vault")  # uma pasta de notas .md estilo Obsidian
squad = ProductSquad(kb, model="openai:gpt-4o")

resposta = squad.chat("Estamos perdendo usuários no cadastro, o que sabemos?")
print(resposta)  # o Growth PM pode consultar a HX antes de responder

# Quando a conversa já tiver o suficiente:
bet = squad.close_bet()
if isinstance(bet, DeferredToolRequests):
    ...  # resolva bet.approvals, depois squad.close_bet(deferred_tool_results=...)

# Um humano revisa `bet` fora da biblioteca. Só repasse depois de aprovado:
resultado = squad.submit_bet(bet)  # -> Backlog, SendBack ou DeferredToolRequests
```

`submit_bet` repassa um `SendBack` do Product Owner de volta ao Growth PM
para revisar o bet automaticamente, até `max_send_backs` vezes (padrão 3).

Veja o roadmap em [docs/roadmap.md](docs/roadmap.md).

## Desenvolvimento

```bash
uv sync
uv run pytest
```

## Licença

MIT
