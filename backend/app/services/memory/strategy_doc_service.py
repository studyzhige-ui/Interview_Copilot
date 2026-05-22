"""Strategy doc service — cross-topic interview answering methodology.

Two sections:

  ## 已内化       — methods the user has actually applied and validated
  ## 尝试中       — methods proposed/agreed-to but not yet validated

Promotion 尝试中 → 已内化 happens when dreaming sees the user report
the method worked across multiple interviews. We don't enforce that
movement schema-side; the extraction prompt is responsible.
"""

from __future__ import annotations

from app.models.strategy_doc import StrategyDoc
from app.services.memory._single_doc_service import SingleDocConfig, SingleDocService


SECTION_INTERNALISED = "已内化"
SECTION_TRYING = "尝试中"


_service = SingleDocService(
    SingleDocConfig(
        model_cls=StrategyDoc,
        doc_type="strategy",
        canonical_sections=(SECTION_INTERNALISED, SECTION_TRYING),
        default_fold_section=SECTION_TRYING,  # unknown content lands as "trying"
    )
)


# Re-exported flat API so callers don't reach into the SingleDocService instance.
load = _service.load
load_as_lines = _service.load_as_lines
load_description = _service.load_description
apply_patches = _service.apply_patches
upsert_user_edit = _service.upsert_user_edit


__all__ = [
    "SECTION_INTERNALISED",
    "SECTION_TRYING",
    "apply_patches",
    "load",
    "load_as_lines",
    "load_description",
    "upsert_user_edit",
]
