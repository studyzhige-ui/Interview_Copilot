"""End-to-end knowledge retrieval orchestration."""

from __future__ import annotations

import asyncio
import logging
from threading import Lock
from time import perf_counter
from typing import Any

from llama_index.core.postprocessor.types import BaseNodePostprocessor

from app.core.bounded_work import WorkCapacityExceeded
from app.rag.retrieval.workers import pool
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.rag.domain.models import (
    EMPTY_CAPACITY_EXHAUSTED,
    EMPTY_RETRIEVAL_INCOMPLETE,
    EMPTY_CANONICAL_UNAVAILABLE,
    EMPTY_ALL_BELOW_THRESHOLD,
    EMPTY_ALL_FILTERED_LIVE_CHECK,
    EMPTY_MILVUS_UNAVAILABLE,
    EMPTY_NO_CANDIDATES,
    EMPTY_PRINCIPAL_UNRESOLVED,
    EMPTY_RERANKER_UNAVAILABLE,
    SCORE_SOURCE_RERANKER,
    RetrievalResult,
    RetrievalState,
    SearchIntent,
)
from app.rag.index.identity import (
    active_knowledge_collection_name,
    current_index_identity,
)
from app.rag.policy import current_rag_policy
from app.rag.reranker_registry import build_reranker
from app.rag.retrieval.candidates import (
    IntentCandidates,
    search_intent_candidates,
)
from app.rag.retrieval.reranking import rerank_groups, select_coverage_aware

logger = logging.getLogger(__name__)


class KnowledgeRetrievalPipeline:
    """The sole implementation of retrieve → rerank → select → hydrate."""

    def __init__(self) -> None:
        self._reranker: BaseNodePostprocessor | None = None
        self._reranker_lock = Lock()

    def initialize(self) -> None:
        if self._reranker is not None:
            return
        with self._reranker_lock:
            if self._reranker is None:
                policy = current_rag_policy().retrieval
                # Preserve the candidate score distribution. Final allocation
                # happens only after every intent has been reranked.
                self._reranker = build_reranker(top_n=policy.candidate_count)

    @staticmethod
    def _coerce_intents(values: list[SearchIntent | dict]) -> list[SearchIntent]:
        maximum = current_rag_policy().retrieval.max_intents
        intents: list[SearchIntent] = []
        for value in values:
            intent = value if isinstance(value, SearchIntent) else SearchIntent(**value)
            if not intent.query:
                continue
            intent_id = intent.intent_id or f"I{len(intents) + 1}"
            intents.append(intent.model_copy(update={"intent_id": intent_id}))
        return intents[:maximum]

    @staticmethod
    def _empty(
        reason: str,
        *,
        intents: list[SearchIntent],
        degraded: bool = False,
        diagnostics: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        return RetrievalResult(
            intents=intents,
            state=RetrievalState(
                retrieval_hit=False,
                empty_reason=reason,
                fallback_used=degraded,
            ),
            diagnostics=diagnostics or {},
        )

    @staticmethod
    def _hydrate(
        node_ids: list[str],
        *,
        user_pk: int,
        source_kind: str | None,
        intents: list[SearchIntent],
    ) -> list[dict[str, Any]]:
        from app.rag.chunk_hydration import hydrate_chunks

        with SessionLocal() as db:
            explicit_ids = {
                doc_id for intent in intents for doc_id in intent.document_ids
            }
            return hydrate_chunks(
                db,
                node_ids,
                user_pk=user_pk,
                source_kind=source_kind,
                document_ids=explicit_ids
                if all(i.document_ids for i in intents)
                else None,
                attachment_document_ids=explicit_ids,
                enforce_index_generation=True,
            )

    async def retrieve(
        self,
        *,
        intents: list[SearchIntent | dict],
        user_id: str,
        source_kind: str | None = None,
        min_score: float | None = None,
        include_diagnostics: bool = False,
    ) -> RetrievalResult:
        policy = current_rag_policy().retrieval
        started = perf_counter()
        planned = self._coerce_intents(intents)
        identity = current_index_identity()
        diagnostics: dict[str, Any] = {
            "index_fingerprint": identity.fingerprint,
            "collection": active_knowledge_collection_name(),
            "intent_count": len(planned),
            "timings_ms": {},
        }

        def finish() -> dict[str, Any]:
            diagnostics["timings_ms"]["total"] = round(
                (perf_counter() - started) * 1000,
                2,
            )
            return diagnostics

        if not planned:
            return self._empty(
                EMPTY_NO_CANDIDATES,
                intents=[],
                diagnostics=finish(),
            )
        principal_started = perf_counter()

        def resolve_principal() -> int | None:
            with SessionLocal() as db:
                return resolve_user_pk(db, user_id)

        try:
            user_pk = await asyncio.wait_for(
                pool("storage").run(resolve_principal), policy.search_timeout_seconds
            )
        except WorkCapacityExceeded:
            return self._empty(
                EMPTY_CAPACITY_EXHAUSTED,
                intents=planned,
                degraded=True,
                diagnostics=finish(),
            )
        except Exception as exc:
            logger.warning("RAG principal lookup unavailable (%s)", type(exc).__name__)
            return self._empty(
                EMPTY_CANONICAL_UNAVAILABLE,
                intents=planned,
                degraded=True,
                diagnostics=finish(),
            )
        diagnostics["timings_ms"]["principal"] = round(
            (perf_counter() - principal_started) * 1000,
            2,
        )
        if user_pk is None:
            return self._empty(
                EMPTY_PRINCIPAL_UNRESOLVED,
                intents=planned,
                diagnostics=finish(),
            )

        from app.usage.runtime import for_owner

        with for_owner(user_pk, operation="retrieval", username=user_id):
            search_started = perf_counter()
            searched = await asyncio.gather(
                *[
                    search_intent_candidates(
                        intent,
                        user_pk=user_pk,
                        source_kind=source_kind,
                        candidate_count=policy.candidate_count,
                    )
                    for intent in planned
                ],
                return_exceptions=True,
            )
            groups: list[IntentCandidates] = []
            search_errors: dict[str, str] = {}
            capacity_exhausted = False
            for intent, result in zip(planned, searched):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, BaseException):
                    capacity_exhausted |= isinstance(result, WorkCapacityExceeded)
                    search_errors[intent.intent_id] = (
                        f"{type(result).__name__}: {result}"
                    )
                    continue
                groups.append(result)
                capacity_exhausted |= result.capacity_exhausted
            diagnostics["timings_ms"]["candidate_search"] = round(
                (perf_counter() - search_started) * 1000,
                2,
            )
            diagnostics["capacity_exhausted"] = capacity_exhausted
            diagnostics["search_failed_intents"] = len(search_errors)
            diagnostics["partial_channel_failures"] = sum(
                len(group.channel_errors) for group in groups
            )
            search_degraded = bool(
                search_errors or diagnostics["partial_channel_failures"]
            )
            diagnostics["candidate_count"] = sum(len(group.hits) for group in groups)
            if not groups:
                return self._empty(
                    EMPTY_CAPACITY_EXHAUSTED
                    if capacity_exhausted
                    else EMPTY_MILVUS_UNAVAILABLE,
                    intents=planned,
                    degraded=True,
                    diagnostics={
                        **finish(),
                        **(
                            {"search_errors": search_errors}
                            if include_diagnostics
                            else {}
                        ),
                    },
                )
            if not any(group.hits for group in groups):
                return self._empty(
                    (
                        EMPTY_CAPACITY_EXHAUSTED
                        if capacity_exhausted
                        else EMPTY_RETRIEVAL_INCOMPLETE
                    )
                    if search_degraded
                    else EMPTY_NO_CANDIDATES,
                    intents=planned,
                    degraded=search_degraded,
                    diagnostics=finish(),
                )

            if include_diagnostics:
                diagnostics.update(
                    {
                        "candidate_node_ids_by_intent": [
                            [str(hit.get("id") or "") for hit in group.hits]
                            for group in groups
                        ],
                        "candidate_node_ids": list(
                            dict.fromkeys(
                                str(hit.get("id") or "")
                                for group in groups
                                for hit in group.hits
                            )
                        ),
                        "candidate_document_ids": list(
                            dict.fromkeys(
                                str(hit.get("document_id") or "")
                                for group in groups
                                for hit in group.hits
                            )
                        ),
                        "search_variant_count": sum(
                            1 + len(group.intent.dense_queries) for group in groups
                        ),
                        "search_errors": search_errors,
                    }
                )

            if self._reranker is None:
                return self._empty(
                    EMPTY_RERANKER_UNAVAILABLE,
                    intents=planned,
                    degraded=True,
                    diagnostics=finish(),
                )
            rerank_started = perf_counter()
            try:
                reranked = await rerank_groups(self._reranker, groups)
            except asyncio.CancelledError:
                raise
            except WorkCapacityExceeded:
                return self._empty(
                    EMPTY_CAPACITY_EXHAUSTED,
                    intents=planned,
                    degraded=True,
                    diagnostics=finish(),
                )
            except Exception as exc:  # noqa: BLE001 — model/transport stage boundary
                logger.warning(
                    "RAG reranker unavailable (%s): %r",
                    type(exc).__name__,
                    exc,
                )
                return self._empty(
                    EMPTY_RERANKER_UNAVAILABLE,
                    intents=planned,
                    degraded=True,
                    diagnostics=finish(),
                )
            diagnostics["timings_ms"]["rerank"] = round(
                (perf_counter() - rerank_started) * 1000,
                2,
            )
            if include_diagnostics:
                diagnostics["reranked"] = [
                    {
                        "node_id": str(row.get("id") or ""),
                        "score": row.get("score"),
                        "intent_ids": row.get("intent_ids", []),
                    }
                    for group in reranked
                    for row in group
                ]

            threshold = policy.min_score if min_score is None else float(min_score)
            selected = select_coverage_aware(
                reranked,
                [group.intent for group in groups],
                min_score=threshold,
                final_count=policy.final_count,
                score_margin=policy.score_margin if min_score is None else None,
            )
            if not selected:
                return self._empty(
                    EMPTY_ALL_BELOW_THRESHOLD,
                    intents=planned,
                    degraded=search_degraded,
                    diagnostics=finish(),
                )

            node_ids = [str(row.get("id") or "") for row in selected]
            hydrate_started = perf_counter()
            try:
                hydrated = await asyncio.wait_for(
                    pool("storage").run(
                        self._hydrate,
                        node_ids,
                        user_pk=user_pk,
                        source_kind=source_kind,
                        intents=planned,
                    ),
                    policy.search_timeout_seconds,
                )
            except WorkCapacityExceeded:
                return self._empty(
                    EMPTY_CAPACITY_EXHAUSTED,
                    intents=planned,
                    degraded=True,
                    diagnostics=finish(),
                )
            except Exception as exc:
                # Never fall back to an untrusted index body when canonical
                # ownership/current-version validation cannot be completed.
                logger.warning(
                    "RAG canonical hydration unavailable (%s)", type(exc).__name__
                )
                return self._empty(
                    EMPTY_CANONICAL_UNAVAILABLE,
                    intents=planned,
                    degraded=True,
                    diagnostics=finish(),
                )
            # A stale index must not redirect a restricted intent to another
            # canonical document, even when another intent has a wider scope.
            selected_scopes = {
                str(row.get("id") or ""): set(row.get("intent_ids", []))
                for row in selected
            }
            hydrated = [
                chunk
                for chunk in hydrated
                if any(
                    intent.intent_id
                    in selected_scopes.get(str(chunk.get("node_id") or ""), set())
                    and (
                        not intent.document_ids
                        or chunk.get("document_id") in intent.document_ids
                    )
                    and (
                        chunk.get("source_kind") != "chat_attachment"
                        or chunk.get("document_id") in intent.document_ids
                    )
                    for intent in planned
                )
            ]
            diagnostics["timings_ms"]["hydrate"] = round(
                (perf_counter() - hydrate_started) * 1000,
                2,
            )
            diagnostics["selected_count"] = len(selected)
            diagnostics["hydrated_count"] = len(hydrated)
            if not hydrated:
                return self._empty(
                    EMPTY_ALL_FILTERED_LIVE_CHECK,
                    intents=planned,
                    degraded=search_degraded,
                    diagnostics=finish(),
                )
            selected_by_id = {str(row.get("id") or ""): row for row in selected}
            for chunk in hydrated:
                selected_row = selected_by_id.get(str(chunk.get("node_id") or ""), {})
                chunk["score"] = float(selected_row.get("score") or 0.0)
                chunk["score_source"] = SCORE_SOURCE_RERANKER
                chunk["intent_ids"] = list(selected_row.get("intent_ids", []))
            return RetrievalResult(
                chunks=hydrated,
                intents=planned,
                state=RetrievalState(
                    retrieval_hit=True,
                    fallback_used=search_degraded,
                ),
                diagnostics=finish(),
            )


knowledge_retrieval_pipeline = KnowledgeRetrievalPipeline()


__all__ = ["KnowledgeRetrievalPipeline", "knowledge_retrieval_pipeline"]
