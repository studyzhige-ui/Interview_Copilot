# Private file storage

The API and workers use `STORAGE_BACKEND=filesystem` by default. `STORAGE_DIR`
is their shared persistent object root; in the desktop Compose deployment it is
`/app/data/storage`. API/workers run in Linux containers (the filesystem adapter
uses `openat`/`O_NOFOLLOW`). The Windows desktop selects the enclosing persistent
workspace, not individual object locations.

`STORAGE_MIN_FREE_BYTES=67108864` is a free-disk reserve, **not an upload cap**.
The seven purpose limits remain in `purpose_registry.py`, including 500 MiB for
interview audio. Upload staging and atomic commit temporarily require space for
two copies. An interrupted transfer removes its staging file; disk exhaustion
returns HTTP 507 and the reservation remains retryable.

## Transfer contract

1. Authenticated `POST /api/v1/file-assets/upload-url` reserves an owned asset.
   Its response remains `{file_asset_id, upload_url, filename}`.
2. `PUT upload_url` streams the original bytes with the declared `Content-Type`.
   The URL is a short-lived, write-only capability; send no bearer credential.
   A successful transfer returns 204. The bytes are immutable, even before
   confirmation: retries after success return 409; clients can confirm instead.
3. Authenticated `POST /file-assets/{id}/confirm` verifies existence, actual size,
   and purpose-specific magic bytes. Domain commands then consume that identity.
4. Authenticated `GET|HEAD /file-assets/{id}/download` or an issued read capability
   supports byte ranges (206/416), with accurate length and private no-store
   caching. Documents and arbitrary types are attachment-only; only an explicit
   image/audio/video allowlist for avatar/audio purposes can render inline.

Capabilities are asset/owner/purpose/operation/URI bound. Read capabilities also
bind the stored checksum version. They are signed with a domain-separated key,
never accepted as login tokens, checked against active owner/token version and
current asset lifecycle, and become unusable after deletion. Legacy local
avatars without FileAsset rows use owner-bound revocable capabilities too.
There is no public static storage mount. Edge and application logs must redact
capability query strings; media responses send `Referrer-Policy: no-referrer`.

`GET /api/v1/file-assets/storage-usage` reports:

- `backend`: `filesystem` or `s3`
- `used_bytes`, `asset_count`: only the signed-in owner's confirmed, nondeleted
  uploaded/consumed assets (across persisted providers)
- `free_bytes`, `total_bytes`: filesystem device capacity when available, otherwise
  null; these are device-wide, not a user quota

No response exposes an absolute storage path or raw object key.

## Optional S3 and existing data

Set `STORAGE_BACKEND=s3` and the existing `AWS_*`/`S3_*` settings for a configured
S3-compatible service. Endpoint and credentials default to empty and are required
before any S3 client is initialized; missing configuration returns actionable
unavailability instead of probing localhost, cloud metadata, or a default AWS
endpoint. Uploads still pass through the bounded capability endpoint
and use conditional `If-None-Match: *` creation, so old upload URLs cannot mutate
confirmed content. The service must support conditional PutObject. S3 clients
are initialized only when needed; filesystem startup needs no MinIO service.

Reads/deletes dispatch using each row's persisted `local://` or `s3://` URI.
Changing the default affects new reservations only. Existing S3 records still
need their configured bucket/endpoint; an outage is surfaced, never silently
reinterpreted as local storage or replaced by a fallback write. No migration,
old MinIO volume removal, or live account/configuration change is performed.
Any migration of existing data is a separate explicit operation.
