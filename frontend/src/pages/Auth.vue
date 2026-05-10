<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { Brain, ShieldCheck, Loader2 } from "lucide-vue-next";
import { register, login, ApiError } from "../api";
import { store } from "../store";

const router = useRouter();

const username = ref(localStorage.getItem("interview-copilot-username") ?? "");
const password = ref("");
const email = ref("");
const authMode = ref<"login" | "register">("login");
const authBusy = ref(false);
const authError = ref("");

async function submitAuth() {
  authError.value = "";
  authBusy.value = true;
  try {
    if (authMode.value === "register") {
      await register(username.value, password.value, email.value);
    }
    const token = await login(username.value, password.value);
    store.setToken(token);
    store.setUsername(username.value);
    router.push("/chat");
  } catch (error) {
    authError.value = error instanceof ApiError ? error.message : "认证失败，请检查后端服务。";
  } finally {
    authBusy.value = false;
  }
}
</script>

<template>
  <div class="auth-card glass-panel">
    <div class="brand-lockup">
      <div class="brand-mark flex-center"><Brain :size="28" color="var(--primary)" /></div>
      <div class="brand-text">
        <p>Interview Copilot</p>
        <strong>面试复盘工作台</strong>
      </div>
    </div>

    <div class="auth-tabs">
      <button 
        type="button" 
        :class="['tab-btn', { active: authMode === 'login' }]" 
        @click="authMode = 'login'"
      >
        登录
      </button>
      <button 
        type="button" 
        :class="['tab-btn', { active: authMode === 'register' }]" 
        @click="authMode = 'register'"
      >
        注册
      </button>
    </div>

    <form class="auth-form" @submit.prevent="submitAuth">
      <div class="form-group">
        <label>用户名</label>
        <input class="input-field" v-model="username" autocomplete="username" required placeholder="输入您的用户名" />
      </div>
      
      <div v-if="authMode === 'register'" class="form-group slide-down">
        <label>邮箱</label>
        <input class="input-field" v-model="email" type="email" autocomplete="email" placeholder="输入您的邮箱" />
      </div>
      
      <div class="form-group">
        <label>密码</label>
        <input class="input-field" v-model="password" type="password" autocomplete="current-password" required placeholder="输入密码" />
      </div>

      <p v-if="authError" class="inline-error">{{ authError }}</p>
      
      <button class="primary-action hover-lift" type="submit" :disabled="authBusy">
        <Loader2 v-if="authBusy" class="spin" :size="20" />
        <ShieldCheck v-else :size="20" />
        <span>{{ authMode === "login" ? "进入工作台" : "创建账号并进入" }}</span>
      </button>
    </form>
  </div>
</template>

<style scoped>
.auth-card {
  padding: 40px;
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 16px;
  justify-content: center;
}

.brand-mark {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-md);
  background-color: var(--primary-light);
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-text p {
  font-size: 1.125rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.brand-text strong {
  font-size: 1.5rem;
  color: var(--text-primary);
  letter-spacing: -0.025em;
}

.auth-tabs {
  display: flex;
  background-color: var(--bg-surface-hover);
  padding: 4px;
  border-radius: var(--radius-md);
}

.tab-btn {
  flex: 1;
  padding: 10px;
  font-weight: 600;
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}

.tab-btn.active {
  background-color: var(--bg-surface);
  color: var(--primary);
  box-shadow: var(--shadow-sm);
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.input-field {
  padding: 12px 16px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  background-color: var(--bg-surface);
  color: var(--text-primary);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  font-size: 1rem;
}

.input-field:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-light);
}

.inline-error {
  color: var(--error);
  font-size: 0.875rem;
  background-color: var(--error-bg);
  padding: 8px 12px;
  border-radius: var(--radius-md);
}

.primary-action {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background-color: var(--primary);
  color: var(--text-inverse);
  padding: 14px;
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: 1rem;
  margin-top: 12px;
}

.primary-action:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.primary-action:not(:disabled):hover {
  background-color: var(--primary-hover);
}

.slide-down {
  animation: slideDown var(--transition-normal);
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
