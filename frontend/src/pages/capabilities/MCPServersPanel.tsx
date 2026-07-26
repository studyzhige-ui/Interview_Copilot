import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Cable, Pencil, Play, Plus, Trash2 } from 'lucide-react';
import {
  createMCPServer,
  deleteMCPServer,
  listMCPServers,
  setMCPServerEnabled,
  testMCPServer,
  updateMCPServer,
  type MCPTransport,
  type MCPServerInput,
  type UserMCPServer,
} from '@/api/capabilities';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { useToastOnError } from '@/hooks/useToastOnError';
import { toast } from '@/store/uiStore';
import { MCPServerEditorModal } from './MCPServerEditorModal';

const statusStyle = {
  connected: 'bg-emerald-50 text-emerald-700',
  connecting: 'bg-amber-50 text-amber-700',
  failed: 'bg-red-50 text-red-700',
  unchecked: 'bg-stone-100 text-stone-500',
};

const statusLabel = {
  connected: '已连接',
  connecting: '连接中',
  failed: '连接失败',
  unchecked: '未测试',
};

function displayStatus(server: UserMCPServer): keyof typeof statusLabel {
  const runtime = server.runtime?.status;
  return runtime === 'closed' || !runtime ? server.last_status : runtime;
}

export function MCPServersPanel({ allowedTransports }: { allowedTransports: MCPTransport[] }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<UserMCPServer | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [deleting, setDeleting] = useState<UserMCPServer | null>(null);
  const query = useQuery({ queryKey: ['capabilities', 'mcp'], queryFn: listMCPServers });
  useToastOnError(query.error, 'MCP 服务加载失败');

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['capabilities', 'mcp'] });
  const save = useMutation({
    mutationFn: (input: MCPServerInput) => editing
      ? updateMCPServer(editing.id, input)
      : createMCPServer(input),
    onSuccess: () => {
      refresh();
      setEditorOpen(false);
      toast.success('MCP 服务已保存');
    },
    onError: (error) => toast.error(extractErr(error, 'MCP 服务保存失败')),
  });
  const toggle = useMutation({
    mutationFn: (server: UserMCPServer) => setMCPServerEnabled(server.id, !server.enabled),
    onSuccess: refresh,
    onError: (error) => toast.error(extractErr(error, 'MCP 状态更新失败')),
  });
  const test = useMutation({
    mutationFn: (id: number) => testMCPServer(id),
    onSuccess: (result) => {
      refresh();
      toast.success(`连接成功，发现 ${result.tools.length} 个工具`);
    },
    onError: (error) => {
      refresh();
      toast.error(extractErr(error, 'MCP 连接失败'));
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteMCPServer(id),
    onSuccess: () => {
      refresh();
      setDeleting(null);
      toast.success('MCP 服务已删除');
    },
    onError: (error) => toast.error(extractErr(error, 'MCP 服务删除失败')),
  });

  const openEditor = (server: UserMCPServer | null) => {
    setEditing(server);
    setEditorOpen(true);
  };

  return (
    <section>
      <div className="flex items-start justify-between gap-6 mb-5">
        <div>
          <h2 className="text-lg font-semibold text-stone-800">MCP 服务</h2>
          <p className="mt-1 text-sm text-stone-500">连接你自己的工具服务；Agent 只会按需加载选中工具的 Schema。</p>
        </div>
        <Btn icon={<Plus size={16} />} onClick={() => openEditor(null)}>添加服务</Btn>
      </div>

      {query.isPending ? (
        <div className="py-16 flex justify-center"><Spinner /></div>
      ) : !query.data?.length ? (
        <EmptyState
          icon={<Cable size={28} />}
          title="还没有 MCP 服务"
          description={allowedTransports.includes('stdio')
            ? '添加一个 Streamable HTTP 或可信的 stdio MCP 服务。'
            : '添加一个远程 Streamable HTTP MCP 服务。'}
        />
      ) : (
        <div className="grid gap-3">
          {query.data.map((server) => {
            const liveStatus = displayStatus(server);
            return <article key={server.id} className="rounded-xl border border-stone-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium text-stone-800 truncate">{server.name}</h3>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] ${statusStyle[liveStatus]}`}>
                      {statusLabel[liveStatus]}
                    </span>
                    {!server.enabled && <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-stone-500">已停用</span>}
                  </div>
                  <p className="mt-1 truncate text-sm text-stone-500">
                    {server.transport === 'streamable_http' ? server.url : [server.command, ...server.args].join(' ')}
                  </p>
                  {server.last_status === 'connected' && <p className="mt-1 text-xs text-stone-400">发现 {server.tool_count} 个工具</p>}
                  {(server.runtime?.error || server.last_error) && <p className="mt-1 text-xs text-danger-500 line-clamp-2">{server.runtime?.error || server.last_error}</p>}
                </div>
                <Btn size="sm" kind="outline" icon={<Play size={14} />} loading={test.isPending && test.variables === server.id} onClick={() => test.mutate(server.id)}>测试</Btn>
                <Btn size="sm" kind="ghost" onClick={() => toggle.mutate(server)}>{server.enabled ? '停用' : '启用'}</Btn>
                <button aria-label={`编辑 ${server.name}`} onClick={() => openEditor(server)} className="p-2 text-stone-500 hover:text-primary-700"><Pencil size={16} /></button>
                <button aria-label={`删除 ${server.name}`} onClick={() => setDeleting(server)} className="p-2 text-stone-500 hover:text-danger-500"><Trash2 size={16} /></button>
              </div>
            </article>;
          })}
        </div>
      )}

      {editorOpen && (
        <MCPServerEditorModal
          key={editing?.id ?? 'new'}
          open
          server={editing}
          saving={save.isPending}
          allowedTransports={allowedTransports}
          onClose={() => setEditorOpen(false)}
          onSave={(input) => save.mutate(input)}
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        title="删除 MCP 服务"
        description={`确定删除 ${deleting?.name ?? ''}？已保存的密文配置也会一并删除。`}
        confirmText="删除"
        danger
        loading={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </section>
  );
}
