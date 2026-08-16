import { useState } from 'react';
import {
  ShieldAlert,
  Check,
  Send,
  Sparkles,
  Layers,
  CheckCircle2,
  ChevronRight,
  Mail,
  UserCheck,
  Briefcase,
} from 'lucide-react';
import { toast } from '@/store/uiStore';

export interface ConfirmationItem {
  id: string;
  category: 'external_action' | 'fact' | 'profile_update';
  title: string;
  description: string;
  contextReason: string;
  suggestedAction: string;
  timestamp?: string;
  metadata?: Record<string, unknown>;
}

const DEFAULT_CONFIRMATION_ITEMS: ConfirmationItem[] = [
  {
    id: 'conf-item-1',
    category: 'external_action',
    title: '腾讯 HR 邮件：确认技术一面面试时间',
    description: '收到腾讯招聘团队发来的面试邀约，建议面试时间为下周二（8月19日）上午 10:30。',
    contextReason: 'Copilot 已检测到该时间段你的日历暂无冲突，是否授权 Copilot 发送确认回信？',
    suggestedAction: '确认发送回信',
    timestamp: '10 分钟前',
  },
  {
    id: 'conf-item-2',
    category: 'fact',
    title: '字节跳动：更新应聘进展至「二面通过」',
    description: '根据最新收到的面试反馈邮件，字节跳动客户端开发岗位已顺利通过二面。',
    contextReason: '是否将该应聘机会当前阶段同步推进至「HR 面 / Offer 沟通」？',
    suggestedAction: '确认更新状态',
    timestamp: '1 小时前',
  },
  {
    id: 'conf-item-3',
    category: 'profile_update',
    title: '求职档案：同步在面试中确证的项目亮点',
    description: '在腾讯二面复盘中确证了「高并发网关链路优化与熔断降级」技术事实。',
    contextReason: '是否将该项已确证的工程经历提炼并沉淀到你的个人核心档案中？',
    suggestedAction: '确认沉淀至档案',
    timestamp: '今天 09:15',
  },
];

export function ConfirmationWidget({
  initialItems = DEFAULT_CONFIRMATION_ITEMS,
  onResolve,
}: {
  initialItems?: ConfirmationItem[];
  onResolve?: (item: ConfirmationItem, decision: 'approve' | 'edit', note?: string) => void;
}) {
  const [items, setItems] = useState<ConfirmationItem[]>(initialItems);
  const [activeId, setActiveId] = useState<string>(initialItems[0]?.id ?? '');
  const [comment, setComment] = useState('');
  const [dismissingId, setDismissingId] = useState<string | null>(null);

  const activeIndex = items.findIndex((it) => it.id === activeId);
  const currentItem = activeIndex >= 0 ? items[activeIndex] : items[0];

  const handleDecision = (decision: 'approve' | 'edit') => {
    if (!currentItem) return;

    setDismissingId(currentItem.id);

    setTimeout(() => {
      onResolve?.(currentItem, decision, comment.trim() || undefined);
      toast.success(decision === 'approve' ? '已确认并执行' : '已提交修改意见');

      const remaining = items.filter((it) => it.id !== currentItem.id);
      setItems(remaining);
      setDismissingId(null);
      setComment('');

      if (remaining.length > 0) {
        setActiveId(remaining[0].id);
      }
    }, 280);
  };

  const getCategoryBadge = (cat: ConfirmationItem['category']) => {
    switch (cat) {
      case 'external_action':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
            <Mail size={10} />
            <span>外部动作审批</span>
          </span>
        );
      case 'fact':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-800 border border-blue-200">
            <Briefcase size={10} />
            <span>进展事实确认</span>
          </span>
        );
      case 'profile_update':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
            <UserCheck size={10} />
            <span>档案更新确认</span>
          </span>
        );
    }
  };

  return (
    <div className="h-full flex flex-col justify-between select-none">
      {/* Header */}
      <div className="flex items-center justify-between pb-1.5 border-b border-slate-200/50">
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-5 rounded-md bg-amber-100/70 text-amber-700 flex items-center justify-center font-bold">
            <ShieldAlert size={12} />
          </div>
          <span className="text-xs font-bold text-slate-800">待我确认</span>
          <span className="text-[10px] text-slate-400">· 需人工裁决</span>
        </div>
        <span className="text-[10px] font-mono font-bold text-amber-800 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">
          {items.length} 项
        </span>
      </div>

      {/* Main Content Area (Borderless) */}
      <div className="flex-1 flex flex-col justify-between py-2 overflow-hidden">
        {items.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-slate-400 animate-in fade-in duration-300">
            <div className="w-8 h-8 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center mb-1 shadow-2xs">
              <CheckCircle2 size={16} />
            </div>
            <p className="text-xs font-bold text-slate-800">🎉 全部处理完毕</p>
            <p className="text-[10px] text-slate-400">当前无待确认事项</p>
          </div>
        ) : (
          <div className="h-full flex flex-col justify-between space-y-2">
            {/* Top Expanded Item (Rendered directly on canvas without card container) */}
            {currentItem && (
              <div
                className={[
                  'space-y-1.5 transition-all duration-300 transform',
                  dismissingId === currentItem.id
                    ? 'translate-x-12 opacity-0 pointer-events-none'
                    : 'translate-x-0 opacity-100',
                ].join(' ')}
              >
                {/* Meta & Title */}
                <div className="flex items-center justify-between gap-2">
                  {getCategoryBadge(currentItem.category)}
                  {currentItem.timestamp && (
                    <span className="text-[10px] text-slate-400 font-mono">
                      {currentItem.timestamp}
                    </span>
                  )}
                </div>

                <div className="text-xs font-bold text-slate-900 leading-snug">
                  {currentItem.title}
                </div>

                <p className="text-[11px] text-slate-600 leading-relaxed">
                  {currentItem.description}
                </p>

                {/* Copilot Context Reason */}
                <div className="flex items-start gap-1 text-[10px] text-amber-900/90 leading-tight">
                  <Sparkles size={11} className="text-amber-600 shrink-0 mt-0.5" />
                  <span>{currentItem.contextReason}</span>
                </div>

                {/* Action Bar: Input + Confirm Button */}
                <div className="pt-1.5 flex items-center gap-1.5">
                  <div className="flex-1 relative">
                    <input
                      type="text"
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      placeholder="意见输入 / 修改建议…"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && comment.trim()) {
                          handleDecision('edit');
                        }
                      }}
                      className="w-full text-[11px] px-2.5 py-1 rounded-full bg-slate-100/90 hover:bg-slate-100 focus:bg-white border border-slate-200 focus:border-blue-400 outline-none transition-all pr-6"
                    />
                    {comment.trim() && (
                      <button
                        type="button"
                        onClick={() => handleDecision('edit')}
                        title="提交修改意见"
                        className="absolute right-1 top-1 p-0.5 text-blue-600 hover:bg-blue-50 rounded cursor-pointer"
                      >
                        <Send size={10} />
                      </button>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => handleDecision('approve')}
                    className="inline-flex items-center justify-center gap-1 px-3 py-1 rounded-full text-[11px] font-bold bg-blue-600 hover:bg-blue-700 active:scale-95 text-white shadow-xs transition-all cursor-pointer shrink-0"
                  >
                    <Check size={11} />
                    <span>{currentItem.suggestedAction || '确认发送回信'}</span>
                  </button>
                </div>
              </div>
            )}

            {/* Backlog Strips (Stacked lightweight pill rows below) */}
            <div className="space-y-1 pt-1 border-t border-slate-100/80">
              {items
                .filter((it) => it.id !== currentItem?.id)
                .slice(0, 2)
                .map((it) => (
                  <div
                    key={it.id}
                    onClick={() => setActiveId(it.id)}
                    className="px-2.5 py-1 rounded-full bg-slate-100/70 hover:bg-slate-200/80 transition-all cursor-pointer flex items-center justify-between gap-2 select-none group"
                  >
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Layers size={10} className="text-slate-400 shrink-0" />
                      <span className="text-[10px] font-medium text-slate-600 group-hover:text-slate-900 truncate">
                        {it.title}
                      </span>
                    </div>
                    <ChevronRight size={11} className="text-slate-400 group-hover:text-blue-600 transition-colors shrink-0" />
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="pt-1.5 border-t border-slate-200/50 flex items-center justify-between text-[9px] text-slate-400">
        <span>手风琴队列单焦点流转</span>
        <span className="text-amber-800 font-semibold">无静默越权</span>
      </div>
    </div>
  );
}
