import { FormEvent, useState } from 'react';
import type { MCPServerInput, MCPTransport, UserMCPServer } from '@/api/capabilities';
import { Btn } from '@/components/ui/Btn';
import { Field } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { parseArgs, parseKeyValueLines } from './formUtils';

interface Props {
  open: boolean;
  server: UserMCPServer | null;
  saving: boolean;
  allowedTransports: MCPTransport[];
  onClose: () => void;
  onSave: (input: MCPServerInput) => void;
}

export function MCPServerEditorModal({
  open,
  server,
  saving,
  allowedTransports,
  onClose,
  onSave,
}: Props) {
  const [name, setName] = useState(server?.name ?? '');
  const [transport, setTransport] = useState<MCPTransport>(server?.transport ?? 'streamable_http');
  const [url, setUrl] = useState(server?.url ?? '');
  const [command, setCommand] = useState(server?.command ?? '');
  const [args, setArgs] = useState(server?.args.join('\n') ?? '');
  const [secrets, setSecrets] = useState('');
  const [clearSecrets, setClearSecrets] = useState(false);
  const [error, setError] = useState('');

  const submit = (event: FormEvent) => {
    event.preventDefault();
    try {
      const parsedSecrets = secrets.trim() ? parseKeyValueLines(secrets) : undefined;
      const secretPatch = clearSecrets ? {} : parsedSecrets;
      onSave({
        name: name.trim(),
        transport,
        url: transport === 'streamable_http' ? url.trim() : undefined,
        command: transport === 'stdio' ? command.trim() : undefined,
        args: transport === 'stdio' ? parseArgs(args) : [],
        headers: transport === 'streamable_http' ? secretPatch : undefined,
        env: transport === 'stdio' ? secretPatch : undefined,
        enabled: server?.enabled ?? true,
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '配置格式错误');
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={server ? `编辑 ${server.name}` : '添加 MCP 服务'} width={620}>
      <form onSubmit={submit}>
        <Field label="名称" value={name} onChange={setName} placeholder="例如 notion" required />
        <label className="block mb-3.5">
          <span className="block text-xs font-medium text-stone-700 mb-1.5">传输方式</span>
          <select
            value={transport}
            onChange={(event) => setTransport(event.target.value as MCPTransport)}
            className="w-full rounded-md border border-stone-200 bg-stone-50 px-3 py-2.5 text-sm outline-none focus:border-primary-300"
          >
            {allowedTransports.includes('streamable_http') && (
              <option value="streamable_http">Streamable HTTP</option>
            )}
            {allowedTransports.includes('stdio') && (
              <option value="stdio">stdio（本地进程）</option>
            )}
          </select>
        </label>

        {transport === 'streamable_http' ? (
          <Field label="MCP URL" value={url} onChange={setUrl} placeholder="https://example.com/mcp" required />
        ) : (
          <>
            <Field label="命令" value={command} onChange={setCommand} placeholder="npx" required />
            <label className="block mb-3.5">
              <span className="block text-xs font-medium text-stone-700 mb-1.5">参数（每行一个）</span>
              <textarea value={args} onChange={(event) => setArgs(event.target.value)} className="w-full min-h-24 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm font-mono outline-none focus:border-primary-300" />
            </label>
          </>
        )}

        <label className="block mb-2">
          <span className="block text-xs font-medium text-stone-700 mb-1.5">
            {transport === 'streamable_http' ? '敏感 Headers' : '环境变量'}（每行 KEY=VALUE）
          </span>
          <textarea
            value={secrets}
            onChange={(event) => setSecrets(event.target.value)}
            placeholder={transport === 'streamable_http' ? 'Authorization=Bearer ...' : 'API_KEY=...'}
            className="w-full min-h-24 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm font-mono outline-none focus:border-primary-300"
          />
        </label>
        {server?.has_secrets && (
          <div className="mb-4 flex items-center justify-between text-xs text-stone-500">
            <span>敏感值已加密保存；留空会保留原值。</span>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={clearSecrets} onChange={(event) => setClearSecrets(event.target.checked)} />
              清除已保存的敏感值
            </label>
          </div>
        )}
        {error && <p className="mb-3 text-xs text-danger-500">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <Btn kind="ghost" onClick={onClose} disabled={saving}>取消</Btn>
          <Btn type="submit" loading={saving}>保存服务</Btn>
        </div>
      </form>
    </Modal>
  );
}
