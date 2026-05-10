<template>
  <div v-if="events.length > 0" class="agent-trace">
    <div
      class="trace-header"
      @click="expanded = !expanded"
      role="button"
      tabindex="0"
    >
      <span class="trace-icon">{{ expanded ? '▼' : '▶' }}</span>
      <span class="trace-title">工具执行过程</span>
      <span class="trace-badge">{{ toolCount }} 次调用</span>
    </div>

    <transition name="trace-slide">
      <div v-if="expanded" class="trace-body">
        <div
          v-for="(event, idx) in displayEvents"
          :key="idx"
          :class="['trace-item', `trace-${event.type}`]"
        >
          <!-- Status -->
          <template v-if="event.type === 'status'">
            <span class="item-icon">⏳</span>
            <span class="item-text">{{ event.data.message }}</span>
          </template>

          <!-- Tool Start -->
          <template v-if="event.type === 'tool_start'">
            <span class="item-icon">{{ toolEmoji(event.data.tool) }}</span>
            <span class="item-tool-name">{{ event.data.tool }}</span>
            <span class="item-args">({{ event.data.args_summary }})</span>
          </template>

          <!-- Tool Done -->
          <template v-if="event.type === 'tool_done'">
            <span class="item-indent"></span>
            <span class="item-icon">{{ event.data.is_error ? '❌' : '✅' }}</span>
            <span class="item-result">{{ event.data.result_summary }}</span>
            <span class="item-latency">{{ event.data.tool_latency_ms }}ms</span>
          </template>

          <!-- Error -->
          <template v-if="event.type === 'error'">
            <span class="item-icon">⚠️</span>
            <span class="item-error">{{ event.data.error }}</span>
          </template>

          <!-- Budget -->
          <template v-if="event.type === 'budget'">
            <span class="item-icon">📊</span>
            <span class="item-text">
              {{ event.data.steps }} 步 · {{ event.data.tool_calls }} 次工具调用 ·
              {{ Math.round(event.data.elapsed_s * 10) / 10 }}s
            </span>
          </template>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

interface HarnessEvent {
  type: string
  data: Record<string, unknown>
  step: number
  elapsed_ms: number
}

const props = defineProps<{
  events: HarnessEvent[]
}>()

const expanded = ref(false)

const toolCount = computed(() =>
  props.events.filter(e => e.type === 'tool_done').length
)

const displayEvents = computed(() =>
  props.events.filter(e =>
    ['tool_start', 'tool_done', 'error', 'budget'].includes(e.type)
  )
)

const TOOL_EMOJIS: Record<string, string> = {
  web_search: '🔍',
  read_url: '📄',
  read_file: '📂',
  write_file: '💾',
  recall_memory: '🧠',
  save_memory: '💾',
  search_knowledge: '📚',
  read_resume: '📄',
  read_interview_history: '📊',
  search_jobs: '💼',
}

function toolEmoji(name: string): string {
  return TOOL_EMOJIS[name] || '🔧'
}
</script>

<style scoped>
.agent-trace {
  margin-top: 0.75rem;
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 8px;
  overflow: hidden;
  font-size: 0.85rem;
  background: var(--bg-secondary, #f8fafc);
}

.trace-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  user-select: none;
  background: var(--bg-tertiary, #f1f5f9);
}

.trace-header:hover {
  background: var(--bg-hover, #e2e8f0);
}

.trace-icon {
  font-size: 0.7rem;
  color: var(--text-secondary, #64748b);
}

.trace-title {
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}

.trace-badge {
  margin-left: auto;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  background: var(--accent-bg, #dbeafe);
  color: var(--accent-text, #1d4ed8);
  font-size: 0.75rem;
  font-weight: 500;
}

.trace-body {
  padding: 0.5rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.trace-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0;
  line-height: 1.4;
}

.trace-tool_done {
  padding-left: 1.5rem;
}

.item-tool-name {
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}

.item-args {
  color: var(--text-secondary, #64748b);
  font-family: monospace;
  font-size: 0.8rem;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-result {
  color: var(--text-primary, #334155);
}

.item-latency {
  margin-left: auto;
  color: var(--text-muted, #94a3b8);
  font-size: 0.75rem;
  font-family: monospace;
}

.item-error {
  color: var(--error-text, #dc2626);
}

.item-text {
  color: var(--text-secondary, #64748b);
}

.trace-slide-enter-active,
.trace-slide-leave-active {
  transition: all 0.2s ease;
}
.trace-slide-enter-from,
.trace-slide-leave-to {
  opacity: 0;
  max-height: 0;
}
</style>
