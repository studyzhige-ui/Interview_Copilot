import { Navigate, Outlet, createBrowserRouter } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { AuthPage } from '@/pages/auth/AuthPage';
import { ReviewPage } from '@/pages/review/ReviewPage';
import { MockPage } from '@/pages/mock/MockPage';
import { AnalyticsPage } from '@/pages/analytics/AnalyticsPage';
import { LibraryPage } from '@/pages/library/LibraryPage';
import { ModelsPage } from '@/pages/models/ModelsPage';
import { ProfilePage } from '@/pages/me/ProfilePage';
import { AppShell } from '@/components/layout/AppShell';

function AuthGuard() {
  const isAuthed = useAuthStore((s) => s.isAuthed);
  if (!isAuthed) return <Navigate to="/auth" replace />;
  return <AppShell><Outlet /></AppShell>;
}

function GuestGuard() {
  const isAuthed = useAuthStore((s) => s.isAuthed);
  if (isAuthed) return <Navigate to="/review" replace />;
  return <Outlet />;
}

export const router = createBrowserRouter([
  {
    element: <GuestGuard />,
    children: [{ path: '/auth', element: <AuthPage /> }],
  },
  {
    element: <AuthGuard />,
    children: [
      { path: '/', element: <Navigate to="/review" replace /> },
      { path: '/review', element: <ReviewPage /> },
      { path: '/mock', element: <MockPage /> },
      { path: '/analytics', element: <AnalyticsPage /> },
      { path: '/library', element: <LibraryPage /> },
      { path: '/models', element: <ModelsPage /> },
      { path: '/me', element: <ProfilePage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
