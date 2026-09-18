import { fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from './AppShell';

vi.mock('./SideNav', () => ({ SideNav: () => null }));
vi.mock('./TopBar', () => ({ TopBar: () => null }));
vi.mock('./ClientActionBridge', () => ({ ClientActionBridge: () => null }));

describe('workspace scrolling', () => {
  it('starts a new page at the top without resetting same-page selection', () => {
    render(<MemoryRouter initialEntries={['/career-process']}><AppShell>
      <Link to="/mock">模拟面试</Link><Link to="/career-process?opportunity=next">选择岗位</Link>
    </AppShell></MemoryRouter>);
    const main = screen.getByRole('main');
    main.scrollTop = 400;
    fireEvent.click(screen.getByRole('link', { name: '选择岗位' }));
    expect(main.scrollTop).toBe(400);
    fireEvent.click(screen.getByRole('link', { name: '模拟面试' }));
    expect(main.scrollTop).toBe(0);
  });
});
