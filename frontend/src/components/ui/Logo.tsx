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
        borderRadius: 8,
        background: 'var(--color-primary-700)',
        fontSize: size * 0.4,
      }}
    >
      IC
    </div>
  );
}
