# pydantic-squads

Open source library (MIT) for declarative, validated agent squads on top of Pydantic AI. Read `README.md`, `docs/architecture.md`, `docs/roadmap.md` and `docs/adr/` before changing anything.

## Layout

- `src/pydantic_squads/`: the core (`role`, `squad`, `policies`, `prompt`) and `cli.py`.
- `src/pydantic_squads/product/`: the ready-made product squad (ADR 0003); its bundled skills live in `product/skills/`.
- `tests/`: the pytest suite, fixtures in `tests/fixtures/`.
- `docs/adr/`: decision records. `docs/architecture.md` (and `.pt-BR.md`): how the product squad works and why; keep both in sync with the code and with each other. `docs/roadmap.md`: non-binding roadmap.

## Commands

- `uv sync` (add `--extra ai` for `tests/test_product_assembly.py`, `tests/test_product_committee.py`, `tests/test_product_marketing.py` and `tests/test_product_observability.py`, `--extra skills` for `tests/test_product_skills.py`, `--extra observability` for `tests/test_cli.py` and `tests/test_product_chat.py`, `--extra otel` for `tests/test_product_otel.py`; each is skipped otherwise)
- `uv run pytest`
- `uv run pytest --cov=pydantic_squads --cov-report=term-missing`

## Rules

- Public API, code and docstrings in English. Docs in English and Portuguese (keep `README.md` and `README.pt-BR.md` in sync).
- The core (`role`, `squad`, `policies`, `prompt`) imports only `pydantic`. Never import `pydantic_ai` there (ADR 0001). Same for `pydantic_squads.product.contracts/roles/squad/knowledge`; only `pydantic_squads.product.assembly` (the `ai` extra), `pydantic_squads.product.committee` (the `ai` extra), `pydantic_squads.product.chat` (the `ai` + `observability` extras, ADR 0017), `pydantic_squads.product.claude_code` (the `ai` extra, ADR 0008), `pydantic_squads.product.observability` (the `ai` extra, ADR 0006), `pydantic_squads.product.skills_integration` (the `skills` extra, ADR 0005) and `pydantic_squads.product.otel` (the `ai` + `otel` extras, ADR 0006) may import `pydantic_ai`/`pydantic_ai_skills`/`logfire`. `committee` runs agents that `assembly` builds and never imports `assembly`, and `assembly` only imports `skills_integration` lazily, when `ProductSquad(skills_dirs=...)` is given.
- `pydantic_squads.cli` (the `pydantic-squads trace` and `chat` commands, ADR 0006 and ADR 0017) imports the `ai` and `observability` extras only lazily, so importing it never requires either. The terminal session lives in `pydantic_squads.product.chat`: do not write another one in `examples/` or in a consuming project.
- Invariants live in `Squad`; opinionated rules are policies (ADR 0002).
- No feature enters the core without a real use case. `pydantic_squads.product` is the one exception: it ships a ready-made product squad as the library's reference implementation (ADR 0003). Content specific to a single company's product still never goes in this repo.
- There is no delete permission, anywhere.
- Every test has a short docstring, which becomes its title in pytest output.
- Tests never call an LLM. Keep coverage at 100%.
- Record new decisions as ADRs in `docs/adr/`.
