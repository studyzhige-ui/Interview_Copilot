import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  CalendarDays,
  Check,
  FileText,
  MapPin,
  Pencil,
  Plus,
} from "lucide-react";
import {
  getJob,
  editJob,
  createDocument,
  blankDocument,
  careerKeys,
  stages,
} from "@/api/careerWorkspace";
import {
  createJobDescriptionSnapshot,
  listJobDescriptionSnapshots,
  createNextAction,
  transitionNextAction,
  correctProcessEvent,
} from "@/api/careerProcess";
import { listAllArtifacts, relateArtifactToOpportunity } from "@/api/artifacts";
import { Modal } from "@/components/ui/Modal";
import { Btn } from "@/components/ui/Btn";
import { Spinner } from "@/components/ui/Spinner";
import {
  FormItem,
  TextInput,
  TextArea,
  SelectInput,
  displayDate,
  isoFromLocal,
} from "./CareerFields";
import { OpportunityForm, StageDialog } from "./OpportunityDialogs";
import { DirectionPicker, ProgressForm } from "./JobTools";
import { ManualInvitationForm } from "./ManualInvitationForm";
import { careerError, useRefreshCareer } from "./useCareerWorkspace";
import type { Stage, ResumeDocument } from "@/api/careerWorkspace";
import type { ProcessEvent } from "@/types/career";
import { copilotObjectHandoffHref } from "@/lib/copilotObjectReference";

function JobDescription({
  id,
  sourceUrl,
}: {
  id: string;
  sourceUrl: string | null;
}) {
  const query = useQuery({
    queryKey: [...careerKeys.job(id), "jd"],
    queryFn: () => listJobDescriptionSnapshots(id),
  });
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const latest = query.data?.at(-1);
  return (
    <section className="career-detail-section">
      <div className="career-section-heading">
        <h2>职位描述</h2>
        <button
          onClick={() => {
            setContent(latest?.canonical_content ?? "");
            setEditing(!editing);
          }}
        >
          {editing ? "取消" : latest ? "更新" : "添加"}
        </button>
      </div>
      {query.isError && (
        <p role="alert">
          读取失败。<button onClick={() => query.refetch()}>重试</button>
        </p>
      )}
      {editing ? (
        <div className="career-form">
          <TextArea
            aria-label="职位描述正文"
            rows={10}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <Btn
            loading={busy}
            disabled={!content.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                const key = crypto.randomUUID();
                await createJobDescriptionSnapshot(id, {
                  source_kind: "typed_product_ui",
                  source_identity: key,
                  source_version: "1",
                  original_url: sourceUrl ?? "",
                  observed_at: new Date().toISOString(),
                  provider: "product_ui",
                  canonical_content: content.trim(),
                  idempotency_key: key,
                });
                await query.refetch();
                setEditing(false);
              } catch (error) {
                careerError(error);
              } finally {
                setBusy(false);
              }
            }}
          >
            保存职位描述
          </Btn>
        </div>
      ) : latest ? (
        <>
          <p className="career-jd">{latest.canonical_content}</p>
          <details className="career-history">
            <summary>{query.data?.length} 个历史版本</summary>
            {query.data?.map((v) => (
              <article key={v.id}>
                <small>
                  v{v.version} · {displayDate(v.observed_at)}
                </small>
                <p className="career-jd">{v.canonical_content}</p>
              </article>
            ))}
          </details>
        </>
      ) : (
        <p className="career-muted">
          粘贴岗位要求，准备材料和面试时可以随时查看。
        </p>
      )}
    </section>
  );
}

export function OpportunityDetail({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: careerKeys.job(id),
    queryFn: () => getJob(id),
    refetchInterval: 30000,
  });
  const refresh = useRefreshCareer();
  const [directionPicker, setDirectionPicker] = useState(false);
  const [progress, setProgress] = useState(false);
  const [tab, setTab] = useState("overview");
  const [editing, setEditing] = useState(false);
  const [stage, setStage] = useState<Stage | null>(null);
  const [rescheduling, setRescheduling] = useState<
    NonNullable<typeof query.data>["interviews"][number] | undefined
  >();
  const [invitation, setInvitation] = useState(false);
  const [action, setAction] = useState(false);
  const [linking, setLinking] = useState(false);
  const [content, setContent] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [correcting, setCorrecting] = useState<ProcessEvent | null>(null);
  const [correction, setCorrection] = useState("");
  const docs = useQuery({
    queryKey: ["artifacts", "link-picker"],
    queryFn: () => listAllArtifacts(),
    enabled: linking,
  });
  const job = query.data;
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      await refresh();
      return true;
    } catch (error) {
      careerError(error);
      return false;
    } finally {
      setBusy(false);
    }
  };
  if (query.isPending)
    return (
      <div className="career-loading">
        <Spinner />
        正在读取岗位…
      </div>
    );
  if (!job)
    return (
      <div className="career-empty">
        <h2>岗位暂时无法读取</h2>
        <Btn onClick={() => query.refetch()}>重试</Btn>
        <Btn kind="outline" onClick={onClose}>
          返回列表
        </Btn>
      </div>
    );
  const pending = job.actions.filter(
    (a) => a.status === "planned" || a.status === "suggested",
  );
  return (
    <div className="career-detail">
      <button className="career-back" onClick={onClose}>
        <ArrowLeft size={15} />
        所有岗位
      </button>
      <header className="career-detail-header">
        <div className="career-company-mark">
          {job.company_name.slice(0, 1)}
        </div>
        <div className="min-w-0">
          <p className="career-eyebrow">{job.company_name}</p>
          <h1>{job.job_title}</h1>
          <p className="career-muted flex gap-3">
            {job.location && (
              <span className="flex items-center gap-1">
                <MapPin size={13} />
                {job.location}
              </span>
            )}
            {job.source_url && /^https?:\/\//i.test(job.source_url) && (
              <a href={job.source_url} target="_blank" rel="noreferrer">
                查看招聘原文 ↗
              </a>
            )}
          </p>
        </div>
        <button
          className="career-icon-button"
          onClick={() => setEditing(true)}
          aria-label="编辑岗位"
        >
          <Pencil size={17} />
        </button>
      </header>
      <div className="career-detail-actions">
        <SelectInput
          aria-label="岗位阶段"
          value={job.stage}
          disabled={busy}
          onChange={(e) => setStage(e.target.value as Stage)}
        >
          {stages.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </SelectInput>
        {!job.outcome && (
          <>
            <Btn onClick={() => setStage("applied")} disabled={busy}>
              记录投递
            </Btn>
            <Btn
              kind="outline"
              icon={<CalendarDays size={14} />}
              onClick={() => {
                setRescheduling(undefined);
                setInvitation(true);
              }}
            >
              安排面试
            </Btn>
          </>
        )}
        <Link
          className="career-text-button"
          to={copilotObjectHandoffHref(
            "job_opportunity",
            job.id,
            `${job.company_name} · ${job.job_title}`,
          )}
        >
          与 Copilot 准备 <ArrowUpRight size={14} />
        </Link>
      </div>
      <nav className="career-tabs" aria-label="岗位详情">
        {[
          ["overview", "概览"],
          ["documents", "申请材料"],
          ["interviews", "面试"],
          ["activity", "记录"],
        ].map(([value, label]) => (
          <button
            key={value}
            aria-current={tab === value ? "page" : undefined}
            onClick={() => setTab(value)}
          >
            {label}
            {value === "documents" && job.documents.length > 0 && (
              <small>{job.documents.length}</small>
            )}
          </button>
        ))}
      </nav>
      {tab === "overview" && (
        <div className="career-overview-grid">
          <div>
            <section className="career-next-step">
              <div>
                <p className="career-eyebrow">接下来</p>
                <h2>
                  {job.outcome
                    ? "这次申请已结束"
                    : (job.next_action?.content ??
                      job.next_interview?.title ??
                      "安排一个明确的下一步")}
                </h2>
                <p className="career-muted">
                  {job.next_action
                    ? displayDate(
                        job.next_action.starts_at ?? job.next_action.due_at,
                      )
                    : job.next_interview
                      ? displayDate(job.next_interview.starts_at)
                      : job.outcome
                        ? "你仍然可以查看材料、面试和历史记录。"
                        : "准备材料、跟进进度，或为下一场面试留出时间。"}
                </p>
              </div>
              {!job.outcome && (
                <button aria-label="添加跟进" onClick={() => setAction(true)}>
                  <Plus size={18} />
                </button>
              )}
            </section>
            {pending.map((a) => (
              <div className="career-task-row" key={a.id}>
                <button
                  className="career-task-check"
                  aria-label={`完成 ${a.content}`}
                  disabled={busy}
                  onClick={() => run(() => transitionNextAction(a, "complete"))}
                >
                  <Check size={13} />
                </button>
                <span>
                  {a.content}
                  <small>{displayDate(a.starts_at ?? a.due_at)}</small>
                </span>
                <button
                  disabled={busy}
                  onClick={() => run(() => transitionNextAction(a, "close"))}
                >
                  关闭
                </button>
              </div>
            ))}
            <JobDescription id={job.id} sourceUrl={job.source_url} />
          </div>
          <aside>
            <section className="career-detail-section">
              <div className="career-section-heading">
                <h2>求职方向</h2>
                <button onClick={() => setDirectionPicker(true)}>
                  关联方向
                </button>
              </div>
              <p className="career-muted">
                {job.direction_links.length
                  ? `已关联 ${job.direction_links.length} 个方向`
                  : "选择与这个岗位相关的求职目标。"}
              </p>
            </section>
            <section className="career-detail-section">
              <div className="career-section-heading">
                <h2>联系人</h2>
                <button onClick={() => setEditing(true)}>编辑</button>
              </div>
              {job.contacts.length ? (
                job.contacts.map((c, i) => (
                  <div key={i} className="career-contact">
                    <strong>{c.name}</strong>
                    <p>
                      {[c.role, c.email, c.phone].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                ))
              ) : (
                <p className="career-muted">
                  记下招聘负责人或内推人的联系方式。
                </p>
              )}
            </section>
            <section className="career-detail-section">
              <div className="career-section-heading">
                <h2>备注</h2>
                <button onClick={() => setEditing(true)}>编辑</button>
              </div>
              <p className="career-jd">
                {job.notes || "这份机会有哪些值得记住的细节？"}
              </p>
            </section>
            <Link
              className="career-offer-link"
              to={`/career-process/${job.id}/offer`}
            >
              <FileText size={17} />
              <span>
                Offer 条款与决定<small>记录薪资、福利和回复期限</small>
              </span>
              <ArrowUpRight size={16} />
            </Link>
            <Link
              className="career-text-button"
              to="/career-insights?view=offers"
            >
              比较已有 Offer ↗
            </Link>
            <button
              className="career-text-button career-muted"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await editJob(job, {
                    company_name: job.company_name,
                    job_title: job.job_title,
                    location: job.location ?? "",
                    source_url: job.source_url ?? "",
                    notes: job.notes,
                    contacts: job.contacts,
                    hidden: !job.hidden,
                  });
                  onClose();
                })
              }
            >
              {job.hidden ? "移出归档" : "归档这个岗位"}
            </button>
          </aside>
        </div>
      )}
      {tab === "documents" && (
        <div className="career-detail-section">
          <div className="career-section-heading">
            <div>
              <h2>为这个岗位准备的材料</h2>
              <p className="career-muted">
                准备中的文档和实际投递版本分别保存。
              </p>
            </div>
            <Btn size="sm" kind="outline" onClick={() => setLinking(true)}>
              关联材料
            </Btn>
          </div>
          <Link
            className="career-text-button"
            to={`/artifacts?create=resume&opportunity=${job.id}`}
          >
            为此岗位新建简历 <Plus size={14} />
          </Link>
          {job.documents.map((d) => (
            <Link
              className="career-document-row"
              key={d.id}
              to={`/artifacts/${d.id}`}
            >
              <FileText size={20} />
              <span>
                {d.current_version.title}
                <small>当前 v{d.current_version.version_no}</small>
              </span>
              <ArrowUpRight size={16} />
            </Link>
          ))}
          <h2 className="mt-7 font-semibold">实际投递记录</h2>
          {job.submissions.length ? (
            job.submissions.map((s) => (
              <Link
                className="career-document-row"
                key={s.id}
                to={`/artifacts/${s.version.artifact_id}?version=${s.version.id}`}
              >
                <Check size={18} />
                <span>
                  {s.version.title}
                  <small>
                    v{s.version.version_no} · {displayDate(s.submitted_at)}
                  </small>
                </span>
                <ArrowUpRight size={16} />
              </Link>
            ))
          ) : (
            <p className="career-muted mt-3">还没有记录确切的投递材料。</p>
          )}
        </div>
      )}
      {tab === "interviews" && (
        <section className="career-detail-section">
          <div className="career-section-heading">
            <h2>面试安排与复盘</h2>
            {!job.outcome && (
              <Btn
                size="sm"
                kind="outline"
                onClick={() => {
                  setRescheduling(undefined);
                  setInvitation(true);
                }}
              >
                安排面试
              </Btn>
            )}
          </div>
          {job.interviews.length ? (
            job.interviews.map((i) => (
              <article className="career-interview-row" key={i.id}>
                <CalendarDays size={20} />
                <div>
                  <h3>{i.stage_label || i.title || "面试"}</h3>
                  <p className="career-muted">
                    {displayDate(i.scheduled_start_at)} {i.scheduled_location}
                  </p>
                  <div className="flex gap-4 mt-2">
                    {!job.outcome && (
                      <button
                        onClick={() => {
                          setRescheduling(i);
                          setInvitation(true);
                        }}
                      >
                        调整安排
                      </button>
                    )}
                    <Link to={`/mock?opportunity=${job.id}`}>准备练习 ↗</Link>
                    <Link to={`/review?id=${i.id}`}>查看面试与复盘 ↗</Link>
                  </div>
                </div>
              </article>
            ))
          ) : (
            <p className="career-muted">
              还没有关联面试，确认时间后即可在这里安排。
            </p>
          )}
        </section>
      )}
      {tab === "activity" && (
        <section className="career-detail-section">
          <div className="career-section-heading">
            <h2>申请记录</h2>
            {!job.outcome && (
              <Btn size="sm" kind="outline" onClick={() => setProgress(true)}>
                记录进展
              </Btn>
            )}
          </div>
          {job.merged_sources?.length > 0 && (
            <p className="career-muted mb-4">
              包含 {job.merged_sources.length}{" "}
              个合并来源的记录。当前阶段以主岗位为准，可在“整理重复岗位”中撤销合并。
            </p>
          )}
          {[...job.events].reverse().map((e) => (
            <article
              key={e.id}
              className={`career-event ${e.active ? "" : "is-superseded"}`}
            >
              <i />
              <div>
                <p>{e.description}</p>
                <small>
                  {displayDate(e.occurred_at)}
                  {!e.active ? " · 已更正" : ""}
                </small>
              </div>
              {e.active && !e.corrects_event_id && (
                <button
                  onClick={() => {
                    setCorrecting(e);
                    setCorrection(e.description);
                  }}
                >
                  更正
                </button>
              )}
            </article>
          ))}
        </section>
      )}
      {directionPicker && (
        <DirectionPicker job={job} onClose={() => setDirectionPicker(false)} />
      )}
      {progress && (
        <ProgressForm job={job} onClose={() => setProgress(false)} />
      )}
      {editing && (
        <OpportunityForm
          job={job}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            void refresh();
          }}
        />
      )}
      {stage && (
        <StageDialog
          job={job}
          stage={stage}
          onClose={() => setStage(null)}
          onSaved={() => {
            setStage(null);
            void refresh();
          }}
        />
      )}
      {invitation && (
        <Modal
          open
          title="安排面试"
          onClose={() => setInvitation(false)}
          width={560}
        >
          <ManualInvitationForm
            opportunity={rescheduling?.opportunity ?? job}
            interview={rescheduling}
            onSaved={() => {
              setInvitation(false);
              setTab("interviews");
              void refresh();
            }}
          />
        </Modal>
      )}
      {action && (
        <Modal
          open
          title="安排下一步"
          onClose={() => setAction(false)}
          footer={
            <Btn
              loading={busy}
              disabled={!content.trim()}
              onClick={async () => {
                const key = crypto.randomUUID();
                if (
                  await run(() =>
                    createNextAction({
                      content,
                      status: "planned",
                      time_kind: due ? "deadline" : "flexible",
                      job_opportunity_id: job.id,
                      source_kind: "user_request",
                      source_identity: key,
                      idempotency_key: key,
                      ...(due
                        ? {
                            due_at: isoFromLocal(due),
                            original_time_text: due,
                            source_timezone:
                              Intl.DateTimeFormat().resolvedOptions().timeZone,
                          }
                        : {}),
                    }),
                  )
                ) {
                  setAction(false);
                  setContent("");
                  setDue("");
                }
              }}
            >
              保存跟进
            </Btn>
          }
        >
          <div className="career-form">
            <FormItem label="要做什么">
              <TextArea
                autoFocus
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="例如：周五询问一面结果"
              />
            </FormItem>
            <FormItem label="截止时间 · 选填">
              <TextInput
                type="datetime-local"
                value={due}
                onChange={(e) => setDue(e.target.value)}
              />
            </FormItem>
          </div>
        </Modal>
      )}
      {linking && (
        <Modal open title="关联已有材料" onClose={() => setLinking(false)}>
          {docs.isError && <p role="alert">读取失败，请重试。</p>}
          {docs.data?.map((d) => (
            <div key={d.id} className="career-document-row">
              <FileText size={18} />
              <span>{d.current_version.title}</span>
              <button
                disabled={busy}
                className="text-xs"
                onClick={async () => {
                  if (
                    await run(() => relateArtifactToOpportunity(d.id, job.id))
                  )
                    setLinking(false);
                }}
              >
                关联原文档
              </button>
              <Btn
                size="sm"
                kind="outline"
                disabled={busy || !d.current_version.content_text}
                onClick={() =>
                  run(async () => {
                    const copied = await createDocument(
                      {
                        title:
                          `${job.company_name} · ${d.current_version.title}`.slice(
                            0,
                            240,
                          ),
                        kind: ["resume", "cover_letter", "portfolio"].includes(
                          d.kind,
                        )
                          ? d.kind
                          : "portfolio",
                        data: (d.current_version
                          .document_json as unknown as ResumeDocument) ?? {
                          ...blankDocument(),
                          sections: [
                            {
                              id: crypto.randomUUID(),
                              title: "原始内容",
                              content: d.current_version.content_text ?? "",
                            },
                          ],
                        },
                        opportunity_id: job.id,
                      },
                      crypto.randomUUID(),
                    );
                    navigate(`/artifacts/${copied.artifact_id}`);
                  })
                }
              >
                为此岗位复制
              </Btn>
            </div>
          ))}
        </Modal>
      )}
      {correcting && (
        <Modal
          open
          title="更正记录说明"
          onClose={() => setCorrecting(null)}
          footer={
            <Btn
              loading={busy}
              disabled={!correction.trim()}
              onClick={async () => {
                const key = crypto.randomUUID();
                if (
                  await run(() =>
                    correctProcessEvent({
                      opportunityId: correcting.job_opportunity_id,
                      eventId: correcting.id,
                      kind: correcting.kind as Exclude<
                        ProcessEvent["kind"],
                        "retraction"
                      >,
                      occurredAt: correcting.occurred_at,
                      description: correction,
                      stepSummary: correcting.step_summary ?? undefined,
                      sourceIdentity: key,
                      idempotencyKey: key,
                    }),
                  )
                )
                  setCorrecting(null);
              }}
            >
              保存更正
            </Btn>
          }
        >
          <TextArea
            aria-label="更正后的说明"
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
          />
        </Modal>
      )}
    </div>
  );
}
