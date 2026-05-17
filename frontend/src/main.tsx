import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { ToastViewport } from './components/ui/Toast';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import { initSentry } from './lib/sentry';
import './styles/index.css';

// Fire and forget — initSentry resolves to a no-op when VITE_SENTRY_DSN
// isn't set, so we don't gate the render on it.
void initSentry();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {/* ErrorBoundary wraps the whole router so a render-time throw in any
        page surfaces as a recoverable banner instead of a blank screen. */}
    <ErrorBoundary>
      <RouterProvider router={router} />
    </ErrorBoundary>
    <ToastViewport />
  </React.StrictMode>,
);
