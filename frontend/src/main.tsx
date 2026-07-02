import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { router } from './router';
import { queryClient } from './lib/queryClient';
import { ToastViewport } from './components/ui/Toast';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import './styles/index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {/* ErrorBoundary wraps the whole router so a render-time throw in any
        page surfaces as a recoverable banner instead of a blank screen. */}
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ErrorBoundary>
    <ToastViewport />
  </React.StrictMode>,
);
