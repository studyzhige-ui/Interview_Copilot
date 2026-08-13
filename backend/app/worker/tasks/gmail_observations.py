"""Bounded Gmail incremental Observation polling for active event tasks."""

from __future__ import annotations

import logging

from app.core.async_runtime import run_async
from app.db.database import SessionLocal
from app.services import (
    gmail_integration_service,
    gmail_observation_service,
    gmail_observation_sync_service,
)
from app.services.google_gmail_connector import (
    build_configured_google_gmail_connector,
)
from app.task_queue.celery_app import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.poll_gmail_observations",
    time_limit=55,
    soft_time_limit=50,
)
def poll_gmail_observations():
    """Poll each active Gmail event-task owner once, with durable repair."""

    connector = build_configured_google_gmail_connector()
    if connector is None:
        return {"status": "adapter_unavailable", "candidates": 0, "synced": 0}
    with SessionLocal() as db:
        candidates = gmail_observation_sync_service.gmail_sync_account_candidates(
            db, limit=50
        )

    synced = 0
    observations = 0
    admitted = 0
    dispatched = 0
    failed = 0
    for user_pk, account_id in candidates:
        with SessionLocal() as db:
            try:
                result = run_async(
                    gmail_observation_sync_service.sync_gmail_observations(
                        db,
                        user_pk=user_pk,
                        account_id=account_id,
                        adapter=connector,
                    )
                )
                db.commit()
            except (
                gmail_integration_service.GmailIntegrationError,
                gmail_observation_service.GmailObservationError,
            ) as exc:
                db.rollback()
                error_code = getattr(exc, "code", type(exc).__name__.lower())
                try:
                    error_code = gmail_observation_sync_service.persist_sync_failure(
                        db,
                        user_pk=user_pk,
                        account_id=account_id,
                        error=exc,
                    )
                    db.commit()
                except Exception:  # noqa: BLE001 - next poll retries safe state
                    db.rollback()
                logger.warning(
                    "Gmail Observation poll failed account=%s code=%s",
                    account_id,
                    error_code,
                )
                failed += 1
                continue
            except Exception:  # noqa: BLE001 - isolate one account
                db.rollback()
                logger.warning(
                    "Gmail Observation poll failed account=%s code=internal_error",
                    account_id,
                )
                failed += 1
                continue
        synced += 1
        observations += result.observations_created
        admitted += len(result.admitted_turn_ids)
        try:
            dispatched += gmail_observation_sync_service.dispatch_sync_admissions(
                result
            )
        except Exception:  # noqa: BLE001 - repair sweep owns redelivery
            logger.warning(
                "Gmail Observation Turn dispatch deferred account=%s",
                account_id,
            )
    return {
        "status": "ok",
        "candidates": len(candidates),
        "synced": synced,
        "failed": failed,
        "observations": observations,
        "turns_admitted": admitted,
        "turns_dispatched": dispatched,
    }


__all__ = ["poll_gmail_observations"]
