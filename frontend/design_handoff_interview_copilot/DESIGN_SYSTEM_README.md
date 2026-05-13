# Interview Copilot Design System

A warm, elegant, and softly rounded design system for **Interview Copilot** — an AI interview-practice and analysis workspace for Chinese-speaking job seekers preparing for technical interviews.

This system is derived from the user's own codebases (FastAPI backend `Interview_Copilot` + React/TypeScript frontend `InterReview`) and re-tones the existing blue/cool palette into a **warm, rounded, elegant** direction per the user's brief: 温暖、圆角、清晰、优雅、不冲突.

---

## Product Context

Interview Copilot is a full-stack AI workspace that combines:

1. **复盘页面 (Review)** — sidebar of past sessions; center pane uploads audio/video, transcribes and shows interview QA pairs; right panel chat for debrief with model-switching, file uploading, and Agent/RAG link switching.
2. **模拟面试 (Mock Interview)** — upload resume + JD, then run a voice mock interview with live transcript that auto-scrolls, plus a push-to-talk mic button.
3. **个人资料库 (Personal Library)** — CRUD over uploaded files (resumes, JDs, notes).
4. **模型选择 (Model Selection)** — vendor-grouped grid where users plug in their own API keys and choose models per provider.
5. **个人中心 (Profile)** — placeholder account page.
6. **登录/注册 (Auth)** — sits in front of all product pages.

### Stack
- **Backend** — FastAPI + SQLAlchemy + Postgres + Redis + Celery + Milvus + MinIO; DeepSeek V4 Flash/Pro routing; Faster-Whisper/WhisperX transcription; LlamaIndex RAG with BGE-M3 embeddings.
- **Frontend** — React 18 + TypeScript + Vite 6 + Tailwind v4 + Radix UI + lucide-react. (The original codebase mentions Vue 3 in places but the active frontend at `studyzhige-ui/InterReview` is React + shadcn/ui.)

### Sources
- **Codebase (local mount):** `Interview_Copilot/` — backend, docs, alembic, evaluation.
- **Frontend repo (GitHub):** `studyzhige-ui/InterReview` @ `main` — React/TS implementation, shadcn/ui components, Tailwind v4 tokens.
- **Backend repo (GitHub):** `studyzhige-ui/Interview_Copilot` @ `main` — FastAPI app.
- **Project guide:** `Interview_Copilot/docs/PROJECT_DETAILED_GUIDE.md` (619 lines, Chinese technical doc).
- **Frontend guide:** `studyzhige-ui/InterReview` README — feature/architecture summary.

---

## Index

```
.
├── README.md                  ← you are here
├── SKILL.md                   ← agent skill manifest (cross-compatible with Claude Code)
├── colors_and_type.css        ← all color + type + radius + shadow tokens
├── assets/                    ← logo placeholder, brand mark, sample illustrations
├── preview/                   ← Design System tab cards (700×~ html specimens)
│   ├── logo.html
│   ├── colors-primary.html
│   ├── colors-neutral.html
│   ├── colors-semantic.html
│   ├── type-display.html
│   ├── type-body.html
│   ├── type-mono.html
│   ├── spacing.html
│   ├── radius.html
│   ├── shadows.html
│   ├── buttons.html
│   ├── form-inputs.html
│   ├── cards.html
│   ├── badges.html
│   ├── status-pills.html
│   ├── sidebar-item.html
│   ├── chat-bubble.html
│   ├── iconography.html
│   └── motion.html
└── ui_kits/
    └── interview_copilot/
        ├── README.md
        ├── index.html         ← interactive click-through prototype (auth → review → mock → library → models)
        ├── tokens.css
        └── ui.jsx             ← React components (Sidebar, LoginCard, UploadDropzone, QAItem, ChatComposer, etc.)
```

---

## Content Fundamentals

**Language.** Primary copy is **Simplified Chinese** with occasional English technical terms (Agent, RAG, QA, JD, JWT). All section headers, labels, buttons, and toasts are Chinese.

**Voice.** Functional, slightly warm. The product talks **about itself** in third-person product names (`InterReview`, `Interview Copilot`) and addresses the user with bare verbs ("登录", "新建面试分析", "开始模拟面试") — no `你` salutation, no exclamation marks unless celebrating a success.

**Tone examples (from codebase):**
- Tagline: *让每一次面试都成为进步的阶梯*
- Section header: *我的面试*
- Empty state: *没有找到匹配的面试记录 / 试试其他关键词*
- Toast (error): *邮箱或密码错误，请检查后重试*
- Toast (success): *注册成功，已自动登录*
- Confirm cue: *至少 6 位* (inline hint next to the label)

**Casing.** Chinese has no casing. English technical labels (`AGENT`, `RAG`) appear in **UPPERCASE with `tracking-wider`** for badge/tag use, otherwise sentence case (`DeepSeek V4 Flash`). Section-header eyebrows use `uppercase tracking-wider text-xs` in muted color.

**Punctuation.** Full-width Chinese punctuation (`，。：？`) in body copy; half-width punctuation (`,. :?`) in code and English labels. Hyphenated counts: `≤200 MB`, `3-5 题`. Use Chinese parentheses `（）` for inline notes in Chinese sentences, ASCII `()` in English.

**Emoji.** **Not used** in production UI. Some marketing prose in the README uses `🚀 🎯 🧠` but the app interface itself is emoji-free — all glyphs are **lucide-react** outline icons.

**Vibe.** Calm and competent. The product treats interview anxiety with composure: encouraging without being chirpy. No "AI wow" — no sparkles, no "✨ Magic Insights ✨", no purple gradients. Words like *复盘 / 优化 / 沉淀 / 闭环* set a thoughtful, almost academic mood.

---

## Visual Foundations

### Palette — warm, rounded, elegant
The original frontend uses cool blue (`oklch(.546 .245 262.881)`). Per the brief 用温暖的色调, this design system **re-tones to a warm clay/terracotta primary** while keeping the same structural roles.

- **Primary — Clay Terracotta** `#C26A4A` (oklch ~0.62 / 0.115 / 45). Used for primary buttons, the brand mark, active sidebar item, and focus rings.
- **Secondary — Warm Sand** `#F1E6D8` — chip backgrounds, subtle hover.
- **Accent — Amber Glow** `#E5A66B` — celebratory states, highlights, score-good badges.
- **Neutrals — Warm Stone** A 9-step warm-gray scale (`stone-50 … stone-900`) that is **slightly orange-warm** rather than pure neutral, so the whole UI feels lit by a warm light source.
- **Semantic**
  - Success (绿 / pass) `#5C8C5A` — muted sage, not the typical bright shadcn green.
  - Warning (黄) `#D7A04A` — toasted amber.
  - Danger (红) `#B7503B` — burnt brick.
  - Info (蓝) `#5B7FA8` — deep dusty blue, present only for "info" toasts so it doesn't fight the warm palette.

Backgrounds are **plain warm cream** `#FAF6F0` for canvas, **pure white** `#FFFFFF` for cards. **No gradients** in shipped UI except the auth screen which uses a soft `cream → white → sand` diagonal (replacing the original `blue-50 → white → purple-50`).

### Type
- **Sans (UI / body)** — `"Inter", "PingFang SC", "Noto Sans SC", system-ui, sans-serif`. The original codebase uses system sans; Inter is added for Latin runs to match the elegance brief.
- **Display (large titles)** — same family, weight 500, tracking `-0.01em`. We do **not** introduce a serif — it would clash with the calm-functional voice.
- **Mono (transcripts, code)** — `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace`. Used for the transcript view and code blocks in chat.
- Scale: 12 / 13 / 14 / 16 / 18 / 20 / 24 / 30 / 36 px. Body default 14 px (matches the existing app). Line-height 1.5 baseline, 1.625 for long-form transcript.
- **Substitution flag** — Inter + JetBrains Mono are Google Fonts substitutes. If the user wants a specific Chinese-paired display face (e.g. Source Han Sans, Alibaba PuHuiTi), drop the TTFs into `fonts/` and update tokens.

### Spacing
4 px base unit (`--spacing` in Tailwind v4). Common steps: 4, 8, 12, 16, 20, 24, 32, 48. Sidebar fixed at **260 px**. Container max widths follow Tailwind: `md 28rem`, `2xl 42rem`, `3xl 48rem`, `4xl 56rem`.

### Radii
Generous and consistent — the brief is 圆角清晰.
- `--radius-sm 6 px` — chips, tiny pills.
- `--radius-md 10 px` — buttons, inputs (this matches the original `--radius: .625rem` exactly).
- `--radius-lg 14 px` — list items, dropdowns.
- `--radius-xl 16 px` — cards, modal corners.
- `--radius-2xl 20 px` — hero cards, login card.
- `--radius-3xl 24 px` — feature panels, large illustrations.
- `--radius-full` — avatars, mic button, status dots.

### Shadows / Elevation
Soft, low-spread, warm-tinted. No harsh black shadows.
- `--shadow-xs` — `0 1px 2px 0 rgba(120, 80, 40, 0.04)` (input depth)
- `--shadow-sm` — `0 1px 3px 0 rgba(120, 80, 40, 0.06), 0 1px 2px -1px rgba(120, 80, 40, 0.06)` (cards at rest)
- `--shadow-md` — `0 4px 12px -2px rgba(120, 80, 40, 0.08)` (hovered cards)
- `--shadow-lg` — `0 10px 25px -5px rgba(120, 80, 40, 0.10), 0 6px 10px -6px rgba(120, 80, 40, 0.08)` (popovers, login card)
- `--shadow-xl` — `0 20px 35px -8px rgba(120, 80, 40, 0.12)` (modals)
- `--shadow-primary-glow` — `0 8px 20px -4px rgba(194, 106, 74, 0.30)` (primary CTA hover; replaces the original `shadow-blue-600/30`)

### Borders
1 px, `--color-stone-200`. Buttons and chips have an **invisible** 1 px border by default that becomes visible on hover for inert/secondary controls — a subtle "card-lift" cue. Dashed `2 px` `--color-stone-300` for upload dropzones; switches to `2 px dashed primary` on drag-over.

### Backgrounds
- App canvas: solid `--color-cream-50`. No textures, no patterns.
- Cards & sidebar: solid white.
- Auth: single subtle 3-stop gradient (`cream → white → sand`), no animation.
- **Never** full-bleed photography — the product has no marketing surface that requires it. The brand mark + ample whitespace carries identity.

### Animation
Calm. Tailwind defaults (`ease-out 150ms`) for color/border. Heavier transitions (modals, sidebars) `cubic-bezier(0.16, 1, 0.3, 1)` `220ms`. No bounce, no spring overshoot. The mic button on the mock-interview screen has a **gentle pulsing ring** (`scale 1 → 1.15`, `opacity 0.4 → 0`, `1.6s` infinite) when recording — the only continuous animation in the app.

### Hover / Press
- **Hover (primary)** — darken 6% (`color-mix(in oklab, primary 94%, black)`).
- **Hover (ghost / secondary)** — fill with `--color-stone-100`.
- **Press** — `transform: scale(0.98)`, 80 ms. Primary buttons additionally `--shadow-primary-glow` on hover.
- **Focus visible** — `2 px` ring in `--color-primary-200` (warm cream), offset 1 px.
- **Disabled** — `opacity: 0.5; pointer-events: none`.

### Transparency / Blur
Used sparingly. Modal scrims `rgba(40, 28, 20, 0.45)` warm-tinted instead of pure black. The sidebar toggle handle uses `backdrop-blur(12px)` on a `bg-white/70` chip when floating over content during auto-hide.

### Imagery
The product itself ships almost no imagery — it's a working tool. Empty states use **single line-icon glyphs** at 32–40 px in `--color-stone-300`, never illustrations. When a future marketing page is needed, imagery should be **warm-toned, soft-focus, candid documentary**, never stocky office photos.

### Layout rules
- Fixed left **navigation rail** (auto-collapsable, default 60 px collapsed / 240 px expanded — distinct from the 260 px **session sidebar** which is the second column).
- Each product page is a **3-column shell**: nav rail · session list · main canvas · (optional) inspector/chat panel.
- Auth screen breaks the shell — single centered 28 rem card.
- All chrome rounds inward to the canvas: sidebars have `border-right`, no shadow; the canvas itself sits flush.

### Cards
White, `--radius-xl` (16 px), `--shadow-sm` at rest, `--shadow-md` on hover, 1 px `--color-stone-200` border (so the card reads at low elevation against the cream canvas). Inner padding 20–24 px.

---

## Iconography

The product uses **lucide-react** exclusively. Stroke style: outline, 1.75 px (lucide default), `round` linecaps + linejoins. Sized at **16 px (sm), 20 px (md, default), 24 px (lg)**.

Common icons in the existing code: `Search, Plus, LogOut, User, Mail, Lock, Eye, EyeOff, UserPlus, LogIn, UploadCloud, Mic, MicOff, Pause, Play, Send, Paperclip, Settings, Sparkles, ChevronLeft, ChevronRight, MoreVertical, Trash2, Pencil, FileText, MessageSquare, BookOpen, Cpu, User2`.

**Reference (CDN)** — `https://unpkg.com/lucide@0.474.0/dist/umd/lucide.js` or React: `import { ... } from 'lucide-react'`. We do not vendor a stripped icon set — the lucide library is small enough and the substitution is **a flag, not a problem**: lucide *is* the original codebase's icon system.

**Unicode glyphs** — only `·` (middle dot) as a separator and `→` in narrow inline cues (`"返回 →"`).

**Emoji** — none in product UI. Marketing prose may use them; the brand profile **is emoji-free**.

**Logo / brand mark** — an `IR` monogram in a `40 × 40` rounded-`xl` clay-terracotta tile, white text. For the broader "Interview Copilot" surface we offer an alternate `IC` monogram. Both live in `assets/`.

---

## UI Kits

| Kit | Path | Notes |
|---|---|---|
| Interview Copilot app | `ui_kits/interview_copilot/` | Click-through prototype with auth, review, mock interview, library, model selection screens. |

Open `ui_kits/interview_copilot/index.html` to walk the full flow.

---

## Caveats & Substitutions

- **Font substitution** — Inter and JetBrains Mono are Google Fonts loaded via CDN as elegant Latin pairings. The original codebase uses system sans only. If you have brand fonts (e.g. Source Han Sans, Alibaba PuHuiTi 3.0), drop them in `fonts/` and replace `--font-sans` in `colors_and_type.css`.
- **Color re-tone** — The original frontend (`InterReview`) is **blue-primary**. This system **rewrites** the palette to warm clay per the brief. Component shapes, spacing, radii, and copy are preserved from the source so the kit drops in cleanly when re-skinning.
- **Iconography** — lucide-react is the existing system; we reference it from CDN rather than vendoring.
- **No logo asset** — the codebase ships only the `IR` text monogram. The brand mark in `assets/` is a faithful recreation.
- **Profile page** — the user's spec says *暂时不知道有什么*. We render a minimal placeholder rather than inventing content.
