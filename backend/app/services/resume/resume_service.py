"""Resume parsing, sectioning, and vector embedding service.

Workflow:
  1. User uploads a resume (PDF/DOCX/TXT)
  2. extract_and_store() parses content, splits into typed sections
     (summary, project, education, skill), stores in resume_sections table
  3. Optionally vectorizes each section into Milvus for later retrieval

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
from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)


PARSE_PROMPT = """你是一个简历解析助手。请将以下简历文本拆分为结构化段落。

输出要求：
- 只输出合法 JSON 数组
- 每个元素包含:
  - section_type: "summary" | "project" | "education" | "skill"
  - title: 段落标题（如 "推荐系统项目" 或 "本科教育"）
  - content: 段落全文（保留原文，不要修改）
  - metadata: 可选的额外结构化信息（如技术栈、时间等）

规则：
- 把每一段项目经历拆成独立条目
- 如果简历有个人简介/目标岗位，归为 summary
- 技能列表归为 skill
- 教育背景归为 education
- 不要遗漏任何段落
- 如果某段不属于上述任何类型，归为 summary

简历文本：
{resume_text}
"""


class ResumeService:
    async def extract_and_store(
        self,
        user_id: str,
        upload_id: str,
        resume_text: str,
    ) -> list[ResumeSection]:
        """Parse resume text into sections, store them, and trigger vectorization."""
        sections_data = await self._parse_with_llm(resume_text)
        sections = self._persist_sections(user_id, upload_id, sections_data)
        self._vectorize_sections(sections)
        return sections

    def get_sections_by_upload(
        self,
        upload_id: str,
        user_id: str | None = None,
    ) -> list[ResumeSection]:
        db: Session = SessionLocal()
        try:
            query = db.query(ResumeSection).filter(ResumeSection.upload_id == upload_id)
            if user_id:
                query = query.filter(ResumeSection.user_id == resolve_user_pk(db, user_id))
            return query.order_by(ResumeSection.id.asc()).all()
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

    async def _parse_with_llm(self, resume_text: str) -> list[dict[str, Any]]:
        """Use LLM to split resume text into structured sections."""
        prompt = PARSE_PROMPT.format(resume_text=resume_text)
        try:
            response = await agent_fast_llm.acomplete(
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
        user_id: str,
        upload_id: str,
        sections_data: list[dict[str, Any]],
    ) -> list[ResumeSection]:
        valid_types = {"summary", "project", "education", "skill"}
        db: Session = SessionLocal()
        persisted: list[ResumeSection] = []
        try:
            user_pk = resolve_user_pk(db, user_id)
            # Remove old sections for this upload (re-parse scenario)
            db.query(ResumeSection).filter(
                ResumeSection.upload_id == upload_id,
                ResumeSection.user_id == user_pk,
            ).delete()

            for item in sections_data:
                section_type = str(item.get("section_type") or "summary").strip()
                if section_type not in valid_types:
                    section_type = "summary"
                title = str(item.get("title") or "").strip()[:200]
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                metadata = item.get("metadata")
                metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

                section = ResumeSection(
                    id=_generate_section_id(),
                    user_id=user_pk,
                    upload_id=upload_id,
                    section_type=section_type,
                    title=title or section_type,
                    content=content,
                    metadata_json=metadata_json,
                    embedding_status="pending",
                )
                db.add(section)
                persisted.append(section)

            db.commit()
            for section in persisted:
                db.expunge(section)
            return persisted
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _vectorize_sections(sections: list[ResumeSection]) -> None:
        """Best-effort vectorization — failures are logged, not raised."""
        try:
            from app.services.resume.resume_vector_service import resume_vector_service
        except Exception:  # noqa: BLE001
            logger.warning("Resume vector service unavailable, skipping vectorization")
            return

        db: Session = SessionLocal()
        try:
            for section in sections:
                try:
                    # Re-attach to this session for the flush
                    merged = db.merge(section)
                    resume_vector_service.upsert_section(merged, db=db)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Resume section vectorization failed for %s: %s",
                        section.id,
                        exc,
                    )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("Resume vectorization batch failed: %s", exc)
        finally:
            db.close()


resume_service = ResumeService()
