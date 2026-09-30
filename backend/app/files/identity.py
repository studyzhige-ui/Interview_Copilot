"""Pure immutable file-reference identity, shared without application side effects."""

from app.models.file_asset import FileAsset


def file_asset_version_token(asset: FileAsset) -> str:
    """Byte digest when recorded; otherwise an explicitly unverified asset identity."""
    checksum = (asset.checksum_sha256 or "").strip().lower()
    return f"sha256:{checksum}" if checksum else f"file_asset:{asset.id}"
