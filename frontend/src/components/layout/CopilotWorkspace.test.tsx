import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { CopilotWorkspace, referenceForPage } from './CopilotWorkspace';
vi.mock('@/pages/chat/GeneralChatPage', () => ({ GeneralChatPage: ({ objectReference }: { objectReference: unknown }) =>
  <div data-testid="shared-conversation">{JSON.stringify(objectReference)}</div> }));
function Host() {
  const location = useLocation();
  return <CopilotWorkspace>{(open) => <><p>{location.pathname + location.search}</p>
    <button onClick={open}>打开页面助手</button></>}</CopilotWorkspace>;
}
describe('product-hosted Copilot', () => {
  it('keeps the product route and explicitly attaches only the selected object', async () => {
    render(<MemoryRouter initialEntries={['/career-process?opportunity=job-1&filter=active']}><Host /></MemoryRouter>);
    fireEvent.click(screen.getByText('打开页面助手'));
    expect(await screen.findByTestId('shared-conversation')).toHaveTextContent('job_opportunity');
    expect(screen.getByText('/career-process?opportunity=job-1&filter=active')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '关闭 Copilot' }));
    expect(screen.queryByTestId('shared-conversation')).not.toBeInTheDocument();
    expect(screen.getByText('/career-process?opportunity=job-1&filter=active')).toBeInTheDocument();
  });
  it('never scrapes pages or admits oversized route references', () => {
    expect(referenceForPage('/library', '?private=text')).toBeNull();
    expect(referenceForPage('/career-process', '?opportunity=' + 'x'.repeat(129))).toBeNull();
    expect(referenceForPage('/review', '?id=review-1')).toEqual({ kind: 'interview_record', object_id: 'review-1' });
  });
});
