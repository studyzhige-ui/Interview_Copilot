import { Suspense, lazy } from 'react';
import { Navigate, Outlet, createBrowserRouter } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { AppShell } from '@/components/layout/AppShell';
import { Spinner } from '@/components/ui/Spinner';

/**
 * Each page is loaded on demand so the initial bundle stays small.
 *
 * React.lazy expects a module with a `default` export. Our pages use named
 * exports (intentional — easier to grep), so each lazy() call adapts the
 * dynamic-import promise to remap the named export to ``default``. The
 * cost is one extra arrow function per route — bundlers tree-shake the
 * rest cleanly.
 */
const AuthPage = lazy(() =>
  import('@/pages/auth/AuthPage').then((m) => ({ default: m.AuthPage })),
);
const ReviewPage = lazy(() =>
  import('@/pages/review/ReviewPage').then((m) => ({ default: m.ReviewPage })),
);
const MockPage = lazy(() =>
  import('@/pages/mock/MockPage').then((m) => ({ default: m.MockPage })),
);
const GeneralChatPage = lazy(() =>
  import('@/pages/chat/GeneralChatPage').then((m) => ({ default: m.GeneralChatPage })),
);
const HistorySearchPage = lazy(() =>
  import('@/pages/history/HistorySearchPage').then((m) => ({ default: m.HistorySearchPage })),
);
const AnalyticsPage = lazy(() =>
  import('@/pages/analytics/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage })),
);
const LibraryPage = lazy(() =>
  import('@/pages/library/LibraryPage').then((m) => ({ default: m.LibraryPage })),
);
const ModelsPage = lazy(() =>
  import('@/pages/models/ModelsPage').then((m) => ({ default: m.ModelsPage })),
);
const CapabilitiesPage = lazy(() =>
  import('@/pages/capabilities/CapabilitiesPage').then((m) => ({ default: m.CapabilitiesPage })),
);
const ProfilePage = lazy(() =>
  import('@/pages/me/ProfilePage').then((m) => ({ default: m.ProfilePage })),
);
const CareerProfilePage = lazy(() =>
  import('@/pages/career/CareerProfilePage').then((m) => ({ default: m.CareerProfilePage })),
);
const CareerProcessPage = lazy(() =>
  import('@/pages/career/CareerProcessPage').then((m) => ({ default: m.CareerProcessPage })),
);
const CareerInsightsPage = lazy(() =>
  import('@/pages/career/CareerInsightsPage').then((m) => ({ default: m.CareerInsightsPage })),
);
const ArtifactsPage = lazy(() =>
  import('@/pages/artifacts/ArtifactsPage').then((m) => ({ default: m.ArtifactsPage })),
);
const OfferPage = lazy(() =>
  import('@/pages/career/OfferPage').then((m) => ({ default: m.OfferPage })),
);
const PersistentTasksPage = lazy(() =>
  import('@/pages/automation/PersistentTasksPage').then((m) => ({ default: m.PersistentTasksPage })),
);
const PersistentTaskConversationPage = lazy(() =>
  import('@/pages/automation/PersistentTasksPage').then((m) => ({ default: m.PersistentTaskConversationPage })),
);
const CopilotPreferencesPage = lazy(() =>
  import('@/pages/settings/CopilotPreferencesPage').then((m) => ({ default: m.CopilotPreferencesPage })),
);

/** Lightweight fallback while a chunk loads. Kept centred + brand-coloured. */
function PageFallback() {
  return (
    <div className="h-full w-full flex items-center justify-center text-stone-400">
      <Spinner size={20} />
    </div>
  );
}

/** Wrap children in a Suspense boundary so each lazy chunk has a loader. */
function LazyOutlet() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Outlet />
    </Suspense>
  );
}

function AuthGuard() {
  const isAuthed = useAuthStore((s) => s.isAuthed);
  if (!isAuthed) return <Navigate to="/auth" replace />;
  return <AppShell><LazyOutlet /></AppShell>;
}

function GuestGuard() {
  const isAuthed = useAuthStore((s) => s.isAuthed);
  if (isAuthed) return <Navigate to="/general-chat" replace />;
  return <LazyOutlet />;
}

export const router = createBrowserRouter([
  {
    element: <GuestGuard />,
    children: [{ path: '/auth', element: <AuthPage /> }],
  },
  {
    element: <AuthGuard />,
    children: [
      { path: '/', element: <Navigate to="/general-chat" replace /> },
      { path: '/review', element: <ReviewPage /> },
      { path: '/mock', element: <MockPage /> },
      { path: '/general-chat', element: <GeneralChatPage /> },
      { path: '/history', element: <HistorySearchPage /> },
      { path: '/persistent-tasks/:taskId/conversation', element: <PersistentTaskConversationPage /> },
      { path: '/persistent-tasks/:taskId?', element: <PersistentTasksPage /> },
      { path: '/analytics', element: <AnalyticsPage /> },
      { path: '/career-profile', element: <CareerProfilePage /> },
      { path: '/career-process', element: <CareerProcessPage /> },
      { path: '/career-insights', element: <CareerInsightsPage /> },
      { path: '/career-process/:opportunityId/offer', element: <OfferPage /> },
      { path: '/artifacts/:artifactId?', element: <ArtifactsPage /> },
      { path: '/library', element: <LibraryPage /> },
      { path: '/models', element: <ModelsPage /> },
      { path: '/capabilities', element: <CapabilitiesPage /> },
      { path: '/plugins', element: <CapabilitiesPage /> },
      { path: '/settings/connections', element: <Navigate to="/plugins?plugin=gmail" replace /> },
      { path: '/settings/personalization', element: <CopilotPreferencesPage /> },
      { path: '/me', element: <ProfilePage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
