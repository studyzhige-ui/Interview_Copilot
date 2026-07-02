"""Auth / credential services.

Bundles the services that own user authentication + per-user
secret material:

  avatar_service                   — avatar validation / URL translation / cleanup
  email_service                    — SMTP delivery (verification codes, etc.)
  user_account_service             — users-table ops (authenticate, register,
                                     password change, profile updates)
  user_api_key_service             — encrypted at-rest per-(user, provider) LLM API keys
  user_provider_settings_service   — non-secret per-(user, provider) overrides
                                     (api_base / organization / extra headers)
  verification_code_service        — Redis-backed email verification codes
                                     with rate-limit + anti-abuse

The JWT revocation blacklist lives at ``app.core.token_blacklist`` — it is
consulted by ``core.security`` on every authenticated request, so keeping
it in core avoids a core→services dependency.

These were previously flat under ``app/services/`` alongside unrelated
domain services (resume, knowledge, etc.); P8-3 grouped them so the
auth surface is searchable in one place.
"""
