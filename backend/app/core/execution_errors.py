"""Execution boundary errors; classifiers never import the runtime itself."""


class ModelDispatchConflictError(RuntimeError):
    pass


class ModelOutcomeUnknownError(RuntimeError):
    """Paid dispatch may have happened; stop instead of blindly retrying."""


class ModelStreamCapacityError(RuntimeError):
    pass


class ConsumptionSettlementUnconfirmedError(ModelOutcomeUnknownError):
    """The local accounting COMMIT is unconfirmed, not necessarily the provider.

    The parent classification prevents automatic network retries. Read the
    original receipt before operator reconciliation; never guess a refund.
    """
