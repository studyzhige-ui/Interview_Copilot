import { apiClient } from './client';
import { putFileToPresignedUrl } from './presignedUpload';

// Unified presigned upload: reserve a file_assets row + PUT bytes to object
// storage + confirm. Mirrors backend/app/api/file_assets.py. Business endpoints
// then consume the confirmed file_asset_id. No server-receives-bytes path.

async function createUploadUrl(payload: {
  purpose: string;
  filename: string;
  content_type?: string;
  size_bytes?: number;
}): Promise<{ file_asset_id: string; upload_url: string; storage_uri: string; filename: string }> {
  const res = await apiClient.post('/file-assets/upload-url', payload);
  return res.data;
}

async function confirmUpload(fileAssetId: string): Promise<void> {
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
  await putFileToPresignedUrl(presign.upload_url, file);
  await confirmUpload(presign.file_asset_id);
  return presign.file_asset_id;
}
