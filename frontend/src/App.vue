<script setup lang="ts">
import {
  AudioLines,
  Bot,
  Brain,
  CheckCircle2,
  CircleAlert,
  DatabaseZap,
  FileAudio,
  Gauge,
  History,
  Loader2,
  LogOut,
  MessageSquarePlus,
  PanelRight,
  Play,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  UserRound
} from "lucide-vue-next";
import { computed, nextTick, onMounted, ref } from "vue";
import {
  ApiError,
  createSession,
  getAnalysisStatus,
  getAnalyticsReport,
  getHistory,
  listMemory,
  listModels,
  listSessions,
  login,
  register,
  streamChat,
  uploadAndAnalyze
} from "./api";
import type { AnalysisPayload, MemoryItem, MessageItem, ModelProfile, SessionListItem } from "./types";

type PanelId = "chat" | "interview" | "memory" | "models";

const token = ref(localStorage.getItem("interview-copilot-token") ?? "");
const username = ref(localStorage.getItem("interview-copilot-username") ?? "");
const password = ref("");
const email = ref("");
const authMode = ref<"login" | "register">("login");
const authBusy = ref(false);
const authError = ref("");

const activePanel = ref<PanelId>("chat");
const sessions = ref<SessionListItem[]>([]);
const activeSessionId = ref("");
const messages = ref<MessageItem[]>([]);
const draft = ref("");
const isStreaming = ref(false);
const chatError = ref("");
const messageList = ref<HTMLElement | null>(null);

const selectedFile = ref<File | null>(null);
const uploadBusy = ref(false);
const analysis = ref<AnalysisPayload | null>(null);
const analysisError = ref("");

const models = ref<ModelProfile[]>([]);
const modelSelection = ref<Record<string, string>>({});
const memoryItems = ref<MemoryItem[]>([]);
const analyticsReport = ref<unknown>(null);
const sideBusy = ref(false);

const isAuthed = computed(() => Boolean(token.value));
const activeSession = computed(() => sessions.value.find((item) => item.session_id === activeSessionId.value));
const readyModels = computed(() => models.value.filter((model) => model.ready).length);
const memorySummary = computed(() => memoryItems.value.slice(0, 5));

function shortDate(value?: string): string {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function prettyJson(value: unknown): string {
  if (!value) return "";
  return JSON.stringify(value, null, 2);
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  if (messageList.value) {
    messageList.value.scrollTop = messageList.value.scrollHeight;
  }
}

async function submitAuth(): Promise<void> {
  authError.value = "";
  authBusy.value = true;
  try {
    if (authMode.value === "register") {
      await register(username.value, password.value, email.value);
    }
    token.value = await login(username.value, password.value);
    localStorage.setItem("interview-copilot-token", token.value);
    localStorage.setItem("interview-copilot-username", username.value);
    await bootstrapWorkspace();
  } catch (error) {
    authError.value = error instanceof ApiError ? error.message : "认证失败，请检查后端服务。";
  } finally {
    authBusy.value = false;
  }
}

function logout(): void {
  token.value = "";
  localStorage.removeItem("interview-copilot-token");
  sessions.value = [];
  messages.value = [];
  activeSessionId.value = "";
}

async function bootstrapWorkspace(): Promise<void> {
  await Promise.all([refreshSessions(), refreshSideData()]);
  if (!activeSessionId.value) {
    await startSession();
  }
}

async function refreshSessions(): Promise<void> {
  if (!token.value) return;
  sessions.value = await listSessions(token.value);
  if (!activeSessionId.value && sessions.value.length > 0) {
    activeSessionId.value = sessions.value[0].session_id;
  }
  if (activeSessionId.value) {
    await loadHistory(activeSessionId.value);
  }
}

async function startSession(): Promise<void> {
  if (!token.value) return;
  activeSessionId.value = await createSession(token.value);
  await refreshSessions();
  messages.value = [];
}

async function loadHistory(sessionId: string): Promise<void> {
  activeSessionId.value = sessionId;
  messages.value = await getHistory(token.value, sessionId);
  await scrollToBottom();
}

async function sendMessage(): Promise<void> {
  const content = draft.value.trim();
  if (!content || !token.value || !activeSessionId.value || isStreaming.value) return;

  chatError.value = "";
  draft.value = "";
  messages.value.push({
    seq: Date.now(),
    role: "user",
    content,
    created_at: new Date().toISOString()
  });
  const assistantMessage: MessageItem = {
    seq: Date.now() + 1,
    role: "assistant",
    content: "",
    created_at: new Date().toISOString()
  };
  messages.value.push(assistantMessage);
  isStreaming.value = true;
  await scrollToBottom();

  try {
    await streamChat(token.value, activeSessionId.value, content, (chunk) => {
      assistantMessage.content += chunk;
      void scrollToBottom();
    });
    await refreshSessions();
    await refreshSideData();
  } catch (error) {
    chatError.value = error instanceof ApiError ? error.message : "流式对话失败。";
    assistantMessage.content ||= "对话请求没有完成，请检查后端服务。";
  } finally {
    isStreaming.value = false;
  }
}

async function analyzeFile(): Promise<void> {
  if (!selectedFile.value || !token.value) return;
  uploadBusy.value = true;
  analysisError.value = "";
  try {
    const payload = await uploadAndAnalyze(token.value, selectedFile.value);
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
  if (!analysis.value || !token.value) return;
  try {
    analysis.value = await getAnalysisStatus(token.value, analysis.value.interview_id);
  } catch (error) {
    analysisError.value = error instanceof ApiError ? error.message : "查询任务状态失败。";
  }
}

async function refreshSideData(): Promise<void> {
  if (!token.value) return;
  sideBusy.value = true;
  try {
    const [modelPayload, memories, report] = await Promise.all([
      listModels(token.value),
      listMemory(token.value).catch(() => []),
      getAnalyticsReport(token.value).catch(() => null)
    ]);
    models.value = modelPayload.profiles;
    modelSelection.value = modelPayload.selection;
    memoryItems.value = memories;
    analyticsReport.value = report;
  } finally {
    sideBusy.value = false;
  }
}

onMounted(() => {
  if (token.value) {
    void bootstrapWorkspace().catch(() => {
      logout();
    });
  }
});
</script>

<template>
  <main class="app-shell">
    <section v-if="!isAuthed" class="auth-view">
      <div class="auth-art" aria-hidden="true">
        <div class="pulse-grid">
          <span v-for="index in 48" :key="index" />
        </div>
      </div>
      <form class="auth-panel" @submit.prevent="submitAuth">
        <div class="brand-lockup">
          <div class="brand-mark"><Brain :size="24" /></div>
          <div>
            <p>Interview Copilot</p>
            <strong>面试复盘工作台</strong>
          </div>
        </div>

        <div class="auth-tabs">
          <button type="button" :class="{ active: authMode === 'login' }" @click="authMode = 'login'">
            登录
          </button>
          <button type="button" :class="{ active: authMode === 'register' }" @click="authMode = 'register'">
            注册
          </button>
        </div>

        <label>
          <span>用户名</span>
          <input v-model="username" autocomplete="username" required />
        </label>
        <label v-if="authMode === 'register'">
          <span>邮箱</span>
          <input v-model="email" type="email" autocomplete="email" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>

        <p v-if="authError" class="inline-error">{{ authError }}</p>
        <button class="primary-action" type="submit" :disabled="authBusy">
          <Loader2 v-if="authBusy" class="spin" :size="18" />
          <ShieldCheck v-else :size="18" />
          {{ authMode === "login" ? "进入工作台" : "创建账号并进入" }}
        </button>
      </form>
    </section>

    <section v-else class="workspace">
      <aside class="rail">
        <div class="rail-brand">
          <div class="brand-mark"><Brain :size="22" /></div>
          <span>Interview Copilot</span>
        </div>
        <nav>
          <button :class="{ active: activePanel === 'chat' }" @click="activePanel = 'chat'">
            <Bot :size="19" />
            对话
          </button>
          <button :class="{ active: activePanel === 'interview' }" @click="activePanel = 'interview'">
            <AudioLines :size="19" />
            分析
          </button>
          <button :class="{ active: activePanel === 'memory' }" @click="activePanel = 'memory'">
            <DatabaseZap :size="19" />
            记忆
          </button>
          <button :class="{ active: activePanel === 'models' }" @click="activePanel = 'models'">
            <Settings2 :size="19" />
            模型
          </button>
        </nav>
        <button class="ghost-icon" title="退出登录" @click="logout">
          <LogOut :size="19" />
        </button>
      </aside>

      <aside class="session-pane">
        <div class="pane-header">
          <div>
            <span>会话</span>
            <strong>{{ sessions.length }}</strong>
          </div>
          <button class="icon-button" title="新建会话" @click="startSession">
            <MessageSquarePlus :size="18" />
          </button>
        </div>
        <div class="search-field">
          <Search :size="16" />
          <input placeholder="查找会话" />
        </div>
        <div class="session-list">
          <button
            v-for="session in sessions"
            :key="session.session_id"
            :class="{ active: session.session_id === activeSessionId }"
            @click="loadHistory(session.session_id)"
          >
            <span>{{ session.title }}</span>
            <small>{{ session.turn_count }} 轮 · {{ shortDate(session.updated_at) }}</small>
          </button>
        </div>
      </aside>

      <section class="main-pane">
        <header class="topbar">
          <div>
            <p>{{ activeSession?.title ?? "新的面试对话" }}</p>
            <span>{{ activeSession?.working_state_summary || "等待建立上下文" }}</span>
          </div>
          <div class="status-pills">
            <span><CheckCircle2 :size="15" /> API 已配置</span>
            <span><Gauge :size="15" /> {{ readyModels }}/{{ models.length || 0 }} 模型可用</span>
          </div>
        </header>

        <div v-if="activePanel === 'chat'" class="chat-board">
          <div ref="messageList" class="message-list">
            <div v-if="messages.length === 0" class="empty-state">
              <Sparkles :size="28" />
              <strong>开始一次面试复盘</strong>
              <span>可以直接贴题目、简历项目、JD，或让 Copilot 基于记忆继续追问。</span>
            </div>
            <article v-for="message in messages" :key="message.seq" :class="['message', message.role]">
              <div class="avatar">
                <UserRound v-if="message.role === 'user'" :size="17" />
                <Bot v-else :size="17" />
              </div>
              <div class="bubble">{{ message.content }}</div>
            </article>
          </div>
          <p v-if="chatError" class="inline-error">{{ chatError }}</p>
          <form class="composer" @submit.prevent="sendMessage">
            <textarea
              v-model="draft"
              placeholder="输入面试题、项目描述或复盘问题"
              @keydown.enter.exact.prevent="sendMessage"
            />
            <button type="submit" class="send-button" :disabled="isStreaming || !draft.trim()">
              <Loader2 v-if="isStreaming" class="spin" :size="18" />
              <Send v-else :size="18" />
            </button>
          </form>
        </div>

        <div v-else-if="activePanel === 'interview'" class="tool-layout">
          <section class="tool-surface">
            <div class="section-title">
              <FileAudio :size="20" />
              <div>
                <strong>音频分析</strong>
                <span>上传录音后交给 Celery worker 转写和评分</span>
              </div>
            </div>
            <label class="drop-zone">
              <input type="file" accept="audio/*,video/*" @change="selectedFile = ($event.target as HTMLInputElement).files?.[0] ?? null" />
              <FileAudio :size="34" />
              <strong>{{ selectedFile?.name ?? "选择音频或视频文件" }}</strong>
              <span>支持后端已配置的转写格式</span>
            </label>
            <div class="action-row">
              <button class="primary-action compact" :disabled="!selectedFile || uploadBusy" @click="analyzeFile">
                <Loader2 v-if="uploadBusy" class="spin" :size="17" />
                <Play v-else :size="17" />
                启动分析
              </button>
              <button class="secondary-action" :disabled="!analysis" @click="pollAnalysis">刷新状态</button>
            </div>
            <p v-if="analysisError" class="inline-error">{{ analysisError }}</p>
          </section>

          <section class="result-surface">
            <div class="section-title">
              <PanelRight :size="20" />
              <div>
                <strong>任务结果</strong>
                <span>{{ analysis?.status ?? "暂无任务" }}</span>
              </div>
            </div>
            <pre>{{ prettyJson(analysis?.analysis ?? analysis) || "上传后这里会显示任务状态和分析结果。" }}</pre>
          </section>
        </div>

        <div v-else-if="activePanel === 'memory'" class="tool-layout">
          <section class="tool-surface">
            <div class="section-title">
              <History :size="20" />
              <div>
                <strong>长期记忆</strong>
                <span>{{ memoryItems.length }} 条候选记忆</span>
              </div>
            </div>
            <div class="memory-list">
              <article v-for="item in memorySummary" :key="item.id">
                <strong>{{ item.description || item.normalized_key }}</strong>
                <span>{{ item.type }} · 置信度 {{ Math.round((item.confidence || 0) * 100) }}%</span>
              </article>
              <div v-if="memorySummary.length === 0" class="empty-line">暂无记忆数据</div>
            </div>
          </section>
          <section class="result-surface">
            <div class="section-title">
              <Gauge :size="20" />
              <div>
                <strong>分析报告</strong>
                <span>个人错题与复盘概览</span>
              </div>
            </div>
            <pre>{{ prettyJson(analyticsReport) || "暂无报告数据。" }}</pre>
          </section>
        </div>

        <div v-else class="model-grid">
          <article v-for="model in models" :key="model.id" class="model-row">
            <div>
              <strong>{{ model.display_name }}</strong>
              <span>{{ model.provider }} · {{ model.model }}</span>
            </div>
            <div class="model-tags">
              <span v-if="model.selected_for.length">{{ model.selected_for.join(", ") }}</span>
              <span :class="{ muted: !model.ready }">{{ model.ready ? "ready" : model.api_key_env }}</span>
            </div>
          </article>
          <div v-if="sideBusy" class="loading-row">
            <Loader2 class="spin" :size="18" />
            正在同步模型状态
          </div>
          <div class="runtime-summary">
            <CircleAlert :size="18" />
            <span>当前选择：{{ prettyJson(modelSelection) }}</span>
          </div>
        </div>
      </section>
    </section>
  </main>
</template>
