import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getCareerProfile } from "@/api/careerProfile";
import {
  appendProcessEvent,
  replaceJobOpportunityDirections,
} from "@/api/careerProcess";
import type { WorkspaceJob } from "@/api/careerWorkspace";
import { Modal } from "@/components/ui/Modal";
import { Btn } from "@/components/ui/Btn";
import {
  FormItem,
  SelectInput,
  TextInput,
  TextArea,
  isoFromLocal,
  localDateTimeNow,
} from "./CareerFields";
import { careerError, useRefreshCareer } from "./useCareerWorkspace";

export function DirectionPicker({
  job,
  onClose,
}: {
  job: WorkspaceJob;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ["career-profile"],
    queryFn: getCareerProfile,
  });
  const [selected, setSelected] = useState(
    job.direction_links.map((d) => ({
      direction_id: d.career_profile_direction_id,
      match_reason: d.match_reason,
    })),
  );
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  const refresh = useRefreshCareer();
  return (
    <Modal
      open
      title="关联求职方向"
      onClose={onClose}
      footer={
        <Btn
          loading={busy}
          disabled={!query.data}
          onClick={async () => {
            setBusy(true);
            try {
              await replaceJobOpportunityDirections({
                opportunityId: job.id,
                expectedVersion: job.direction_version,
                sourceIdentity: key.current,
                directions: selected,
              });
              await refresh();
              onClose();
            } catch (error) {
              careerError(error);
            } finally {
              setBusy(false);
            }
          }}
        >
          保存关联
        </Btn>
      }
    >
      <p className="career-muted">关联方向可帮助对照目标和分析投递效果。</p>
      {query.isError && (
        <button onClick={() => query.refetch()}>读取失败，点击重试</button>
      )}
      {query.data?.directions.map((d) => (
        <div key={d.id} className="career-form mt-4">
          <label className="flex gap-2">
            <input
              type="checkbox"
              checked={selected.some((s) => s.direction_id === d.id)}
              onChange={(e) =>
                setSelected(
                  e.target.checked
                    ? [...selected, { direction_id: d.id, match_reason: "" }]
                    : selected.filter((s) => s.direction_id !== d.id),
                )
              }
            />
            {d.label}
          </label>
          {selected.some((s) => s.direction_id === d.id) && (
            <TextInput
              aria-label={`${d.label}关联原因`}
              placeholder="为什么适合这个方向？"
              value={
                selected.find((s) => s.direction_id === d.id)?.match_reason
              }
              onChange={(e) =>
                setSelected(
                  selected.map((s) =>
                    s.direction_id === d.id
                      ? { ...s, match_reason: e.target.value }
                      : s,
                  ),
                )
              }
            />
          )}
        </div>
      ))}
      {query.data?.directions.length === 0 && (
        <p className="career-muted mt-4">
          还没有设置方向。<Link to="/career-profile">前往个人档案设置 ↗</Link>
        </p>
      )}
    </Modal>
  );
}

const progressKinds = [
  ["preparation_started", "开始准备"],
  ["application_acknowledged", "招聘方已收到申请"],
  ["recruiter_contact", "招聘沟通"],
  ["assessment_invited", "收到测评"],
  ["assessment_completed", "完成测评"],
  ["hiring_step", "其他流程进展"],
  ["interview_completed", "完成面试"],
  ["background_check_started", "开始背调"],
] as const;

export function ProgressForm({
  job,
  onClose,
}: {
  job: WorkspaceJob;
  onClose: () => void;
}) {
  const [kind, setKind] =
    useState<(typeof progressKinds)[number][0]>("recruiter_contact");
  const [description, setDescription] = useState("");
  const [time, setTime] = useState(localDateTimeNow);
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  const refresh = useRefreshCareer();
  return (
    <Modal
      open
      title="记录一条进展"
      onClose={onClose}
      footer={
        <Btn
          loading={busy}
          disabled={!description.trim() || !time}
          onClick={async () => {
            setBusy(true);
            try {
              await appendProcessEvent({
                opportunityId: job.id,
                kind,
                occurredAt: isoFromLocal(time),
                description,
                sourceIdentity: key.current,
                idempotencyKey: key.current,
              });
              await refresh();
              onClose();
            } catch (error) {
              careerError(error);
            } finally {
              setBusy(false);
            }
          }}
        >
          保存记录
        </Btn>
      }
    >
      <div className="career-form">
        <FormItem label="发生了什么">
          <SelectInput
            value={kind}
            onChange={(e) => setKind(e.target.value as typeof kind)}
          >
            {progressKinds.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </SelectInput>
        </FormItem>
        <FormItem label="发生时间">
          <TextInput
            type="datetime-local"
            value={time}
            onChange={(e) => setTime(e.target.value)}
          />
        </FormItem>
        <FormItem label="进展说明">
          <TextArea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </FormItem>
        <p className="career-muted">
          这条记录会加入时间线。调整当前阶段、记录实际投递或安排面试，请使用岗位上方的对应入口。
        </p>
      </div>
    </Modal>
  );
}
