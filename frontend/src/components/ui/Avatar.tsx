import { useState } from 'react';

const FALLBACK_COLORS = [
  'bg-macaron-peach',
  'bg-macaron-mint',
  'bg-macaron-butter',
  'bg-macaron-lavender',
  'bg-macaron-sky',
];

function fallbackColor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length];
}

export function Avatar({
  src,
  name,
  colorSeed = name,
  alt = '',
  className,
  fallbackClassName = '',
}: {
  src?: string | null;
  name: string;
  colorSeed?: string;
  alt?: string;
  className: string;
  fallbackClassName?: string;
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = !!src && failedSrc !== src;

  if (showImage) {
    return (
      <img
        src={src}
        alt={alt}
        className={`${className} rounded-full object-cover border border-stone-200`}
        onError={() => setFailedSrc(src)}
      />
    );
  }

  return (
    <span
      className={`${className} rounded-full ${fallbackColor(colorSeed)} text-white font-semibold flex items-center justify-center ${fallbackClassName}`}
      aria-label={alt || name}
    >
      {(name || '?').slice(0, 1).toUpperCase()}
    </span>
  );
}
