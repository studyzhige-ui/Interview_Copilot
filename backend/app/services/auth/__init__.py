"""Auth / credential services.

Bundles the 5 services that own user authentication + per-user
secret material:

  email_service                    — SMTP delivery (verification codes, etc.)
  token_blacklist_service          — JWT revocation via Redis (read on every authed request)
  user_api_key_service             — encrypted at-rest per-(user, provider) LLM API keys
  user_provider_settings_service   — non-secret per-(user, provider) overrides
                                     (api_base / organization / extra headers)
  verification_code_service        — Redis-backed email verification codes
                                     with rate-limit + anti-abuse

These were previously flat under ``app/services/`` alongside unrelated
domain services (resume, knowledge, etc.); P8-3 grouped them so the
auth surface is searchable in one place.
"""
