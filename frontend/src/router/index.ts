import { createRouter, createWebHistory } from 'vue-router';
import { store } from '../store';

const routes = [
  {
    path: '/auth',
    name: 'Auth',
    component: () => import('../pages/Auth.vue'),
    meta: { layout: 'AuthLayout', requiresGuest: true }
  },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        redirect: '/chat'
      },
      {
        path: 'chat',
        name: 'Chat',
        component: () => import('../pages/Chat.vue')
      },
      {
        path: 'analysis',
        name: 'Analysis',
        component: () => import('../pages/InterviewAnalysis.vue')
      },
      {
        path: 'memory',
        name: 'Memory',
        component: () => import('../pages/Memory.vue')
      },
      {
        path: 'models',
        name: 'Models',
        component: () => import('../pages/Models.vue')
      },
      {
        path: 'voice-mock',
        name: 'VoiceMock',
        component: () => import('../pages/VoiceInterview.vue')
      }
    ]
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

router.beforeEach((to, from, next) => {
  const isAuthed = store.isAuthed;
  
  if (to.meta.requiresAuth && !isAuthed) {
    next('/auth');
  } else if (to.meta.requiresGuest && isAuthed) {
    next('/');
  } else {
    next();
  }
});

export default router;
