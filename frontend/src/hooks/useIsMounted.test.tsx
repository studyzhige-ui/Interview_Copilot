import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { useEffect } from 'react';

import { useIsMounted } from './useIsMounted';

describe('useIsMounted', () => {
  it('returns true while the component is mounted', () => {
    let observedMounted: boolean | null = null;
    function Probe() {
      const isMounted = useIsMounted();
      // Read inside an effect so we see the value AFTER the mount
      // effect has flipped it to true.
      useEffect(() => {
        observedMounted = isMounted.current;
      }, [isMounted]);
      return <div data-testid="probe" />;
    }
    render(<Probe />);
    expect(observedMounted).toBe(true);
  });

  it('flips to false on unmount', () => {
    // We need to capture the ref returned from the hook so we can
    // observe its ``.current`` AFTER the component unmounts. The
    // ref object itself is stable for the lifetime of the
    // component instance.
    let capturedRef: { current: boolean } | null = null;
    function Probe() {
      const isMounted = useIsMounted();
      capturedRef = isMounted;
      return null;
    }
    const view = render(<Probe />);
    // Sanity: ref captured, mounted true.
    expect(capturedRef!.current).toBe(true);
    view.unmount();
    expect(capturedRef!.current).toBe(false);
  });
});
