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

export async function listResumes(): Promise<PersonalResume[]> {
  const res = await apiClient.get('/resumes');
  return res.data ?? [];
}

export async function createResume(payload: {
  file_asset_id?: string;
  title?: string;
  make_default?: boolean;
}): Promise<PersonalResume> {
  const res = await apiClient.post('/resumes', payload);
  return res.data;
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

export async function setDefaultResume(id: string): Promise<void> {
  await apiClient.post(`/resumes/${encodeURIComponent(id)}/set-default`);
}

export async function deleteResume(id: string): Promise<void> {
  await apiClient.delete(`/resumes/${encodeURIComponent(id)}`);
}
