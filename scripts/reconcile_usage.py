#!/usr/bin/env python3
"""Operator-only consumption reconciliation. Default is dry-run/rollback.

Reads a local evidence-bound JSON document, never contacts a provider. Do not
put invoice documents, account identifiers or secrets in the public repository.
"""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "request",
        type=Path,
        help="JSON containing user_id, receipt_id, expected_revision, request_id, operator, outcome, observed_units, observed_tokens, currency; optional rates/invoice_cost_micros/quiesced",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Verified local supplier receipt/invoice or allocation evidence; only its hash enters the ledger",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the correction rather than validate then roll back",
    )
    parser.add_argument(
        "--acknowledge-external-evidence",
        action="store_true",
        help="Attest evidence was verified and does not merely show a local timeout",
    )
    args = parser.parse_args()
    if args.apply and not args.acknowledge_external_evidence:
        parser.error("--apply requires --acknowledge-external-evidence")
    if args.request.stat().st_size > 65536 or args.evidence.stat().st_size > 20_000_000:
        parser.error("request or evidence exceeds the local input limit")
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "evidence_ref" in payload:
        parser.error(
            "request must be an object; evidence_ref is computed from --evidence"
        )
    digest = hashlib.sha256(args.evidence.read_bytes()).hexdigest()
    # Environment/operator DB connection, never a browser token or client key.
    from app.db.database import SessionLocal
    from app.usage.reconciliation import reconcile

    with SessionLocal() as db:
        result = reconcile(db, evidence_ref=f"sha256:{digest}", **payload)
        output = {
            "adjustment_id": result.id,
            "receipt_id": result.receipt_id,
            "revision": result.after_json["revision"],
            "committed": args.apply,
            "evidence_sha256": digest,
        }
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
