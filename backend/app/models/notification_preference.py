"""User-level delivery settings for planned NextAction reminders.

The row configures notification delivery only.  It is not a Reminder,
NotificationTask, or second action lifecycle; the scheduled business intent
continues to live exclusively on ``NextAction``.
"""

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, String

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint(
            "default_channel = 'in_app'",
            name="ck_notification_preferences_channel",
        ),
        CheckConstraint(
            "(quiet_start IS NULL AND quiet_end IS NULL) OR "
            "(quiet_start IS NOT NULL AND quiet_end IS NOT NULL)",
            name="ck_notification_preferences_quiet_pair",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_notification_preferences_version",
        ),
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    default_channel = Column(
        String(24), nullable=False, default="in_app", server_default="in_app"
    )
    timezone = Column(
        String(80),
        nullable=False,
        default="Asia/Shanghai",
        server_default="Asia/Shanghai",
    )
    # Local HH:MM strings.  NULL/NULL means no quiet hours.
    quiet_start = Column(String(5), nullable=True)
    quiet_end = Column(String(5), nullable=True)
    version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


__all__ = ["NotificationPreference"]
