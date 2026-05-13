interface LogoProps {
  size?: number;
}

export function Logo({ size = 36 }: LogoProps) {
  return (
    <div
      className="flex items-center justify-center text-white font-bold tracking-tight"
      style={{
        width: size,
        height: size,
        borderRadius: 12,
        background:
          'linear-gradient(135deg, var(--color-macaron-peach) 0%, var(--color-accent-500) 55%, var(--color-macaron-lavender) 100%)',
        fontSize: size * 0.4,
        boxShadow:
          '0 2px 6px rgba(238, 150, 160, 0.32), inset 0 1px 0 rgba(255,255,255,0.45)',
      }}
    >
      IC
    </div>
  );
}
