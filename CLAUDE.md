# pydantic-squads

Open source library (MIT) for declarative, validated agent squads on top of Pydantic AI. Read `README.md`, `docs/roadmap.md` and `docs/adr/` before changing anything.

## Commands

- `uv sync`
- `uv run pytest`
- `uv run pytest --cov=pydantic_squads --cov-report=term-missing`

## Rules

- Public API, code and docstrings in English. Docs in English and Portuguese (keep `README.md` and `README.pt-BR.md` in sync).
- The core (`role`, `squad`, `policies`, `prompt`, `contracts`) imports only `pydantic`. Never import `pydantic_ai` there (ADR 0001).
- Invariants live in `Squad`; opinionated rules are policies (ADR 0002).
- No feature enters the core without a real use case. `pydantic_squads.product` is the one exception: it ships a ready-made product squad as the library's reference implementation (ADR 0003). Content specific to a single company's product still never goes in this repo.
- There is no delete permission, anywhere.
- Every test has a short docstring, which becomes its title in pytest output.
- Tests never call an LLM. Keep coverage at 100%.
- Record new decisions as ADRs in `docs/adr/`.
