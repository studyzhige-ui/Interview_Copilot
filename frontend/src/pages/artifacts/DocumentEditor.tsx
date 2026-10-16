import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  Download,
  History,
  Plus,
  Save,
  Trash2,
  Undo2,
} from "lucide-react";
import {
  getDocumentDraft,
  saveDocumentDraft,
  publishDocument,
  downloadText,
  type DocumentDraft,
  type ResumeDocument,
} from "@/api/careerWorkspace";
import { listArtifactVersions } from "@/api/artifacts";
import { extractErr } from "@/api/client";
import { useAuthStore } from "@/store/authStore";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { Spinner } from "@/components/ui/Spinner";
import { useRefreshCareer, careerError } from "../career/useCareerWorkspace";
import { displayDate } from "../career/CareerFields";
import { copilotObjectHandoffHref } from "@/lib/copilotObjectReference";
import { downloadFileAsset } from "@/api/fileAssets";

const PdfPreview = lazy(() => import("./PdfPreview"));

export function DocumentEditor({ id }: { id: string }) {
  const query = useQuery({
    queryKey: ["document-draft", id],
    queryFn: () => getDocumentDraft(id),
    gcTime: 0,
    staleTime: 0,
    refetchInterval: (q) => (q.state.data?.awaiting_extraction ? 2500 : false),
  });
  if (query.isPending)
    return (
      <div className="career-loading">
        <Spinner />
        正在打开文档…
      </div>
    );
  if (!query.data)
    return (
      <div className="career-empty" role="alert">
        <h2>文档暂时无法打开</h2>
        <Btn onClick={() => query.refetch()}>重试</Btn>
      </div>
    );
  return (
    <Editor
      key={`${id}:${query.data.awaiting_extraction}`}
      initial={query.data}
    />
  );
}

function Editor({ initial }: { initial: DocumentDraft }) {
  const [draft, setDraft] = useState(initial);
  const current = useRef(initial);
  const saved = useRef(JSON.stringify([initial.title, initial.data]));
  const request = useRef<Promise<DocumentDraft> | null>(null);
  const [status, setStatus] = useState("saved");
  const [error, setError] = useState("");
  const [mode, setMode] = useState("write");
  const [history, setHistory] = useState(false);
  const [busy, setBusy] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const saveAttempt = useRef<{ fingerprint: string; key: string } | null>(null);
  const publishAttempt = useRef<{ revision: number; key: string } | null>(null);
  const [conflict, setConflict] = useState<DocumentDraft | null>(null);
  const [pdfPreview, setPdfPreview] = useState(false);
  const [params, setParams] = useSearchParams();
  const historicalId = params.get("version");
  const [undo, setUndo] = useState<
    Array<{ title: string; data: ResumeDocument }>
  >([]);
  const user = useAuthStore((s) => s.subjectId);
  const storageKey = `career-document:${user}:${initial.artifact_id}`;
  const [recoverable, setRecoverable] = useState<{
    title: string;
    data: ResumeDocument;
  } | null>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) ?? "null");
      return value?.data?.schema_version === 1 &&
        JSON.stringify([value.title, value.data]) !==
          JSON.stringify([initial.title, initial.data])
        ? value
        : null;
    } catch {
      return null;
    }
  });
  const refresh = useRefreshCareer();
  const versions = useQuery({
    queryKey: ["artifact", initial.artifact_id, "versions"],
    queryFn: () => listArtifactVersions(initial.artifact_id),
  });
  const historical = versions.data?.find((v) => v.id === historicalId);
  const shownData = historical
    ? ((historical.document_json as ResumeDocument | undefined) ?? {
        ...initial.data,
        name: "",
        headline: "",
        contact: "",
        summary: "",
        sections: [
          {
            id: "legacy",
            title: historical.title,
            content: historical.content_text ?? "",
          },
        ],
      })
    : draft.data;
  const readOnly =
    Boolean(historicalId) || initial.archived || initial.awaiting_extraction;
  const update = (patch: Partial<Pick<DocumentDraft, "title" | "data">>) => {
    if (readOnly || publishing) return;
    setUndo((stack) => [
      ...stack.slice(-99),
      { title: current.current.title, data: current.current.data },
    ]);
    const next = { ...current.current, ...patch };
    current.current = next;
    setDraft(next);
    setStatus("changed");
    setError("");
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({ title: next.title, data: next.data }),
      );
    } catch {
      setError("设备存储空间不足，请保持页面打开并保存到服务器。");
    }
  };
  const save = async (force = false): Promise<DocumentDraft> => {
    if (request.current) await request.current;
    const snapshot = current.current;
    const serialized = JSON.stringify([snapshot.title, snapshot.data]);
    if (!force && saved.current === serialized) return snapshot;
    setStatus("saving");
    const fingerprint = JSON.stringify([
      snapshot.revision,
      snapshot.base_version_id,
      serialized,
    ]);
    if (saveAttempt.current?.fingerprint !== fingerprint)
      saveAttempt.current = { fingerprint, key: crypto.randomUUID() };
    const pending = saveDocumentDraft(snapshot.artifact_id, {
      operation_key: saveAttempt.current.key,
      title: snapshot.title || "未命名文档",
      data: snapshot.data,
      expected_revision: snapshot.revision,
      base_version_id: snapshot.base_version_id,
    });
    request.current = pending;
    try {
      const result = await pending;
      saved.current = serialized;
      const next = {
        ...current.current,
        revision: result.revision,
        base_version_id: result.base_version_id,
        current_version_id: result.current_version_id,
      };
      current.current = next;
      setDraft(next);
      setStatus(
        saved.current === JSON.stringify([next.title, next.data])
          ? "saved"
          : "changed",
      );
      setError("");
      if (saved.current === JSON.stringify([next.title, next.data])) {
        try {
          localStorage.removeItem(storageKey);
        } catch {
          /* Server save is authoritative even if device storage is unavailable. */
        }
      }
      return next;
    } catch (cause) {
      setStatus("error");
      setError(extractErr(cause));
      throw cause;
    } finally {
      request.current = null;
    }
  };
  useEffect(() => {
    if (status !== "changed" || readOnly) return;
    const timer = setTimeout(() => {
      void save().catch(() => {});
    }, 900);
    return () => clearTimeout(timer);
    // save uses the latest draft and serializes requests through request.current.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, status, readOnly]);
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => {
      if (
        saved.current !==
        JSON.stringify([current.current.title, current.current.data])
      ) {
        event.preventDefault();
      }
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, []);
  const field = (
    key: "name" | "headline" | "contact" | "summary",
    label: string,
    multiline = false,
  ) => (
    <label>
      {label}
      {multiline ? (
        <textarea
          value={draft.data[key]}
          onChange={(e) =>
            update({ data: { ...draft.data, [key]: e.target.value } })
          }
        />
      ) : (
        <input
          value={draft.data[key]}
          onChange={(e) =>
            update({ data: { ...draft.data, [key]: e.target.value } })
          }
        />
      )}
    </label>
  );
  if (historicalId && !historical)
    return (
      <div
        className="career-empty"
        role={versions.isPending ? "status" : "alert"}
      >
        <h2>
          {versions.isPending ? "正在读取历史版本…" : "无法读取这个历史版本"}
        </h2>
        <Btn onClick={() => setParams({})}>返回当前草稿</Btn>
      </div>
    );
  return (
    <>
      <Link to="/artifacts" className="career-back">
        <ArrowLeft size={15} />
        简历与材料
      </Link>
      <header className="document-editor-heading">
        <input
          aria-label="文档名称"
          value={historical?.title ?? draft.title}
          readOnly={readOnly || publishing}
          onChange={(e) => update({ title: e.target.value })}
        />
        <small aria-live="polite">
          {historicalId
            ? "历史版本 · 只读"
            : {
                saved: "草稿已保存",
                changed: "等待保存",
                saving: "正在保存…",
                error: "保存失败",
              }[status]}
        </small>
        <button
          className="career-icon-button"
          aria-label="版本历史"
          onClick={() => setHistory(true)}
        >
          <History size={16} />
        </button>
        <Btn
          kind="outline"
          size="sm"
          icon={<Download size={14} />}
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const { exportResumePdf } = await import("./ResumePdf");
              await exportResumePdf(
                shownData,
                historical?.title ?? draft.title,
              );
            } catch (cause) {
              careerError(cause);
            } finally {
              setBusy(false);
            }
          }}
        >
          导出 PDF
        </Btn>
        {!readOnly && (
          <Btn
            size="sm"
            icon={<Save size={14} />}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setPublishing(true);
              try {
                let next = await save(current.current.revision === 0);
                while (
                  saved.current !==
                  JSON.stringify([current.current.title, current.current.data])
                )
                  next = await save();
                if (publishAttempt.current?.revision !== next.revision)
                  publishAttempt.current = {
                    revision: next.revision,
                    key: crypto.randomUUID(),
                  };
                const published = await publishDocument(
                  next,
                  publishAttempt.current.key,
                );
                current.current = published;
                setDraft(published);
                await versions.refetch();
                await refresh();
              } catch (cause) {
                careerError(cause);
              } finally {
                setBusy(false);
                setPublishing(false);
              }
            }}
          >
            保存正式版本
          </Btn>
        )}
      </header>
      {error && (
        <div className="document-save-error" role="alert">
          {error}{" "}
          <button onClick={() => void save().catch(() => {})}>重试保存</button>{" "}
          ·{" "}
          <button
            onClick={async () => {
              try {
                setConflict(await getDocumentDraft(initial.artifact_id));
              } catch (cause) {
                careerError(cause);
              }
            }}
          >
            比较服务器版本
          </button>{" "}
          ·{" "}
          <button
            onClick={() =>
              downloadText(
                JSON.stringify(current.current, null, 2),
                `${draft.title}.json`,
              )
            }
          >
            下载本地草稿
          </button>
        </div>
      )}
      {recoverable && (
        <div className="document-save-error">
          这个设备上有尚未同步的草稿。
          <button
            onClick={() => {
              update(recoverable);
              setRecoverable(null);
            }}
          >
            恢复设备草稿
          </button>{" "}
          ·{" "}
          <button
            onClick={() => {
              localStorage.removeItem(storageKey);
              setRecoverable(null);
            }}
          >
            使用服务器版本
          </button>
        </div>
      )}
      {historicalId && (
        <div className="document-save-error">
          正在查看 v{historical?.version_no ?? "…"}。
          <button onClick={() => setParams({})}>返回当前草稿</button>
          {historical && !initial.archived && (
            <button
              className="ml-4"
              onClick={() => {
                setParams({});
                const next = {
                  ...current.current,
                  title: historical.title,
                  data: shownData,
                };
                current.current = next;
                setDraft(next);
                setStatus("changed");
                try {
                  localStorage.setItem(
                    storageKey,
                    JSON.stringify({ title: next.title, data: next.data }),
                  );
                } catch {
                  setError("设备草稿未保存，请保持页面打开。");
                }
              }}
            >
              恢复到草稿
            </button>
          )}
        </div>
      )}
      <div className="document-editor-layout">
        <aside className="document-controls">
          <fieldset disabled={publishing} className="min-w-0">
            <nav className="career-tabs">
              <button
                aria-current={mode === "write" ? "page" : undefined}
                onClick={() => setMode("write")}
              >
                内容
              </button>
              <button
                aria-current={mode === "design" ? "page" : undefined}
                onClick={() => setMode("design")}
              >
                样式
              </button>
            </nav>
            {readOnly ? (
              <p className="career-muted">
                {initial.awaiting_extraction
                  ? "正在提取原文件。完成后可编辑；解析失败时请返回材料库重试。原文件始终可以下载。"
                  : initial.archived
                    ? "已归档文档可查看和导出。"
                    : "历史版本保留原始内容，不会随当前草稿改变。"}
              </p>
            ) : mode === "write" ? (
              <>
                {field("name", "姓名 / 标题")}
                {field("headline", "求职标题")}
                {field("contact", "联系方式", true)}
                {field("summary", "个人简介", true)}
                {draft.data.sections.map((section, index) => (
                  <div className="document-section-controls" key={section.id}>
                    <input
                      aria-label={`章节 ${index + 1} 标题`}
                      value={section.title}
                      onChange={(e) =>
                        update({
                          data: {
                            ...draft.data,
                            sections: draft.data.sections.map((s) =>
                              s.id === section.id
                                ? { ...s, title: e.target.value }
                                : s,
                            ),
                          },
                        })
                      }
                    />
                    <textarea
                      aria-label={`${section.title}内容`}
                      rows={7}
                      value={section.content}
                      onChange={(e) =>
                        update({
                          data: {
                            ...draft.data,
                            sections: draft.data.sections.map((s) =>
                              s.id === section.id
                                ? { ...s, content: e.target.value }
                                : s,
                            ),
                          },
                        })
                      }
                    />
                    <div>
                      <button
                        aria-label={`上移${section.title}`}
                        disabled={index === 0}
                        onClick={() => {
                          const sections = [...draft.data.sections];
                          [sections[index - 1], sections[index]] = [
                            sections[index],
                            sections[index - 1],
                          ];
                          update({ data: { ...draft.data, sections } });
                        }}
                      >
                        <ArrowUp size={13} />
                      </button>
                      <button
                        aria-label={`下移${section.title}`}
                        disabled={index === draft.data.sections.length - 1}
                        onClick={() => {
                          const sections = [...draft.data.sections];
                          [sections[index + 1], sections[index]] = [
                            sections[index],
                            sections[index + 1],
                          ];
                          update({ data: { ...draft.data, sections } });
                        }}
                      >
                        <ArrowDown size={13} />
                      </button>
                      <button
                        aria-label={`删除${section.title}`}
                        onClick={() =>
                          update({
                            data: {
                              ...draft.data,
                              sections: draft.data.sections.filter(
                                (s) => s.id !== section.id,
                              ),
                            },
                          })
                        }
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                ))}
                <button
                  className="career-text-button"
                  onClick={() =>
                    update({
                      data: {
                        ...draft.data,
                        sections: [
                          ...draft.data.sections,
                          {
                            id: crypto.randomUUID(),
                            title: "新章节",
                            content: "",
                          },
                        ],
                      },
                    })
                  }
                >
                  <Plus size={14} />
                  添加章节
                </button>
              </>
            ) : (
              <>
                <label>
                  版式
                  <select
                    value={draft.data.template}
                    onChange={(e) =>
                      update({
                        data: {
                          ...draft.data,
                          template: e.target
                            .value as ResumeDocument["template"],
                        },
                      })
                    }
                  >
                    <option value="classic">经典 · 清晰单栏</option>
                    <option value="modern">现代 · 醒目页眉</option>
                  </select>
                </label>
                <label>
                  主题颜色
                  <select
                    value={draft.data.accent}
                    onChange={(e) =>
                      update({
                        data: {
                          ...draft.data,
                          accent: e.target.value as ResumeDocument["accent"],
                        },
                      })
                    }
                  >
                    <option value="forest">森林绿</option>
                    <option value="slate">石墨灰</option>
                    <option value="blue">深海蓝</option>
                  </select>
                </label>
                <label>
                  正文字号
                  <select
                    value={draft.data.font_size}
                    onChange={(e) =>
                      update({
                        data: {
                          ...draft.data,
                          font_size: Number(e.target.value),
                        },
                      })
                    }
                  >
                    {[9, 10, 11, 12, 13, 14].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </label>
                <p className="career-muted">
                  PDF 导出使用 A4 分页和嵌入式中文字体，文字可选择和检索。
                </p>
              </>
            )}
            {!readOnly && (
              <button
                className="career-text-button"
                disabled={!undo.length}
                onClick={() => {
                  const previous = undo.at(-1);
                  if (previous) {
                    const next = { ...current.current, ...previous };
                    current.current = next;
                    setDraft(next);
                    setUndo(undo.slice(0, -1));
                    setStatus("changed");
                    try {
                      localStorage.setItem(
                        storageKey,
                        JSON.stringify(previous),
                      );
                    } catch {
                      setError("设备草稿未保存，请保持页面打开。");
                    }
                  }
                }}
              >
                <Undo2 size={14} />
                撤销上一步
              </button>
            )}
            <Link
              className="career-text-button"
              to={copilotObjectHandoffHref(
                "artifact",
                initial.artifact_id,
                draft.title,
              )}
            >
              与 Copilot 打磨表达 ↗
            </Link>
            <button
              className="career-text-button"
              onClick={() =>
                downloadText(
                  JSON.stringify(
                    {
                      title: historical?.title ?? draft.title,
                      data: shownData,
                    },
                    null,
                    2,
                  ),
                  `${draft.title}.json`,
                  "application/json",
                )
              }
            >
              导出 JSON
            </button>
            <button
              className="career-text-button"
              onClick={() =>
                downloadText(
                  [
                    `# ${shownData.name || draft.title}`,
                    shownData.headline,
                    shownData.contact,
                    shownData.summary,
                    ...shownData.sections.map(
                      (s) => `## ${s.title}\n${s.content}`,
                    ),
                  ]
                    .filter(Boolean)
                    .join("\n\n"),
                  `${draft.title}.md`,
                  "text/markdown;charset=utf-8",
                )
              }
            >
              导出 Markdown
            </button>
            {(historical ?? versions.data?.[0])?.file_asset_id && (
              <button
                className="career-text-button"
                onClick={() =>
                  void downloadFileAsset(
                    (historical ?? versions.data![0]).file_asset_id!,
                    draft.title,
                  ).catch(careerError)
                }
              >
                下载原始文件
              </button>
            )}
          </fieldset>
        </aside>
        <div className="document-canvas">
          <div className="flex justify-end gap-4 mb-3 text-xs text-stone-500">
            <button
              aria-pressed={!pdfPreview}
              onClick={() => setPdfPreview(false)}
            >
              编辑预览
            </button>
            <button
              aria-pressed={pdfPreview}
              onClick={() => setPdfPreview(true)}
            >
              PDF 分页预览
            </button>
          </div>
          {pdfPreview ? (
            <Suspense fallback={<Spinner />}>
              <PdfPreview
                data={shownData}
                title={historical?.title ?? draft.title}
              />
            </Suspense>
          ) : (
            <ResumePaper
              data={shownData}
              title={historical?.title ?? draft.title}
            />
          )}
        </div>
      </div>
      {conflict && (
        <Modal
          open
          title="比较尚未同步的修改"
          onClose={() => setConflict(null)}
        >
          <p className="career-muted">
            选择要继续编辑的内容。当前正式版本和投递历史会保留。
          </p>
          <div className="career-overview-grid">
            {[
              { label: "本设备草稿", value: draft },
              { label: "服务器草稿", value: conflict },
            ].map(({ label, value }) => (
              <section key={label}>
                <h3>
                  {label} · {value.title}
                </h3>
                <p className="career-jd max-h-64 overflow-auto">
                  {[
                    value.data.name,
                    value.data.summary,
                    ...value.data.sections.map(
                      (s) => `${s.title}\n${s.content}`,
                    ),
                  ].join("\n\n")}
                </p>
              </section>
            ))}
          </div>
          <div className="flex gap-3 mt-5">
            <Btn
              onClick={() => {
                const next = {
                  ...conflict,
                  title: current.current.title,
                  data: current.current.data,
                  base_version_id: conflict.current_version_id,
                };
                saved.current = JSON.stringify([conflict.title, conflict.data]);
                current.current = next;
                setDraft(next);
                setStatus("changed");
                setError("");
                setConflict(null);
              }}
            >
              继续保存本设备内容
            </Btn>
            <Btn
              kind="outline"
              onClick={() => {
                current.current = conflict;
                saved.current = JSON.stringify([conflict.title, conflict.data]);
                setDraft(conflict);
                setStatus("saved");
                setError("");
                setConflict(null);
                try {
                  localStorage.removeItem(storageKey);
                } catch {
                  /* Device cache is optional. */
                }
              }}
            >
              使用服务器内容
            </Btn>
          </div>
        </Modal>
      )}
      {history && (
        <Modal open title="正式版本历史" onClose={() => setHistory(false)}>
          <p className="career-muted">
            每个正式版本都可以查看、导出或恢复到草稿。
          </p>
          {versions.isError && <p role="alert">读取失败，请重试。</p>}
          {versions.data?.map((v) => (
            <button
              key={v.id}
              className="career-document-row w-full"
              onClick={() => {
                setParams({ version: v.id });
                setHistory(false);
              }}
            >
              <span>
                v{v.version_no} · {v.title}
                <small>{displayDate(v.created_at)}</small>
              </span>
            </button>
          ))}
        </Modal>
      )}
    </>
  );
}

export function ResumePaper({
  data,
  title,
}: {
  data: ResumeDocument;
  title: string;
}) {
  const accent = { forest: "#476c4a", slate: "#394957", blue: "#356587" }[
    data.accent
  ];
  return (
    <article
      className={`resume-paper ${data.template}`}
      style={
        {
          "--resume-accent": accent,
          fontSize: `${data.font_size}px`,
        } as CSSProperties
      }
      aria-label="简历预览"
    >
      <header>
        <h1>{data.name || title}</h1>
        <p>{data.headline}</p>
        <small>{data.contact}</small>
      </header>
      {data.summary && <p className="whitespace-pre-line">{data.summary}</p>}
      {data.sections.map((s) => (
        <section key={s.id}>
          <h2>{s.title}</h2>
          <p>{s.content || " "}</p>
        </section>
      ))}
    </article>
  );
}
