import type { AnalysisPayload, MemoryItem, MessageItem, ModelProfile, SessionListItem } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export function authHeader(token: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "string" ? body : body.detail ?? body.message ?? "请求失败";
    throw new ApiError(message, response.status);
  }
  return body as T;
}

export async function register(username: string, password: string, email?: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, email: email || null })
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
    body
  });
  const payload = await parseResponse<{ access_token: string }>(response);
  return payload.access_token;
}

export async function createSession(token: string): Promise<string> {
  const response = await fetch(`${API_BASE}/api/v1/chat/sessions`, {
    method: "POST",
    headers: authHeader(token)
  });
  const payload = await parseResponse<{ session_id: string }>(response);
  return payload.session_id;
}

export async function listSessions(token: string): Promise<SessionListItem[]> {
  const response = await fetch(`${API_BASE}/api/v1/chat/sessions`, {
    headers: authHeader(token)
  });
  return parseResponse<SessionListItem[]>(response);
}

export async function getHistory(token: string, sessionId: string): Promise<MessageItem[]> {
  const response = await fetch(`${API_BASE}/api/v1/chat/history?session_id=${encodeURIComponent(sessionId)}&limit=80`, {
    headers: authHeader(token)
  });
  return parseResponse<MessageItem[]>(response);
}

export async function streamChat(
  token: string,
  sessionId: string,
  message: string,
  onChunk: (chunk: string) => void
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/chat/sse/${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: {
      ...authHeader(token),
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ message })
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
      const data = JSON.parse(line.slice(6));
      if (data.type === "chunk") onChunk(data.content);
    }
  }
}

export async function uploadAndAnalyze(token: string, file: File): Promise<{ interview_id: number; task_id: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const uploadResponse = await fetch(`${API_BASE}/api/v1/upload/audio/direct`, {
    method: "POST",
    headers: authHeader(token),
    body: formData
  });
  const upload = await parseResponse<{ file_path: string }>(uploadResponse);
  const analyzeResponse = await fetch(`${API_BASE}/api/v1/analyze`, {
    method: "POST",
    headers: {
      ...authHeader(token),
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ file_path: upload.file_path })
  });
  return parseResponse(analyzeResponse);
}

export async function getAnalysisStatus(token: string, interviewId: number): Promise<AnalysisPayload> {
  const response = await fetch(`${API_BASE}/api/v1/analyze/${interviewId}/status`, {
    headers: authHeader(token)
  });
  return parseResponse(response);
}

export async function listModels(token: string): Promise<{ selection: Record<string, string>; profiles: ModelProfile[] }> {
  const response = await fetch(`${API_BASE}/api/v1/models/catalog`, {
    headers: authHeader(token)
  });
  return parseResponse(response);
}

export async function listMemory(token: string): Promise<MemoryItem[]> {
  const response = await fetch(`${API_BASE}/api/v1/memory/items`, {
    headers: authHeader(token)
  });
  const payload = await parseResponse<{ items: MemoryItem[] }>(response);
  return payload.items;
}

export async function getAnalyticsReport(token: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/api/v1/analytics/report`, {
    headers: authHeader(token)
  });
  return parseResponse(response);
}
