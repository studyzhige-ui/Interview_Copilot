import type { AnalysisPayload, MemoryItem, MessageItem, ModelProfile, SessionListItem } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

// ---------------------------------------------------------------------------
// Token management
// ---------------------------------------------------------------------------

function getAccessToken(): string {
  return localStorage.getItem("interview-copilot-token") ?? "";
}

function getRefreshToken(): string {
  return localStorage.getItem("interview-copilot-refresh-token") ?? "";
}

function setTokens(access: string, refresh: string): void {
  localStorage.setItem("interview-copilot-token", access);
  localStorage.setItem("interview-copilot-refresh-token", refresh);
}

export function clearTokens(): void {
  localStorage.removeItem("interview-copilot-token");
  localStorage.removeItem("interview-copilot-refresh-token");
}

export function authHeader(token: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ---------------------------------------------------------------------------
// Auto-refresh wrapper
// ---------------------------------------------------------------------------

let _refreshPromise: Promise<string> | null = null;

async function tryRefreshToken(): Promise<string> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) throw new ApiError("No refresh token", 401);

  const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    clearTokens();
    throw new ApiError("Refresh token expired", 401);
  }

  const payload = await response.json();
  setTokens(payload.access_token, payload.refresh_token);
  return payload.access_token;
}

/**
 * Fetch wrapper that automatically retries once with a refreshed token
 * when the server returns 401.
 */
async function authedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = getAccessToken();
  const headers = { ...authHeader(token), ...(init?.headers ?? {}) };
  let response = await fetch(input, { ...init, headers });

  if (response.status === 401 && getRefreshToken()) {
    // Deduplicate concurrent refresh attempts.
    if (!_refreshPromise) {
      _refreshPromise = tryRefreshToken().finally(() => {
        _refreshPromise = null;
      });
    }
    try {
      const newToken = await _refreshPromise;
      const retryHeaders = { ...authHeader(newToken), ...(init?.headers ?? {}) };
      response = await fetch(input, { ...init, headers: retryHeaders });
    } catch {
      // Refresh failed — return the original 401 response.
    }
  }

  return response;
}

// ---------------------------------------------------------------------------
// Response parsing
// ---------------------------------------------------------------------------

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "string" ? body : body.detail ?? body.message ?? "请求失败";
    throw new ApiError(message, response.status);
  }
  return body as T;
}

// ---------------------------------------------------------------------------
// Auth endpoints (no auto-refresh needed)
// ---------------------------------------------------------------------------

export async function register(username: string, password: string, email?: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, email: email || null }),
  });
  await parseResponse(response);
}

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams();
  body.set("username", username);
  body.set("password", password);
  const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const payload = await parseResponse<{ access_token: string; refresh_token: string }>(response);
  setTokens(payload.access_token, payload.refresh_token);
  return payload.access_token;
}

// ---------------------------------------------------------------------------
// Authenticated API endpoints (use authedFetch for auto-refresh)
// ---------------------------------------------------------------------------

export async function createSession(token: string): Promise<string> {
  const response = await authedFetch(`${API_BASE}/api/v1/chat/sessions`, {
    method: "POST",
  });
  const payload = await parseResponse<{ session_id: string }>(response);
  return payload.session_id;
}

export async function listSessions(token: string): Promise<SessionListItem[]> {
  const response = await authedFetch(`${API_BASE}/api/v1/chat/sessions`);
  return parseResponse<SessionListItem[]>(response);
}

export async function getHistory(token: string, sessionId: string): Promise<MessageItem[]> {
  const response = await authedFetch(
    `${API_BASE}/api/v1/chat/history?session_id=${encodeURIComponent(sessionId)}&limit=80`
  );
  return parseResponse<MessageItem[]>(response);
}

export async function streamChat(
  token: string,
  sessionId: string,
  message: string,
  onChunk: (chunk: string) => void
): Promise<void> {
  const response = await authedFetch(`${API_BASE}/api/v1/chat/sse/${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok || !response.body) {
    await parseResponse(response);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      const line = event.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      try {
        const data = JSON.parse(line.slice(6));
        if (data.type === "chunk") onChunk(data.content);
      } catch {
        // Ignore malformed SSE events to prevent stream breakage.
      }
    }
  }
}

export async function uploadAndAnalyze(token: string, file: File): Promise<{ interview_id: number; task_id: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const uploadResponse = await authedFetch(`${API_BASE}/api/v1/upload/audio/direct`, {
    method: "POST",
    body: formData,
  });
  const upload = await parseResponse<{ upload_id: string }>(uploadResponse);
  const analyzeResponse = await authedFetch(`${API_BASE}/api/v1/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upload_id: upload.upload_id }),
  });
  return parseResponse(analyzeResponse);
}

export async function getAnalysisStatus(token: string, interviewId: number): Promise<AnalysisPayload> {
  const response = await authedFetch(`${API_BASE}/api/v1/analyze/${interviewId}/status`);
  return parseResponse(response);
}

export async function listModels(token: string): Promise<{ selection: Record<string, string>; profiles: ModelProfile[] }> {
  const response = await authedFetch(`${API_BASE}/api/v1/models/catalog`);
  return parseResponse(response);
}

export async function listMemory(token: string): Promise<MemoryItem[]> {
  const response = await authedFetch(`${API_BASE}/api/v1/memory/items`);
  const payload = await parseResponse<{ items: MemoryItem[] }>(response);
  return payload.items;
}

export async function getAnalyticsReport(token: string): Promise<unknown> {
  const response = await authedFetch(`${API_BASE}/api/v1/analytics/report`);
  return parseResponse(response);
}

// ---------------------------------------------------------------------------
// Mock Interview endpoints
// ---------------------------------------------------------------------------

export async function createMockSession(token: string, title?: string): Promise<string> {
  const response = await authedFetch(`${API_BASE}/api/v1/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_type: "mock_interview", title: title || "模拟面试" }),
  });
  const payload = await parseResponse<{ session_id: string }>(response);
  return payload.session_id;
}

export async function startMockInterview(
  token: string,
  sessionId: string,
  resumeUploadId?: string,
): Promise<{
  status: string;
  plan_phases: { phase_id: string; phase_name: string; question_count: number }[];
  current_question: { done: boolean; question?: string; phase_id?: string; phase_name?: string };
}> {
  const response = await authedFetch(`${API_BASE}/api/v1/chat/mock-interview/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, resume_upload_id: resumeUploadId || null }),
  });
  return parseResponse(response);
}

export async function submitMockAnswer(
  token: string,
  sessionId: string,
  answer: string,
): Promise<{
  interviewer_response: string;
  is_finished: boolean;
  phase_progress: { current_phase: string; question_idx: number; total_answered: number };
}> {
  const response = await authedFetch(`${API_BASE}/api/v1/chat/mock-interview/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, answer }),
  });
  return parseResponse(response);
}

export async function finishMockInterview(
  token: string,
  sessionId: string,
): Promise<{
  status: string;
  record_id: string;
  debrief_session_id: string;
  summary: Record<string, unknown>;
}> {
  const response = await authedFetch(
    `${API_BASE}/api/v1/chat/mock-interview/finish?session_id=${encodeURIComponent(sessionId)}`,
    { method: "POST" },
  );
  return parseResponse(response);
}

export async function fetchTTSAudio(token: string, text: string, voice?: string): Promise<Blob> {
  const response = await authedFetch(`${API_BASE}/api/v1/chat/mock-interview/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice: voice || null }),
  });
  if (!response.ok) {
    const msg = await response.text();
    throw new ApiError(msg, response.status);
  }
  return response.blob();
}
