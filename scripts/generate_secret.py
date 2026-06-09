#!/usr/bin/env python3
"""Generate a cryptographically secure SECRET_KEY value.

Why this script exists
----------------------
``SECRET_KEY`` is used for two things in this app:

  1. **JWT signing** (HS256) — every access/refresh token is signed with
     this key. Anyone who knows it can forge tokens for any user.
  2. **Fernet encryption** of user-stored third-party API keys — the
     ciphertexts live in the ``user_model_credentials`` table. Anyone who knows the
     key can decrypt all of them.

Because of (2), the key cannot be auto-rotated on every restart: changing
it would make every stored ciphertext unreadable. Treat key changes as
a deliberate rotation (use ``SECRET_KEYS_OLD`` for the grace period).

Usage
-----
::

    python scripts/generate_secret.py

Copy the printed line into your ``.env`` file. Never commit it.

When rotating
-------------
1. Move the current value into ``SECRET_KEYS_OLD`` (comma-separated if
   multiple).
2. Run this script and put the new value in ``SECRET_KEY``.
3. Restart the app. New tokens use the new key; old Fernet ciphertexts
   still decrypt via ``SECRET_KEYS_OLD``.
4. Once enough time has passed that no old tokens are in circulation and
   all stored ciphertexts have been lazily re-encrypted, drop the old
   value from ``SECRET_KEYS_OLD``.
"""

import secrets


def main() -> None:
    # 48 bytes → 64-char URL-safe string. Comfortably above HS256's 32-byte
    # minimum, and the same length the rest of the security-tooling
    # ecosystem prints.
    value = secrets.token_urlsafe(48)
    print(f"SECRET_KEY={value}")


if __name__ == "__main__":
    main()
