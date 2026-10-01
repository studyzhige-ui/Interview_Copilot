"""Short-lived, single-asset capabilities; never valid as login credentials."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from urllib.parse import quote

import jwt

from app.core.config import settings


def _key():
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY is required for private file access")
    return hmac.new(
        settings.SECRET_KEY.encode(), b"copilot:file-capability:v1", hashlib.sha256
    ).digest()


def asset_url(asset, *, owner, operation: str, expiration=600):
    token = jwt.encode(
        {
            "aud": "file-asset",
            "op": operation,
            "asset": asset.id,
            "owner": asset.user_id,
            "purpose": asset.purpose,
            "tv": owner.token_version,
            "version": (asset.checksum_sha256 or "") if operation == "read" else "",
            "uri": hashlib.sha256(asset.storage_uri.encode()).hexdigest(),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=expiration),
        },
        _key(),
        algorithm="HS256",
    )
    return f"/api/v1/file-assets/{quote(asset.id, safe='')}/content?token={token}"


def decode_capability(token, *, operation):
    claims = jwt.decode(
        token,
        _key(),
        algorithms=["HS256"],
        audience="file-asset",
        options={
            "require": [
                "exp",
                "aud",
                "op",
                "asset",
                "owner",
                "purpose",
                "uri",
                "tv",
                "version",
            ]
        },
    )
    if claims["op"] != operation:
        raise ValueError("Wrong capability operation")
    return claims


def matches_asset(claims, asset):
    return (
        claims["asset"] == asset.id
        and claims["owner"] == asset.user_id
        and claims["purpose"] == asset.purpose
        and (
            claims["op"] != "read" or claims["version"] == (asset.checksum_sha256 or "")
        )
        and hmac.compare_digest(
            claims["uri"], hashlib.sha256(asset.storage_uri.encode()).hexdigest()
        )
    )


def legacy_avatar_asset(user):
    from types import SimpleNamespace
    import mimetypes

    return SimpleNamespace(
        id=f"legacy-avatar-{user.id}",
        user_id=user.id,
        purpose="avatar",
        storage_uri=user.avatar_url,
        checksum_sha256=None,
        original_filename=user.avatar_url.rsplit("/", 1)[-1],
        content_type=mimetypes.guess_type(user.avatar_url)[0]
        or "application/octet-stream",
        upload_status="consumed",
        validation_status="passed",
    )
