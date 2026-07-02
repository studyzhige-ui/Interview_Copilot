import { useState } from 'react';
import type { ProviderInfo } from '@/api/models';
import { BRAND_COLORS } from './constants';

export function VendorAvatar({ info, small = false }: { info: ProviderInfo; small?: boolean }) {
  const [failed, setFailed] = useState(false);
  const hasIcon = !!info.icon_slug && !failed;
  const size = small ? 'w-7 h-7' : 'w-9 h-9';
  const iconPx = small ? 14 : 18;
  const brand = BRAND_COLORS[info.provider] ?? '#71717A';
  return (
    <div
      className={`${size} rounded-lg flex items-center justify-center shrink-0 overflow-hidden`}
      style={{ background: brand }}
      aria-label={info.display_label}
    >
      {hasIcon ? (
        <img
          src={`https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/${info.icon_slug}.svg`}
          alt=""
          width={iconPx}
          height={iconPx}
          loading="lazy"
          onError={() => setFailed(true)}
          style={{ width: iconPx, height: iconPx, filter: 'brightness(0) invert(1)' }}
        />
      ) : (
        <span className={`${small ? 'text-xs' : 'text-sm'} font-bold text-white`}>
          {info.display_label[0]}
        </span>
      )}
    </div>
  );
}
