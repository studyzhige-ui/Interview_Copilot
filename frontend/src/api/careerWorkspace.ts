import { apiClient } from "./client";
import type {
  Artifact,
  ArtifactVersion,
  JobOpportunity,
  NextAction,
  ProcessEvent,
} from "@/types/career";

export const stages = [
  { id: "saved", label: "待投递", color: "#8c9289" },
  { id: "applied", label: "已投递", color: "#6389a5" },
  { id: "screening", label: "筛选 / 测评", color: "#a49060" },
  { id: "interview", label: "面试", color: "#8b79a5" },
  { id: "offer", label: "Offer", color: "#47876b" },
  { id: "in_process", label: "进行中", color: "#6f9792" },
  { id: "closed", label: "已结束", color: "#aaa59e" },
] as const;
export type Stage = (typeof stages)[number]["id"];
export interface Contact {
  name: string;
  role: string;
  email: string;
  phone: string;
}
export interface WorkspaceJob extends JobOpportunity {
  version: number;
  stage: Stage;
  notes: string;
  contacts: Contact[];
  hidden: boolean;
  next_action: NextAction | null;
  next_interview: { id: string; title: string; starts_at: string } | null;
}
export interface JobDetail extends WorkspaceJob {
  merged_sources: Array<{
    id: string;
    company_name: string;
    job_title: string;
  }>;
  events: Array<ProcessEvent & { active: boolean }>;
  actions: NextAction[];
  documents: Artifact[];
  submissions: Array<{
    id: string;
    submitted_at: string;
    version: ArtifactVersion;
  }>;
  interviews: Array<{
    id: string;
    title: string;
    source: string;
    schedule_version: number;
    opportunity: {
      id: string;
      version: number;
      company_name: string;
      job_title: string;
    };
    scheduled_start_at: string | null;
    scheduled_end_at: string | null;
    scheduled_location: string | null;
    meeting_url: string | null;
    stage_label: string | null;
  }>;
}
export interface ResumeDocument {
  schema_version: 1;
  name: string;
  headline: string;
  contact: string;
  summary: string;
  sections: Array<{ id: string; title: string; content: string }>;
  template: "classic" | "modern";
  accent: "forest" | "slate" | "blue";
  font_size: number;
}
export interface DocumentDraft {
  artifact_id: string;
  kind: string;
  archived: boolean;
  awaiting_extraction: boolean;
  revision: number;
  base_version_id: string;
  current_version_id: string;
  title: string;
  data: ResumeDocument;
  updated_at: string;
}
export const blankDocument = (): ResumeDocument => ({
  schema_version: 1,
  name: "",
  headline: "",
  contact: "",
  summary: "",
  sections: [
    { id: crypto.randomUUID(), title: "工作经历", content: "" },
    { id: crypto.randomUUID(), title: "项目经历", content: "" },
    { id: crypto.randomUUID(), title: "教育背景", content: "" },
  ],
  template: "classic",
  accent: "forest",
  font_size: 11,
});
export const careerKeys = {
  all: ["career-workspace"] as const,
  job: (id: string) => ["career-workspace", "job", id] as const,
};
export async function getJobs(
  params: {
    q?: string;
    stage?: string;
    closed?: boolean;
    hidden?: boolean;
    offset?: number;
    limit?: number;
  } = {},
) {
  return (
    await apiClient.get<{
      items: WorkspaceJob[];
      total: number;
      counts: Record<Stage, number>;
    }>("/career-workspace/jobs", {
      params: { ...params, stage: params.stage || undefined },
    })
  ).data;
}
export async function getJob(id: string) {
  return (
    await apiClient.get<JobDetail>(
      `/career-workspace/jobs/${encodeURIComponent(id)}`,
    )
  ).data;
}
export async function saveJob(
  input: {
    company_name: string;
    job_title: string;
    location: string;
    source_url: string;
    description: string;
  },
  operationKey: string,
) {
  return (
    await apiClient.post<JobDetail>("/career-workspace/jobs", {
      ...input,
      operation_key: operationKey,
    })
  ).data;
}
export async function editJob(
  job: WorkspaceJob,
  input: {
    company_name: string;
    job_title: string;
    location: string;
    source_url: string;
    notes: string;
    contacts: Contact[];
    hidden: boolean;
  },
) {
  return (
    await apiClient.patch<JobDetail>(
      `/career-workspace/jobs/${encodeURIComponent(job.id)}`,
      { ...input, expected_version: job.version },
    )
  ).data;
}
export async function moveJob(
  job: WorkspaceJob,
  input: {
    stage: Stage;
    outcome?: string;
    note?: string;
    channel?: string;
    version_ids?: string[];
    occurred_at?: string;
  },
  operationKey: string,
) {
  return (
    await apiClient.post<JobDetail>(
      `/career-workspace/jobs/${encodeURIComponent(job.id)}/stage`,
      {
        ...input,
        expected_version: job.version,
        operation_key: operationKey,
        occurred_at: input.occurred_at ?? new Date().toISOString(),
      },
    )
  ).data;
}
export async function createDocument(
  input: {
    title: string;
    kind: string;
    data: ResumeDocument;
    opportunity_id?: string;
  },
  operationKey: string,
) {
  return (
    await apiClient.post<DocumentDraft>("/career-workspace/documents", {
      ...input,
      operation_key: operationKey,
    })
  ).data;
}
export async function getDocumentDraft(id: string) {
  return (
    await apiClient.get<DocumentDraft>(
      `/career-workspace/documents/${encodeURIComponent(id)}/draft`,
    )
  ).data;
}
export async function saveDocumentDraft(
  id: string,
  body: {
    title: string;
    data: ResumeDocument;
    expected_revision: number;
    base_version_id: string;
    operation_key: string;
  },
) {
  return (
    await apiClient.put<DocumentDraft>(
      `/career-workspace/documents/${encodeURIComponent(id)}/draft`,
      body,
    )
  ).data;
}
export async function publishDocument(
  draft: DocumentDraft,
  operationKey: string,
) {
  return (
    await apiClient.post<DocumentDraft>(
      `/career-workspace/documents/${encodeURIComponent(draft.artifact_id)}/publish`,
      { expected_revision: draft.revision, operation_key: operationKey },
    )
  ).data;
}
export function downloadText(
  content: string,
  filename: string,
  type = "text/plain;charset=utf-8",
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
