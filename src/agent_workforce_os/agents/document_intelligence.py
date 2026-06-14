from __future__ import annotations

from .base_imports import AgentDecision, BaseAgent, DocumentRecord, new_id
from agent_workforce_os.tools.document_parsers import (
    extract_candidate_tasks,
    extract_skills,
    parse_document,
    summarize_text,
)


class DocumentIntelligenceAgent(BaseAgent):
    name = "document_intelligence"

    def _run(self, input_payload: dict) -> AgentDecision:
        path = input_payload["path"]
        parsed = parse_document(path)
        skills = extract_skills(parsed.text, self.context.config.skills_catalog)
        summary = summarize_text(parsed.text)
        if self.context.llm.available and input_payload.get("llm_summary"):
            response = self.context.llm.complete(
                system="You summarize business, resume, and technical documents for an operations system.",
                user=f"Return a concise operational summary of this document:\n\n{parsed.text[:12000]}",
            )
            summary = response.text.strip()

        record = DocumentRecord(
            id=new_id("doc"),
            source_path=str(parsed.path),
            content_hash=parsed.content_hash,
            text=parsed.text,
            summary=summary,
            skills=skills,
            metadata={**parsed.metadata, "candidate_tasks": extract_candidate_tasks(parsed.text)},
        )
        self.context.storage.save_document(record)
        self.context.storage.record_event(
            "document",
            record.id,
            "document_ingested",
            {"source_path": record.source_path, "skills": skills},
        )
        return AgentDecision(
            agent_name=self.name,
            action="document_ingested",
            confidence=0.9 if record.text else 0.2,
            reasons=[f"Parsed {parsed.metadata['suffix']} document", f"Extracted {len(skills)} skills"],
            payload={
                "document_id": record.id,
                "summary": record.summary,
                "skills": record.skills,
                "candidate_tasks": record.metadata["candidate_tasks"],
            },
        )

