# Handoff: Interview Copilot 前端 → 后端对齐包

> 这是一份"设计交付包"，给本地 Claude Code 用的。  
> 收件人：你（产品/工程负责人）+ 你本地的 Claude Code 实例。  
> 目标：把这份 HTML 原型在你已经存在的 `Interview_Copilot/` 工程里**落成真实的 React 前端**，并且**把前端调用方式与后端现有 API 精准对齐**——必要时反过来给后端提改造建议。

---

## 0. 包内是什么

```
design_handoff_interview_copilot/
├─ README.md                  ← 你正在读
├─ BACKEND_INTEGRATION.md     ← 每一个 UI 动作 ↔ 你后端真实端点的映射表（最重要）
├─ DESIGN_SYSTEM_README.md    ← 完整的视觉系统说明（颜色/字体/间距/动效/语气）
├─ SKILL.md                   ← 给 Claude Code 当 skill 用的快速入口
├─ colors_and_type.css        ← 全部设计 Token（直接 import 即可）
├─ fonts/                     ← Inter 字体（OTF + 可变 TTF）
├─ assets/                    ← Logo、icon、illustration
└─ ui_kits/interview_copilot/
   ├─ index.html              ← 可点击全流程原型
   ├─ ui.jsx                  ← 原子组件：Logo / Btn / Field / Pill / SideNav / TopBar / EmptyState
   ├─ screens.jsx             ← 7 个一级页面：Auth / Review / Mock / Library / Analytics / Models / Profile
   └─ README.md
```

**所有文件都是设计参考**——不是要你直接打包成生产代码 copy 进去。它的作用是给你（和 Claude Code）一份**像素级 + 行为级**的目标参照，让你在 `Interview_Copilot/` 这个真实工程里用 React/Vite/TS 重写出同样的界面、并且每个交互都接到后端正确的 API 上。

---

## 1. 一句话给 Claude Code 的开场指令

把这个包丢进 `Interview_Copilot/frontend/` 之后，对你本地的 Claude Code 直接说：

> "读 `Interview_Copilot/frontend/design_handoff_interview_copilot/README.md` 和 `BACKEND_INTEGRATION.md`，把里面的 HTML 原型用 React + TypeScript + Vite + Tailwind 在 `Interview_Copilot/frontend/src/` 下复刻出来，所有 API 调用必须对照 `BACKEND_INTEGRATION.md` 的端点表使用 `Interview_Copilot/backend/app/api/` 下已有的 FastAPI 路由；如果原型期望的字段后端没有，给我列出后端需要改的 schema/路由并给出最小 diff 建议，不要擅自构造端点。"

如果你倾向用别的栈（Next.js / Vue / SwiftUI 等），把 React+Vite 那段换掉即可，包里没有对栈的硬要求。

---

## 2. 保真度

**高保真 (hifi)**。颜色、字号、字重、行高、圆角、阴影、间距、状态色都已最终化。

落地原则：
- 颜色、字号、圆角、间距、阴影 → **必须** 1:1 用 `colors_and_type.css` 里的 CSS 变量或 Tailwind token，不允许"差不多"。
- 组件结构（DOM 层级、flex/grid 选择）→ 按 `screens.jsx` 的结构对齐；可以拆得更细，但视觉层级要一致。
- 文案 → 包里所有中文文案是"产品文案稿"，可以直接搬。
- 后端字段 → 以 `Interview_Copilot/backend/app/` 现状为准；前端**适配后端**，详见 `BACKEND_INTEGRATION.md`。

---

## 3. 七个页面（IA）

| # | 路由建议 | 页面 | 主要职责 | 关键接口（详见 BACKEND_INTEGRATION.md） |
|---|---|---|---|---|
| 0 | `/auth` | 登录 / 注册 | 凭证录入、tab 切换 | `POST /register`, `POST /login`, `POST /refresh` |
| 1 | `/review` | 复盘 | 三栏：session 列表 / 中间 QA / 右侧聊天 | `/interview-records`, `/upload/audio/direct`, `/analyze`, `/chat/sessions`, `/chat/ws` |
| 2 | `/mock` | 模拟面试 | 双文件 setup → live 推流 | `/upload/resume/direct`, `/chat/mock-interview/start`, `/answer`, `/finish` |
| 3 | `/analytics` | 能力分析 | 六维雷达 + 薄弱点卡片 | `/analytics/report` |
| 4 | `/library` | 个人资料库 | 文件 CRUD | `/knowledge/documents`（GET/POST/PATCH/DELETE） |
| 5 | `/models` | 模型选择 | 厂家分块 + API Key | `/models/catalog`, `/models/runtime` |
| 6 | `/me` | 个人中心 | 占位 | （后端暂无对应路由，详见集成文档） |

侧边栏导航顺序：**复盘 / 模拟面试 / 能力分析 / 资料库 / 模型 / 个人中心**。  
登录后默认 landing：`/review`。

---

## 4. 关键交互行为（必须保留）

所有这些都在 `screens.jsx` 里能找到对应实现，前端只需照搬交互逻辑，把数据源换成后端调用：

### 4.1 复盘页 (`Review`)
- session 列表支持**新建（+）/ 选中 / 重命名（双击或 ⋯ 菜单）/ 删除（⋯ 菜单）**；删除当前选中后自动 fallback 到列表第一个。
- 中间区在 `qa.length === 0` 时只显示上传卡片，**禁止**显示空 QA 列表。点击卡片真实弹出 `<input type="file">`。
- 上传成功 → 1.4s 内出现"转录完成"toast → 上传卡片淡出 → QA 列表淡入。落到真实后端时，把 1.4s 换成对 `/analyze/{interview_id}/status` 的轮询（或后端推送）。
- 单条 QA 卡片：双击问题或答案直接进入编辑模式；底部"优化回答"区默认折叠，点击展开（CSS 过渡 200ms）。
- 右侧 ChatPanel 是**会话级独立的多对话容器**：
  - 不同 session 之间对话隔离（key by `sessionId`）。
  - 顶部 chip 行支持新建（虚线 +）/ 切换 / 重命名（hover 出 ✎ 或双击）/ 删除（hover 出 ✕，最后一个时禁用）。
  - **当 session 还没有 QA 时，新对话必须是空的**（显示"等待上传完成"占位），上传解析完才注入欢迎语。
  - 模型选择器在面板右上，点击下拉。
  - 底部 toolbar 有 AGENT/CHAT 切换、📎 文件附加（真实 file input）、textarea（Enter 发送，Shift+Enter 换行）。

### 4.2 模拟面试页 (`Mock`)
- **Setup 阶段**：3 个上传卡（音视频 *、简历 *、JD 可选）按 1fr 1fr 1fr 网格排列；只有当**音视频 + 简历**都有时"开始模拟面试"按钮才点亮。整个 setup 居中（max-width 880，左右 auto margin）。
- **Live 阶段**：消息流 max-width 760 居中，自动滚到底；下方常驻一个圆形麦克风按钮（直径 88px），点击进入"录音中"状态（按钮内有 pulse 动画 + 红点）；再次点击结束，把"我"的回答 push 到 turns。（你说过暂时没做自动打断检测，所以这里就是手动 push-to-talk。）
- "结束面试"按钮在右上，点击后保存到 interview-records 并跳回复盘。

### 4.3 能力分析页 (`Analytics`)
- 顶部综合分大圆（SVG），中央数字 = 6 维平均。
- 六维 SVG 雷达图，半径 120，主色 `--color-primary-500`，填充透明度 0.25。
- 三个汇总卡（已完成 / 平均时长 / 最强维度）一排。
- 下方薄弱点列表，每条卡片含：原因分析（why）、推荐文档 list（每条带 `<a target="_blank">` 外链 + ↗ 图标）、练习计划 list（每条带 → 站内链接）。两个 CTA 按钮："开始学习" / "针对性模拟"。

### 4.4 个人资料库 (`Library`)
- 顶部 toolbar：搜索框 + 分类筛选 + 上传按钮（弹文件选择器）。
- 表格行：文件名 / 大小 / 类型 / 更新时间 / 操作（重命名 ✎ / 删除 🗑）。
- 重命名走 inline edit。

### 4.5 模型选择 (`Models`)
- 厂家 grid（OpenAI / Anthropic / DeepSeek / 通义 / Moonshot / 智谱 / NVIDIA …）。
- 每个 vendor 卡片：vendor logo + 名称、单选 model 列表（radio）、API Key 输入（type=password，眼睛切换显隐）、"测试连接"按钮、Last verified 时间。
- 改动后立即 PATCH 到 `/models/runtime`。

### 4.6 登录 (`Auth`)
- 单页面，tab 切换"登录 / 注册"。
- 不要在登录页放业务导航、不要放 IC 之外的品牌内容。
- 登录成功后存 `access_token`（建议放 `localStorage.access_token` + axios interceptor），路由跳 `/review`。

---

## 5. 视觉系统速查

详见 `DESIGN_SYSTEM_README.md` 和 `colors_and_type.css`，最常用的几条：

### 5.1 颜色
- **背景**：`--color-cream-50` = `#E9F1F8` —— 整个 app 的 page bg，"蓝天云白"中的"云"。
- **主色（蓝天）**：`--color-primary-500` = `#5BA8D6`，导航激活态、链接、雷达图。
- **强调色（马卡龙薄荷）**：`--color-accent-500` = `#8FCFB8`，**所有主按钮**用这个。
- **马卡龙分类色**（chart/tag）：peach `#F8B79A` / mint `#A8DCC8` / butter `#FAD980` / lavender `#C9B8E6` / sky `#A6CDEC`。
- **中性（云灰）**：`--color-stone-50/100/200/.../900`，文字主色 `stone-800`，次级 `stone-500`。
- **语义色**：success `#56A878`、warning `#E5A66B`、danger `#D87474`、info `#5BA8D6`。

### 5.2 字体
- 正文：Inter，本地 OTF 已附在 `fonts/`，对应 `--font-sans`。
- 等宽：JetBrains Mono（Google Fonts，按需在 `index.html` 加 `<link>`）。
- 显示字号：见 `colors_and_type.css` 的 `--text-xs/sm/base/lg/xl/2xl/3xl/4xl`。

### 5.3 间距 / 圆角 / 阴影
- 圆角：`--radius-sm:8 / md:10 / lg:14 / xl:16 / 2xl:20 / full:999`。卡片普遍 `lg–xl`，pill `full`。
- 阴影：`--shadow-xs/sm/md/lg`；卡片用 `sm`，弹窗 `lg`。
- 间距：8-pt 基准，最常用 8 / 12 / 16 / 22 / 32。

### 5.4 logo
- 36×36 圆角矩形，三色对角渐变 peach → 薄荷 → 薰衣草，内嵌 "IC" 白色 700 字重。**不要再单色蓝**。

---

## 6. 真实落地建议（Claude Code 友好）

推荐目录（在你的 `Interview_Copilot/` 工程里）：

```
Interview_Copilot/
├─ backend/                              # 已存在，不要动
├─ frontend/                             # 新建
│  ├─ design_handoff_interview_copilot/  # ← 这个包整体放进来
│  ├─ src/
│  │  ├─ pages/                          # 对应 7 个页面
│  │  ├─ components/                     # 复用原型里 ui.jsx 的原子
│  │  ├─ api/                            # axios client + 每个 endpoint 的封装
│  │  ├─ styles/
│  │  │  └─ tokens.css                   # = copy 自 design_handoff/colors_and_type.css
│  │  └─ main.tsx
│  ├─ vite.config.ts                     # proxy /api → backend:8000
│  └─ package.json
└─ ...
```

**Vite proxy 建议**（让前端 `fetch('/api/login')` 直接打到 `backend:8000/login`）：

```ts
server: {
  proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true, rewrite: p => p.replace(/^\/api/, '') } }
}
```

---

## 7. "如果后端没这个字段怎么办"

这是你最关心的——**前端做出来需要 X 字段，但后端只返回 Y**。

我已经在 `BACKEND_INTEGRATION.md` 里逐个 endpoint 列出了：
- UI 期望的请求 / 响应字段
- 当前后端真实提供的字段（基于 `Interview_Copilot/backend/app/api/`）
- ⚠️ 标注**有 gap 的地方**和**最小后端改动建议**

你让 Claude Code 按那份文档照单全收即可——前端先实现兼容当前后端的最小版本，再对每一个 ⚠️ 项发起一次小 PR 给后端。

---

## 8. Assets

- Logo：当前是 CSS 渐变（无图片），落地可以保留 CSS 实现，或者用 `assets/logo.svg`（如果包里有）。
- 图标：项目用 **lucide** 一整套（`https://unpkg.com/lucide@latest`），前端用 `lucide-react` 装一下即可，**不要**用 emoji 替代。
- 没有用到的素材：模拟面试录音波形图请用 `wavesurfer.js` 或类似库，不要画 SVG 假波。

---

## 9. 验收清单

接到这份包之后，**最起码**要能跑通这条 happy path：

1. 注册 → 登录 → 自动跳 `/review`
2. 新建 session → 拖一个 mp3 → 看到"转录中…" → QA 列表渲染出 3-5 条
3. 右侧 ChatPanel：切 AGENT、问一个问题、看到流式回答
4. 切到 `/mock` → 上传简历 + JD → 进入 Live → 录一条回答 → 结束面试 → 在 `/review` 看到这条 session
5. 切到 `/analytics` → 看到雷达图（哪怕只有 1 次面试也能渲染）
6. 切到 `/library` → 上传一个 PDF → 重命名 → 删除
7. 切到 `/models` → 选 DeepSeek → 粘贴假 key → 保存 → 刷新后仍在
8. 退出登录 → 401 后自动跳 `/auth`

每一步必须能命中 `BACKEND_INTEGRATION.md` 里对应的真实端点。

---

## 10. 联系上下文

- 设计来源：本对话产生的 HTML 原型（即本目录 `ui_kits/interview_copilot/index.html`）。
- 设计系统：项目根的 Design System 标签下 19 张 token / 组件卡。
- 后端代码：`Interview_Copilot/backend/app/`（FastAPI + SQLAlchemy + Alembic + Celery + Redis）。
- 字体替代说明：JetBrains Mono 当前走 Google Fonts，如果你要离线优先，请把 JetBrainsMono-VariableFont 放进 `fonts/` 并在 `colors_and_type.css` 改 `@font-face`。
