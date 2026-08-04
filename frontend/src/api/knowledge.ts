import { apiClient } from './client';
import { putFileToPresignedUrl } from './presignedUpload';
import type { KnowledgeDoc, KnowledgeCategory } from '@/types/api';

export type KnowledgeSourceKind = 'user_upload' | 'improved_qa' | 'manual_text';

/**
 * ``accept`` hint for knowledge-document file inputs — UX only; the backend
 * ``POST /knowledge/documents`` whitelist (services/knowledge/document_formats.py)
 * is the authoritative gate. Keep in sync with ALLOWED_KNOWLEDGE_EXTENSIONS.
 * Images OCR via Docling/LlamaParse; legacy Office (.doc/.ppt/.xls) parses via
 * LlamaParse or a server-side LibreOffice conversion (friendly error if neither).
 */
export const KNOWLEDGE_ACCEPT =
  '.pdf,.docx,.pptx,.xlsx,.html,.htm,.md,.markdown,.txt,.csv,.tsv,.json,.py,.java,.cpp,.c,.png,.jpg,.jpeg,.tiff,.bmp,.webp,.doc,.ppt,.xls';

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

// Request a presigned upload URL (creates an Upload row, returns upload_id + upload_url).
async function createKnowledgeUploadUrl(payload: {
  filename: string;
  content_type?: string;
  size_bytes?: number;
}): Promise<{ upload_id: string; upload_url: string; filename: string }> {
  const res = await apiClient.post('/knowledge/upload/url', payload);
  return res.data;
}

// Create a KnowledgeDocument row referencing the consumed upload_id.
async function createKnowledgeDocument(payload: {
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
  await putFileToPresignedUrl(presign.upload_url, file);
  return createKnowledgeDocument({
    upload_id: presign.upload_id,
    title: opts.title ?? file.name,
    category: opts.category,
    source_kind: opts.source_kind,
  });
}
