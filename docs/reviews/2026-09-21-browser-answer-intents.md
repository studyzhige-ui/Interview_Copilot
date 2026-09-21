# Browser generation retries are new intents, not unknown-call replay

CI #149 (`35568438056`, HEAD `ad32b430`) completed six jobs successfully and
failed the text-interview browser case on equality of the original and retry
`request_id`. The production flow already issued a fresh intent only on the
explicit "重试生成下一题" action. Refresh/reconnect did not POST, and the
candidate answer remained stored once. The stale browser assertion predated
persistent answer-intent receipts.

The corrected contract still requires identical answer/question payloads, but
requires a different request ID for the deliberate new model generation. It
additionally inspects real PostgreSQL: exactly two intent receipts must exist;
the first stays unknown with no response; the second is completed and references
the single new interviewer message. The three-message transcript, read-only
refresh/reconnect, no-microphone requirement and absence of browser errors remain.
No production code, timeout, skip or automatic-retry policy is relaxed here.

This is a test-contract correction, not proof of real model or device quality.
The amended real browser campaign must pass CI on the resulting branch.
