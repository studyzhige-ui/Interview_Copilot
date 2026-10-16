import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  Columns3,
  List,
  Plus,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import {
  getJobs,
  careerKeys,
  stages,
  downloadText,
  type WorkspaceJob,
  type Stage,
} from "@/api/careerWorkspace";
import { apiClient } from "@/api/client";
import { Btn } from "@/components/ui/Btn";
import { Spinner } from "@/components/ui/Spinner";
import { Modal } from "@/components/ui/Modal";
import { OpportunityDetail } from "./OpportunityDetail";
import {
  OpportunityForm,
  StageDialog,
  MergeDialog,
} from "./OpportunityDialogs";
import { useRefreshCareer, careerError } from "./useCareerWorkspace";
import { displayDate } from "./CareerFields";
import { parseCsv, toCsv } from "./transfer";

export function CareerProcessPage() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [closed, setClosed] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [stage, setStage] = useState("");
  const [creating, setCreating] = useState(false);
  const [menu, setMenu] = useState(false);
  const [merging, setMerging] = useState(false);
  const [moving, setMoving] = useState<{
    job: WorkspaceJob;
    stage: Stage;
  } | null>(null);
  const [dragging, setDragging] = useState<WorkspaceJob | null>(null);
  const [exporting, setExporting] = useState(false);
  const [importRows, setImportRows] = useState<string[][] | null>(null);
  const [importing, setImporting] = useState(false);
  const importKey = useRef(crypto.randomUUID());
  const fileRef = useRef<HTMLInputElement>(null);
  const refresh = useRefreshCareer();
  const view = params.get("view") === "board" ? "board" : "list";
  const selected = params.get("opportunity");
  const query = useQuery({
    queryKey: [
      ...careerKeys.all,
      "jobs",
      search,
      stage,
      closed,
      hidden,
      offset,
      view,
    ],
    refetchInterval: 30000,
    queryFn: () =>
      getJobs({
        q: search,
        stage,
        closed,
        hidden,
        offset,
        limit: view === "board" ? 100 : 30,
      }),
  });
  const select = (id: string | null) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (id) next.set("opportunity", id);
      else next.delete("opportunity");
      return next;
    });
  const jobs = query.data?.items ?? [];
  const exportCsv = async () => {
    setExporting(true);
    try {
      const all: WorkspaceJob[] = [];
      let page = 0;
      while (true) {
        const result = await getJobs({
          q: search,
          stage,
          closed,
          hidden,
          offset: page,
          limit: 100,
        });
        all.push(...result.items);
        page += result.items.length;
        if (page >= result.total || !result.items.length) break;
      }
      downloadText(
        toCsv([
          ["公司", "岗位", "地点", "阶段", "链接", "备注"],
          ...all.map((j) => [
            j.company_name,
            j.job_title,
            j.location ?? "",
            stages.find((s) => s.id === j.stage)?.label ?? "",
            j.source_url ?? "",
            j.notes,
          ]),
        ]),
        "求职岗位.csv",
        "text/csv;charset=utf-8",
      );
    } catch (error) {
      careerError(error);
    } finally {
      setExporting(false);
    }
  };
  if (selected)
    return (
      <div className="career-workspace">
        <OpportunityDetail
          key={selected}
          id={selected}
          onClose={() => select(null)}
        />
      </div>
    );
  return (
    <div className="career-workspace">
      <header className="career-page-heading">
        <div>
          <p className="career-eyebrow">YOUR NEXT CHAPTER</p>
          <h1>让每个机会，向前一步。</h1>
          <p>从感兴趣的岗位，到下一场面试，在这里有序推进。</p>
        </div>
        <Btn icon={<Plus size={16} />} onClick={() => setCreating(true)}>
          保存岗位
        </Btn>
      </header>
      <div className="career-summary-strip">
        {stages
          .filter(
            (s) =>
              s.id !== "in_process" || (query.data?.counts.in_process ?? 0) > 0,
          )
          .map((s) => (
            <button
              key={s.id}
              className={stage === s.id ? "is-active" : ""}
              onClick={() => {
                setStage(stage === s.id ? "" : s.id);
                if (s.id === "closed") setClosed(true);
                setOffset(0);
              }}
            >
              <span>
                <i style={{ background: s.color }} />
                {s.label}
              </span>
              <strong>{query.data?.counts[s.id] ?? "—"}</strong>
            </button>
          ))}
      </div>
      <div className="career-toolbar">
        <label className="career-search">
          <Search size={16} />
          <input
            aria-label="搜索岗位"
            placeholder="搜索公司、岗位或地点…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <div className="career-view-switch" aria-label="岗位视图">
          <button
            aria-pressed={view === "list"}
            aria-label="列表视图"
            onClick={() => {
              setOffset(0);
              setParams({ view: "list" });
            }}
          >
            <List size={16} />
          </button>
          <button
            aria-pressed={view === "board"}
            aria-label="看板视图"
            onClick={() => {
              setOffset(0);
              setParams({ view: "board" });
            }}
          >
            <Columns3 size={16} />
          </button>
        </div>
        <div className="career-menu-wrap">
          <button
            className="career-toolbar-button"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            <SlidersHorizontal size={15} />
            管理
          </button>
          {menu && (
            <div className="career-menu">
              <label>
                <input
                  type="checkbox"
                  checked={closed}
                  onChange={(e) => {
                    setClosed(e.target.checked);
                    setOffset(0);
                    if (!e.target.checked && stage === "closed") setStage("");
                  }}
                />
                显示已结束岗位
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={hidden}
                  onChange={(e) => {
                    setHidden(e.target.checked);
                    setOffset(0);
                  }}
                />
                查看归档
              </label>
              <button disabled={exporting} onClick={exportCsv}>
                {exporting ? "导出中…" : "导出筛选结果 CSV"}
              </button>
              <button onClick={() => fileRef.current?.click()}>
                从 CSV 导入
              </button>
              <button
                onClick={() => {
                  setMerging(true);
                  setMenu(false);
                }}
              >
                整理重复岗位
              </button>
            </div>
          )}
        </div>
      </div>
      <input
        ref={fileRef}
        hidden
        type="file"
        accept=".csv"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          try {
            if (file.size > 2_000_000) throw new Error("文件请小于 2 MB");
            const rows = parseCsv(await file.text());
            if (rows.length < 2 || rows.length > 201)
              throw new Error("每次导入 1–200 个岗位");
            const aliases = [
              ["公司", "company", "company_name"],
              ["岗位", "role", "job_title"],
              ["地点", "location"],
              ["链接", "url", "source_url"],
            ];
            const indexes = aliases.map((a) =>
              rows[0].findIndex((h) => a.includes(h.trim().toLowerCase())),
            );
            if (indexes[0] < 0 || indexes[1] < 0)
              throw new Error("CSV 需要“公司”和“岗位”列");
            const mapped = rows
              .slice(1)
              .map((r) =>
                indexes.map((i) => (i < 0 ? "" : (r[i]?.trim() ?? ""))),
              );
            if (mapped.some((r) => !r[0] || !r[1]))
              throw new Error("每行都需要公司与岗位名称");
            importKey.current = crypto.randomUUID();
            setImportRows(mapped);
          } catch (error) {
            careerError(error);
          }
        }}
      />
      {query.isError ? (
        <div className="career-empty" role="alert">
          <h2>暂时无法读取岗位</h2>
          <p>请检查服务连接后重试。</p>
          <Btn onClick={() => query.refetch()}>重新加载</Btn>
        </div>
      ) : query.isPending ? (
        <div className="career-loading">
          <Spinner />
          正在整理机会…
        </div>
      ) : jobs.length === 0 ? (
        <div className="career-empty">
          <span className="career-empty-icon">
            <BriefcaseBusiness size={30} />
          </span>
          <h2>
            {search || stage || hidden
              ? "没有符合条件的岗位"
              : "下一份理想工作，从一个机会开始"}
          </h2>
          <p>
            {search || stage || hidden
              ? "试试其他关键词或筛选条件。"
              : "保存职位描述、准备申请材料，跟进每一步进展。"}
          </p>
          <Btn
            kind="outline"
            onClick={() => {
              if (search || stage || hidden) {
                setSearch("");
                setStage("");
                setHidden(false);
              } else setCreating(true);
            }}
          >
            {search || stage || hidden ? "清除筛选" : "保存第一个岗位"}
          </Btn>
        </div>
      ) : view === "list" ? (
        <div className="career-table">
          <div className="career-table-head">
            <span>公司 / 岗位</span>
            <span>阶段</span>
            <span>下一步</span>
            <span>最近更新</span>
            <span />
          </div>
          {jobs.map((j) => (
            <button
              key={j.id}
              className="career-table-row"
              onClick={() => select(j.id)}
            >
              <span className="career-job-identity">
                <i>{j.company_name.slice(0, 1)}</i>
                <span>
                  <strong>{j.job_title}</strong>
                  <small>
                    {j.company_name}
                    {j.location ? ` · ${j.location}` : ""}
                  </small>
                </span>
              </span>
              <StageBadge stage={j.stage} />
              <span className="career-next-cell">
                {j.next_action ? (
                  <>
                    {j.next_action.content}
                    <small>
                      {displayDate(
                        j.next_action.starts_at ?? j.next_action.due_at,
                      )}
                    </small>
                  </>
                ) : j.next_interview ? (
                  <>
                    {j.next_interview.title}
                    <small>{displayDate(j.next_interview.starts_at)}</small>
                  </>
                ) : (
                  <span className="career-muted">
                    {j.outcome ? "申请已结束" : "等待安排"}
                  </span>
                )}
              </span>
              <span className="career-updated">
                {new Date(j.updated_at).toLocaleDateString("zh-CN", {
                  month: "short",
                  day: "numeric",
                })}
              </span>
              <ArrowRight size={15} />
            </button>
          ))}
        </div>
      ) : (
        <div className="career-board">
          {stages
            .filter(
              (s) =>
                (s.id !== "closed" || closed) &&
                (s.id !== "in_process" || jobs.some((j) => j.stage === s.id)),
            )
            .map((s) => (
              <section
                key={s.id}
                className="career-board-column"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (dragging && dragging.stage !== s.id)
                    setMoving({ job: dragging, stage: s.id });
                  setDragging(null);
                }}
              >
                <h2>
                  <i style={{ background: s.color }} />
                  {s.label}
                  <small>{jobs.filter((j) => j.stage === s.id).length}</small>
                </h2>
                {jobs
                  .filter((j) => j.stage === s.id)
                  .map((j) => (
                    <article
                      key={j.id}
                      className="career-board-card"
                      draggable
                      onDragStart={() => setDragging(j)}
                      onDragEnd={() => setDragging(null)}
                    >
                      <button onClick={() => select(j.id)}>
                        <span className="career-company-label">
                          {j.company_name}
                        </span>
                        <h3>{j.job_title}</h3>
                        <p>{j.location || "地点未填写"}</p>
                        {j.next_action && (
                          <div className="career-board-next">
                            {j.next_action.content}
                          </div>
                        )}
                      </button>
                      <select
                        aria-label={`移动 ${j.company_name} 的岗位`}
                        value={j.stage}
                        onChange={(e) =>
                          setMoving({ job: j, stage: e.target.value as Stage })
                        }
                      >
                        {stages.map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.label}
                          </option>
                        ))}
                      </select>
                    </article>
                  ))}
                <button
                  className="career-board-add"
                  onClick={() => setCreating(true)}
                >
                  <Plus size={14} />
                  保存岗位
                </button>
              </section>
            ))}
        </div>
      )}
      {query.data && query.data.total > 0 && (
        <footer className="career-pagination">
          <span>
            {view === "board" ? "看板展示本页岗位 · " : ""}
            {hidden ? "已归档 · " : ""}共 {query.data.total} 个岗位
          </span>
          <div>
            <button
              aria-label="上一页"
              disabled={offset === 0}
              onClick={() =>
                setOffset(Math.max(0, offset - (view === "board" ? 100 : 30)))
              }
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {offset + 1}–{Math.min(offset + jobs.length, query.data.total)}
            </span>
            <button
              aria-label="下一页"
              disabled={offset + jobs.length >= query.data.total}
              onClick={() => setOffset(offset + (view === "board" ? 100 : 30))}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </footer>
      )}
      {creating && (
        <OpportunityForm
          onClose={() => setCreating(false)}
          onSaved={(j) => {
            setCreating(false);
            void refresh();
            select(j.id);
          }}
        />
      )}
      {moving && (
        <StageDialog
          job={moving.job}
          stage={moving.stage}
          onClose={() => setMoving(null)}
          onSaved={() => {
            setMoving(null);
            void refresh();
          }}
        />
      )}
      {merging && <MergeDialog onClose={() => setMerging(false)} />}
      {importRows && (
        <Modal
          open
          title="核对导入岗位"
          width={650}
          onClose={() => setImportRows(null)}
          footer={
            <Btn
              loading={importing}
              onClick={async () => {
                setImporting(true);
                try {
                  await apiClient.post(
                    "/career-workspace/import",
                    importRows.map((r, i) => ({
                      company_name: r[0],
                      job_title: r[1],
                      location: r[2],
                      source_url: r[3],
                      operation_key: `${importKey.current}:${i}`,
                    })),
                  );
                  setImportRows(null);
                  await refresh();
                } catch (error) {
                  careerError(error);
                } finally {
                  setImporting(false);
                }
              }}
            >
              导入 {importRows.length} 个岗位
            </Btn>
          }
        >
          <p className="career-muted mb-4">
            仅导入公司、岗位、地点和链接，统一保存为待投递。阶段、备注和投递历史不会导入；来源链接相同的岗位会复用已有记录。
          </p>
          {importRows.map((r, i) => (
            <div key={i} className="career-choice">
              <strong>{r[0]}</strong>
              <span>{r[1]}</span>
              <small>{r[2]}</small>
            </div>
          ))}
        </Modal>
      )}
    </div>
  );
}

export function StageBadge({ stage }: { stage: Stage }) {
  const item = stages.find((s) => s.id === stage)!;
  return (
    <span className={`career-stage career-stage-${stage}`}>
      <i style={{ background: item.color }} />
      {item.label}
    </span>
  );
}
