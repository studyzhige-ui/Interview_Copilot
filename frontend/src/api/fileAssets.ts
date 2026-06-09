import { apiClient } from './client';

// Unified presigned upload: reserve a file_assets row + PUT bytes to object
// storage + confirm. Mirrors backend/app/api/file_assets.py. Business endpoints
// then consume the confirmed file_asset_id. No server-receives-bytes path.

export async function createUploadUrl(payload: {
  purpose: string;
  filename: string;
  content_type?: string;
  size_bytes?: number;
}): Promise<{ file_asset_id: string; upload_url: string; storage_uri: string; filename: string }> {
  const res = await apiClient.post('/file-assets/upload-url', payload);
  return res.data;
}

// PUT raw bytes to the presigned URL (not via apiClient — different origin/credentials).
export async function putToPresignedUrl(uploadUrl: string, file: File): Promise<void> {
  const r = await fetch(uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
  });
  if (!r.ok) throw new Error(`Presigned upload failed: ${r.status}`);
}

export async function confirmUpload(fileAssetId: string): Promise<void> {
  await apiClient.post(`/file-assets/${encodeURIComponent(fileAssetId)}/confirm`);
}

/** One-shot: presigned-url → PUT → confirm. Returns the confirmed file_asset_id. */
export async function uploadFileAsset(file: File, purpose: string): Promise<string> {
  const presign = await createUploadUrl({
    purpose,
    filename: file.name,
    content_type: file.type || undefined,
    size_bytes: file.size,
  });
  await putToPresignedUrl(presign.upload_url, file);
  await confirmUpload(presign.file_asset_id);
  return presign.file_asset_id;
}
