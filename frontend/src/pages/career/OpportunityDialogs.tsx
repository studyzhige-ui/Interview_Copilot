import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listAllArtifacts, listArtifactVersions } from "@/api/artifacts";
import {
  editJob,
  moveJob,
  saveJob,
  stages,
  type WorkspaceJob,
  type Stage,
  type Contact,
} from "@/api/careerWorkspace";
import {
  listJobOpportunityMergeCandidates,
  listJobOpportunityMerges,
  listJobOpportunities,
  mergeJobOpportunities,
  retractJobOpportunityMerge,
} from "@/api/careerProcess";
import { Modal } from "@/components/ui/Modal";
import { Btn } from "@/components/ui/Btn";
import {
  FormItem,
  TextInput,
  TextArea,
  SelectInput,
  localDateTimeNow,
  isoFromLocal,
} from "./CareerFields";
import { careerError, useRefreshCareer } from "./useCareerWorkspace";

export function OpportunityForm({
  job,
  onClose,
  onSaved,
}: {
  job?: WorkspaceJob;
  onClose: () => void;
  onSaved: (job: WorkspaceJob) => void;
}) {
  const [form, setForm] = useState({
    company_name: job?.company_name ?? "",
    job_title: job?.job_title ?? "",
    location: job?.location ?? "",
    source_url: job?.source_url ?? "",
    description: "",
    notes: job?.notes ?? "",
  });
  const [contacts, setContacts] = useState<Contact[]>(job?.contacts ?? []);
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  const update = (field: keyof typeof form, value: string) =>
    setForm((f) => ({ ...f, [field]: value }));
  const save = async () => {
    setBusy(true);
    try {
      const saved = job
        ? await editJob(job, { ...form, contacts, hidden: job.hidden })
        : await saveJob(
            {
              company_name: form.company_name,
              job_title: form.job_title,
              location: form.location,
              source_url: form.source_url,
              description: form.description,
            },
            key.current,
          );
      onSaved(saved);
    } catch (error) {
      careerError(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={job ? "编辑岗位" : "保存一个新岗位"}
      width={640}
      footer={
        <>
          <Btn kind="outline" onClick={onClose} disabled={busy}>
            取消
          </Btn>
          <Btn
            loading={busy}
            disabled={!form.company_name.trim() || !form.job_title.trim()}
            onClick={save}
          >
            保存岗位
          </Btn>
        </>
      }
    >
      <div className="career-form">
        <p className="career-muted">先记下感兴趣的机会，再一步步准备。</p>
        <div className="career-form-row">
          <FormItem label="公司">
            <TextInput
              autoFocus
              maxLength={200}
              value={form.company_name}
              onChange={(e) => update("company_name", e.target.value)}
            />
          </FormItem>
          <FormItem label="岗位名称">
            <TextInput
              maxLength={300}
              value={form.job_title}
              onChange={(e) => update("job_title", e.target.value)}
            />
          </FormItem>
        </div>
        <div className="career-form-row">
          <FormItem label="工作地点 · 选填">
            <TextInput
              value={form.location}
              onChange={(e) => update("location", e.target.value)}
            />
          </FormItem>
          <FormItem label="岗位链接 · 选填">
            <TextInput
              type="url"
              value={form.source_url}
              onChange={(e) => update("source_url", e.target.value)}
            />
          </FormItem>
        </div>
        <FormItem label={job ? "备注" : "职位描述 · 可以直接粘贴"}>
          <TextArea
            rows={6}
            value={job ? form.notes : form.description}
            onChange={(e) =>
              update(job ? "notes" : "description", e.target.value)
            }
            placeholder="职责、要求，或你希望记住的细节…"
          />
        </FormItem>
        {job && (
          <fieldset className="career-form">
            <legend>联系人</legend>
            {contacts.map((c, i) => (
              <div key={i} className="career-contact-form">
                <TextInput
                  aria-label={`联系人 ${i + 1} 姓名`}
                  placeholder="姓名"
                  value={c.name}
                  onChange={(e) =>
                    setContacts(
                      contacts.map((v, n) =>
                        n === i ? { ...v, name: e.target.value } : v,
                      ),
                    )
                  }
                />
                <TextInput
                  aria-label={`联系人 ${i + 1} 邮箱或电话`}
                  placeholder="邮箱或电话"
                  value={c.email}
                  onChange={(e) =>
                    setContacts(
                      contacts.map((v, n) =>
                        n === i ? { ...v, email: e.target.value } : v,
                      ),
                    )
                  }
                />
                <button
                  onClick={() =>
                    setContacts(contacts.filter((_, n) => n !== i))
                  }
                >
                  移除
                </button>
              </div>
            ))}
            <Btn
              size="sm"
              kind="outline"
              onClick={() =>
                setContacts([
                  ...contacts,
                  { name: "", role: "", email: "", phone: "" },
                ])
              }
            >
              添加联系人
            </Btn>
          </fieldset>
        )}
      </div>
    </Modal>
  );
}

export function StageDialog({
  job,
  stage,
  onClose,
  onSaved,
}: {
  job: WorkspaceJob;
  stage: Stage;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [note, setNote] = useState("");
  const [channel, setChannel] = useState("");
  const [time, setTime] = useState(localDateTimeNow);
  const [outcome, setOutcome] = useState("rejected");
  const [versions, setVersions] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  const documents = useQuery({
    queryKey: ["artifacts", "submit-picker"],
    queryFn: () => listAllArtifacts(),
    enabled: stage === "applied",
  });
  const save = async () => {
    setBusy(true);
    try {
      await moveJob(
        job,
        {
          stage,
          note,
          channel: channel || undefined,
          occurred_at: isoFromLocal(time),
          version_ids: Object.values(versions),
          ...(stage === "closed" ? { outcome } : {}),
        },
        key.current,
      );
      onSaved();
    } catch (error) {
      careerError(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={
        stage === "applied"
          ? "记录实际投递"
          : stage === "closed"
            ? "结束这次申请"
            : `更新为${stages.find((s) => s.id === stage)?.label}`
      }
      width={560}
      footer={
        <>
          <Btn kind="outline" onClick={onClose} disabled={busy}>
            取消
          </Btn>
          <Btn loading={busy} disabled={!time} onClick={save}>
            确认记录
          </Btn>
        </>
      }
    >
      <div className="career-form">
        <p className="career-muted">
          {job.company_name} · {job.job_title}
        </p>
        <FormItem label="发生时间">
          <TextInput
            type="datetime-local"
            value={time}
            onChange={(e) => setTime(e.target.value)}
          />
        </FormItem>
        {stage === "closed" && (
          <FormItem label="结束原因">
            <SelectInput
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
            >
              <option value="rejected">未通过</option>
              <option value="withdrawn">主动退出</option>
              <option value="posting_closed">岗位关闭</option>
              <option value="declined_offer">拒绝 Offer</option>
              <option value="accepted">已接受 Offer</option>
            </SelectInput>
          </FormItem>
        )}
        {stage === "applied" && (
          <>
            <FormItem label="投递渠道">
              <TextInput
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                placeholder="官网、内推、招聘平台…"
              />
            </FormItem>
            <fieldset>
              <legend className="mb-2 text-sm">本次使用的材料</legend>
              <p className="career-muted">
                选择后保存此刻的确切版本；不确定时可以留空。
              </p>
              {documents.isError && (
                <p role="alert">材料读取失败，请重试后选择。</p>
              )}
              {documents.data?.map((a) => (
                <label key={a.id} className="career-choice">
                  <input
                    type="checkbox"
                    checked={Boolean(versions[a.id])}
                    onChange={(e) =>
                      setVersions((current) => {
                        const next = { ...current };
                        if (e.target.checked) next[a.id] = a.current_version.id;
                        else delete next[a.id];
                        return next;
                      })
                    }
                  />
                  <span>{a.current_version.title}</span>
                  <small>v{a.current_version.version_no}</small>
                  {versions[a.id] && (
                    <VersionPicker
                      id={a.id}
                      selected={versions[a.id]}
                      onChange={(value) =>
                        setVersions((current) => ({
                          ...current,
                          [a.id]: value,
                        }))
                      }
                    />
                  )}
                </label>
              ))}
            </fieldset>
          </>
        )}
        <FormItem label="补充说明 · 选填">
          <TextArea
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </FormItem>
        {job.outcome && stage !== "closed" && (
          <p className="career-muted">
            重新开启后，历史记录仍然保留。已关闭的旧任务不会自动恢复。
          </p>
        )}
      </div>
    </Modal>
  );
}

function VersionPicker({
  id,
  selected,
  onChange,
}: {
  id: string;
  selected: string;
  onChange: (id: string) => void;
}) {
  const query = useQuery({
    queryKey: ["artifact", id, "versions"],
    queryFn: () => listArtifactVersions(id),
  });
  return (
    <select
      aria-label="投递材料版本"
      className="max-w-36 rounded border p-1 text-xs"
      value={selected}
      onChange={(e) => onChange(e.target.value)}
    >
      {query.data?.map((v) => (
        <option key={v.id} value={v.id}>
          v{v.version_no} · {v.title}
        </option>
      ))}
    </select>
  );
}

export function MergeDialog({ onClose }: { onClose: () => void }) {
  const refresh = useRefreshCareer();
  const [busy, setBusy] = useState(false);
  const jobs = useQuery({
    queryKey: ["job-opportunities", "all-for-merge"],
    queryFn: () => listJobOpportunities(true),
  });
  const label = (id: string) => {
    const job = jobs.data?.find((j) => j.id === id);
    return job ? `${job.company_name} · ${job.job_title}` : "正在读取岗位…";
  };
  const candidates = useQuery({
    queryKey: ["career-workspace", "merge-candidates"],
    queryFn: listJobOpportunityMergeCandidates,
  });
  const merges = useQuery({
    queryKey: ["career-workspace", "merges"],
    queryFn: () => listJobOpportunityMerges(),
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
  return (
    <Modal open onClose={onClose} title="整理重复岗位" width={620}>
      <div className="career-form">
        <p className="career-muted">
          合并后在列表显示为一个岗位，原始记录仍然保留，可以撤销。
        </p>
        {candidates.isError || merges.isError ? (
          <p role="alert">读取失败，请关闭后重试。</p>
        ) : null}
        {candidates.data?.length === 0 && <p>没有发现疑似重复岗位。</p>}
        {candidates.data?.map((c) => (
          <div key={c.duplicate_opportunity_id} className="career-choice">
            <span>
              {c.reasons.join("、")}
              <small className="block">
                {label(c.duplicate_opportunity_id)} →{" "}
                {label(c.canonical_opportunity_id)}
              </small>
            </span>
            <Btn
              disabled={busy}
              size="sm"
              onClick={() =>
                run(() =>
                  mergeJobOpportunities({
                    duplicateOpportunityId: c.duplicate_opportunity_id,
                    canonicalOpportunityId: c.canonical_opportunity_id,
                    reason: "用户确认重复岗位",
                    operationKey: crypto.randomUUID(),
                  }),
                )
              }
            >
              合并
            </Btn>
          </div>
        ))}
        {merges.data?.map((m) => (
          <div className="career-choice" key={m.id}>
            <span>
              {label(m.duplicate_opportunity_id)} →{" "}
              {label(m.canonical_opportunity_id)}
            </span>
            <Btn
              size="sm"
              kind="outline"
              disabled={busy}
              onClick={() =>
                run(() =>
                  retractJobOpportunityMerge({
                    merge: m,
                    reason: "用户撤销合并",
                    operationKey: crypto.randomUUID(),
                  }),
                )
              }
            >
              撤销合并
            </Btn>
          </div>
        ))}
      </div>
    </Modal>
  );
}
