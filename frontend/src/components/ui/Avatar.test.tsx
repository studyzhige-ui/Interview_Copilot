import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Avatar } from './Avatar';

describe('Avatar', () => {
  it('falls back to the user initial when an image fails to load', () => {
    render(
      <Avatar
        src="https://example.invalid/avatar.png"
        name="蝶祈"
        alt="用户头像"
        className="w-8 h-8"
      />,
    );

    fireEvent.error(screen.getByRole('img', { name: '用户头像' }));

    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByLabelText('用户头像')).toHaveTextContent('蝶');
  });
});
