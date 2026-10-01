import { useQuery } from '@tanstack/react-query';
import { getStorageUsage } from '@/api/storage';
import { useAuthStore } from '@/store/authStore';

function bytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return '未知';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const index = value === 0 ? 0 : Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} ${units[index]}`;
}

export function StorageUsagePanel() {
  const subjectId = useAuthStore((state) => state.subjectId);
  const query = useQuery({
    queryKey: ['storage-usage', subjectId],
    queryFn: ({ signal }) => getStorageUsage(signal),
    enabled: !!subjectId,
    retry: false,
  });
  if (!subjectId) return null;
  return <section aria-label="文件存储" className="mt-6 rounded-xl border border-stone-200 bg-white p-5 shadow-xs">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-base font-semibold text-stone-800">文件存储</h2>
      <button type="button" disabled={query.isFetching} onClick={() => { void query.refetch(); }}
        className="text-xs text-primary-700 underline disabled:opacity-50" aria-label="刷新存储用量">刷新用量</button>
    </div>
    {query.isPending ? <p role="status" className="mt-3 text-sm text-stone-500">正在读取存储用量…</p>
      : query.isError ? <p role="alert" className="mt-3 text-sm text-stone-600">暂时无法读取存储用量。已有文件不会因此改变，不能据此判断空间已清零。</p>
        : <>
          <p className="mt-3 text-sm text-stone-600">新文件保存位置：{query.data.backend === 'filesystem' ? '本地文件存储' : 'S3 对象存储'}</p>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-stone-500">当前账号文件</dt><dd className="mt-1 font-medium">{query.data.asset_count.toLocaleString('zh-CN')} 个</dd></div>
            <div><dt className="text-stone-500">当前账号文件体积</dt><dd className="mt-1 font-medium">{bytes(query.data.used_bytes)}</dd></div>
          </dl>
          <p className="mt-2 text-xs text-stone-500">跨本地与对象存储的受管文件</p>
          {query.data.backend === 'filesystem' ? <p className="mt-3 text-sm leading-relaxed text-stone-600">
            存储目录可用空间： {query.data.free_bytes === null ? '未知' : bytes(query.data.free_bytes)}
            {query.data.total_bytes !== null && ` / 共 ${bytes(query.data.total_bytes)}`}
          </p> : <p className="mt-3 text-xs leading-relaxed text-stone-500">对象存储容量由服务商管理，此处不提供剩余磁盘空间。</p>}
          <details className="mt-3 text-xs leading-relaxed text-stone-500">
            <summary className="cursor-pointer">统计范围</summary>
            <p className="mt-2">仅统计当前账号已确认、可读取且未删除的受管文件，不含数据库、模型缓存或运行环境；跨存储的文件体积不等于本地磁盘占用。</p>
            {query.data.backend === 'filesystem' && <p className="mt-2">可用空间来自存储目录所在文件系统。容器中可能是挂载卷或虚拟磁盘，不是整台电脑的物理磁盘空间，也不是账号配额。</p>}
          </details>
        </>}
  </section>;
}
