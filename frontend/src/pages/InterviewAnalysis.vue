<script setup lang="ts">
import { ref } from "vue";
import { FileAudio, Play, Loader2, PanelRight } from "lucide-vue-next";
import { store } from "../store";
import { uploadAndAnalyze, getAnalysisStatus, ApiError } from "../api";
import type { AnalysisPayload } from "../types";

const selectedFile = ref<File | null>(null);
const uploadBusy = ref(false);
const analysis = ref<AnalysisPayload | null>(null);
const analysisError = ref("");

function prettyJson(value: unknown): string {
  if (!value) return "";
  return JSON.stringify(value, null, 2);
}

async function analyzeFile(): Promise<void> {
  if (!selectedFile.value || !store.token) return;
  uploadBusy.value = true;
  analysisError.value = "";
  try {
    const payload = await uploadAndAnalyze(store.token, selectedFile.value);
    analysis.value = {
      interview_id: payload.interview_id,
      status: "PROCESSING"
    };
  } catch (error) {
    analysisError.value = error instanceof ApiError ? error.message : "上传或分析任务创建失败。";
  } finally {
    uploadBusy.value = false;
  }
}

async function pollAnalysis(): Promise<void> {
  if (!analysis.value || !store.token) return;
  try {
    analysis.value = await getAnalysisStatus(store.token, analysis.value.interview_id);
  } catch (error) {
    analysisError.value = error instanceof ApiError ? error.message : "查询任务状态失败。";
  }
}
</script>

<template>
  <div class="analysis-page grid-layout">
    <section class="card glass-panel">
      <div class="card-header">
        <div class="header-icon flex-center"><FileAudio :size="20" color="var(--primary)" /></div>
        <div>
          <h3 class="h3">音频分析</h3>
          <span class="text-muted">上传录音后交给后端进行转写和自动评分</span>
        </div>
      </div>
      
      <div class="card-body">
        <label class="drop-zone hover-lift">
          <input 
            type="file" 
            accept="audio/*,video/*" 
            class="hidden-input"
            @change="selectedFile = ($event.target as HTMLInputElement).files?.[0] ?? null" 
          />
          <FileAudio :size="48" color="var(--text-muted)" class="mb-2" />
          <strong class="drop-title">{{ selectedFile?.name ?? "点击选择或拖拽音频/视频文件" }}</strong>
          <span class="text-muted">支持后端已配置的转写格式 (mp3, mp4, wav等)</span>
        </label>
        
        <div class="action-row">
          <button 
            class="primary-btn hover-lift" 
            :disabled="!selectedFile || uploadBusy" 
            @click="analyzeFile"
          >
            <Loader2 v-if="uploadBusy" class="spin" :size="18" />
            <Play v-else :size="18" />
            <span>启动分析</span>
          </button>
          
          <button 
            class="secondary-btn hover-lift" 
            :disabled="!analysis" 
            @click="pollAnalysis"
          >
            刷新状态
          </button>
        </div>
        
        <p v-if="analysisError" class="inline-error">{{ analysisError }}</p>
      </div>
    </section>

    <section class="card glass-panel">
      <div class="card-header">
        <div class="header-icon flex-center"><PanelRight :size="20" color="var(--secondary)" /></div>
        <div>
          <h3 class="h3">任务结果</h3>
          <span class="text-muted">
            状态: <span class="status-badge">{{ analysis?.status ?? "暂无任务" }}</span>
          </span>
        </div>
      </div>
      
      <div class="card-body bg-light">
        <pre class="json-viewer">{{ prettyJson(analysis?.analysis ?? analysis) || "上传文件后，分析结果将在这里实时更新展示。" }}</pre>
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
  padding: 24px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.card-body.bg-light {
  background-color: var(--bg-app);
  margin: 16px;
  border-radius: var(--radius-md);
  padding: 16px;
  border: 1px solid var(--border-light);
  overflow-y: auto;
}

.hidden-input {
  display: none;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  border: 2px dashed var(--border-strong);
  border-radius: var(--radius-md);
  background-color: var(--bg-app);
  cursor: pointer;
  text-align: center;
  transition: all var(--transition-fast);
}

.drop-zone:hover {
  border-color: var(--primary);
  background-color: var(--primary-light);
}

.mb-2 {
  margin-bottom: 16px;
}

.drop-title {
  font-size: 1.125rem;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.action-row {
  display: flex;
  gap: 16px;
}

.primary-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  background-color: var(--primary);
  color: white;
  border-radius: var(--radius-md);
  font-weight: 600;
}

.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.secondary-btn {
  padding: 12px 24px;
  background-color: white;
  border: 1px solid var(--border-strong);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  font-weight: 600;
}

.secondary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.inline-error {
  color: var(--error);
  font-size: 0.875rem;
  padding: 12px;
  background-color: var(--error-bg);
  border-radius: var(--radius-md);
}

.status-badge {
  background-color: var(--primary-light);
  color: var(--primary);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-size: 0.75rem;
  font-weight: 600;
  margin-left: 8px;
}

.json-viewer {
  font-family: monospace;
  font-size: 0.875rem;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
