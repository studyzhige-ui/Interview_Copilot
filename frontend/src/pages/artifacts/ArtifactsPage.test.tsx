import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ArtifactsPage } from './ArtifactsPage';
import {
  getArtifact,
  listArtifactRelations,
  listArtifactSubmissions,
  listArtifactVersions,
  listArtifacts,
  recordArtifactSubmission,
  relateArtifactToOpportunity,
} from '@/api/artifacts';
import { listJobOpportunities } from '@/api/careerProcess';
import { downloadFileAsset } from '@/api/fileAssets';

vi.mock('@/api/artifacts', () => ({
  archiveArtifact: vi.fn(), createArtifact: vi.fn(), createArtifactVersion: vi.fn(),
  getArtifact: vi.fn(), listArtifactRelations: vi.fn(), listArtifactSubmissions: vi.fn(),
  listArtifactVersions: vi.fn(), listArtifacts: vi.fn(), recordArtifactSubmission: vi.fn(),
  relateArtifactToOpportunity: vi.fn(),
}));
vi.mock('@/api/careerProcess', () => ({ listJobOpportunities: vi.fn() }));
vi.mock('@/api/fileAssets', () => ({ downloadFileAsset: vi.fn() }));

const currentVersion = {
  id: 'version-2', artifact_id: 'artifact-1', version_no: 2,
  title: '后端工程师简历', content_text: '当前内容', content_format: 'markdown',
  file_asset_id: null, file_asset_version: null, origin_kind: 'edit' as const,
  source_message_id: null, source_turn_id: null,
  source_owner_type: null, source_owner_id: null, created_at: '2026-08-13T10:00:00Z',
};
const submittedVersion = {
  ...currentVersion, id: 'version-1', version_no: 1, title: '投递版简历',
  content_text: '投递时被冻结的内容', origin_kind: 'explicit_save' as const,
  created_at: '2026-08-10T10:00:00Z',
};
const artifact = {
  id: 'artifact-1', kind: 'resume', archived_at: null, current_version: currentVersion,
};
const opportunities = [
  { id: 'job-1', user_id: 1, company_name: '甲公司', job_title: '后端工程师', location: '上海', team: null, source_url: null, source_provider: null, external_job_id: null, external_application_id: null, phase: 'applied' as const, current_step: '已投递', outcome: null, archived_at: null, last_event_at: null, direction_version: 0, direction_links: [], created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' },
  { id: 'job-2', user_id: 1, company_name: '乙公司', job_title: '平台工程师', location: null, team: null, source_url: null, source_provider: null, external_job_id: null, external_application_id: null, phase: 'pending_application' as const, current_step: '待投递', outcome: null, archived_at: null, last_event_at: null, direction_version: 0, direction_links: [], created_at: '2026-08-02T00:00:00Z', updated_at: '2026-08-02T00:00:00Z' },
];

describe('ArtifactsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listArtifacts).mockResolvedValue([artifact]);
    vi.mocked(getArtifact).mockResolvedValue(artifact);
    vi.mocked(listArtifactVersions).mockResolvedValue([currentVersion, submittedVersion]);
    vi.mocked(listArtifactRelations).mockResolvedValue([{
      id: 'relation-1', artifact_id: 'artifact-1', job_opportunity_id: 'job-1',
      created_at: '2026-08-11T00:00:00Z',
    }]);
    vi.mocked(listArtifactSubmissions).mockResolvedValue([{
      id: 'submission-1', artifact_id: 'artifact-1', artifact_version_id: 'version-1',
      job_opportunity_id: 'job-1', basis: 'user_confirmation', confirmation_message_id: 9,
      receipt_owner_type: null, receipt_owner_id: null, submitted_at: '2026-08-12T00:00:00Z',
      submitted_version: submittedVersion,
    }]);
    vi.mocked(listJobOpportunities).mockResolvedValue(opportunities);
    vi.mocked(relateArtifactToOpportunity).mockResolvedValue({
      id: 'relation-2', artifact_id: 'artifact-1', job_opportunity_id: 'job-2',
      created_at: '2026-08-13T00:00:00Z',
    });
    vi.mocked(recordArtifactSubmission).mockResolvedValue({
      id: 'submission-2', artifact_id: 'artifact-1', artifact_version_id: 'version-2',
      job_opportunity_id: 'job-2', basis: 'product_ui_confirmation',
      confirmation_message_id: null, receipt_owner_type: null, receipt_owner_id: null,
      submitted_at: '2026-08-13T12:00:00Z', submitted_version: currentVersion,
    });
    vi.mocked(downloadFileAsset).mockResolvedValue();
  });

  it('renders the cloud-backed Artifact list across page loads', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter initialEntries={['/artifacts']}>
        <QueryClientProvider client={client}>
          <Routes><Route path="/artifacts/:artifactId?" element={<ArtifactsPage />} /></Routes>
        </QueryClientProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText('后端工程师简历')).toBeInTheDocument();
    expect(screen.getByText('v2')).toBeInTheDocument();
    expect(listArtifacts).toHaveBeenCalledWith(false);
  });

  it('shows exact frozen submission content and relates through a JobOpportunity selector', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter initialEntries={['/artifacts/artifact-1']}>
        <QueryClientProvider client={client}>
          <Routes><Route path="/artifacts/:artifactId?" element={<ArtifactsPage />} /></Routes>
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('投递时被冻结的内容')).toBeInTheDocument();
    expect(screen.getByText('投递时 v1')).toBeInTheDocument();
    expect(screen.getAllByText(/甲公司 · 后端工程师/).length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: /询问 Copilot/ })).toHaveAttribute(
      'href',
      expect.stringContaining('object_kind=artifact&object_id=artifact-1'),
    );

    fireEvent.click(screen.getByRole('button', { name: '关联岗位' }));
    fireEvent.change(screen.getByRole('combobox', { name: '关联岗位机会' }), {
      target: { value: 'job-2' },
    });
    fireEvent.click(screen.getByRole('button', { name: '关联' }));
    await waitFor(() => expect(relateArtifactToOpportunity).toHaveBeenCalledWith(
      'artifact-1', 'job-2',
    ));
  });

  it('records the currently viewed immutable version through an explicit UI command', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter initialEntries={['/artifacts/artifact-1']}>
        <QueryClientProvider client={client}>
          <Routes><Route path="/artifacts/:artifactId?" element={<ArtifactsPage />} /></Routes>
        </QueryClientProvider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: /v1 · 投递版简历/ }));
    fireEvent.click(screen.getByRole('button', { name: '确认已投递当前查看版本' }));
    expect(screen.getByText(/将冻结 v1/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: '关联岗位机会' }), {
      target: { value: 'job-2' },
    });
    fireEvent.click(screen.getByRole('button', { name: '确认已投递' }));

    await waitFor(() => expect(recordArtifactSubmission).toHaveBeenCalledWith(
      expect.objectContaining({
        artifactId: 'artifact-1', artifactVersionId: 'version-1', jobOpportunityId: 'job-2',
      }),
    ));
  });

  it('downloads the exact file-backed version through the owner-scoped API', async () => {
    const fileVersion = {
      ...currentVersion,
      file_asset_id: 'fa-export-1',
      content_text: null,
    };
    vi.mocked(getArtifact).mockResolvedValue({ ...artifact, current_version: fileVersion });
    vi.mocked(listArtifactVersions).mockResolvedValue([fileVersion]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter initialEntries={['/artifacts/artifact-1']}>
        <QueryClientProvider client={client}>
          <Routes><Route path="/artifacts/:artifactId?" element={<ArtifactsPage />} /></Routes>
        </QueryClientProvider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '下载文件' }));

    await waitFor(() => expect(downloadFileAsset).toHaveBeenCalledWith(
      'fa-export-1', '后端工程师简历',
    ));
  });
});
