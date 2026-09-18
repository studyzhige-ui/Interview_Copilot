import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { LibraryPage } from './LibraryPage';

vi.mock('@/api/knowledge', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/knowledge')>(),
  listKnowledgeDocuments: vi.fn().mockResolvedValue([]),
  listKnowledgeCategories: vi.fn(() => new Promise(() => {})),
}));

it('shows the document list even when categories have not returned', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><LibraryPage /></QueryClientProvider></MemoryRouter>);
  expect(await screen.findByText('资料库还是空的')).toBeInTheDocument();
});
