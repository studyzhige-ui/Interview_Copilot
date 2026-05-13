/* global React, ReactDOM */
const { useState, useRef, useEffect } = React;

/* ---------- Icons (inline SVG, lucide style) ---------- */
const Icon = ({ d, w = 18, sw = 1.75, fill = "none" }) => (
  <svg width={w} height={w} viewBox="0 0 24 24" fill={fill} stroke="currentColor"
       strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">{d}</svg>
);
const I = {
  search:  <Icon d={<><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></>}/>,
  plus:    <Icon d={<><path d="M12 5v14M5 12h14"/></>}/>,
  upload:  <Icon d={<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></>}/>,
  mic:     <Icon d={<><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4"/></>}/>,
  send:    <Icon d={<><path d="m22 2-7 20-4-9-9-4 20-7z"/></>}/>,
  clip:    <Icon d={<><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></>}/>,
  cog:     <Icon d={<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></>}/>,
  user:    <Icon d={<><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></>}/>,
  logout:  <Icon d={<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></>}/>,
  trash:   <Icon d={<><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></>}/>,
  pencil: <Icon d={<><path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></>}/>,
  file:    <Icon d={<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></>}/>,
  msg:     <Icon d={<><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></>}/>,
  book:    <Icon d={<><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></>}/>,
  cpu:     <Icon d={<><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/></>}/>,
  panelL:  <Icon d={<><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/></>}/>,
  chev:    <Icon d={<><path d="m9 18 6-6-6-6"/></>}/>,
  eye:     <Icon d={<><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></>}/>,
  lock:    <Icon d={<><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></>}/>,
  mail:    <Icon d={<><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/></>}/>,
  more:    <Icon d={<><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></>}/>,
  check:   <Icon d={<><path d="M20 6 9 17l-5-5"/></>}/>,
  x:       <Icon d={<><path d="M18 6 6 18M6 6l12 12"/></>}/>,
  sparkle: <Icon d={<><path d="M12 3v18M3 12h18M5.5 5.5l13 13M18.5 5.5l-13 13"/></>}/>,
};

/* ---------- Atoms ---------- */
const Logo = ({ size = 36 }) => (
  <div style={{ width: size, height: size, borderRadius: 12,
    background: "linear-gradient(135deg, var(--color-macaron-peach) 0%, var(--color-accent-500) 55%, var(--color-macaron-lavender) 100%)",
    color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
    fontWeight: 700, fontSize: size * 0.4, letterSpacing: "-0.02em",
    boxShadow: "0 2px 6px rgba(238, 150, 160, 0.32), inset 0 1px 0 rgba(255,255,255,0.45)" }}>IC</div>
);

const Btn = ({ children, kind = "primary", size = "md", icon, onClick, full }) => {
  const pad = size === "sm" ? "6px 12px" : size === "lg" ? "12px 22px" : "9px 16px";
  const fs = size === "sm" ? 12 : size === "lg" ? 15 : 13;
  const base = { display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
    padding: pad, fontSize: fs, fontWeight: 500, borderRadius: 10, border: "1px solid transparent",
    cursor: "pointer", transition: "all 150ms var(--ease-out)", fontFamily: "var(--font-sans)",
    width: full ? "100%" : "auto" };
  const styles = {
    primary: { background: "var(--color-accent-500)", color: "#fff", boxShadow: "0 1px 2px rgba(79, 154, 126, 0.25)" },
    secondary: { background: "var(--color-sand-200)", color: "var(--color-stone-800)" },
    ghost: { background: "transparent", color: "var(--color-stone-700)" },
    outline: { background: "#fff", color: "var(--color-stone-700)", borderColor: "var(--color-stone-200)" },
    danger: { background: "transparent", color: "var(--color-danger-500)" },
  };
  return <button onClick={onClick} style={{ ...base, ...styles[kind] }}>{icon}{children}</button>;
};

const Field = ({ label, type = "text", icon, hint, value, onChange, placeholder }) => (
  <label style={{ display: "block", marginBottom: 14 }}>
    <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-stone-700)", marginBottom: 6 }}>{label}</div>
    <div style={{ position: "relative" }}>
      {icon && <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)",
        color: "var(--color-stone-400)" }}>{icon}</span>}
      <input type={type} value={value} placeholder={placeholder}
        onChange={e => onChange?.(e.target.value)}
        style={{ width: "100%", padding: icon ? "10px 12px 10px 38px" : "10px 12px",
          fontSize: 14, fontFamily: "var(--font-sans)", color: "var(--color-stone-800)",
          background: "var(--color-stone-50)", border: "1px solid var(--color-stone-200)",
          borderRadius: 10, outline: "none", boxSizing: "border-box" }}/>
    </div>
    {hint && <div style={{ fontSize: 11, color: "var(--color-stone-500)", marginTop: 4 }}>{hint}</div>}
  </label>
);

const Pill = ({ children, tone = "neutral" }) => {
  const tones = {
    neutral: { bg: "var(--color-stone-100)", c: "var(--color-stone-700)" },
    primary: { bg: "var(--color-primary-50)", c: "var(--color-primary-700)" },
    success: { bg: "var(--color-success-50)", c: "var(--color-success-700)" },
    warn: { bg: "var(--color-warning-50)", c: "var(--color-warning-700)" },
    danger: { bg: "var(--color-danger-50)", c: "var(--color-danger-700)" },
    sand: { bg: "var(--color-sand-200)", c: "var(--color-stone-700)" },
  }[tone];
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 4,
    padding: "3px 10px", fontSize: 11, fontWeight: 500, borderRadius: 999,
    background: tones.bg, color: tones.c, letterSpacing: 0.02 }}>{children}</span>;
};

/* ---------- Navigation Rail ---------- */
const NavRail = ({ current, onNav, collapsed, onToggle }) => {
  const items = [
    { k: "review",  icon: I.book,    label: "复盘" },
    { k: "mock",    icon: I.mic,     label: "模拟面试" },
    { k: "ability", icon: I.sparkle, label: "能力分析" },
    { k: "lib",     icon: I.file,    label: "资料库" },
    { k: "models",  icon: I.cpu,     label: "模型" },
    { k: "me",      icon: I.user,    label: "个人中心" },
  ];
  const w = collapsed ? 64 : 220;
  return (
    <aside style={{ width: w, transition: "width 220ms var(--ease-soft)", background: "#fff",
      borderRight: "1px solid var(--color-stone-200)", display: "flex", flexDirection: "column",
      flexShrink: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: collapsed ? "18px 14px" : "18px 18px" }}>
        <Logo size={32}/>
        {!collapsed && <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-stone-800)" }}>Interview Copilot</div>}
      </div>
      <nav style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
        {items.map(it => {
          const active = current === it.k;
          return (
            <button key={it.k} onClick={() => onNav(it.k)}
              style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 12px",
                borderRadius: 10, border: "none", cursor: "pointer", textAlign: "left",
                background: active ? "var(--color-primary-50)" : "transparent",
                color: active ? "var(--color-primary-700)" : "var(--color-stone-700)",
                fontWeight: active ? 600 : 500, fontSize: 13, fontFamily: "var(--font-sans)",
                transition: "background 150ms" }}>
              <span style={{ color: active ? "var(--color-primary-500)" : "var(--color-stone-500)" }}>{it.icon}</span>
              {!collapsed && <span>{it.label}</span>}
            </button>
          );
        })}
      </nav>
      <div style={{ padding: 10, borderTop: "1px solid var(--color-stone-200)" }}>
        <button onClick={onToggle} title="收起 / 展开"
          style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
            width: "100%", borderRadius: 10, border: "none", background: "transparent",
            color: "var(--color-stone-500)", cursor: "pointer", fontSize: 12 }}>
          <span style={{ transform: collapsed ? "" : "rotate(180deg)", transition: "transform 200ms" }}>{I.chev}</span>
          {!collapsed && <span>收起</span>}
        </button>
      </div>
    </aside>
  );
};

window.UIKit = { I, Logo, Btn, Field, Pill, NavRail };
