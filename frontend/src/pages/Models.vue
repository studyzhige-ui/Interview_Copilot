<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Settings2, CircleAlert, Server, Loader2 } from "lucide-vue-next";
import { store } from "../store";
import { listModels } from "../api";

const isLoading = ref(false);

async function fetchModels() {
  if (!store.token) return;
  isLoading.value = true;
  try {
    const payload = await listModels(store.token);
    store.models = payload.profiles;
    store.modelSelection = payload.selection;
  } finally {
    isLoading.value = false;
  }
}

function prettyJson(value: unknown): string {
  if (!value) return "";
  return JSON.stringify(value, null, 2);
}

onMounted(() => {
  fetchModels();
});
</script>

<template>
  <div class="models-page">
    <div class="page-header">
      <div class="header-content">
        <h2 class="h2">大模型管理</h2>
        <p class="text-muted">查看当前后端配置的 LLM 和 Embedding 模型状态</p>
      </div>
      <button class="refresh-btn hover-lift" @click="fetchModels" :disabled="isLoading">
        <Loader2 v-if="isLoading" class="spin" :size="18" />
        <span>刷新状态</span>
      </button>
    </div>

    <div class="grid-layout">
      <div class="model-cards">
        <div v-if="isLoading && store.models.length === 0" class="loading-state">
          <Loader2 class="spin" :size="32" color="var(--primary)" />
          <p>正在同步模型状态...</p>
        </div>

        <article v-for="model in store.models" :key="model.id" class="model-card glass-panel hover-lift">
          <div class="card-top">
            <div class="icon-wrap">
              <Server :size="20" color="var(--primary)" />
            </div>
            <div class="status-indicator">
              <span :class="['dot', { ready: model.ready }]"></span>
              {{ model.ready ? "可用" : "未配置" }}
            </div>
          </div>
          
          <div class="card-info">
            <h3 class="h3">{{ model.display_name }}</h3>
            <p class="provider-info">{{ model.provider }} · {{ model.model }}</p>
          </div>
          
          <div class="card-tags">
            <span v-if="model.selected_for.length" class="tag purpose-tag">
              {{ model.selected_for.join(", ") }}
            </span>
            <span v-if="!model.ready" class="tag env-tag">
              缺少: {{ model.api_key_env }}
            </span>
          </div>
        </article>
      </div>

      <aside class="runtime-panel glass-panel">
        <div class="panel-header">
          <CircleAlert :size="18" color="var(--warning)" />
          <strong>当前应用选择</strong>
        </div>
        <div class="panel-body">
          <pre class="json-viewer">{{ prettyJson(store.modelSelection) }}</pre>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.models-page {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background-color: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  font-weight: 500;
  color: var(--text-primary);
}

.grid-layout {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 24px;
  align-items: start;
}

@media (max-width: 1024px) {
  .grid-layout {
    grid-template-columns: 1fr;
  }
}

.model-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.loading-state {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px;
  color: var(--text-muted);
  gap: 16px;
}

.model-card {
  padding: 24px;
  border-radius: var(--radius-lg);
  background-color: var(--bg-surface);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background-color: var(--primary-light);
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--error);
}

.dot.ready {
  background-color: var(--success);
}

.card-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.provider-info {
  font-size: 0.875rem;
  color: var(--text-muted);
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: auto;
}

.tag {
  font-size: 0.75rem;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-weight: 600;
}

.purpose-tag {
  background-color: #f3e8ff;
  color: var(--secondary);
}

.env-tag {
  background-color: var(--error-bg);
  color: var(--error);
}

.runtime-panel {
  border-radius: var(--radius-lg);
  background-color: var(--bg-surface);
  overflow: hidden;
  position: sticky;
  top: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px;
  border-bottom: 1px solid var(--border-light);
  background-color: var(--bg-surface-hover);
}

.panel-body {
  padding: 20px;
  background-color: var(--bg-app);
  margin: 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
}

.json-viewer {
  font-family: monospace;
  font-size: 0.875rem;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
