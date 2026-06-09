import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { ToastViewport } from './components/ui/Toast';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import './styles/index.css';

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
