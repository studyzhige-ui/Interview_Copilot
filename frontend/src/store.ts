import { reactive } from 'vue';
import type { SessionListItem, MessageItem, ModelProfile, MemoryItem } from './types';
import { clearTokens } from './api';

export const store = reactive({
  token: localStorage.getItem("interview-copilot-token") ?? "",
  username: localStorage.getItem("interview-copilot-username") ?? "",
  sessions: [] as SessionListItem[],
  activeSessionId: "",
  messages: [] as MessageItem[],
  models: [] as ModelProfile[],
  modelSelection: {} as Record<string, string>,
  memoryItems: [] as MemoryItem[],
  analyticsReport: null as unknown,
  
  get isAuthed() {
    return Boolean(this.token);
  },
  
  get activeSession() {
    return this.sessions.find(item => item.session_id === this.activeSessionId);
  },
  
  get readyModels() {
    return this.models.filter(model => model.ready).length;
  },

  get memorySummary() {
    return this.memoryItems.slice(0, 5);
  },

  setToken(newToken: string) {
    this.token = newToken;
  },

  setUsername(newUsername: string) {
    this.username = newUsername;
    localStorage.setItem("interview-copilot-username", newUsername);
  },

  logout() {
    this.token = "";
    clearTokens();
    this.sessions = [];
    this.messages = [];
    this.activeSessionId = "";
  }
});
