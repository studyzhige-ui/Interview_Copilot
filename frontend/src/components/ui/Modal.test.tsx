import { useState } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Modal } from './Modal';

afterEach(cleanup);
function Demo() {
  const [open, setOpen] = useState(false);
  const [nested, setNested] = useState(false);
  const [count, setCount] = useState(0);
  return <><button onClick={() => setOpen(true)}>打开编辑器</button>
    <Modal open={open} onClose={() => setOpen(false)} title="编辑器">
      <input autoFocus aria-label="名称" />
      <button onClick={() => setCount(count + 1)}>更改 {count}</button>
      <button onClick={() => setNested(true)}>打开子窗口</button>
      <Modal open={nested} onClose={() => setNested(false)} title="子窗口"><input aria-label="子输入" /></Modal>
    </Modal></>;
}
function openDemo() {
  const result = render(<Demo />);
  const trigger = screen.getByRole('button', { name: '打开编辑器' });
  trigger.focus();
  fireEvent.click(trigger);
  return { ...result, trigger };
}
it('names the dialog, preserves autofocus, isolates background and restores its opener', () => {
  const { container, trigger } = openDemo();
  expect(screen.getByRole('dialog', { name: '编辑器' })).toHaveAttribute('aria-modal', 'true');
  expect(screen.getByRole('textbox', { name: '名称' })).toHaveFocus();
  expect(container).toHaveAttribute('aria-hidden', 'true');
  expect(container.inert).toBe(true);
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  expect(container).not.toHaveAttribute('aria-hidden');
  expect(container.inert).not.toBe(true);
});
it('wraps Tab in both directions and guards programmatic background focus', () => {
  const { trigger } = openDemo();
  const dialog = screen.getByRole('dialog', { name: '编辑器' });
  const first = within(dialog).getByRole('button', { name: '关闭' });
  const last = screen.getByRole('button', { name: '打开子窗口' });
  last.focus();
  fireEvent.keyDown(last, { key: 'Tab' });
  expect(first).toHaveFocus();
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true });
  expect(last).toHaveFocus();
  trigger.focus();
  expect(first).toHaveFocus();
});
it('only closes the top dialog and returns focus to its parent without unlocking the page', () => {
  openDemo();
  const parentTrigger = screen.getByRole('button', { name: '打开子窗口' });
  parentTrigger.focus();
  fireEvent.click(parentTrigger);
  expect(screen.getByRole('dialog', { name: '子窗口' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog', { name: '编辑器' })).not.toBeInTheDocument();
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
  expect(screen.queryByRole('dialog', { name: '子窗口' })).not.toBeInTheDocument();
  expect(screen.getByRole('dialog', { name: '编辑器' })).toBeInTheDocument();
  expect(parentTrigger).toHaveFocus();
  expect(document.body.style.overflow).toBe('hidden');
});
it('does not reset focus on ordinary rerenders and restores scroll on cleanup', () => {
  document.body.style.overflow = 'scroll';
  const { unmount } = openDemo();
  const control = screen.getByRole('button', { name: '更改 0' });
  control.focus();
  fireEvent.click(control);
  expect(screen.getByRole('button', { name: '更改 1' })).toHaveFocus();
  unmount();
  expect(document.body.style.overflow).toBe('scroll');
  document.body.style.overflow = '';
});
it('does not dismiss on content clicks and supplies a fallback accessible name', () => {
  const close = vi.fn();
  render(<Modal open onClose={close}><button>内容</button></Modal>);
  fireEvent.click(screen.getByRole('button', { name: '内容' }));
  expect(close).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('dialog', { name: '对话框' }).parentElement!);
  expect(close).toHaveBeenCalledTimes(1);
});

it('skips disabled controls and CSS-hidden panels when wrapping focus', () => {
  render(<Modal open onClose={() => {}} title="表单"><button disabled>禁用</button><button>最后操作</button><div style={{ display: 'none' }}><input aria-label="隐藏输入" /></div></Modal>);
  const last = screen.getByRole('button', { name: '最后操作' });
  last.focus();
  fireEvent.keyDown(last, { key: 'Tab' });
  expect(screen.getByRole('button', { name: '关闭' })).toHaveFocus();
});
