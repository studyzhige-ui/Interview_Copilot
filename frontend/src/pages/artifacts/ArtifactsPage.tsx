import { useRef, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Copy,
  FileText,
  Plus,
  Search,
  Upload,
  Star,
  Archive,
  Download,
} from "lucide-react";
import {
  archiveArtifact,
  restoreArtifact,
  listAllArtifacts,
} from "@/api/artifacts";
import { getCareerProfile } from "@/api/careerProfile";
import {
  createResumeFromFile,
  listResumes,
  setDefaultResume,
  retryResumeParse,
  replaceResumeFromFile,
} from "@/api/resumes";
import { downloadFileAsset } from "@/api/fileAssets";
import {
  blankDocument,
  createDocument,
  type ResumeDocument,
} from "@/api/careerWorkspace";
import type { Artifact, PersonalFact } from "@/types/career";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { FormItem, TextInput, SelectInput } from "../career/CareerFields";
import { careerError, useRefreshCareer } from "../career/useCareerWorkspace";
import { DocumentEditor } from "./DocumentEditor";

export function ArtifactsPage() {
  const { artifactId } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("我的简历");
  const [newKind, setNewKind] = useState("resume");
  const [useProfile, setUseProfile] = useState(true);
  const [busy, setBusy] = useState(false);
  const [archive, setArchive] = useState<Artifact | null>(null);
  const [replacing, setReplacing] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const refresh = useRefreshCareer();
  const query = useQuery({
    queryKey: ["artifacts", "library", archived],
    queryFn: () => listAllArtifacts(archived),
    enabled: !artifactId,
  });
  const resumes = useQuery({
    queryKey: ["resumes"],
    queryFn: () => listResumes(),
    enabled: !artifactId,
    refetchInterval: (q) =>
      q.state.data?.some((r) =>
        ["pending", "processing"].includes(r.parse_status),
      )
        ? 2500
        : false,
  });
  const openCreate = creating || Boolean(params.get("create"));
  const profile = useQuery({
    queryKey: ["career-profile"],
    queryFn: getCareerProfile,
    enabled: openCreate,
  });
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (error) {
      careerError(error);
    } finally {
      setBusy(false);
    }
  };
  if (artifactId)
    return (
      <div className="career-workspace">
        <DocumentEditor key={artifactId} id={artifactId} />
      </div>
    );
  const visible =
    query.data?.filter(
      (d) =>
        (archived ? Boolean(d.archived_at) : true) &&
        (!kind || d.kind === kind) &&
        d.current_version.title
          .toLocaleLowerCase()
          .includes(search.toLocaleLowerCase()),
    ) ?? [];
  return (
    <div className="career-workspace">
      <header className="career-page-heading">
        <div>
          <p className="career-eyebrow">MAKE YOUR EXPERIENCE COUNT</p>
          <h1>把经历，写成你的下一步。</h1>
          <p>为不同岗位准备合适的简历，保留每一次正式版本。</p>
        </div>
        <div className="flex gap-2">
          <Btn
            kind="outline"
            icon={<Upload size={14} />}
            disabled={busy}
            onClick={() => {
              setReplacing(null);
              file.current?.click();
            }}
          >
            导入
          </Btn>
          <Btn icon={<Plus size={15} />} onClick={() => setCreating(true)}>
            新建文档
          </Btn>
        </div>
      </header>
      <div className="career-toolbar">
        <label className="career-search">
          <Search size={16} />
          <input
            aria-label="搜索材料"
            placeholder="搜索文档…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <SelectInput
          aria-label="材料类型"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="!w-auto"
        >
          <option value="">全部文档</option>
          <option value="resume">简历</option>
          <option value="cover_letter">求职信</option>
          <option value="portfolio">作品集说明</option>
        </SelectInput>
        <label className="career-muted ml-auto flex gap-2">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => setArchived(e.target.checked)}
          />
          已归档
        </label>
      </div>
      <input
        ref={file}
        hidden
        type="file"
        accept=".pdf,.doc,.docx,.txt,.md,.json"
        onChange={async (e) => {
          const picked = e.target.files?.[0];
          e.target.value = "";
          if (!picked) return;
          await run(async () => {
            if (picked.name.endsWith(".json")) {
              const value = JSON.parse(await picked.text());
              const result = await createDocument(
                {
                  title: value.title || picked.name,
                  kind: "resume",
                  data: value.data,
                },
                crypto.randomUUID(),
              );
              navigate(`/artifacts/${result.artifact_id}`);
            } else if (replacing) {
              await replaceResumeFromFile(replacing, picked);
            } else {
              const result = await createResumeFromFile(picked);
              navigate(`/artifacts/${result.id}`);
            }
          });
        }}
      />
      {query.isError ? (
        <div role="alert" className="career-empty">
          <h2>材料读取失败</h2>
          <Btn onClick={() => query.refetch()}>重新加载</Btn>
        </div>
      ) : query.isPending ? (
        <div className="career-loading">正在读取文档…</div>
      ) : visible.length ? (
        <div className="document-grid">
          {visible.map((d) => {
            const data = d.current_version.document_json as unknown as
              | ResumeDocument
              | undefined;
            const resume = resumes.data?.find((r) => r.id === d.id);
            return (
              <article className="document-card" key={d.id}>
                <button
                  className="document-card-preview w-full text-left"
                  onClick={() => navigate(`/artifacts/${d.id}`)}
                  aria-label={`打开 ${d.current_version.title}`}
                >
                  <div className="document-card-sheet">
                    <strong>{data?.name || d.current_version.title}</strong>
                    <small>
                      {data?.headline ||
                        (d.kind === "resume" ? "个人简历" : "申请材料")}
                    </small>
                    <p>
                      {data
                        ? [
                            data.summary,
                            ...data.sections.map(
                              (s) => `${s.title}\n${s.content}`,
                            ),
                          ].join("\n\n")
                        : d.current_version.content_text?.slice(0, 450) ||
                          "文件文档 · 原件已保存"}
                    </p>
                  </div>
                </button>
                <Link className="document-card-title" to={`/artifacts/${d.id}`}>
                  {d.current_version.title}
                </Link>
                <div className="document-card-footer">
                  <span>
                    {d.kind === "resume"
                      ? "简历"
                      : d.kind === "cover_letter"
                        ? "求职信"
                        : "材料"}{" "}
                    · v{d.current_version.version_no}
                    {resume?.is_default ? " · 默认" : ""}
                  </span>
                  <button
                    aria-label={`复制 ${d.current_version.title}`}
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        const created = await createDocument(
                          {
                            title: `${d.current_version.title} · 副本`,
                            kind: [
                              "resume",
                              "cover_letter",
                              "portfolio",
                            ].includes(d.kind)
                              ? d.kind
                              : "portfolio",
                            data: data ?? {
                              ...blankDocument(),
                              sections: [
                                {
                                  id: crypto.randomUUID(),
                                  title: "内容",
                                  content: d.current_version.content_text ?? "",
                                },
                              ],
                            },
                          },
                          crypto.randomUUID(),
                        );
                        navigate(`/artifacts/${created.artifact_id}`);
                      })
                    }
                  >
                    <Copy size={13} />
                  </button>
                  {d.archived_at && (
                    <button
                      disabled={busy}
                      onClick={() => run(() => restoreArtifact(d.id))}
                    >
                      恢复
                    </button>
                  )}
                  {!d.archived_at && (
                    <button
                      aria-label={`归档 ${d.current_version.title}`}
                      onClick={() => setArchive(d)}
                    >
                      <Archive size={13} />
                    </button>
                  )}
                </div>
                {resume && (
                  <div className="document-card-footer">
                    {resume.parse_status === "failed" ? (
                      <button
                        disabled={busy}
                        onClick={() => run(() => retryResumeParse(resume.id))}
                      >
                        解析失败 · 重试
                      </button>
                    ) : ["pending", "processing"].includes(
                        resume.parse_status,
                      ) ? (
                      <span>正在提取原文…</span>
                    ) : (
                      <span>可用于面试准备</span>
                    )}
                    {!resume.is_default && (
                      <button
                        aria-label={`设为默认 ${resume.title}`}
                        disabled={busy}
                        onClick={() => run(() => setDefaultResume(resume.id))}
                      >
                        <Star size={13} />
                      </button>
                    )}
                    {resume.file_asset_id && (
                      <>
                        <button
                          aria-label={`下载原件 ${resume.title}`}
                          onClick={() =>
                            run(() =>
                              downloadFileAsset(
                                resume.file_asset_id!,
                                resume.title,
                              ),
                            )
                          }
                        >
                          <Download size={13} />
                        </button>
                        <button
                          disabled={busy}
                          onClick={() => {
                            setReplacing(resume.id);
                            file.current?.click();
                          }}
                        >
                          替换文件
                        </button>
                      </>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="career-empty">
          <FileText size={30} />
          <h2>
            {search || kind || archived
              ? "没有符合条件的文档"
              : "让你的经历，有一份好的呈现"}
          </h2>
          <p>从个人档案创建一份简历，或导入已有文件。</p>
          <Btn kind="outline" onClick={() => setCreating(true)}>
            创建第一份文档
          </Btn>
        </div>
      )}
      {openCreate && (
        <Modal
          open
          title="创建一份新文档"
          onClose={() => {
            setCreating(false);
            setParams({});
          }}
          footer={
            <Btn
              loading={busy}
              disabled={!title.trim() || (useProfile && profile.isPending)}
              onClick={() =>
                run(async () => {
                  const data =
                    useProfile && profile.data
                      ? fromProfile(
                          profile.data.personal_facts.map((f) => f.value),
                        )
                      : blankDocument();
                  const result = await createDocument(
                    {
                      title,
                      kind: params.get("create") || newKind,
                      data,
                      opportunity_id: params.get("opportunity") || undefined,
                    },
                    crypto.randomUUID(),
                  );
                  setCreating(false);
                  navigate(`/artifacts/${result.artifact_id}`);
                })
              }
            >
              创建文档
            </Btn>
          }
        >
          <div className="career-form">
            <FormItem label="文档名称">
              <TextInput
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </FormItem>
            <FormItem label="文档类型">
              <SelectInput
                value={params.get("create") || newKind}
                onChange={(e) => {
                  setNewKind(e.target.value);
                  const next = new URLSearchParams(params);
                  next.delete("create");
                  setParams(next);
                }}
              >
                <option value="resume">简历</option>
                <option value="cover_letter">求职信</option>
                <option value="portfolio">作品集说明</option>
              </SelectInput>
            </FormItem>
            <label className="career-muted flex gap-2">
              <input
                type="checkbox"
                checked={useProfile}
                onChange={(e) => setUseProfile(e.target.checked)}
              />
              从已确认的个人档案复制经历
            </label>
            <p className="career-muted">
              创建后可以独立编辑，不会修改个人档案。
            </p>
          </div>
        </Modal>
      )}
      {archive && (
        <Modal
          open
          title="归档这份文档？"
          onClose={() => setArchive(null)}
          footer={
            <Btn
              loading={busy}
              onClick={() =>
                run(async () => {
                  await archiveArtifact(archive.id);
                  setArchive(null);
                })
              }
            >
              归档
            </Btn>
          }
        >
          <p className="career-muted">
            {archive.current_version.title}{" "}
            将移入归档。已保存的历史版本和投递记录仍然可查看。
          </p>
        </Modal>
      )}
    </div>
  );
}

function fromProfile(facts: PersonalFact[]): ResumeDocument {
  const data = blankDocument();
  data.sections = [];
  const labels: Partial<Record<PersonalFact["kind"], string>> = {
    experience: "工作经历",
    education: "教育背景",
    project: "项目经历",
    skill: "专业技能",
    certificate: "资格证书",
    achievement: "荣誉成果",
    volunteer: "志愿经历",
    organization: "组织经历",
  };
  for (const fact of facts) {
    if (fact.kind === "personal") {
      data.name = fact.name;
      continue;
    }
    if (fact.kind === "summary") {
      data.summary = fact.text;
      continue;
    }
    if (fact.kind === "contact" || fact.kind === "location") {
      data.contact += (data.contact ? " · " : "") + fact.value;
      continue;
    }
    const title = labels[fact.kind];
    if (!title) continue;
    let section = data.sections.find((s) => s.title === title);
    if (!section) {
      section = { id: crypto.randomUUID(), title, content: "" };
      data.sections.push(section);
    }
    const values = Object.entries(fact)
      .filter(
        ([key, value]) =>
          key !== "kind" &&
          key !== "ongoing" &&
          value !== null &&
          value !== undefined &&
          value !== "",
      )
      .map(([, value]) =>
        Array.isArray(value) ? value.join("、") : String(value),
      );
    section.content += (section.content ? "\n\n" : "") + values.join("\n");
  }
  if (!data.sections.length) data.sections = blankDocument().sections;
  return data;
}
