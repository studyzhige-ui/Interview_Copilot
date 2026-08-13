import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Cable, CheckCircle2, Mail, RefreshCw, Shield, Unplug } from 'lucide-react';
import {
  authorizeGmailIntegration,
  getGmailIntegration,
  revokeGmailIntegration,
  testGmailIntegration,
} from '@/api/integrations';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { displayDate } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';

const GMAIL_KEY = ['integrations', 'gmail'] as const;

function connectionError(error: unknown): string {
  const status = (error as { response?: { status?: number } })?.response?.status;
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  if (status === 503 || detail === 'gmail_adapter_unavailable') {
    return '当前部署尚未配置真实 Gmail Provider Adapter，无法执行连接测试或撤销。';
  }
  if (status === 409 || detail === 'gmail_connection_required') {
    return '当前没有可用的 Gmail 授权。';
  }
  return extractErr(error);
}

function oauthReturnError(code: string | null): string {
  if (code === 'oauth_authorization_denied') return 'Google 授权已取消，Gmail 连接没有发生变化。';
  if (code === 'oauth_state_expired' || code === 'oauth_state_invalid') {
    return 'Gmail 授权链接已失效，请重新发起连接。';
  }
  if (code === 'gmail_readonly_scope_required') {
    return '未获得必需的 Gmail 只读范围，请重新授权并保留该范围。';
  }
  if (code === 'google_email_unverified') {
    return '该 Google 邮箱身份尚未验证，暂时无法连接。';
  }
  if (code === 'provider_timeout' || code === 'provider_unavailable') {
    return 'Google 授权服务暂时不可用，请稍后重试。';
  }
  return 'Gmail 授权未能完成，请重新发起连接。';
}

export function ConnectionsPage() {
  const queryClient = useQueryClient();
  const gmailQuery = useQuery({ queryKey: GMAIL_KEY, queryFn: getGmailIntegration });
  const { refetch: refetchGmail } = gmailQuery;
  const [busy, setBusy] = useState<'authorize' | 'test' | 'revoke' | null>(null);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [adapterFailure, setAdapterFailure] = useState(false);
  const account = gmailQuery.data?.account ?? null;
  const adapterUnavailable = gmailQuery.data?.adapter_available === false || adapterFailure;

  useEffect(() => {
    const returnUrl = new URL(window.location.href);
    const outcome = returnUrl.searchParams.get('gmail_oauth_outcome');
    const errorCode = returnUrl.searchParams.get('gmail_oauth_error');
    if (outcome === null && errorCode === null) return;

    // Consume only the backend's bounded result fields. Never surface raw
    // provider query text, and keep unrelated product query parameters.
    returnUrl.searchParams.delete('gmail_oauth_outcome');
    returnUrl.searchParams.delete('gmail_oauth_error');
    window.history.replaceState(
      window.history.state,
      '',
      `${returnUrl.pathname}${returnUrl.search}${returnUrl.hash}`,
    );

    if (outcome === 'connected') toast.success('Gmail 已连接，可以使用只读检查与搜索。');
    else toast.error(oauthReturnError(errorCode));
    void refetchGmail();
  }, [refetchGmail]);

  useEffect(() => {
    const refreshOnReturn = () => { void refetchGmail(); };
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') void refetchGmail();
    };
    window.addEventListener('focus', refreshOnReturn);
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => {
      window.removeEventListener('focus', refreshOnReturn);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
    };
  }, [refetchGmail]);

  const authorize = async () => {
    // Open synchronously with the user's click so browser popup protection
    // does not discard the OAuth handoff while the authorization URL is
    // being requested. Cut the opener before navigating to Google.
    const authorizationWindow = window.open(
      'about:blank',
      'gmail-oauth',
      'popup,width=620,height=760',
    );
    if (authorizationWindow) authorizationWindow.opener = null;
    setBusy('authorize');
    try {
      const handoff = await authorizeGmailIntegration();
      setAdapterFailure(false);
      if (authorizationWindow) authorizationWindow.location.replace(handoff.authorization_url);
      else window.location.assign(handoff.authorization_url);
    } catch (error) {
      authorizationWindow?.close();
      const status = (error as { response?: { status?: number } })?.response?.status;
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (status === 503 || detail === 'gmail_adapter_unavailable') setAdapterFailure(true);
      toast.error(connectionError(error));
    } finally {
      setBusy(null);
    }
  };

  const run = async (kind: 'test' | 'revoke') => {
    setBusy(kind);
    try {
      const next = kind === 'test'
        ? await testGmailIntegration()
        : await revokeGmailIntegration();
      queryClient.setQueryData(GMAIL_KEY, next);
      if (kind === 'revoke') setRevokeOpen(false);
      toast.success(kind === 'test' ? 'Gmail 连接检查已完成' : 'Gmail 授权已撤销');
    } catch (error) {
      toast.error(connectionError(error));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-xl font-semibold text-stone-800">外部连接</h1>
        <p className="mt-1 text-sm text-stone-500">外部账号、授权范围和连接状态在这里明确管理；Secret 不会显示或进入 Agent 对话。</p>
      </header>

      <section className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-xs">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-stone-100 p-5">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-danger-50 p-2.5 text-danger-600"><Mail size={20} /></div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold text-stone-800">Gmail</h2>
                {gmailQuery.data && (
                  <Pill tone={account?.status === 'active' && !gmailQuery.data.connection_required ? 'success' : 'neutral'}>
                    {account?.status === 'active' && !gmailQuery.data.connection_required ? '已连接' : '未连接'}
                  </Pill>
                )}
              </div>
              <p className="mt-1 text-xs text-stone-500">只提供受控的只读邮箱检查与搜索，不会代替你发送邮件。</p>
            </div>
          </div>
          <Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={() => { setAdapterFailure(false); void refetchGmail(); }}>刷新状态</Btn>
        </div>

        {gmailQuery.isLoading ? (
          <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Spinner size={15} />正在读取连接状态…</div>
        ) : gmailQuery.isError ? (
          <div className="p-5">
            <EmptyState icon={<Cable size={30} />} title="Gmail 状态暂时无法读取" description={connectionError(gmailQuery.error)} action={<Btn size="sm" onClick={() => refetchGmail()}>重试</Btn>} />
          </div>
        ) : account ? (
          <div className="space-y-4 p-5">
            <div className="grid gap-4 text-sm sm:grid-cols-2">
              <ConnectionFact label="账号" value={account.account_hint} />
              <ConnectionFact label="状态" value={account.status} />
              <ConnectionFact label="最近检查" value={displayDate(account.last_checked_at)} />
              <ConnectionFact label="最近错误" value={account.last_error_code ?? '无'} />
              <ConnectionFact label="Observation 增量游标" value={account.history_cursor_updated_at ? '已建立' : '尚未建立'} />
              <ConnectionFact label="最近增量同步" value={displayDate(account.last_observation_sync_at)} />
            </div>
            {account.last_observation_sync_error_code && (
              <div role="alert" className="rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800">
                增量同步需要处理：{account.last_observation_sync_error_code === 'history_cursor_expired'
                  ? 'Gmail 游标已过期，请进入对应持续任务确认从当前时点重建。'
                  : account.last_observation_sync_error_code}
              </div>
            )}
            <div>
              <div className="mb-2 text-xs font-medium text-stone-500">已授权 scope</div>
              <div className="flex flex-wrap gap-1.5">
                {account.scopes.map((scope) => <Pill key={scope}>{scope}</Pill>)}
              </div>
            </div>
            <div className="flex flex-wrap gap-2 border-t border-stone-100 pt-4">
              {gmailQuery.data?.connection_required && (
                <Btn size="sm" icon={<Cable size={14} />} loading={busy === 'authorize'} disabled={busy !== null || adapterUnavailable} onClick={() => { void authorize(); }}>
                  {account.status === 'revoked' ? '重新连接 Gmail' : '修复 Gmail 连接'}
                </Btn>
              )}
              <Btn size="sm" icon={<CheckCircle2 size={14} />} loading={busy === 'test'} disabled={busy !== null || account.status !== 'active'} onClick={() => { void run('test'); }}>测试真实连接</Btn>
              <Btn kind="outline" size="sm" icon={<Unplug size={14} />} disabled={busy !== null || account.status === 'revoked'} onClick={() => setRevokeOpen(true)}>撤销授权</Btn>
            </div>
          </div>
        ) : (
          <div className="p-5">
            <div className="rounded-xl border border-warning-200 bg-warning-50 p-4">
              <div className="flex items-start gap-3">
                <Cable size={18} className="mt-0.5 shrink-0 text-warning-700" />
                <div>
                  <h3 className="text-sm font-medium text-stone-800">连接 Gmail</h3>
                  <p className="mt-1 text-xs leading-relaxed text-stone-600">
                    点击后会前往 Google 授权页，只请求已列明的 Gmail 只读范围。返回本页时会重新读取服务端连接状态。
                  </p>
                  {adapterUnavailable && (
                    <p role="alert" className="mt-2 text-xs text-danger-700">当前部署未配置 Gmail Adapter；配置完成前无法发起授权，Gmail Tool 也不会注册。</p>
                  )}
                  <Btn className="mt-3" size="sm" loading={busy === 'authorize'} disabled={busy !== null || adapterUnavailable} onClick={() => { void authorize(); }}>
                    {adapterUnavailable ? 'Gmail 尚未配置' : '前往 Google 连接'}
                  </Btn>
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={revokeOpen}
        title="撤销 Gmail 授权？"
        description="撤销后，Agent 将无法继续检查或搜索此 Gmail 账号；重新使用前需要再次完成 Google 授权。"
        confirmText="撤销授权"
        danger
        loading={busy === 'revoke'}
        onCancel={() => setRevokeOpen(false)}
        onConfirm={() => { void run('revoke'); }}
      />

      <section className="rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
        <div className="flex items-start gap-3">
          <Shield size={18} className="mt-0.5 shrink-0 text-primary-600" />
          <div>
            <h2 className="text-sm font-medium text-stone-800">连接边界</h2>
            <p className="mt-1 text-xs leading-relaxed text-stone-500">
              Agent 只能通过已接入的具体 Tool 使用你明确授权的远程服务。连接不等于批准每次外部写操作，也不会让模型看到 OAuth token 或 credential handle。
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

function ConnectionFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-stone-50 px-3 py-2">
      <div className="text-[11px] text-stone-400">{label}</div>
      <div className="mt-0.5 break-words text-stone-700">{value}</div>
    </div>
  );
}
