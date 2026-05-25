import { useCallback, useEffect, useRef } from 'react';

interface ResizerProps {
  /** Current width in px. */
  value: number;
  /** Update target width (called continuously while dragging). */
  onChange: (next: number) => void;
  /** Allowed bounds in px. */
  min?: number;
  max?: number;
  /** "left" means the handle is on the right edge of a panel and drag-right grows the panel. */
  direction?: 'left' | 'right';
  /** Read the current reference width from a parent element instead of using `value` for delta math. */
  anchorRef?: React.RefObject<HTMLElement>;
}

/**
 * Thin vertical drag handle. Place between two flex children. Width = 6px,
 * highlights on hover, captures pointer events while dragging.
 */
export function Resizer({
  value,
  onChange,
  min = 180,
  max = 800,
  direction = 'right',
  anchorRef,
}: ResizerProps) {
  const startXRef = useRef<number>(0);
  const startValRef = useRef<number>(0);
  const draggingRef = useRef<boolean>(false);

  const onMouseMove = useCallback((e: MouseEvent) => {
    if (!draggingRef.current) return;
    const delta = e.clientX - startXRef.current;
    const baseline = anchorRef?.current
      ? anchorRef.current.getBoundingClientRect().width
      : startValRef.current;
    const next = direction === 'right'
      ? Math.max(min, Math.min(max, baseline + delta))
      : Math.max(min, Math.min(max, baseline - delta));
    onChange(next);
  }, [direction, min, max, onChange, anchorRef]);

  // Window listeners are only attached during a drag — pre-fix
  // every Resizer instance held a permanent mousemove listener for
  // the page's lifetime, doing nothing 99% of the time. Multiple
  // Resizer instances on the same page (review's left+right panels)
  // each fired their no-op listener on every mousemove. Lazy attach
  // costs one extra event per drag (mousedown) but removes the
  // continuous-listener cost.
  const detachRef = useRef<(() => void) | null>(null);
  const onMouseUp = useCallback(() => {
    draggingRef.current = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    detachRef.current?.();
    detachRef.current = null;
  }, []);

  // Tear down on unmount in case the user releases focus mid-drag
  // (e.g. tab switch) so we don't leak listeners.
  useEffect(() => {
    return () => { detachRef.current?.(); };
  }, []);

  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    startXRef.current = e.clientX;
    startValRef.current = value;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    // Attach listeners only for the duration of this drag.
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    detachRef.current = () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  };

  return (
    <div
      onMouseDown={onMouseDown}
      className="shrink-0 w-[6px] cursor-col-resize bg-transparent hover:bg-primary-200/50 transition-colors relative group"
      title="拖动调整宽度"
    >
      <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-stone-200 group-hover:bg-primary-300" />
    </div>
  );
}
