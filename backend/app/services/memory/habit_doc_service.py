"""Habit doc service — stable practice routine + mental state coping.

Two sections:

  ## 稳定的练习节奏  — recurring study / mock-interview cadence the user
                       has actually maintained for at least 2-3 cycles
  ## 心态与应对      — emotional / psychological coping mechanisms that
                       are noticeably stable
"""

from __future__ import annotations

from app.models.habit_doc import HabitDoc
from app.services.memory._single_doc_service import SingleDocConfig, SingleDocService


SECTION_ROUTINE = "稳定的练习节奏"
SECTION_MINDSET = "心态与应对"


_service = SingleDocService(
    SingleDocConfig(
        model_cls=HabitDoc,
        doc_type="habit",
        canonical_sections=(SECTION_ROUTINE, SECTION_MINDSET),
        default_fold_section=SECTION_MINDSET,
    )
)


load = _service.load
load_as_lines = _service.load_as_lines
apply_patches = _service.apply_patches
upsert_user_edit = _service.upsert_user_edit


__all__ = [
    "SECTION_ROUTINE",
    "SECTION_MINDSET",
    "apply_patches",
    "load",
    "load_as_lines",
    "upsert_user_edit",
]
