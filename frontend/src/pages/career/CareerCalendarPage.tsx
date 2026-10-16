import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Download,
} from "lucide-react";
import { listAllInterviewRecords } from "@/api/interview";
import { getNextActionAgenda } from "@/api/careerInsights";
import { downloadText } from "@/api/careerWorkspace";
import { Btn } from "@/components/ui/Btn";
import { ActionAgenda } from "./ActionAgenda";
import { buildIcs } from "./transfer";
import { displayDate } from "./CareerFields";
import { isScheduledAction } from '@/lib/schedule';

export function CareerCalendarPage() {
  const [params, setParams] = useSearchParams();
  const [month, setMonth] = useState(
    () => new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  );
  const view = params.get("view") === "actions" ? "actions" : "calendar";
  const setView = (value: string) => setParams(current => {
    const next = new URLSearchParams(current);
    next.set('view', value);
    return next;
  });
  const interviews = useQuery({
    queryKey: ["interview-records", "calendar"],
    queryFn: () => listAllInterviewRecords(),
    refetchInterval: 30000,
  });
  const agenda = useQuery({
    queryKey: ["next-action-agenda"],
    queryFn: getNextActionAgenda,
    refetchInterval: 30000,
  });
  const events = [
    ...(interviews.data ?? [])
      .filter((i) => i.scheduled_start_at)
      .map((i) => ({
        id: i.id,
        title: i.title,
        start: i.scheduled_start_at!,
        end: i.scheduled_end_at,
        location: i.scheduled_location,
        kind: "interview",
        href: i.job_opportunity_id
          ? `/career-process?opportunity=${i.job_opportunity_id}`
          : `/review?id=${i.id}`,
      })),
    ...(agenda.data?.items ?? [])
      .filter(
        (i) =>
          isScheduledAction(i.action) &&
          (i.action.starts_at || i.action.due_at),
      )
      .map((i) => ({
        id: i.action.id,
        title: i.action.content,
        start: (i.action.starts_at ?? i.action.due_at)!,
        end: i.action.ends_at,
        location: "",
        kind: "action",
        href: i.action.job_opportunity_id
          ? `/career-process?opportunity=${i.action.job_opportunity_id}`
          : `/career-calendar?view=actions#action-${encodeURIComponent(i.action.id)}`,
      })),
  ];
  const inMonth = events.filter((e) => {
    const d = new Date(e.start);
    return (
      d.getFullYear() === month.getFullYear() &&
      d.getMonth() === month.getMonth()
    );
  });
  const first = (month.getDay() + 6) % 7;
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const shift = (amount: number) =>
    setMonth(new Date(month.getFullYear(), month.getMonth() + amount, 1));
  const failed = interviews.isError || agenda.isError;
  return (
    <div className="career-workspace">
      <header className="career-page-heading">
        <div>
          <p className="career-eyebrow">A LITTLE CLARITY, EVERY DAY</p>
          <h1>把时间，留给重要的机会。</h1>
          <p>面试、跟进和回复期限，一起安排。</p>
        </div>
        <Btn
          kind="outline"
          icon={<Download size={14} />}
          disabled={
            failed ||
            interviews.isPending ||
            agenda.isPending ||
            !inMonth.length
          }
          onClick={() =>
            downloadText(
              buildIcs(inMonth),
              "求职日程.ics",
              "text/calendar;charset=utf-8",
            )
          }
        >
          导出本月日程
        </Btn>
      </header>
      <nav className="career-tabs">
        <button
          aria-current={view === "calendar" ? "page" : undefined}
          onClick={() => setView("calendar")}
        >
          日历
        </button>
        <button
          aria-current={view === "actions" ? "page" : undefined}
          onClick={() => setView("actions")}
        >
          行动与提醒
        </button>
      </nav>
      {view === "actions" ? (
        <ActionAgenda />
      ) : (
        <>
          {failed && (
            <div className="document-save-error" role="alert">
              部分日程读取失败。
              <button
                onClick={() => {
                  void interviews.refetch();
                  void agenda.refetch();
                }}
              >
                重新加载
              </button>
            </div>
          )}
          <div className="calendar-heading">
            <button onClick={() => shift(-1)} aria-label="上个月">
              <ChevronLeft size={17} />
            </button>
            <h2>
              {month.toLocaleDateString("zh-CN", {
                year: "numeric",
                month: "long",
              })}
            </h2>
            <button onClick={() => shift(1)} aria-label="下个月">
              <ChevronRight size={17} />
            </button>
            <button
              className="ml-auto"
              onClick={() =>
                setMonth(
                  new Date(new Date().getFullYear(), new Date().getMonth(), 1),
                )
              }
            >
              本月
            </button>
          </div>
          <div className="career-calendar">
            {["一", "二", "三", "四", "五", "六", "日"].map((d) => (
              <div className="calendar-weekday" key={d}>
                {d}
              </div>
            ))}
            {Array.from(
              { length: Math.ceil((first + days) / 7) * 7 },
              (_, index) => {
                const day = index - first + 1;
                const current = day >= 1 && day <= days;
                const today = new Date();
                const isToday =
                  current &&
                  day === today.getDate() &&
                  month.getMonth() === today.getMonth() &&
                  month.getFullYear() === today.getFullYear();
                return (
                  <div
                    className={`calendar-day ${!current ? "is-empty" : ""}`}
                    key={index}
                  >
                    {current && (
                      <>
                        <span className={isToday ? "is-today" : ""}>{day}</span>
                        {inMonth
                          .filter((e) => new Date(e.start).getDate() === day)
                          .map((e) => (
                            <Link
                              key={e.id}
                              className={`calendar-event ${e.kind}`}
                              to={e.href}
                            >
                              <small>
                                {new Date(e.start).toLocaleTimeString("zh-CN", {
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })}
                              </small>
                              {e.title}
                            </Link>
                          ))}
                      </>
                    )}
                  </div>
                );
              },
            )}
          </div>
          <section className="career-detail-section">
            <div className="career-section-heading">
              <h2>本月安排</h2>
              <span className="career-muted">{inMonth.length} 项</span>
            </div>
            {inMonth.length ? (
              inMonth
                .sort((a, b) => a.start.localeCompare(b.start))
                .map((e) => (
                  <Link className="career-interview-row" key={e.id} to={e.href}>
                    <CalendarDays size={18} />
                    <span>
                      {e.title}
                      <small className="block career-muted">
                        {displayDate(e.start)} {e.location}
                      </small>
                    </span>
                  </Link>
                ))
            ) : (
              <p className="career-muted">
                这个月还没有安排。打开岗位，添加下一步或确认面试时间。
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
