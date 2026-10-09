"""The notes the product squad writes itself, as Markdown a person reads.

The synthesis, the decision, the approved brief and the founder questions
are rendered here, by code, in the squad's language (ADR 0018). Only
pydantic (ADR 0001): a note is a string built from a contract.
"""

from datetime import datetime

from pydantic_squads.product.contracts import (
    BriefDraft,
    BriefRecord,
    HumanDecision,
    Opinion,
    Prototype,
    Synthesis,
)
from pydantic_squads.product.knowledge import format_note
from pydantic_squads.product.roles import (
    DESIGNER,
    FACILITATOR,
    GROWTH_PM,
    HX,
    PM_MARKETING,
    PM_PRODUCT,
    PRODUCT_OWNER,
    SOCIAL_MEDIA,
)
from pydantic_squads.product.squad import Language

_ROLE_NAMES = {
    role.id: role.name
    for role in (FACILITATOR, GROWTH_PM, PM_PRODUCT, PM_MARKETING, HX, PRODUCT_OWNER, DESIGNER, SOCIAL_MEDIA)
}

_LABELS: dict[Language, dict[str, str]] = {
    "en": {
        "date": "%Y-%m-%d %H:%M",
        "brief": "Brief",
        "decision": "Decision",
        "approved": "✅ Approved",
        "rejected": "❌ Rejected",
        "decided": "{verdict} on {when}",
        "when": "When",
        "owners": "Owners",
        "notes": "Notes",
        "no_notes": "No notes.",
        "problem": "Problem",
        "hypothesis": "Hypothesis",
        "success_metric": "Success metric",
        "acceptance_criteria": "Acceptance criteria",
        "synthesis": "Synthesis",
        "request": "Request",
        "summary": "Summary",
        "divergences": "Divergences",
        "questions_for_human": "Questions for the human",
        "none": "None.",
        "gaps": "What we don't know",
        "no_gaps": "HX reported no gap during this round.",
        "raw_gaps": "Gaps as HX reported them",
        "asked_hx": "Asked HX",
        "asked_marketing": "Asked the Marketing PM",
        "asked_by": "Asked by",
        "proposed_brief": "Proposed brief",
        "opinions": "Opinions",
        "replies": "Replies",
        "confidence": "Confidence",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "risks": "Risks",
        "sources": "Sources",
        "founder_questions": "Questions for the founder",
        "no_questions": "No open questions.",
        "prototype": "Prototype",
        "origin": "Origin",
        "hx_gap": "HX had no answer",
        "positioning": "the Marketing PM had no answer",
        "suggested_default": "Suggested default",
        "answer": "Answer",
    },
    "pt-BR": {
        "date": "%d/%m/%Y %H:%M",
        "brief": "Brief",
        "decision": "Decisão",
        "approved": "✅ Aprovado",
        "rejected": "❌ Rejeitado",
        "decided": "{verdict} em {when}",
        "when": "Quando",
        "owners": "Responsáveis",
        "notes": "Notas",
        "no_notes": "Sem notas.",
        "problem": "Problema",
        "hypothesis": "Hipótese",
        "success_metric": "Métrica de sucesso",
        "acceptance_criteria": "Critérios de aceite",
        "synthesis": "Síntese",
        "request": "Pedido",
        "summary": "Resumo",
        "divergences": "Divergências",
        "questions_for_human": "Perguntas para o humano",
        "none": "Nenhuma.",
        "gaps": "O que não sabemos",
        "no_gaps": "O HX não reportou nenhuma lacuna nesta rodada.",
        "raw_gaps": "Lacunas como o HX reportou",
        "asked_hx": "Pergunta ao HX",
        "asked_marketing": "Pergunta ao Marketing PM",
        "asked_by": "Quem perguntou",
        "proposed_brief": "Brief proposto",
        "opinions": "Opiniões",
        "replies": "Réplicas",
        "confidence": "Confiança",
        "low": "baixa",
        "medium": "média",
        "high": "alta",
        "risks": "Riscos",
        "sources": "Fontes",
        "founder_questions": "Perguntas para o founder",
        "no_questions": "Nenhuma pergunta em aberto.",
        "prototype": "Protótipo",
        "origin": "Origem",
        "hx_gap": "o HX não tinha resposta",
        "positioning": "o Marketing PM não tinha resposta",
        "suggested_default": "Padrão sugerido",
        "answer": "Resposta",
    },
}


def _role(role_id: str) -> str:
    """A role's display name, or the id itself when the squad has no such role."""
    return _ROLE_NAMES.get(role_id, role_id)


def _roles(role_ids: list[str]) -> str:
    return ", ".join(_role(role_id) for role_id in role_ids)


def _when(moment: datetime, labels: dict[str, str]) -> str:
    """`moment` in the local time of the machine that writes the note."""
    return moment.astimezone().strftime(labels["date"])


def _quote(text: str) -> str:
    return "\n".join(f"> {line}".rstrip() for line in text.splitlines())


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _brief_sections(brief: BriefDraft, labels: dict[str, str], heading: str) -> list[str]:
    """A brief's fields, one section each, under headings of level `heading` (`##` or `###`)."""
    criteria = "\n".join(f"- [ ] {criterion}" for criterion in brief.acceptance_criteria)
    return [
        f"{heading} {labels['problem']}\n\n{brief.problem}",
        f"{heading} {labels['hypothesis']}\n\n{brief.hypothesis}",
        f"{heading} {labels['success_metric']}\n\n{brief.success_metric}",
        f"{heading} {labels['acceptance_criteria']}\n\n{criteria}",
    ]


def brief_note(record: BriefRecord, language: Language = "en") -> str:
    """The `squad/briefs/<brief_id>.md` note: an approved brief, for a person to read.

    The same brief as data is `record` as JSON, in the `.json` file next to
    it, which the frontmatter's `data` names.
    """
    labels = _LABELS[language]
    brief, decision = record.brief, record.brief.human_decision
    decided = labels["decided"].format(
        verdict=labels[decision.verdict], when=_when(decision.decided_at, labels)
    )
    header = f"- **{labels['decision']}:** {decided}\n- **{labels['owners']}:** {_roles(brief.owner_roles)}"
    sections = [f"# {labels['brief']}", header]
    if decision.notes:
        sections.append(_quote(decision.notes))
    sections.extend(_brief_sections(brief, labels, "##"))
    frontmatter: dict[str, str | list[str]] = {
        "cycle_id": record.cycle_id,
        "schema_version": str(record.schema_version),
        "brief_id": record.brief_id,
        "decided_at": decision.decided_at.isoformat(),
        "data": f"squad/briefs/{record.brief_id}.json",
    }
    return format_note(frontmatter, "\n\n".join(sections) + "\n")


def decision_note(
    decision: HumanDecision,
    cycle_id: str,
    synthesis_path: str,
    brief_path: str | None = None,
    language: Language = "en",
) -> str:
    """The `decision.md` note: the verdict, when it was given, and the human's notes."""
    labels = _LABELS[language]
    facts = [
        f"- **{labels['when']}:** {_when(decision.decided_at, labels)}",
        f"- **{labels['synthesis']}:** `{synthesis_path}`",
    ]
    frontmatter: dict[str, str | list[str]] = {
        "cycle_id": cycle_id,
        "schema_version": "1",
        "verdict": decision.verdict,
        "decided_at": decision.decided_at.isoformat(),
        "synthesis": synthesis_path,
    }
    if brief_path is not None:
        facts.append(f"- **{labels['brief']}:** `{brief_path}`")
        frontmatter["brief"] = brief_path
    sections = [
        f"# {labels['decision']}: {labels[decision.verdict]}",
        "\n".join(facts),
        f"## {labels['notes']}\n\n{decision.notes or labels['no_notes']}",
    ]
    return format_note(frontmatter, "\n\n".join(sections) + "\n")


def _opinion_section(opinion: Opinion, labels: dict[str, str]) -> str:
    parts = [
        f"### {_role(opinion.role)}",
        f"**{labels['confidence']}:** {labels[opinion.confidence]}",
        opinion.recommendation,
    ]
    for label, items in (
        (labels["risks"], opinion.risks),
        (labels["questions_for_human"], opinion.questions_for_human),
        (labels["sources"], [f"`{source}`" for source in opinion.sources]),
    ):
        if items:
            parts.append(f"**{label}**\n\n{_bullets(items)}")
    return "\n\n".join(parts)


def synthesis_note(synthesis: Synthesis, cycle_id: str, version: int, language: Language = "en") -> str:
    """The note the human reads at the gate: the synthesis, then everything it was made from.

    Under "What we don't know" it lists each gap HX reported during the
    round with the question that surfaced it and the PM that asked.
    """
    labels = _LABELS[language]
    brief = synthesis.proposed_brief
    sections = [
        f"# {labels['synthesis']}",
        f"## {labels['request']}\n\n{_quote(synthesis.request)}",
        f"## {labels['summary']}\n\n{synthesis.summary}",
    ]

    if synthesis.divergences:
        body = "\n\n".join(
            f"### {d.topic}\n\n"
            + "\n".join(f"- **{_role(role)}:** {position}" for role, position in d.positions.items())
            for d in synthesis.divergences
        )
    else:
        body = labels["none"]
    sections.append(f"## {labels['divergences']}\n\n{body}")

    questions = "\n".join(f"{n}. {q}" for n, q in enumerate(synthesis.questions_for_human, 1)) or labels["none"]
    sections.append(f"## {labels['questions_for_human']}\n\n{questions}")

    if synthesis.gaps:
        body = "\n\n".join(
            f"### {gap.gap}\n\n"
            + "\n".join(f"- **{labels['asked_hx']}:** {question}" for question in gap.questions)
            + f"\n- **{labels['asked_by']}:** {_roles(gap.asked_by)}"
            for gap in synthesis.gaps
        )
    else:
        body = labels["no_gaps"]
    sections.append(f"## {labels['gaps']}\n\n{body}")
    if synthesis.raw_gaps != synthesis.gaps:
        # The grouping is the Facilitator's: HX's own words stay next to it.
        reported = "\n".join(
            f"- {gap.gap} _({labels['asked_by']}: {_roles(gap.asked_by)})_" for gap in synthesis.raw_gaps
        )
        sections.append(f"## {labels['raw_gaps']}\n\n{reported}")

    sections.append(f"## {labels['proposed_brief']}\n\n**{labels['owners']}:** {_roles(brief.owner_roles)}")
    sections.extend(_brief_sections(brief, labels, "###"))
    sections.append(f"## {labels['opinions']}")
    sections.extend(_opinion_section(o, labels) for o in synthesis.opinions)
    if synthesis.rebuttals:
        sections.append(f"## {labels['replies']}")
        sections.extend(_opinion_section(o, labels) for o in synthesis.rebuttals)

    frontmatter: dict[str, str | list[str]] = {
        "cycle_id": cycle_id,
        "schema_version": "1",
        "version": str(version),
        "roles": [o.role for o in synthesis.opinions],
    }
    return format_note(frontmatter, "\n\n".join(sections) + "\n")


def founder_questions_note(prototype: Prototype, cycle_id: str, language: Language = "en") -> str:
    """The `questions.md` note: every open founder question, for the founder to answer."""
    labels = _LABELS[language]
    sections = [f"# {labels['founder_questions']}", f"**{labels['prototype']}:** `{prototype.html_path}`"]
    if not prototype.founder_questions:
        sections.append(labels["no_questions"])
    for q in prototype.founder_questions:
        facts = [f"- **{labels['origin']}:** {labels[q.origin]}"]
        if q.hx_question is not None:
            facts.append(f"- **{labels['asked_hx']}:** {q.hx_question}")
        if q.marketing_question is not None:
            facts.append(f"- **{labels['asked_marketing']}:** {q.marketing_question}")
        facts.append(f"- **{labels['suggested_default']}:** {q.suggested_default}")
        facts.append(f"- **{labels['answer']}:**")
        sections.append(f"## {q.question}\n\n{q.context}\n\n" + "\n".join(facts))
    frontmatter: dict[str, str | list[str]] = {
        "cycle_id": cycle_id,
        "schema_version": "1",
        "prototype": prototype.html_path,
    }
    return format_note(frontmatter, "\n\n".join(sections) + "\n")
