import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Workflow,
  Plus,
  Search,
  RefreshCw,
} from 'lucide-react';
import {
  listJobOpportunities,
  createJobOpportunity,
  type OpportunityCreateInput,
} from '@/api/careerProcess';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type { JobOpportunity } from '@/types/career';
import { OpportunityCard } from './OpportunityCard';
import { ClosedOpportunitiesStack } from './ClosedOpportunitiesStack';
import { FormItem, TextInput, SelectInput } from './CareerFields';

export function CareerPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creating, setCreating] = useState(false);

  // New Opportunity Form State
  const [companyName, setCompanyName] = useState('');
  const [jobTitle, setJobTitle] = useState('');
  const [location, setLocation] = useState('');
  const [team, setTeam] = useState('');
  const [entryReason, setEntryReason] = useState<OpportunityCreateInput['entry_reason']>('explicit_tracking');

  // Query all opportunities including archived
  const opportunitiesQuery = useQuery({
    queryKey: ['career-opportunities-all'],
    queryFn: () => listJobOpportunities(true),
  });

  const allOpportunities = useMemo(() => opportunitiesQuery.data ?? [], [opportunitiesQuery.data]);

  // Split into active and closed
  const { activeOpportunities, closedOpportunities } = useMemo(() => {
    const active: JobOpportunity[] = [];
    const closed: JobOpportunity[] = [];

    const query = search.trim().toLowerCase();

    for (const opp of allOpportunities) {
      if (query) {
        const matches =
          opp.company_name.toLowerCase().includes(query) ||
          opp.job_title.toLowerCase().includes(query) ||
          (opp.location && opp.location.toLowerCase().includes(query));
        if (!matches) continue;
      }

      if (opp.outcome !== null || opp.archived_at !== null) {
        closed.push(opp);
      } else {
        active.push(opp);
      }
    }

    return { activeOpportunities: active, closedOpportunities: closed };
  }, [allOpportunities, search]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['career-opportunities-all'] });
  };

  const handleCreateOpportunity = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!companyName.trim() || !jobTitle.trim()) {
      toast.error('请填写公司名称与岗位名称');
      return;
    }

    setCreating(true);
    try {
      await createJobOpportunity({
        company_name: companyName.trim(),
        job_title: jobTitle.trim(),
        entry_reason: entryReason,
        occurred_at: new Date().toISOString(),
        source_kind: 'user_assertion',
        source_identity: 'user_manual_entry',
        source_description: '用户在求职看板手动创建岗位机会',
        location: location.trim() || undefined,
        team: team.trim() || undefined,
      });

      await refresh();
      toast.success('已添加新岗位跟进');
      setShowCreateModal(false);
      setCompanyName('');
      setJobTitle('');
      setLocation('');
      setTeam('');
    } catch (error) {
      toast.error(extractErr(error));
    } finally {
      setCreating(false);
    }
  };

  const handleAction = (opp: JobOpportunity) => {
    toast.success(`正在跳转处理：${opp.company_name} · ${opp.job_title}`);
  };

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6 lg:p-8 bg-[#F8FAFC]">
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 pb-2 border-b border-slate-200/80">
          <div>
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-semibold mb-1.5">
              <Workflow size={13} />
              <span>多岗位动态求职空间</span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">求职进程</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              全生命周期动态跟进各应聘机会，客观呈现真实演进阶段与行动指南。
            </p>
          </div>

          <div className="flex items-center gap-2.5">
            <Btn
              kind="ghost"
              size="sm"
              icon={<RefreshCw size={13} />}
              loading={opportunitiesQuery.isFetching}
              onClick={refresh}
            >
              刷新
            </Btn>
            <Btn
              kind="primary"
              size="sm"
              icon={<Plus size={14} />}
              className="rounded-full shadow-xs"
              onClick={() => setShowCreateModal(true)}
            >
              跟进新岗位
            </Btn>
          </div>
        </header>

        {/* Search & Filter Bar */}
        <div className="flex items-center justify-between gap-3">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3.5 top-3 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索公司名称、岗位或地点…"
              className="w-full pl-9 pr-4 py-2 rounded-2xl bg-white border border-slate-200 text-xs text-slate-800 placeholder-slate-400 focus:border-blue-400 outline-none shadow-2xs transition-all"
            />
          </div>

          <div className="text-xs font-mono font-bold text-slate-500 bg-white px-3 py-2 rounded-2xl border border-slate-200 shadow-2xs">
            正在跟进 {activeOpportunities.length} 个岗位
          </div>
        </div>

        {/* Active Opportunities Horizontal Cards Stream */}
        <div className="space-y-4">
          {opportunitiesQuery.isLoading ? (
            <div className="py-16 flex flex-col items-center justify-center text-slate-400 text-xs gap-2">
              <Spinner size={20} />
              <span>载入求职进程…</span>
            </div>
          ) : activeOpportunities.length === 0 ? (
            <EmptyState
              icon={<Workflow size={24} />}
              title="暂无进行中的岗位跟进"
              description="点击右上角「跟进新岗位」或在 Copilot 对话中让 Agent 自动为你捕获招聘邮件与面试进度。"
            />
          ) : (
            activeOpportunities.map((opp) => (
              <OpportunityCard
                key={opp.id}
                opportunity={opp}
                onHandleAction={handleAction}
              />
            ))
          )}
        </div>

        {/* Closed Opportunities Bottom Stack */}
        <ClosedOpportunitiesStack opportunities={closedOpportunities} />
      </div>

      {/* Create Opportunity Modal */}
      {showCreateModal && (
        <Modal
          open
          onClose={() => setShowCreateModal(false)}
          title="跟进新的岗位应聘"
        >
          <form onSubmit={handleCreateOpportunity} className="space-y-4 text-xs">
            <FormItem label="目标公司名称 (必填)">
              <TextInput
                placeholder="例如：腾讯、字节跳动、阿里巴巴…"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
              />
            </FormItem>

            <FormItem label="投递岗位名称 (必填)">
              <TextInput
                placeholder="例如：高级后端开发工程师、前端架构师…"
                value={jobTitle}
                onChange={(e) => setJobTitle(e.target.value)}
              />
            </FormItem>

            <div className="grid grid-cols-2 gap-3">
              <FormItem label="工作地点 (可选)">
                <TextInput
                  placeholder="例如：北京 / 深圳 / 远程"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                />
              </FormItem>

              <FormItem label="所属部门 / 业务线 (可选)">
                <TextInput
                  placeholder="例如：微信事业群 / 基础架构"
                  value={team}
                  onChange={(e) => setTeam(e.target.value)}
                />
              </FormItem>
            </div>

            <FormItem label="跟进初始状态">
              <SelectInput
                value={entryReason}
                onChange={(e) => setEntryReason(e.target.value as OpportunityCreateInput['entry_reason'])}
              >
                <option value="explicit_tracking">开始跟进（意向 / 准备中）</option>
                <option value="user_confirmed_application">已正式投递（等待初筛）</option>
                <option value="targeted_preparation">针对性冲刺准备中</option>
              </SelectInput>
            </FormItem>

            <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
              <Btn kind="ghost" size="sm" onClick={() => setShowCreateModal(false)}>
                取消
              </Btn>
              <Btn kind="primary" size="sm" loading={creating} disabled={!companyName.trim() || !jobTitle.trim()}>
                确认创建
              </Btn>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
