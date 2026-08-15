import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Cable, CheckCircle2, Clipboard, ExternalLink, RefreshCw, Shield, Unplug, X } from 'lucide-react';
import {
  authorizeExternalPlugin,
  authorizeGmailIntegration,
  getExternalPluginStatus,
  getGmailIntegration,
  revokeExternalPlugin,
  revokeGmailIntegration,
  testExternalPlugin,
  testGmailIntegration,
} from '@/api/integrations';
import { extractErr } from '@/api/client';
import { apiUrl } from '@/api/apiUrl';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { displayDate } from '@/pages/career/CareerFields';
import { toast } from '@/store/uiStore';
import type {
  ExternalPluginProvider,
  ExternalPluginStatus,
  GmailIntegrationStatus,
} from '@/types/integrations';

export type ConnectablePlugin = 'gmail' | ExternalPluginProvider;
type PluginStatus = GmailIntegrationStatus | ExternalPluginStatus;

const PLUGIN_COPY: Record<ConnectablePlugin, {
  name: string;
  accountLabel: string;
  connectLabel: string;
  description: string;
  permission: string;
}> = {
  gmail: {
    name: 'Gmail', accountLabel: 'Google 账号', connectLabel: '前往 Google 连接',
    description: '读取招聘邮件与流程变化；不会发送、修改或删除邮件。',
    permission: 'Gmail 只读',
  },
  canva: {
    name: 'Canva', accountLabel: 'Canva 账号', connectLabel: '前往 Canva 连接',
    description: '搜索你拥有或共享的设计元数据；不会修改、导出或发布设计。',
    permission: 'design:meta:read',
  },
  notion: {
    name: 'Notion', accountLabel: 'Notion 工作区', connectLabel: '前往 Notion 连接',
    description: '只搜索你在授权页明确共享给连接的页面标题；不会读取整个工作区。',
    permission: '页面读取',
  },
};

const DEPLOYMENT_SETUP: Record<ConnectablePlugin, {
  portalUrl: string;
  portalLabel: string;
  docsUrl: string;
}> = {
  gmail: {
    portalUrl: 'https://console.cloud.google.com/apis/credentials',
    portalLabel: '打开 Google Cloud OAuth 凭据',
    docsUrl: 'https://developers.google.com/workspace/gmail/api/auth/web-server',
  },
  canva: {
    portalUrl: 'https://www.canva.com/developers/',
    portalLabel: '打开 Canva Developer Portal',
    docsUrl: 'https://www.canva.dev/docs/connect/authentication/',
  },
  notion: {
    portalUrl: 'https://www.notion.so/profile/integrations',
    portalLabel: '打开 Notion Creator Dashboard',
    docsUrl: 'https://developers.notion.com/guides/get-started/authorization',
  },
};

function deploymentTemplate(provider: ConnectablePlugin): { callback: string; text: string } {
  const productReturn = `${window.location.origin}/plugins`;
  if (provider === 'gmail') {
    const callback = apiUrl('/integrations/gmail/callback');
    return {
      callback,
      text: [
        'GMAIL_GOOGLE_OAUTH_CLIENT_ID=<Google Client ID>',
        'GMAIL_GOOGLE_OAUTH_CLIENT_SECRET=<Google Client Secret>',
        `GMAIL_GOOGLE_OAUTH_REDIRECT_URI=${callback}`,
        `GMAIL_OAUTH_PRODUCT_RETURN_URI=${productReturn}`,
        'GMAIL_CREDENTIAL_STORE_FILE=D:/InterviewCopilotSecrets/gmail-credentials.json',
        'GMAIL_CREDENTIAL_STORE_KEY=<独立 Fernet key>',
      ].join('\n'),
    };
  }
  const callback = apiUrl(`/integrations/plugins/${provider}/callback`);
  const prefix = provider === 'canva' ? 'CANVA' : 'NOTION';
  return {
    callback,
    text: [
      `PLUGIN_OAUTH_PRODUCT_RETURN_URI=${productReturn}`,
      'PLUGIN_CREDENTIAL_STORE_FILE=D:/InterviewCopilotSecrets/plugin-credentials.json',
      'PLUGIN_CREDENTIAL_STORE_KEY=<独立 Fernet key>',
      `${prefix}_OAUTH_CLIENT_ID=<${PLUGIN_COPY[provider].name} Client ID>`,
      `${prefix}_OAUTH_CLIENT_SECRET=<${PLUGIN_COPY[provider].name} Client Secret>`,
      `${prefix}_OAUTH_REDIRECT_URI=${callback}`,
    ].join('\n'),
  };
}

function queryKey(provider: ConnectablePlugin) {
  return ['integrations', provider] as const;
}

async function statusFor(provider: ConnectablePlugin): Promise<PluginStatus> {
  return provider === 'gmail' ? getGmailIntegration() : getExternalPluginStatus(provider);
}

async function authorizeFor(provider: ConnectablePlugin) {
  return provider === 'gmail' ? authorizeGmailIntegration() : authorizeExternalPlugin(provider);
}

async function testFor(provider: ConnectablePlugin): Promise<PluginStatus> {
  return provider === 'gmail' ? testGmailIntegration() : testExternalPlugin(provider);
}

async function revokeFor(provider: ConnectablePlugin): Promise<PluginStatus> {
  return provider === 'gmail' ? revokeGmailIntegration() : revokeExternalPlugin(provider);
}

function safeOAuthError(provider: ConnectablePlugin, code: string | null): string {
  if (code === 'oauth_authorization_denied') return `${PLUGIN_COPY[provider].name} 授权已取消，连接没有发生变化。`;
  if (code === 'oauth_state_expired' || code === 'oauth_state_invalid') return '授权链接已失效，请重新发起连接。';
  if (code === 'invalid_scope' || code === 'gmail_readonly_scope_required') return '没有获得必需的只读权限，请重新授权。';
  if (code === 'provider_timeout' || code === 'provider_unavailable') return '授权服务暂时不可用，请稍后重试。';
  return `${PLUGIN_COPY[provider].name} 授权未能完成，请重新发起连接。`;
}

function connectionError(provider: ConnectablePlugin, error: unknown): string {
  const status = (error as { response?: { status?: number } })?.response?.status;
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  if (status === 503 || detail === 'gmail_adapter_unavailable' || detail === 'plugin_adapter_unavailable') {
    return `当前部署尚未配置真实 ${PLUGIN_COPY[provider].name} OAuth Adapter。`;
  }
  if (status === 409 || detail === 'gmail_connection_required' || detail === 'plugin_connection_required') {
    return `当前没有可用的 ${PLUGIN_COPY[provider].name} 授权。`;
  }
  return extractErr(error);
}

export function PluginConnectionPanel({
  provider,
  onClose,
}: {
  provider: ConnectablePlugin;
  onClose: () => void;
}) {
  const copy = PLUGIN_COPY[provider];
  const client = useQueryClient();
  const statusQuery = useQuery({ queryKey: queryKey(provider), queryFn: () => statusFor(provider) });
  const { refetch } = statusQuery;
  const [busy, setBusy] = useState<'authorize' | 'test' | 'revoke' | null>(null);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [adapterFailure, setAdapterFailure] = useState(false);
  const account = statusQuery.data?.account ?? null;
  const unavailable = statusQuery.data?.adapter_available === false || adapterFailure;

  useEffect(() => {
    const url = new URL(window.location.href);
    const isGmailReturn = provider === 'gmail' && (
      url.searchParams.has('gmail_oauth_outcome') || url.searchParams.has('gmail_oauth_error')
    );
    const returnedProvider = url.searchParams.get('plugin_oauth_provider');
    const isExternalReturn = provider !== 'gmail'
      && returnedProvider === provider
      && (url.searchParams.has('plugin_oauth_outcome') || url.searchParams.has('plugin_oauth_error'));
    if (!isGmailReturn && !isExternalReturn) return;

    const outcomeKey = provider === 'gmail' ? 'gmail_oauth_outcome' : 'plugin_oauth_outcome';
    const errorKey = provider === 'gmail' ? 'gmail_oauth_error' : 'plugin_oauth_error';
    const outcome = url.searchParams.get(outcomeKey);
    const errorCode = url.searchParams.get(errorKey);
    url.searchParams.delete(outcomeKey);
    url.searchParams.delete(errorKey);
    if (provider !== 'gmail') url.searchParams.delete('plugin_oauth_provider');
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
    if (outcome === 'connected') toast.success(`${copy.name} 已连接`);
    else toast.error(safeOAuthError(provider, errorCode));
    void refetch();
  }, [copy.name, provider, refetch]);

  useEffect(() => {
    const refresh = () => { void refetch(); };
    const visible = () => { if (document.visibilityState === 'visible') void refetch(); };
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [refetch]);

  const authorize = async () => {
    const popup = window.open('about:blank', `${provider}-oauth`, 'popup,width=620,height=760');
    if (popup) popup.opener = null;
    setBusy('authorize');
    try {
      const handoff = await authorizeFor(provider);
      setAdapterFailure(false);
      if (popup) popup.location.replace(handoff.authorization_url);
      else window.location.assign(handoff.authorization_url);
    } catch (error) {
      popup?.close();
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (status === 503) setAdapterFailure(true);
      toast.error(connectionError(provider, error));
    } finally {
      setBusy(null);
    }
  };

  const run = async (kind: 'test' | 'revoke') => {
    setBusy(kind);
    try {
      const next = kind === 'test' ? await testFor(provider) : await revokeFor(provider);
      client.setQueryData(queryKey(provider), next);
      if (kind === 'revoke') setRevokeOpen(false);
      toast.success(kind === 'test' ? `${copy.name} 连接检查已完成` : `${copy.name} 授权已撤销`);
    } catch (error) {
      toast.error(connectionError(provider, error));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-label={`${copy.name} 插件连接`} className="mt-5 overflow-hidden rounded-2xl border border-primary-200 bg-white shadow-sm">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-stone-100 p-5">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-stone-900">{copy.name}</h2>
            {statusQuery.data && (
              <Pill tone={account?.status === 'active' && !statusQuery.data.connection_required ? 'success' : 'neutral'}>
                {account?.status === 'active' && !statusQuery.data.connection_required ? '已连接' : '未连接'}
              </Pill>
            )}
          </div>
          <p className="mt-1 text-sm text-stone-500">{copy.description}</p>
        </div>
        <div className="flex gap-1">
          <Btn kind="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={() => { setAdapterFailure(false); void refetch(); }}>刷新</Btn>
          <button type="button" aria-label="关闭插件详情" onClick={onClose} className="rounded-lg p-2 text-stone-400 hover:bg-stone-100 hover:text-stone-700"><X size={16} /></button>
        </div>
      </header>

      {statusQuery.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Spinner size={15} />正在读取连接状态…</div>
      ) : statusQuery.isError ? (
        <div className="p-5"><EmptyState icon={<Cable size={28} />} title="连接状态暂时无法读取" description={connectionError(provider, statusQuery.error)} action={<Btn size="sm" onClick={() => refetch()}>重试</Btn>} /></div>
      ) : account ? (
        <div className="space-y-4 p-5">
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <ConnectionFact label={copy.accountLabel} value={account.account_hint} />
            <ConnectionFact label="状态" value={account.status} />
            <ConnectionFact label="最近检查" value={displayDate(account.last_checked_at)} />
            <ConnectionFact label="最近错误" value={account.last_error_code ?? '无'} />
          </div>
          <div>
            <div className="mb-2 text-xs font-medium text-stone-500">已授权范围</div>
            <div className="flex flex-wrap gap-1.5">{account.scopes.map((scope) => <Pill key={scope}>{scope}</Pill>)}</div>
          </div>
          <div className="flex flex-wrap gap-2 border-t border-stone-100 pt-4">
            {statusQuery.data?.connection_required && <Btn size="sm" loading={busy === 'authorize'} disabled={busy !== null || unavailable} onClick={() => { void authorize(); }}>重新连接</Btn>}
            <Btn size="sm" icon={<CheckCircle2 size={14} />} loading={busy === 'test'} disabled={busy !== null || account.status !== 'active'} onClick={() => { void run('test'); }}>测试真实连接</Btn>
            <Btn kind="outline" size="sm" icon={<Unplug size={14} />} disabled={busy !== null || account.status === 'revoked'} onClick={() => setRevokeOpen(true)}>撤销授权</Btn>
          </div>
        </div>
      ) : (
        <div className="p-5">
          <div className="rounded-xl border border-warning-200 bg-warning-50 p-4">
            <h3 className="text-sm font-medium text-stone-800">连接 {copy.name}</h3>
            <p className="mt-1 text-xs leading-relaxed text-stone-600">授权会在新窗口完成，只请求「{copy.permission}」。返回插件市场后会重新读取服务端事实。</p>
            {unavailable ? (
              <DeploymentSetup provider={provider} onRefresh={() => { setAdapterFailure(false); void refetch(); }} />
            ) : (
              <Btn className="mt-3" size="sm" loading={busy === 'authorize'} disabled={busy !== null} onClick={() => { void authorize(); }}>
                {copy.connectLabel}
              </Btn>
            )}
          </div>
        </div>
      )}

      <footer className="flex items-start gap-2 border-t border-stone-100 bg-stone-50 px-5 py-3 text-xs text-stone-500">
        <Shield size={14} className="mt-0.5 shrink-0 text-primary-600" />
        OAuth token 与 credential handle 不会显示或进入模型；连接也不等于批准外部写操作。
      </footer>
      <ConfirmDialog
        open={revokeOpen}
        title={`撤销 ${copy.name} 授权？`}
        description={`撤销后，Copilot 无法继续使用此 ${copy.name} 账号；重新使用前需要再次授权。`}
        confirmText="撤销授权"
        danger
        loading={busy === 'revoke'}
        onCancel={() => setRevokeOpen(false)}
        onConfirm={() => { void run('revoke'); }}
      />
    </section>
  );
}

function DeploymentSetup({
  provider,
  onRefresh,
}: {
  provider: ConnectablePlugin;
  onRefresh: () => void;
}) {
  const setup = DEPLOYMENT_SETUP[provider];
  const template = deploymentTemplate(provider);
  const copy = PLUGIN_COPY[provider];
  const copyTemplate = async () => {
    try {
      await navigator.clipboard.writeText(template.text);
      toast.success(`${copy.name} 的 .env 配置清单已复制`);
    } catch {
      toast.error('复制失败，请手动复制配置清单');
    }
  };
  return (
    <div className="mt-3 rounded-xl border border-warning-300 bg-white p-4" role="alert">
      <div className="text-sm font-medium text-warning-900">先完成一次部署配置，再连接个人账号</div>
      <ol className="mt-2 space-y-2 text-xs leading-relaxed text-stone-600">
        <li><span className="mr-1 font-semibold text-stone-800">1.</span>在 {copy.name} 开发者后台创建 OAuth Web 应用，并只申请本卡片标明的只读范围。</li>
        <li><span className="mr-1 font-semibold text-stone-800">2.</span>登记完全一致的回调地址：<code className="ml-1 break-all rounded bg-stone-100 px-1 py-0.5 text-[11px]">{template.callback}</code></li>
        <li><span className="mr-1 font-semibold text-stone-800">3.</span>把 Client ID、Client Secret 和独立 Fernet key 写入项目根目录 <code className="rounded bg-stone-100 px-1 py-0.5 text-[11px]">.env</code>，重启 API 与 Worker 后点击“重新检查”。</li>
      </ol>
      <div className="mt-3 rounded-lg bg-stone-950 p-3 font-mono text-[11px] leading-relaxed text-stone-100 whitespace-pre-wrap break-all">{template.text}</div>
      <p className="mt-2 text-[11px] leading-relaxed text-stone-500">
        Fernet key 可在后端环境运行：<code className="rounded bg-stone-100 px-1 py-0.5">python -c &quot;from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())&quot;</code>。Client Secret 不应提交 Git，也不能由普通用户在网页里填写。
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <a href={setup.portalUrl} target="_blank" rel="noreferrer"><Btn size="sm" icon={<ExternalLink size={13} />}>{setup.portalLabel}</Btn></a>
        <a href={setup.docsUrl} target="_blank" rel="noreferrer"><Btn kind="outline" size="sm">官方配置文档</Btn></a>
        <Btn kind="outline" size="sm" icon={<Clipboard size={13} />} onClick={() => { void copyTemplate(); }}>复制 .env 清单</Btn>
        <Btn kind="ghost" size="sm" icon={<RefreshCw size={13} />} onClick={onRefresh}>重新检查</Btn>
      </div>
    </div>
  );
}

function ConnectionFact({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-stone-50 px-3 py-2"><div className="text-[11px] text-stone-400">{label}</div><div className="mt-0.5 break-words text-stone-700">{value}</div></div>;
}
