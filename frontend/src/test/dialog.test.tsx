import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { expect, it } from 'vitest';
import { Modal } from '@/components/ui/Modal';

function NestedDialogs() {
  const [outer, setOuter] = useState(true);
  const [inner, setInner] = useState(false);
  return <><button>背景按钮</button><Modal open={outer} onClose={() => setOuter(false)} title="父层">
    <button onClick={() => setInner(true)}>打开子层</button>
    <Modal open={inner} onClose={() => setInner(false)} title="子层"><button>确认</button></Modal>
  </Modal></>;
}

it('Escape closes only the current dialog and keeps background locked until the final close', () => {
  const { container } = render(<NestedDialogs />);
  fireEvent.click(screen.getByText('打开子层'));
  expect(screen.getByRole('dialog', { name: '子层' })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog', { name: '子层' })).not.toBeInTheDocument();
  expect(screen.getByRole('dialog', { name: '父层' })).toBeInTheDocument();
  expect(container).toHaveAttribute('aria-hidden', 'true');
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(container).not.toHaveAttribute('aria-hidden');
});
