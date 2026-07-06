import type { ModelRole } from '@/types/api';

// Brand colors for the vendor avatar tile. Static — these don't come from
// the backend, and they shouldn't be user-configurable. Provider ids
// without a colour fall back to a neutral stone tone, which is fine.
export const BRAND_COLORS: Record<string, string> = {
  deepseek:     '#3A6AC1',
  openai:       '#10A37F',
  anthropic:    '#C26A4A',
  gemini:       '#4285F4',
  qwen:         '#7A5BC0',
  moonshot:     '#1E4A78',
  zai:          '#0F62FE',
  xiaomi:       '#FF6900',
  nvidia_nim:   '#76B900',
  mistral:      '#FE5D26',
  cohere:       '#FF7A0E',
  groq:         '#F55036',
  together_ai:  '#0F76FB',
  fireworks_ai: '#F58025',
  perplexity:   '#1C4D5F',
  xai:          '#000000',
  novita:       '#7B61FF',
};

// Visible rows in each vendor card's scrollable model list. 2 rows is
// the original design intent — keeps the page compact when there are
// 9+ vendor cards. The "下滑查看全部" hint + the vendor's tier_rank sort
// (highest-priority models at top) mean the first 2 are always the
// recommended choices; users with the rare "show me every model" need
// just scroll the card.
export const MODELS_VISIBLE_ROWS = 2;
export const MODEL_ROW_HEIGHT_PX = 64;
export const MODEL_ROW_GAP_PX = 8;

export const ROLE_DESC: Record<ModelRole, { label: string; short: string }> = {
  primary:        { label: '主对话', short: '主' },
  agent:          { label: 'Agent · 工具调用', short: 'A' },
  mock_interview: { label: '模拟面试', short: '模' },
};
export const ROLES: ModelRole[] = ['primary', 'agent', 'mock_interview'];
