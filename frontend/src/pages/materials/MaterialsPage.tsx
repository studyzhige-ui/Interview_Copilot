import { useSearchParams } from 'react-router-dom';
import {
  FolderGit2,
  Contact,
  FileText,
  TrendingUp,
} from 'lucide-react';
import { CareerProfilePage } from '@/pages/career/CareerProfilePage';
import { LibraryPage } from '@/pages/library/LibraryPage';
import { GrowthPage } from '@/pages/growth/GrowthPage';

export function MaterialsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'profile';

  return (
    <div className="h-full flex flex-col bg-[#F8FAFC]">
      {/* Sub-Header Tabs */}
      <div className="px-6 py-3 bg-white border-b border-slate-200/80 flex flex-wrap items-center justify-between gap-3 shrink-0 select-none">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
            <FolderGit2 size={16} />
          </div>
          <div>
            <h1 className="text-base font-bold text-slate-900 leading-none">资料与档案中枢</h1>
            <p className="text-[11px] text-slate-400 mt-0.5">个人真实事实库、知识参考文档与能力图谱</p>
          </div>
        </div>

        {/* Navigation Tabs Pill */}
        <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-2xl text-xs font-semibold text-slate-600">
          <button
            type="button"
            onClick={() => setSearchParams({ tab: 'profile' })}
            className={[
              'flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl transition-all cursor-pointer',
              activeTab === 'profile'
                ? 'bg-white text-blue-600 shadow-2xs font-bold'
                : 'hover:text-slate-900',
            ].join(' ')}
          >
            <Contact size={14} />
            <span>个人档案</span>
          </button>

          <button
            type="button"
            onClick={() => setSearchParams({ tab: 'library' })}
            className={[
              'flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl transition-all cursor-pointer',
              activeTab === 'library'
                ? 'bg-white text-blue-600 shadow-2xs font-bold'
                : 'hover:text-slate-900',
            ].join(' ')}
          >
            <FileText size={14} />
            <span>参考资料</span>
          </button>

          <button
            type="button"
            onClick={() => setSearchParams({ tab: 'growth' })}
            className={[
              'flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl transition-all cursor-pointer',
              activeTab === 'growth'
                ? 'bg-white text-blue-600 shadow-2xs font-bold'
                : 'hover:text-slate-900',
            ].join(' ')}
          >
            <TrendingUp size={14} />
            <span>能力图谱</span>
          </button>
        </div>
      </div>

      {/* Tab Content Stage */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {activeTab === 'profile' && <CareerProfilePage />}
        {activeTab === 'library' && <LibraryPage />}
        {activeTab === 'growth' && <GrowthPage />}
      </div>
    </div>
  );
}
