import { apiClient } from './client';
import { uploadFileAsset } from './fileAssets';

// The first-class personal ``resumes`` entity (at most two active, one default).
// Mirrors backend/app/api/resumes.py. Resumes are a personal-profile asset —
// they never enter the knowledge base.

export interface PersonalResume {
  id: string;
  title: string;
  is_default: boolean;
  parse_status: string;
  file_asset_id: string | null;
  has_text: boolean;
  created_at: string;
  updated_at: string;
}

async function createResume(payload: {
  file_asset_id?: string;
  title?: string;
  make_default?: boolean;
}): Promise<PersonalResume> {
  const res = await apiClient.post('/resumes', payload);
  return res.data;
}

export async function listResumes(
  opts: { signal?: AbortSignal } = {},
): Promise<PersonalResume[]> {
  const res = await apiClient.get('/resumes', { signal: opts.signal });
  return res.data;
}

export async function waitForResumeUsable(
  id: string,
  opts: { timeoutMs?: number; pollMs?: number } = {},
): Promise<PersonalResume> {
  const timeoutMs = opts.timeoutMs ?? 90_000;
  const pollMs = opts.pollMs ?? 1_500;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const resume = (await listResumes()).find((item) => item.id === id);
    if (!resume) throw new Error('简历不存在');
    if (resume.has_text || resume.parse_status === 'ready') return resume;
    if (resume.parse_status === 'failed') throw new Error('简历解析失败');
    await new Promise((resolve) => window.setTimeout(resolve, pollMs));
  }
  throw new Error('简历解析超时');
}

/** Upload a file as a NEW personal resume entity. Returns the resume (parsing
 *  into sections happens asynchronously server-side). May 409 if the user
 *  already has two active resumes. */
export async function createResumeFromFile(
  file: File,
  opts: { title?: string; make_default?: boolean } = {},
): Promise<PersonalResume> {
  const fileAssetId = await uploadFileAsset(file, 'resume');
  return createResume({
    file_asset_id: fileAssetId,
    title: opts.title ?? file.name,
    make_default: opts.make_default,
  });
}

/** Replace one resume without briefly exceeding the two-resume limit. */
export async function replaceResumeFromFile(
  id: string,
  file: File,
  opts: { title?: string } = {},
): Promise<PersonalResume> {
  const fileAssetId = await uploadFileAsset(file, 'resume');
  const res = await apiClient.post(`/resumes/${encodeURIComponent(id)}/replace`, {
    file_asset_id: fileAssetId,
    title: opts.title ?? file.name,
  });
  return res.data;
}

export async function setDefaultResume(id: string): Promise<PersonalResume> {
  const res = await apiClient.post(`/resumes/${encodeURIComponent(id)}/set-default`);
  return res.data;
}

export async function deleteResume(id: string): Promise<void> {
  await apiClient.delete(`/resumes/${encodeURIComponent(id)}`);
}
