import { apiClient } from './client';
import { putFileToPresignedUrl } from './presignedUpload';
import type { FileAssetDeletionImpact } from '@/types/api';

// Unified presigned upload: reserve a file_assets row + PUT bytes to object
// storage + confirm. Mirrors backend/app/api/file_assets.py. Business endpoints
// then consume the confirmed file_asset_id. No server-receives-bytes path.

async function createUploadUrl(payload: {
  purpose: string;
  filename: string;
  content_type?: string;
  size_bytes?: number;
}): Promise<{ file_asset_id: string; upload_url: string; filename: string }> {
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

export async function getFileAssetDeletionImpact(
  fileAssetId: string,
): Promise<FileAssetDeletionImpact> {
  return (
    await apiClient.get(`/file-assets/${encodeURIComponent(fileAssetId)}/deletion-impact`)
  ).data as FileAssetDeletionImpact;
}

export async function permanentlyDeleteFileAsset(
  impact: FileAssetDeletionImpact,
  confirmedFilename: string,
): Promise<void> {
  await apiClient.delete(
    `/file-assets/${encodeURIComponent(impact.file_asset_id)}/permanent`,
    {
      data: {
        confirmation_token: impact.confirmation_token,
        confirm_file_asset_id: impact.file_asset_id,
        confirm_filename: confirmedFilename,
      },
    },
  );
}

function filenameFromDisposition(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(value)?.[1];
  if (utf8) {
    try { return decodeURIComponent(utf8); } catch { return undefined; }
  }
  return /filename="?([^";]+)"?/i.exec(value)?.[1];
}

/** Read an owner-scoped FileAsset through the API and start a browser download. */
export async function downloadFileAsset(
  fileAssetId: string,
  fallbackFilename = 'artifact-download',
): Promise<void> {
  const response = await apiClient.get(
    `/file-assets/${encodeURIComponent(fileAssetId)}/download`,
    { responseType: 'blob' },
  );
  const objectUrl = URL.createObjectURL(response.data as Blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filenameFromDisposition(response.headers['content-disposition'])
    ?? fallbackFilename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  }
}
