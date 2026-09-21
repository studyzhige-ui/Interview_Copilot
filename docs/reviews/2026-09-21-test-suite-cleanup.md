# First test-suite cleanup: coverage before case counts

## Scope and evidence

An AST body-equivalence scan of backend test functions found one exact group:
three knowledge-document whitelist tests with identical assertions but different
input domains. Different inputs are not redundant coverage. They are retained
in one explicit finite-domain matrix, with exact normalized output assertions
and an equality check against the complete business whitelist. Historical
comments that purported to verify particular OCR/cloud parsers were removed:
these tests only validate upload eligibility, not parser execution.

The 101 valid tenth-point scores (0.0 through 10.0) remain exhaustive, but share
one TypeAdapter and one test lifecycle. The 14 distinct invalid score inputs,
unknown-versus-zero/history behavior and evaluator boundary remain independent.

The generic no-extension rejection duplicated a more specific friendly-error
contract. Both former inputs, `noext` and `plainname`, now use that stronger
contract. MIME conflict and unsupported-extension security tests are retained.

## Collection accounting

| Scope | Before | After | Coverage change |
| --- | ---: | ---: | --- |
| Score module | 117 nodes | 17 nodes | All 101 valid values and all invalid inputs retained |
| Document-format module | 34 nodes | 8 nodes | All 26 supported filenames and both extensionless inputs retained; exact outputs strengthened |
| Browser cases in each backend matrix job | 3 skipped nodes | Not collected there | Still explicitly executed in the real browser job |

This is **126 fewer test nodes**, not 126 deleted behavioral checks. The backend
CI matrix additionally stops collecting three browser cases that could only be
skipped there. `pytest backend/tests --setup-plan -q` still resolves all fixtures,
including the browser campaign, before integration work. PostgreSQL, Redis/Celery
kill/recovery, browser response-loss, permissions, usage accounting, cancellation,
version/CAS and idempotency campaigns are untouched.

The initial CI #130 JUnit attributes about 95.65 seconds to the real Celery
recovery module, far more than these finite-domain tests. That is meaningful
recovery coverage, not a reason to delete it. No suite-wide speedup is claimed
without comparable completed-run measurements; CI provisioning and job scheduling
are separate from pytest test-body duration.

## Boundaries

This is a first measured cleanup, not a claim that every historical test has been
reviewed or that thousands of tests are unnecessary. Tests named `legacy` may
still protect data compatibility or active adapters. Cross-layer tests are not
removed merely because they assert the same invariant at different trust
boundaries. Temporary source/preparation workflows are removed from the final
branch tree; no enduring write-enabled refactor automation is added.
