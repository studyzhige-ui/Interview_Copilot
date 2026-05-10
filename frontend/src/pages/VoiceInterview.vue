<script setup lang="ts">
import { ref, nextTick, computed } from "vue";
import { useRouter } from "vue-router";
import { Mic, Square, Sparkles, Activity, Loader2, CheckCircle2, ArrowRight, Send } from "lucide-vue-next";
import { store } from "../store";
import {
  createMockSession,
  startMockInterview,
  submitMockAnswer,
  finishMockInterview,
  fetchTTSAudio,
} from "../api";

// ── State ──────────────────────────────────────────────────────────────

type InterviewState = "idle" | "preparing" | "ai_speaking" | "user_turn" | "processing" | "finishing" | "done";

const state = ref<InterviewState>("idle");
const sessionId = ref("");
const planPhases = ref<{ phase_id: string; phase_name: string; question_count: number }[]>([]);
const currentPhase = ref("");
const totalAnswered = ref(0);
const errorMsg = ref("");

// Conversation log
interface ChatEntry {
  role: "interviewer" | "user";
  text: string;
}
const chatLog = ref<ChatEntry[]>([]);
const chatContainer = ref<HTMLElement | null>(null);

// Speech recognition
const transcript = ref("");
const isListening = ref(false);
let recognition: any = null;

// Text input fallback
const textInput = ref("");
const hasSpeechSupport = ref(
  typeof window !== "undefined" &&
  ("SpeechRecognition" in window || "webkitSpeechRecognition" in window)
);

// Audio playback
const audioElement = ref<HTMLAudioElement | null>(null);

// Debrief redirect
const router = useRouter();
const debriefSessionId = ref("");

const phaseNames: Record<string, string> = {
  self_intro: "自我介绍",
  resume_deep_dive: "简历深挖",
  technical: "技术基础",
  behavioral: "行为面试",
  reverse_qa: "反问环节",
};

const currentPhaseName = computed(() => {
  const p = planPhases.value.find((ph) => ph.phase_id === currentPhase.value);
  return p?.phase_name || phaseNames[currentPhase.value] || currentPhase.value;
});

// ── Actions ────────────────────────────────────────────────────────────

async function startInterview() {
  state.value = "preparing";
  errorMsg.value = "";
  chatLog.value = [];
  try {
    sessionId.value = await createMockSession(store.token);
    const result = await startMockInterview(store.token, sessionId.value);
    planPhases.value = result.plan_phases;

    const firstQ = result.current_question;
    if (firstQ.done) {
      errorMsg.value = "面试计划生成失败";
      state.value = "idle";
      return;
    }

    currentPhase.value = firstQ.phase_id || "";

    // Interviewer's opening + first question
    const opening = `你好，我是今天的面试官，很高兴认识你。我们开始吧。\n\n${firstQ.question}`;
    chatLog.value.push({ role: "interviewer", text: opening });
    await speakText(opening);
    state.value = "user_turn";
  } catch (e: any) {
    errorMsg.value = e.message || "启动失败";
    state.value = "idle";
  }
}

async function speakText(text: string) {
  state.value = "ai_speaking";
  try {
    const blob = await fetchTTSAudio(store.token, text);
    const url = URL.createObjectURL(blob);
    await new Promise<void>((resolve, reject) => {
      const audio = new Audio(url);
      audioElement.value = audio as any;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        audioElement.value = null;
        resolve();
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        audioElement.value = null;
        reject(new Error("Audio playback failed"));
      };
      audio.play().catch(reject);
    });
  } catch {
    // TTS failed, continue silently (text is still shown)
  }
}

function startListening() {
  if (!hasSpeechSupport.value) {
    errorMsg.value = "你的浏览器不支持语音识别，请使用下方文字输入框回答。";
    return;
  }

  errorMsg.value = "";
  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.continuous = true;
  recognition.interimResults = true;

  let finalTranscript = "";

  recognition.onresult = (event: any) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      } else {
        interim += event.results[i][0].transcript;
      }
    }
    transcript.value = finalTranscript + interim;
  };

  recognition.onerror = (event: any) => {
    if (event.error === "not-allowed") {
      errorMsg.value = "麦克风权限被拒绝，请在浏览器设置中允许麦克风访问，或使用下方文字输入。";
      isListening.value = false;
    } else if (event.error === "no-speech") {
      errorMsg.value = "未检测到语音，请确认麦克风正常后重试，或使用下方文字输入。";
    } else if (event.error !== "aborted") {
      console.error("Speech recognition error:", event.error);
      errorMsg.value = `语音识别错误: ${event.error}，可使用文字输入。`;
    }
  };

  recognition.onend = () => {
    isListening.value = false;
  };

  transcript.value = "";
  finalTranscript = "";
  isListening.value = true;
  recognition.start();
}

async function stopAndSubmit() {
  if (recognition) {
    recognition.stop();
    // Wait briefly for final results to arrive
    await new Promise((r) => setTimeout(r, 300));
    recognition = null;
  }
  isListening.value = false;

  const answer = transcript.value.trim();
  if (!answer) {
    errorMsg.value = "没有检测到语音内容，请重试或使用下方文字输入框。";
    return;
  }

  await doSubmitAnswer(answer);
  transcript.value = "";
}

async function submitTextAnswer() {
  const answer = textInput.value.trim();
  if (!answer) return;
  textInput.value = "";
  await doSubmitAnswer(answer);
}

function handleTextKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    submitTextAnswer();
  }
}

async function doSubmitAnswer(answer: string) {
  errorMsg.value = "";
  chatLog.value.push({ role: "user", text: answer });
  scrollToBottom();

  state.value = "processing";
  try {
    const result = await submitMockAnswer(store.token, sessionId.value, answer);
    currentPhase.value = result.phase_progress.current_phase;
    totalAnswered.value = result.phase_progress.total_answered;

    if (result.is_finished) {
      const closing = result.interviewer_response || "好的，今天的面试就到这里，感谢你的时间。";
      chatLog.value.push({ role: "interviewer", text: closing });
      await speakText(closing);
      await finishAndRedirect();
    } else {
      chatLog.value.push({ role: "interviewer", text: result.interviewer_response });
      scrollToBottom();
      await speakText(result.interviewer_response);
      state.value = "user_turn";
    }
  } catch (e: any) {
    errorMsg.value = e.message || "提交失败";
    state.value = "user_turn";
  }
}

async function finishAndRedirect() {
  state.value = "finishing";
  try {
    const result = await finishMockInterview(store.token, sessionId.value);
    debriefSessionId.value = result.debrief_session_id;
    state.value = "done";
  } catch (e: any) {
    errorMsg.value = e.message || "生成分析报告失败";
    state.value = "done";
  }
}

function goToDebrief() {
  if (debriefSessionId.value) {
    router.push(`/chat?session=${debriefSessionId.value}`);
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
    }
  });
}
</script>

<template>
  <div class="voice-page">
    <!-- Header -->
    <div class="hero-section">
      <div class="title-wrap">
        <Sparkles class="sparkle-icon" :size="24" />
        <h1 class="h1">AI 语音模拟面试</h1>
      </div>
      <p class="subtitle">
        {{ state === "idle" ? "高度还原真实面试场景，实时语音对话，结束后自动进入复盘。" : currentPhaseName }}
      </p>
    </div>

    <!-- Phase progress bar -->
    <div v-if="planPhases.length" class="phase-bar">
      <div
        v-for="(phase, i) in planPhases"
        :key="phase.phase_id"
        :class="['phase-item', {
          active: phase.phase_id === currentPhase,
          completed: planPhases.findIndex(p => p.phase_id === currentPhase) > i || state === 'done',
        }]"
      >
        <span class="phase-dot"></span>
        <span class="phase-label">{{ phase.phase_name }}</span>
      </div>
    </div>

    <!-- Error message -->
    <div v-if="errorMsg" class="error-banner" @click="errorMsg = ''">
      ⚠️ {{ errorMsg }}
    </div>

    <!-- Idle state: start button -->
    <div v-if="state === 'idle'" class="start-area">
      <div class="start-card glass-panel">
        <Activity :size="48" color="var(--border-strong)" />
        <p>准备好了吗？点击开始模拟面试。</p>
        <p class="hint">面试过程中请使用语音回答，AI 面试官会用语音提问。</p>
        <button class="start-btn hover-lift" @click="startInterview">
          <Sparkles :size="18" /> 开始面试
        </button>
      </div>
    </div>

    <!-- Preparing state -->
    <div v-if="state === 'preparing'" class="preparing-area">
      <Loader2 :size="48" class="spinner" />
      <p>正在生成面试计划...</p>
    </div>

    <!-- Active interview area -->
    <div v-if="state !== 'idle' && state !== 'preparing'" class="interview-area">
      <!-- Chat log -->
      <div ref="chatContainer" class="chat-log glass-panel">
        <div v-for="(entry, i) in chatLog" :key="i" :class="['chat-entry', entry.role]">
          <span class="chat-role">{{ entry.role === "interviewer" ? "🤖 面试官" : "👤 你" }}</span>
          <p class="chat-text">{{ entry.text }}</p>
        </div>

        <!-- Live transcript while recording -->
        <div v-if="isListening && transcript" class="chat-entry user live">
          <span class="chat-role">👤 你 (识别中...)</span>
          <p class="chat-text">{{ transcript }}</p>
        </div>
      </div>

      <!-- Visualizer / status -->
      <div class="status-bar">
        <div v-if="state === 'ai_speaking'" class="status-indicator ai-speaking">
          <div class="waves">
            <div class="bar" style="animation-delay: 0.1s"></div>
            <div class="bar" style="animation-delay: 0.2s"></div>
            <div class="bar" style="animation-delay: 0.3s"></div>
            <div class="bar" style="animation-delay: 0.1s"></div>
            <div class="bar" style="animation-delay: 0.4s"></div>
          </div>
          <span>面试官正在说话...</span>
        </div>
        <div v-else-if="state === 'processing'" class="status-indicator processing">
          <Loader2 :size="20" class="spinner" />
          <span>正在处理...</span>
        </div>
        <div v-else-if="state === 'finishing'" class="status-indicator processing">
          <Loader2 :size="20" class="spinner" />
          <span>正在生成分析报告...</span>
        </div>
      </div>

      <!-- Controls -->
      <div v-if="state === 'user_turn'" class="controls">
        <div class="mic-row">
          <button
            v-if="!isListening"
            class="record-btn hover-lift"
            @click="startListening"
          >
            <Mic :size="28" />
          </button>
          <button
            v-else
            class="record-btn recording hover-lift"
            @click="stopAndSubmit"
          >
            <Square :size="28" fill="currentColor" />
          </button>
          <span class="status-text">{{ isListening ? "正在倾听... 说完后点击停止" : "点击麦克风开始回答" }}</span>
        </div>
        <!-- Text input fallback -->
        <div class="text-input-row">
          <input
            v-model="textInput"
            type="text"
            class="text-input"
            placeholder="语音不可用？在此输入文字回答..."
            @keydown="handleTextKeydown"
          />
          <button class="send-btn hover-lift" @click="submitTextAnswer" :disabled="!textInput.trim()">
            <Send :size="18" />
          </button>
        </div>
      </div>

      <!-- Done: redirect to debrief -->
      <div v-if="state === 'done'" class="done-area">
        <div class="done-card glass-panel">
          <CheckCircle2 :size="48" color="var(--success)" />
          <h3>面试结束</h3>
          <p>分析报告已生成，点击下方按钮进入面试复盘。</p>
          <button class="debrief-btn hover-lift" @click="goToDebrief">
            <ArrowRight :size="18" /> 进入复盘
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.voice-page {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding-bottom: 40px;
}

.hero-section {
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  padding: 16px 0;
}

.title-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sparkle-icon {
  color: var(--secondary);
}

.subtitle {
  color: var(--text-secondary);
  font-size: 1rem;
}

/* Phase progress bar */
.phase-bar {
  display: flex;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.phase-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-full);
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
  font-size: 0.8rem;
  color: var(--text-muted);
  transition: all var(--transition-fast);
}

.phase-item.active {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
  font-weight: 600;
}

.phase-item.completed {
  background: var(--bg-surface);
  color: var(--success);
  border-color: var(--success);
}

.phase-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

/* Error */
.error-banner {
  padding: 12px 16px;
  background: #fef2f2;
  color: #dc2626;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: 0.875rem;
}

/* Start area */
.start-area, .preparing-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 40px 0;
}

.start-card, .done-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 40px;
  text-align: center;
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
}

.hint {
  color: var(--text-muted);
  font-size: 0.875rem;
}

.start-btn, .debrief-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 32px;
  border-radius: var(--radius-full);
  background: linear-gradient(135deg, var(--primary), var(--secondary));
  color: white;
  font-size: 1rem;
  font-weight: 600;
  box-shadow: 0 4px 16px rgba(59, 130, 246, 0.3);
  transition: all var(--transition-fast);
  margin-top: 8px;
}

.start-btn:hover, .debrief-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.4);
}

.spinner {
  animation: spin 1s linear infinite;
  color: var(--primary);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Interview area */
.interview-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Chat log */
.chat-log {
  max-height: 400px;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
}

.chat-entry {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chat-role {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-muted);
}

.chat-entry.interviewer .chat-role {
  color: var(--secondary);
}

.chat-text {
  padding: 12px 16px;
  border-radius: var(--radius-md);
  line-height: 1.7;
  white-space: pre-line;
}

.chat-entry.interviewer .chat-text {
  background: linear-gradient(135deg, #f0e6ff, #e8f0fe);
  color: var(--text-primary);
}

.chat-entry.user .chat-text {
  background: var(--bg-app);
  color: var(--text-primary);
}

.chat-entry.live .chat-text {
  border: 2px dashed var(--primary);
  opacity: 0.7;
}

/* Status bar */
.status-bar {
  display: flex;
  justify-content: center;
  min-height: 40px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.waves {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 24px;
}

.bar {
  width: 4px;
  background: linear-gradient(180deg, var(--secondary), var(--primary));
  border-radius: var(--radius-full);
  animation: equalize 0.8s infinite ease-in-out;
}

@keyframes equalize {
  0%, 100% { height: 6px; }
  50% { height: 24px; }
}

/* Controls */
.controls {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.mic-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.record-btn {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: var(--primary);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.35);
  transition: all var(--transition-fast);
}

.record-btn.recording {
  background: var(--error);
  box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.2);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
  70% { box-shadow: 0 0 0 16px rgba(239, 68, 68, 0); }
  100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}

.status-text {
  font-weight: 500;
  font-size: 0.875rem;
  color: var(--text-secondary);
}

/* Text input fallback */
.text-input-row {
  display: flex;
  gap: 8px;
  width: 100%;
  max-width: 600px;
}

.text-input {
  flex: 1;
  padding: 12px 16px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-light);
  background: var(--bg-surface);
  font-size: 0.95rem;
  outline: none;
  transition: border-color var(--transition-fast);
}

.text-input:focus {
  border-color: var(--primary);
}

.send-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--primary);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Done area */
.done-area {
  display: flex;
  justify-content: center;
  padding: 20px 0;
}

.done-card h3 {
  font-size: 1.25rem;
  font-weight: 600;
}
</style>
