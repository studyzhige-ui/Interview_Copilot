import { apiClient } from './client';
import type { KnowledgeDoc, KnowledgeCategory } from '@/types/api';

export type KnowledgeSourceKind = 'user_upload' | 'improved_qa' | 'manual_text';

export interface ListKnowledgeQuery {
  category?: string;
  status?: string;
  source_kind?: KnowledgeSourceKind;
}

export async function listKnowledgeDocuments(
  q: ListKnowledgeQuery = {},
  opts: { signal?: AbortSignal } = {},
): Promise<KnowledgeDoc[]> {
  const res = await apiClient.get('/knowledge/documents', {
    params: q,
    signal: opts.signal,
  });
  return res.data?.documents ?? [];
}

export async function listKnowledgeCategories(
  opts: { signal?: AbortSignal } = {},
): Promise<KnowledgeCategory[]> {
  const res = await apiClient.get('/knowledge/categories', { signal: opts.signal });
  return res.data?.categories ?? [];
}

export async function getKnowledgeDocument(id: string): Promise<KnowledgeDoc> {
  const res = await apiClient.get(`/knowledge/documents/${encodeURIComponent(id)}`);
  return res.data?.document;
}

// Step 1: request a presigned upload URL (creates an Upload row, returns upload_id + upload_url).
export async function createKnowledgeUploadUrl(payload: {
  filename: string;
  content_type?: string;
  size_bytes?: number;
}): Promise<{ upload_id: string; upload_url: string; filename: string }> {
  const res = await apiClient.post('/knowledge/upload/url', payload);
  return res.data;
}

// Step 2: PUT the file bytes to the presigned URL (raw, not via apiClient — different origin/credentials).
export async function putToPresignedUrl(uploadUrl: string, file: File): Promise<void> {
  const r = await fetch(uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
  });
  if (!r.ok) throw new Error(`Presigned upload failed: ${r.status}`);
}

// Step 3: create KnowledgeDocument row referencing the consumed upload_id.
export async function createKnowledgeDocument(payload: {
  upload_id: string;
  title?: string;
  category?: string;
  source_kind?: KnowledgeSourceKind;
}): Promise<KnowledgeDoc> {
  const res = await apiClient.post('/knowledge/documents', payload);
  return res.data?.document;
}

export async function updateKnowledgeDocument(
  id: string,
  patch: { title?: string; category?: string },
): Promise<KnowledgeDoc> {
  const res = await apiClient.patch(`/knowledge/documents/${encodeURIComponent(id)}`, patch);
  return res.data?.document;
}

export async function deleteKnowledgeDocument(id: string): Promise<void> {
  await apiClient.delete(`/knowledge/documents/${encodeURIComponent(id)}`);
}

// One-shot helper: presigned-url → PUT → create-document.
export async function uploadKnowledgeFile(
  file: File,
  opts: { title?: string; category?: string; source_kind?: KnowledgeSourceKind } = {},
): Promise<KnowledgeDoc> {
  const presign = await createKnowledgeUploadUrl({
    filename: file.name,
    content_type: file.type || undefined,
    size_bytes: file.size,
  });
  await putToPresignedUrl(presign.upload_url, file);
  return createKnowledgeDocument({
    upload_id: presign.upload_id,
    title: opts.title ?? file.name,
    category: opts.category,
    source_kind: opts.source_kind,
  });
}
