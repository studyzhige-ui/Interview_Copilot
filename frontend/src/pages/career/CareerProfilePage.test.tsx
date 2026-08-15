import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CareerProfilePage } from './CareerProfilePage';
import {
  getCareerProfile,
  listCareerProfileDrafts,
} from '@/api/careerProfile';

vi.mock('@/api/careerProfile', () => ({
  getCareerProfile: vi.fn(), listCareerProfileDrafts: vi.fn(),
  removePersonalFact: vi.fn(), resolveCareerProfileDraft: vi.fn(), resolveCareerProfileCandidates: vi.fn(),
  saveCareerDirection: vi.fn(), savePersonalFact: vi.fn(), setCareerDirectionLifecycle: vi.fn(),
}));

describe('CareerProfilePage', () => {
  beforeEach(() => {
    vi.mocked(getCareerProfile).mockResolvedValue({
      id: 'profile-1', user_id: 1, version: 2,
      personal_facts: [{
        id: 'fact-1', value: { kind: 'skill', name: 'Python', category: '编程语言' },
        confirmed_source_kind: 'user_edit', confirmed_source_id: null, confirmed_at: '2026-08-13T10:00:00Z',
      }],
      directions: [{
        id: 'direction-1', label: 'AI 工程师', lifecycle: 'active', priority: 1,
        criteria: { role_keywords: ['Agent'], seniority: [], locations: ['上海'], work_modes: ['hybrid'], salary_min: null, salary_max: null, salary_currency: null, industries: [], technologies: ['Python'], exclusions: [] },
        confirmed_source_kind: 'user_edit', confirmed_source_id: null, confirmed_at: '2026-08-13T10:00:00Z',
      }], created_at: '2026-08-13T10:00:00Z', updated_at: '2026-08-13T10:00:00Z',
    });
    vi.mocked(listCareerProfileDrafts).mockResolvedValue([{
      id: 'draft-1', career_profile_id: 'profile-1', source_kind: 'resume', source_id: 'resume-1',
      base_profile_version: 2, proposed_facts: [{ operation: 'upsert', fact: { kind: 'location', value: '上海' } }],
      proposed_directions: [], status: 'pending', resolution_note: null, version: 1,
      created_at: '2026-08-13T10:00:00Z', resolved_at: null,
    }]);
  });

  it('keeps confirmed facts and pending candidates visibly separate while providing link to growth', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<MemoryRouter><QueryClientProvider client={client}><CareerProfilePage /></QueryClientProvider></MemoryRouter>);
    expect(await screen.findByText('Python')).toBeInTheDocument();
    expect(screen.getByText('待你确认的档案更新')).toBeInTheDocument();
    expect(screen.getByText('AI 工程师')).toBeInTheDocument();
    expect(screen.getByText(/持续化成长与能力演进/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /查看我的成长图谱 ➔/ })).toBeInTheDocument();
    const handoffs = screen.getAllByRole('link', { name: /询问 Copilot/ });
    expect(handoffs.map((link) => link.getAttribute('href'))).toEqual(expect.arrayContaining([
      expect.stringContaining('object_kind=career_profile&object_id=profile-1'),
      expect.stringContaining('object_kind=career_profile_direction&object_id=direction-1'),
    ]));
  });
});
