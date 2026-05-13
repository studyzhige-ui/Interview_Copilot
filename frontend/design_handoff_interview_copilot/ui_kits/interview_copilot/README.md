# Interview Copilot UI Kit

Recreation of the Interview Copilot product, re-toned to the warm clay-terracotta palette.

`index.html` is a single-page click-through prototype with all 5 spec'd screens:

1. **登录 / 注册 (Auth)** — landing, gates the rest.
2. **复盘 (Review)** — sidebar of sessions · center upload + QA pairs · right chat panel with model switcher, attach, agent toggle.
3. **模拟面试 (Mock Interview)** — resume + JD upload, then live transcript view with auto-scroll and push-to-talk mic.
4. **个人资料库 (Personal Library)** — CRUD over uploaded files.
5. **模型选择 (Model Selection)** — vendor-grouped grid with per-provider API key + model picks.
6. **个人中心 (Profile)** — minimal placeholder per spec.

The left **navigation rail** can be pinned/auto-hidden. Click the logo or drag the handle to collapse.

Built as a single HTML page (no build) using React + Babel from CDN, the design-system CSS tokens, and lucide icons. Use it as a visual reference; component code is in `ui.jsx`.
