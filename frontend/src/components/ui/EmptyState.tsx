import { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-8">
      {icon && <div className="text-stone-400 mb-4">{icon}</div>}
      <div className="text-base font-medium text-stone-800">{title}</div>
      {description && (
        <div className="text-sm text-stone-500 mt-2 max-w-md">{description}</div>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
