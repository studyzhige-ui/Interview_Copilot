"""Database fixtures are available to every database contract, including new files.

Keep provisioning opt-in: importing this module does not connect to a database.
pytest --setup-plan verifies dependency resolution without executing fixtures.
"""

from tests.test_db.test_alembic_migrations import fresh_pg_db  # noqa: F401
from tests.test_db.test_budget_and_invitation_recovery_postgres import database  # noqa: F401
