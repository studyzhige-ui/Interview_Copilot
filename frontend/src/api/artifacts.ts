import { apiClient } from './client';
import type {
  Artifact,
  ArtifactRelation,
  ArtifactSubmission,
  ArtifactVersion,
  ArtifactWriteInput,
} from '@/types/career';

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

export async function getArtifact(artifactId: string): Promise<Artifact> {
  return (await apiClient.get(`/artifacts/${encodeURIComponent(artifactId)}`)).data;
}

export async function listArtifactVersions(artifactId: string): Promise<ArtifactVersion[]> {
  return (await apiClient.get(`/artifacts/${encodeURIComponent(artifactId)}/versions`)).data;
}

export async function listArtifactRelations(artifactId: string): Promise<ArtifactRelation[]> {
  return (await apiClient.get(`/artifacts/${encodeURIComponent(artifactId)}/related`)).data;
}

export async function listArtifactSubmissions(artifactId: string): Promise<ArtifactSubmission[]> {
  return (await apiClient.get(`/artifacts/${encodeURIComponent(artifactId)}/submissions`)).data;
}

export async function createArtifactVersion(input: {
  artifactId: string;
  operationKey: string;
  version: ArtifactWriteInput;
}): Promise<Artifact> {
  return (
    await apiClient.post(`/artifacts/${encodeURIComponent(input.artifactId)}/versions`, {
      operation_key: input.operationKey,
      version: input.version,
    })
  ).data;
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
