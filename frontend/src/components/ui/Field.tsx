import { InputHTMLAttributes, ReactNode, useId } from 'react';

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  label?: string;
  hint?: string;
  error?: string;
  icon?: ReactNode;
  rightSlot?: ReactNode;
  onChange?: (v: string) => void;
}

export function Field({
  label,
  hint,
  error,
  icon,
  rightSlot,
  onChange,
  className,
  ...rest
}: FieldProps) {
  const id = useId();
  return (
    <label htmlFor={id} className="block mb-3.5">
      {label && (
        <div className="text-xs font-medium text-stone-700 mb-1.5">{label}</div>
      )}
      <div className="relative">
        {icon && (
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-stone-400">
            {icon}
          </span>
        )}
        <input
          id={id}
          onChange={(e) => onChange?.(e.target.value)}
          className={[
            'w-full bg-stone-50 border border-stone-200 rounded-md outline-none',
            'text-sm text-stone-800 placeholder:text-stone-400',
            'focus:border-primary-300 focus:ring-2 focus:ring-primary-300/30',
            'transition',
            icon ? 'pl-10' : 'pl-3',
            rightSlot ? 'pr-10' : 'pr-3',
            'py-2.5',
            error ? 'border-danger-500' : '',
            className ?? '',
          ].join(' ')}
          {...rest}
        />
        {rightSlot && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-stone-400">
            {rightSlot}
          </span>
        )}
      </div>
      {(error || hint) && (
        <div
          className={
            error
              ? 'text-xs text-danger-500 mt-1'
              : 'text-xs text-stone-500 mt-1'
          }
        >
          {error ?? hint}
        </div>
      )}
    </label>
  );
}
