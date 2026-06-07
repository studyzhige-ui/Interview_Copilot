import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface State {
  error: Error | null;
  resetKey: number;
}

/**
 * Top-level React error boundary.
 *
 * Without one, a render-time exception (e.g. a TypeError reading a missing
 * field on stale state) blanks the entire SPA — the user sees a white page
 * with no way to recover except a hard reload. This boundary catches the
 * throw, renders a polite fallback, and offers a one-click reset that
 * remounts the routed view. Bumping ``resetKey`` triggers React to mount
 * a fresh subtree, which clears whatever bad state caused the throw.
 *
 * Place at the very top of the tree (above RouterProvider) so route-level
 * errors AND lazy-import failures both land here.
 */
export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  State
> {
  state: State = { error: null, resetKey: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] render crash:', error, info.componentStack);
  }

  handleReset = () => {
    this.setState((s) => ({ error: null, resetKey: s.resetKey + 1 }));
  };

  render() {
    if (!this.state.error) {
      // resetKey forces a remount of the routed subtree after reset.
      return (
        <React.Fragment key={this.state.resetKey}>
          {this.props.children}
        </React.Fragment>
      );
    }
    return (
      <div className="min-h-screen flex items-center justify-center bg-stone-50 px-4">
        <div className="max-w-md w-full bg-white rounded-xl border border-stone-200 shadow-sm p-6">
          <div className="flex items-start gap-3 mb-4">
            <div className="w-10 h-10 rounded-lg bg-danger-50 text-danger-500 flex items-center justify-center shrink-0">
              <AlertTriangle size={20} />
            </div>
            <div className="min-w-0">
              <div className="text-base font-semibold text-stone-800">页面遇到错误</div>
              <div className="text-xs text-stone-500 mt-0.5">
                可能是缓存或临时状态问题，重置一下视图通常就能恢复。
              </div>
            </div>
          </div>
          <details className="bg-stone-50 border border-stone-200 rounded-md p-2.5 mb-4 text-[11px] text-stone-600">
            <summary className="cursor-pointer select-none text-stone-700 font-medium">
              查看错误详情
            </summary>
            <pre className="whitespace-pre-wrap break-words mt-2 font-mono leading-relaxed">
              {this.state.error.message}
            </pre>
          </details>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={this.handleReset}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary-500 text-white text-sm font-medium hover:bg-primary-600"
            >
              <RotateCcw size={14} />
              重置视图
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-3 py-1.5 rounded-md border border-stone-300 text-stone-700 text-sm hover:bg-stone-50"
            >
              整页刷新
            </button>
          </div>
        </div>
      </div>
    );
  }
}
