"""Upload pipeline services.

  file_validation   — magic-byte validator for audio / resume / JD
                      uploads; streams large files via
                      SpooledTemporaryFile, enforces size caps
  upload_service    — create presigned upload URL + UserUpload row;
                      thin wrapper around storage_service

The shared boto3 wrapper ``storage_service`` lives at services/ root
(not here) because it has 8 cross-domain importers — auth uploads
avatar images, knowledge uploads documents, interview uploads audio,
and agent tools read/write arbitrary blobs. Putting it under uploads/
would imply it's specific to this pipeline, which it isn't.
"""
