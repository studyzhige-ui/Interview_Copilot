import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AuthPage } from './AuthPage';

describe('AuthPage password recovery', () => {
  it('opens the reset form from login and returns to login', () => {
    render(
      <MemoryRouter>
        <AuthPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: '忘记密码？' }));
    expect(screen.getByText('重置密码', { selector: 'div' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('you@example.com')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /返回登录/ }));
    expect(screen.getByPlaceholderText('请输入用户名')).toBeInTheDocument();
  });
});
