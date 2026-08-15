import { ReactNode } from 'react';

interface PromptStarterCardProps {
  icon: ReactNode;
  tag?: string;
  title: string;
  description: string;
  onClick: () => void;
}

export function PromptStarterCard({
  icon,
  tag,
  title,
  description,
  onClick,
}: PromptStarterCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative flex flex-col items-start p-5 text-left bg-white/90 hover:bg-white rounded-2xl border border-slate-200/80 hover:border-blue-300 shadow-xs hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 cursor-pointer overflow-hidden"
    >
      <div className="flex items-center justify-between w-full mb-3">
        <div className="w-10 h-10 rounded-xl bg-slate-50 group-hover:bg-blue-50 text-slate-600 group-hover:text-blue-600 flex items-center justify-center transition-colors">
          {icon}
        </div>
        {tag && (
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-100 group-hover:bg-blue-50 text-slate-500 group-hover:text-blue-600 transition-colors">
            {tag}
          </span>
        )}
      </div>
      <div className="text-sm font-semibold text-slate-800 group-hover:text-blue-700 transition-colors mb-1">
        {title}
      </div>
      <div className="text-xs text-slate-500 line-clamp-2 leading-relaxed">
        {description}
      </div>
      <div className="absolute right-3 bottom-3 opacity-0 group-hover:opacity-100 transition-opacity text-blue-500">
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
        </svg>
      </div>
    </button>
  );
}
