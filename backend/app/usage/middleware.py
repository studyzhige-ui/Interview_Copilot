"""Request-local attribution without storing a Session in a ContextVar."""

from app.usage.runtime import _scope


class ConsumptionContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Authentication, not headers/query parameters, binds the account later.
        token = _scope.set(None)
        try:
            await self.app(scope, receive, send)
        finally:
            _scope.reset(token)
