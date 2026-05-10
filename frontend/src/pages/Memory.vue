<script setup lang="ts">
import { onMounted, ref } from "vue";
import { History, Gauge, DatabaseZap } from "lucide-vue-next";
import { store } from "../store";
import { listMemory, getAnalyticsReport } from "../api";

const isLoading = ref(false);

async function loadData() {
  if (!store.token) return;
  isLoading.value = true;
  try {
    const [memories, report] = await Promise.all([
      listMemory(store.token).catch(() => []),
      getAnalyticsReport(store.token).catch(() => null)
    ]);
    store.memoryItems = memories;
    store.analyticsReport = report;
  } finally {
    isLoading.value = false;
  }
}

function prettyJson(value: unknown): string {
  if (!value) return "";
  return JSON.stringify(value, null, 2);
}

onMounted(() => {
  loadData();
});
</script>

<template>
  <div class="memory-page grid-layout">
    <section class="card glass-panel">
      <div class="card-header">
        <div class="header-icon flex-center"><History :size="20" color="var(--primary)" /></div>
        <div>
          <h3 class="h3">长期记忆</h3>
          <span class="text-muted">共 {{ store.memoryItems.length }} 条记忆切片</span>
        </div>
      </div>
      
      <div class="card-body">
        <div class="memory-list" v-if="store.memorySummary.length > 0">
          <article v-for="item in store.memorySummary" :key="item.id" class="memory-item hover-lift">
            <div class="memory-icon"><DatabaseZap :size="16" /></div>
            <div class="memory-content">
              <strong>{{ item.description || item.normalized_key }}</strong>
              <span>类型: {{ item.type }} · 置信度 {{ Math.round((item.confidence || 0) * 100) }}%</span>
            </div>
          </article>
        </div>
        <div v-else class="empty-state">
          <DatabaseZap :size="48" color="var(--border-strong)" />
          <p>暂无记忆数据</p>
          <span>多与 Copilot 交流，它会自动记住您的背景和项目经历。</span>
        </div>
      </div>
    </section>

    <section class="card glass-panel">
      <div class="card-header">
        <div class="header-icon flex-center"><Gauge :size="20" color="var(--warning)" /></div>
        <div>
          <h3 class="h3">分析报告</h3>
          <span class="text-muted">个人错题与复盘概览</span>
        </div>
      </div>
      
      <div class="card-body bg-light">
        <div v-if="isLoading" class="loading-state">
          <div class="spin-wrap"><Gauge class="spin" :size="32" color="var(--primary)" /></div>
          <p>正在生成分析报告...</p>
        </div>
        <pre v-else class="json-viewer">{{ prettyJson(store.analyticsReport) || "暂无报告数据。" }}</pre>
      </div>
    </section>
  </div>
</template>

<style scoped>
.grid-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  height: 100%;
}

@media (max-width: 1024px) {
  .grid-layout {
    grid-template-columns: 1fr;
  }
}

.card {
  border-radius: var(--radius-lg);
  background-color: var(--bg-surface);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px;
  border-bottom: 1px solid var(--border-light);
}

.header-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background-color: var(--primary-light);
}

.card-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.card-body.bg-light {
  background-color: var(--bg-app);
  margin: 16px;
  border-radius: var(--radius-md);
  padding: 16px;
  border: 1px solid var(--border-light);
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.memory-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background-color: var(--bg-app);
}

.memory-icon {
  color: var(--primary);
  background-color: white;
  padding: 8px;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-sm);
}

.memory-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.memory-content strong {
  font-size: 1rem;
  color: var(--text-primary);
}

.memory-content span {
  font-size: 0.875rem;
  color: var(--text-muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--text-muted);
  text-align: center;
}

.empty-state p {
  font-weight: 600;
  color: var(--text-secondary);
}

.json-viewer {
  font-family: monospace;
  font-size: 0.875rem;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 16px;
  color: var(--text-muted);
}
</style>
