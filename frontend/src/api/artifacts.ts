import { apiClient } from './client';
import type {
  Artifact,
  ArtifactRelation,
  ArtifactVersion,
  ArtifactWriteInput,
} from '@/types/career';

export async function listAllArtifacts(includeArchived = false): Promise<Artifact[]> {
  const all: Artifact[] = [];
  for (let offset = 0; ; offset += 100) {
    const rows = await listArtifacts(includeArchived, 100, offset);
    all.push(...rows);
    if (rows.length < 100) return all;
  }
}

export async function listArtifacts(
  includeArchived = false,
  limit = 100,
  offset = 0,
): Promise<Artifact[]> {
  return (
    await apiClient.get('/artifacts', {
      params: { include_archived: includeArchived, limit, offset },
    })
  ).data;
}

export async function createArtifact(input: {
  operationKey: string;
  kind: string;
  version: ArtifactWriteInput;
}): Promise<Artifact> {
  return (
    await apiClient.post('/artifacts', {
      operation_key: input.operationKey,
      artifact_kind: input.kind,
      version: input.version,
    })
  ).data;
}

export async function listArtifactVersions(artifactId: string): Promise<ArtifactVersion[]> {
  return (await apiClient.get(`/artifacts/${encodeURIComponent(artifactId)}/versions`)).data;
}

export async function archiveArtifact(artifactId: string): Promise<Artifact> {
  return (await apiClient.post(`/artifacts/${encodeURIComponent(artifactId)}/archive`)).data;
}

export async function relateArtifactToOpportunity(
  artifactId: string,
  jobOpportunityId: string,
): Promise<ArtifactRelation> {
  return (await apiClient.post(`/artifacts/${encodeURIComponent(artifactId)}/related`, {
    job_opportunity_id: jobOpportunityId,
  })).data;
}

export async function restoreArtifact(artifactId: string): Promise<Artifact> { return (await apiClient.post<Artifact>(`/artifacts/${encodeURIComponent(artifactId)}/restore`)).data; }
