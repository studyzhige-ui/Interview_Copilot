import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CareerProfilePage } from '@/pages/career/CareerProfilePage';
import { getCareerProfile, savePersonalFact } from '@/api/careerProfile';
import { createResumeFromFile } from '@/api/resumes';
import type { CareerProfile } from '@/types/career';

vi.mock('@/api/careerProfile', () => ({
  getCareerProfile: vi.fn(), savePersonalFact: vi.fn(),
  listCareerProfileDrafts: vi.fn().mockResolvedValue([]), removePersonalFact: vi.fn(),
  resolveCareerProfileCandidates: vi.fn(), saveCareerDirection: vi.fn(), setCareerDirectionLifecycle: vi.fn(),
}));
vi.mock('@/api/resumes', () => ({ listResumes: vi.fn().mockResolvedValue([]), createResumeFromFile: vi.fn() }));

const profile: CareerProfile = { id: 'cp_fixture', user_id: 1, version: 1,
  personal_facts: [], directions: [], created_at: '2030-01-01', updated_at: '2030-01-01' };
afterEach(() => vi.unstubAllGlobals());
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getCareerProfile).mockResolvedValue(profile);
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} });
  Element.prototype.scrollIntoView = vi.fn();
});
function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><CareerProfilePage /></MemoryRouter></QueryClientProvider>);
}

it('shows a continuous resume and edits personal information in its section', async () => {
  show();
  await screen.findByRole('heading', { name: '个人经历档案' });
  expect(screen.queryByRole('button', { name: '导出 PDF' })).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: '打开简历与材料 ↗' })).toHaveAttribute('href', '/artifacts');
  for (const name of ['个人优势', '期望职位', '项目经历', '教育经历', '资格证书', '志愿者经历', '专业技能']) {
    expect(screen.getByRole('heading', { name })).toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole('button', { name: '编辑个人信息' }));
  const form = screen.getByRole('form', { name: '编辑个人信息' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText('姓名'), { target: { value: '合成候选人' } });
  fireEvent.change(within(form).getByLabelText('当前状态'), { target: { value: '应届毕业生' } });
  vi.mocked(savePersonalFact).mockResolvedValue(profile);
  fireEvent.click(within(form).getByRole('button', { name: '保存' }));
  await waitFor(() => expect(savePersonalFact).toHaveBeenCalledWith(expect.objectContaining({
    profileVersion: 1, fact: expect.objectContaining({ kind: 'personal', name: '合成候选人', career_status: '应届毕业生' }),
  })));
  await waitFor(() => expect(screen.queryByRole('form')).not.toBeInTheDocument());
});

it('imports through the canonical resume command without changing confirmed facts', async () => {
  show();
  await screen.findByRole('heading', { name: '个人经历档案' });
  const file = new File(['synthetic resume'], 'synthetic.txt', { type: 'text/plain' });
  fireEvent.change(screen.getByLabelText('选择导入的简历'), { target: { files: [file] } });
  await waitFor(() => expect(createResumeFromFile).toHaveBeenCalledWith(file, { make_default: true }));
  expect(savePersonalFact).not.toHaveBeenCalled();
});
