"""Upload pipeline services.

  file_validation   — magic-byte validator for audio / resume / JD
                      uploads; streams large files via
                      SpooledTemporaryFile, enforces size caps
  file_asset_service — create presigned upload URL + FileAsset row,
                      confirm/consume lifecycle; thin wrapper around
                      app.core.storage
  outbox_service    — reliable cross-system side effects (object cleanup,
                      Milvus index maintenance) drained by the worker

The shared boto3 wrapper lives at ``app.core.storage`` (not here)
because it has 8 cross-domain importers — auth uploads avatar images,
knowledge uploads documents, interview uploads audio, and agent tools
read/write arbitrary blobs. Putting it under uploads/ would imply it's
specific to this pipeline, which it isn't.
"""
