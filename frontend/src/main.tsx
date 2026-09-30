import { SESSION_SYNC_KEY } from './lib/token';
import { initializeAuth, synchronizeStoredSession } from './lib/supabaseAuth';
import { useAuthStore } from './store/authStore';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { router } from './router';
import { queryClient } from './lib/queryClient';
import { ToastViewport } from './components/ui/Toast';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import './styles/index.css';

window.addEventListener('storage', event => {
  if (event.key !== SESSION_SYNC_KEY || event.newValue !== localStorage.getItem(SESSION_SYNC_KEY)) return;
  if (!event.newValue) { synchronizeStoredSession(null); return; }
  try {
    const session = JSON.parse(event.newValue) as { access?: unknown; refresh?: unknown };
    if (typeof session.access === 'string' && typeof session.refresh === 'string') synchronizeStoredSession({ access_token: session.access, refresh_token: session.refresh });
  } catch { /* A malformed local hint grants no authority; API verification still applies. */ }
});

const root = ReactDOM.createRoot(document.getElementById('root')!);
void initializeAuth(session => {
  if (session) {
    useAuthStore.getState().setSession(session.access_token, session.refresh_token);
    void useAuthStore.getState().fetchMe();
  }
  else useAuthStore.getState().clearSession();
}).then(() => root.render(
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
)).catch(error => root.render(<main role="alert" className="p-8"><p>{error instanceof Error ? error.message : '本地服务暂不可用'}</p><button onClick={() => window.location.reload()}>重新连接</button></main>));
