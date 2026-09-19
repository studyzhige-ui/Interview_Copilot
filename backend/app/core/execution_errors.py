"""Execution boundary errors; classifiers never import the runtime itself."""


class ModelDispatchConflictError(RuntimeError):
    pass


class ModelOutcomeUnknownError(RuntimeError):
    """Paid dispatch may have happened; stop instead of blindly retrying."""


class ModelStreamCapacityError(RuntimeError):
    pass
