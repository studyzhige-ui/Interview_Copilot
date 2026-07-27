"""Resume parsing, sectioning, and vector embedding service.

Workflow:
  1. User uploads a resume (PDF/DOCX/TXT)
  2. extract_and_store() parses content, splits into typed sections
     (summary, project, education, skill), stores in resume_sections table
  3. Enqueues a durable Milvus rebuild in the same transaction

Supported section types:
  - "summary"   — personal summary / objective
  - "project"   — project experience
  - "education" — education background
  - "skill"     — technical skills list
"""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.resume_section import ResumeSection, _generate_section_id
from app.core.llm_client_factory import get_internal_llm
from app.prompts.resume import RESUME_PARSE_PROMPT

logger = logging.getLogger(__name__)


class ResumeService:
    async def extract_and_store(
        self,
        *,
        user_pk: int,
        resume_id: str,
        resume_text: str,
        user_id: str | None = None,
    ) -> list[ResumeSection]:
        """Parse a resume entity's text into typed sections, persist them
        (keyed by ``resume_id``), and enqueue its Milvus rebuild.

        ``user_pk`` is the stable users.id (redundant scope key)."""
        sections_data = await self._parse_with_llm(resume_text, user_id=user_id)
        return self._persist_sections(user_pk, resume_id, sections_data)

    def get_sections_by_resume(
        self,
        resume_id: str,
        user_id: str | None = None,
    ) -> list[ResumeSection]:
        db: Session = SessionLocal()
        try:
            query = db.query(ResumeSection).filter(ResumeSection.resume_id == resume_id)
            if user_id:
                query = query.filter(
                    ResumeSection.user_id == resolve_user_pk(db, user_id)
                )
            return query.order_by(ResumeSection.order_idx.asc()).all()
        finally:
            db.close()

    def get_sections_by_user(self, user_id: str) -> list[ResumeSection]:
        db: Session = SessionLocal()
        try:
            return (
                db.query(ResumeSection)
                .filter(ResumeSection.user_id == resolve_user_pk(db, user_id))
                .order_by(ResumeSection.created_at.desc())
                .all()
            )
        finally:
            db.close()

    def format_for_context(
        self,
        sections: list[ResumeSection],
        *,
        section_types: list[str] | None = None,
    ) -> str:
        """Format sections as text suitable for injection into context slot."""
        filtered = sections
        if section_types:
            allowed = set(section_types)
            filtered = [s for s in sections if s.section_type in allowed]
        if not filtered:
            return ""
        parts = []
        for s in filtered:
            parts.append(f"[{s.section_type}] {s.title}\n{s.content}")
        return "\n\n".join(parts)

    # ── Internal ──────────────────────────────────────────────────────

    async def _parse_with_llm(
        self,
        resume_text: str,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Use LLM to split resume text into structured sections."""
        prompt = RESUME_PARSE_PROMPT.format(resume_text=resume_text)
        try:
            response = await get_internal_llm("worker").acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            raw = str(response.text).strip()
            data = json.loads(raw)
            # Handle {"sections": [...]} or [...] format
            if isinstance(data, dict):
                data = data.get("sections", data.get("items", []))
            if not isinstance(data, list):
                data = []
            return data
        except Exception as exc:  # noqa: BLE001
            logger.error("Resume LLM parsing failed: %s", exc)
            # Fallback: treat entire text as a single summary section
            return [
                {
                    "section_type": "summary",
                    "title": "简历全文",
                    "content": resume_text,
                    "metadata": None,
                }
            ]

    def _persist_sections(
        self,
        user_pk: int,
        resume_id: str,
        sections_data: list[dict[str, Any]],
    ) -> list[ResumeSection]:
        valid_types = {
            "summary",
            "project",
            "experience",
            "education",
            "skill",
            "other",
        }
        db: Session = SessionLocal()
        persisted: list[ResumeSection] = []
        try:
            # Postgres is the fact source. The same transaction also queues a
            # rebuild, so a Milvus outage cannot lose the cleanup or leave the
            # resume permanently half-indexed.
            db.query(ResumeSection).filter(
                ResumeSection.resume_id == resume_id,
                ResumeSection.user_id == user_pk,
            ).delete()

            for order_idx, item in enumerate(sections_data):
                section_type = str(item.get("section_type") or "summary").strip()
                if section_type not in valid_types:
                    section_type = "summary"
                title = str(item.get("title") or "").strip()[:200]
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                metadata = item.get("metadata")
                metadata_json = (
                    json.dumps(metadata, ensure_ascii=False) if metadata else None
                )

                section = ResumeSection(
                    id=_generate_section_id(),
                    user_id=user_pk,
                    resume_id=resume_id,
                    section_type=section_type,
                    title=title or section_type,
                    content=content,
                    metadata_json=metadata_json,
                    order_idx=order_idx,
                    embedding_status="pending",
                )
                db.add(section)
                persisted.append(section)

            from app.models.resume import Resume
            from app.services.resume.resume_outbox import enqueue_resume_reindex

            resume = db.query(Resume).filter(Resume.id == resume_id).first()
            if resume is not None:
                resume.parse_status = "processing"
                resume.parse_error = None
                db.add(resume)
            enqueue_resume_reindex(db, user_pk=user_pk, resume_id=resume_id)
            db.commit()
            for section in persisted:
                db.expunge(section)
            return persisted
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


resume_service = ResumeService()
