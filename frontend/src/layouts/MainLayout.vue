<script setup lang="ts">
import { computed } from "vue";
import { useRouter, useRoute } from "vue-router";
import {
  Bot,
  AudioLines,
  DatabaseZap,
  Settings2,
  LogOut,
  Brain,
  Mic,
  Gauge,
  CheckCircle2
} from "lucide-vue-next";
import { store } from "../store";

const router = useRouter();
const route = useRoute();

const activePanel = computed(() => route.name);

function logout() {
  store.logout();
  router.push("/auth");
}
</script>

<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="brand-icon flex-center"><Brain :size="24" color="var(--primary)" /></div>
        <span class="brand-title">Interview Copilot</span>
      </div>
      
      <nav class="nav-menu">
        <router-link to="/chat" class="nav-item" active-class="active">
          <Bot :size="20" />
          <span>对话</span>
        </router-link>
        <router-link to="/analysis" class="nav-item" active-class="active">
          <AudioLines :size="20" />
          <span>分析</span>
        </router-link>
        <router-link to="/memory" class="nav-item" active-class="active">
          <DatabaseZap :size="20" />
          <span>记忆</span>
        </router-link>
        <router-link to="/models" class="nav-item" active-class="active">
          <Settings2 :size="20" />
          <span>模型</span>
        </router-link>
        <div class="nav-divider"></div>
        <!-- The reserved Voice Mock Interview Page -->
        <router-link to="/voice-mock" class="nav-item premium-item" active-class="active">
          <Mic :size="20" />
          <span>语音模拟</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <button class="logout-btn hover-lift" @click="logout" title="退出登录">
          <LogOut :size="18" />
          <span>退出</span>
        </button>
      </div>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <div class="topbar-left">
          <h2 class="h2">{{ activePanel === 'VoiceMock' ? '语音面试模拟' : (store.activeSession?.title || '新会话') }}</h2>
          <span class="text-muted">{{ activePanel === 'VoiceMock' ? '实时语音交互体验' : (store.activeSession?.working_state_summary || '工作台') }}</span>
        </div>
        <div class="topbar-right">
          <div class="status-pill">
            <CheckCircle2 :size="16" color="var(--success)" /> 
            <span>API 已连接</span>
          </div>
          <div class="status-pill">
            <Gauge :size="16" color="var(--primary)" /> 
            <span>{{ store.readyModels }}/{{ store.models.length || 0 }} 模型可用</span>
          </div>
        </div>
      </header>

      <div class="page-container">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </main>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background-color: var(--bg-app);
}

/* Sidebar */
.sidebar {
  width: 260px;
  background-color: var(--bg-surface);
  border-right: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-sm);
  z-index: 10;
}

.sidebar-header {
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-icon {
  width: 40px;
  height: 40px;
  background-color: var(--primary-light);
  border-radius: var(--radius-md);
}

.brand-title {
  font-weight: 700;
  font-size: 1.125rem;
  color: var(--text-primary);
  letter-spacing: -0.025em;
}

.nav-menu {
  flex: 1;
  padding: 0 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-weight: 500;
  transition: all var(--transition-fast);
}

.nav-item:hover {
  background-color: var(--bg-surface-hover);
  color: var(--text-primary);
}

.nav-item.active {
  background-color: var(--primary-light);
  color: var(--primary);
}

.nav-divider {
  height: 1px;
  background-color: var(--border-light);
  margin: 12px 0;
}

.premium-item {
  color: var(--secondary);
}
.premium-item:hover {
  background-color: #f3e8ff; /* secondary light */
  color: var(--secondary-hover);
}
.premium-item.active {
  background-color: #f3e8ff;
  color: var(--secondary-hover);
}

.sidebar-footer {
  padding: 24px 16px;
  border-top: 1px solid var(--border-light);
}

.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 12px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  background-color: var(--bg-surface-hover);
  font-weight: 500;
  transition: all var(--transition-fast);
}

.logout-btn:hover {
  background-color: var(--error-bg);
  color: var(--error);
}

/* Main Content */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background-color: var(--bg-app);
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 32px;
  background-color: var(--bg-surface);
  border-bottom: 1px solid var(--border-light);
  box-shadow: var(--shadow-sm);
  z-index: 5;
}

.topbar-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.status-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background-color: var(--bg-surface-hover);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-full);
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.page-container {
  flex: 1;
  overflow: auto;
  padding: 32px;
  position: relative;
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--transition-fast), transform var(--transition-fast);
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
</style>
