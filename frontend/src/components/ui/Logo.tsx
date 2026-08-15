interface LogoProps {
  size?: number;
  showText?: boolean;
}

export function Logo({ size = 32 }: LogoProps) {
  return (
    <div
      className="inline-flex items-center justify-center shrink-0 transition-transform duration-300 hover:scale-105"
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full drop-shadow-sm"
      >
        <defs>
          <linearGradient id="gemini-logo-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#4285F4" />
            <stop offset="35%" stopColor="#8AB4F8" />
            <stop offset="65%" stopColor="#9B72CB" />
            <stop offset="100%" stopColor="#D96570" />
          </linearGradient>
          <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="1.5" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>
        {/* Gemini 4-point sparkle star shape */}
        <path
          d="M16 2C16 9.73 9.73 16 2 16C9.73 16 16 22.27 16 30C16 22.27 22.27 16 30 16C22.27 16 16 9.73 16 2Z"
          fill="url(#gemini-logo-grad)"
        />
        {/* Inner subtle glow point */}
        <circle cx="16" cy="16" r="3" fill="#FFFFFF" opacity="0.85" filter="url(#glow)" />
      </svg>
    </div>
  );
}
