<script setup lang="ts">
import { ref, onMounted, nextTick } from "vue";
import { UserRound, Bot, Sparkles, Send, Loader2, MessageSquarePlus } from "lucide-vue-next";
import { store } from "../store";
import { createSession, listSessions, getHistory, streamChat, ApiError } from "../api";

const draft = ref("");
const isStreaming = ref(false);
const chatError = ref("");
const messageList = ref<HTMLElement | null>(null);

async function scrollToBottom() {
  await nextTick();
  if (messageList.value) {
    messageList.value.scrollTop = messageList.value.scrollHeight;
  }
}

async function refreshSessions() {
  if (!store.token) return;
  store.sessions = await listSessions(store.token);
  if (!store.activeSessionId && store.sessions.length > 0) {
    store.activeSessionId = store.sessions[0].session_id;
  }
  if (store.activeSessionId) {
    await loadHistory(store.activeSessionId);
  }
}

async function startSession() {
  if (!store.token) return;
  store.activeSessionId = await createSession(store.token);
  await refreshSessions();
  store.messages = [];
}

async function loadHistory(sessionId: string) {
  store.activeSessionId = sessionId;
  store.messages = await getHistory(store.token, sessionId);
  await scrollToBottom();
}

async function sendMessage() {
  const content = draft.value.trim();
  if (!content || !store.token || !store.activeSessionId || isStreaming.value) return;

  chatError.value = "";
  draft.value = "";
  store.messages.push({
    seq: Date.now(),
    role: "user",
    content,
    created_at: new Date().toISOString()
  });
  
  const assistantMessage = {
    seq: Date.now() + 1,
    role: "assistant",
    content: "",
    created_at: new Date().toISOString()
  };
  store.messages.push(assistantMessage);
  isStreaming.value = true;
  await scrollToBottom();

  try {
    await streamChat(store.token, store.activeSessionId, content, (chunk) => {
      assistantMessage.content += chunk;
      void scrollToBottom();
    });
    await refreshSessions();
  } catch (error) {
    chatError.value = error instanceof ApiError ? error.message : "流式对话失败。";
    assistantMessage.content ||= "对话请求没有完成，请检查后端服务。";
  } finally {
    isStreaming.value = false;
  }
}

function shortDate(value?: string) {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
  }).format(date);
}

onMounted(() => {
  if (store.token) {
    refreshSessions();
  }
});
</script>

<template>
  <div class="chat-container">
    <aside class="session-sidebar">
      <div class="session-header">
        <div class="header-text">
          <h3>会话历史</h3>
          <span class="badge">{{ store.sessions.length }}</span>
        </div>
        <button class="icon-btn hover-lift" @click="startSession" title="新建会话">
          <MessageSquarePlus :size="18" />
        </button>
      </div>
      
      <div class="session-list">
        <button 
          v-for="session in store.sessions" 
          :key="session.session_id"
          :class="['session-item', { active: session.session_id === store.activeSessionId }]"
          @click="loadHistory(session.session_id)"
        >
          <span class="session-title">{{ session.title }}</span>
          <span class="session-meta">{{ session.turn_count }} 轮 · {{ shortDate(session.updated_at) }}</span>
        </button>
      </div>
    </aside>

    <div class="chat-main">
      <div ref="messageList" class="message-list">
        <div v-if="store.messages.length === 0" class="empty-state">
          <div class="empty-icon-wrap flex-center"><Sparkles :size="32" color="var(--primary)" /></div>
          <h3>开始一次面试复盘</h3>
          <p>您可以直接贴上题目、简历项目、JD，或让 Copilot 基于您的长期记忆继续追问。</p>
        </div>
        
        <div 
          v-for="msg in store.messages" 
          :key="msg.seq" 
          :class="['message-row', msg.role]"
        >
          <div class="avatar flex-center">
            <UserRound v-if="msg.role === 'user'" :size="18" />
            <Bot v-else :size="18" />
          </div>
          <div class="bubble glass-panel">
            {{ msg.content }}
          </div>
        </div>
      </div>
      
      <div class="composer-area">
        <p v-if="chatError" class="inline-error">{{ chatError }}</p>
        <div class="composer-box glass-panel">
          <textarea 
            v-model="draft"
            placeholder="输入面试题、项目描述或复盘问题... (Enter 发送)"
            @keydown.enter.exact.prevent="sendMessage"
          ></textarea>
          <button class="send-btn flex-center" @click="sendMessage" :disabled="!draft.trim() || isStreaming">
            <Loader2 v-if="isStreaming" class="spin" :size="20" />
            <Send v-else :size="20" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-container {
  display: flex;
  height: 100%;
  gap: 24px;
}

.session-sidebar {
  width: 280px;
  background-color: var(--bg-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.session-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-light);
  background-color: var(--bg-surface-hover);
}

.header-text {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-text h3 {
  font-size: 1rem;
  font-weight: 600;
}

.badge {
  background-color: var(--primary-light);
  color: var(--primary);
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-weight: 600;
}

.icon-btn {
  color: var(--text-secondary);
  padding: 6px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.session-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  text-align: left;
  transition: all var(--transition-fast);
  border: 1px solid transparent;
}

.session-item:hover {
  background-color: var(--bg-surface-hover);
}

.session-item.active {
  background-color: var(--primary-light);
  border-color: rgba(59, 130, 246, 0.2);
}

.session-title {
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.session-meta {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-light);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 32px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.empty-state {
  margin: auto;
  text-align: center;
  max-width: 400px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 40px;
}

.empty-icon-wrap {
  width: 64px;
  height: 64px;
  border-radius: var(--radius-full);
  background-color: var(--primary-light);
}

.empty-state h3 {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-primary);
}

.empty-state p {
  color: var(--text-secondary);
  font-size: 0.875rem;
  line-height: 1.6;
}

.message-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  max-width: 85%;
}

.message-row.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  flex-shrink: 0;
}

.message-row.user .avatar {
  background-color: var(--primary);
  color: white;
}

.message-row.assistant .avatar {
  background-color: var(--bg-app);
  color: var(--primary);
  border: 1px solid var(--border-light);
}

.bubble {
  padding: 16px 20px;
  border-radius: var(--radius-lg);
  font-size: 0.95rem;
  line-height: 1.6;
  white-space: pre-wrap;
}

.message-row.user .bubble {
  background-color: var(--primary);
  color: white;
  border-top-right-radius: 4px;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border: none;
}

.message-row.assistant .bubble {
  background-color: var(--bg-surface);
  border-top-left-radius: 4px;
}

.composer-area {
  padding: 24px;
  background-color: var(--bg-surface-hover);
  border-top: 1px solid var(--border-light);
}

.composer-box {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 12px;
  border-radius: var(--radius-lg);
  background-color: var(--bg-surface);
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}

.composer-box textarea {
  flex: 1;
  border: none;
  resize: none;
  padding: 8px 4px;
  min-height: 48px;
  max-height: 150px;
  font-size: 0.95rem;
  background: transparent;
  color: var(--text-primary);
}

.composer-box textarea::placeholder {
  color: var(--text-muted);
}

.send-btn {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background-color: var(--primary);
  color: white;
  transition: all var(--transition-fast);
}

.send-btn:not(:disabled):hover {
  background-color: var(--primary-hover);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.send-btn:disabled {
  background-color: var(--border-strong);
  cursor: not-allowed;
}

.inline-error {
  color: var(--error);
  font-size: 0.875rem;
  margin-bottom: 8px;
  padding: 8px 12px;
  background-color: var(--error-bg);
  border-radius: var(--radius-md);
}
</style>
