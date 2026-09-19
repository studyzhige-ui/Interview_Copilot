# Git + GitHub Desktop 初学者完整指南

> 目标：让第一次接触 Git 的开发者，从“本地项目已经有了、GitHub Desktop 也装好了”开始，建立一套不会混乱、可长期复用的 Git 工作流。  
> 适用环境：Windows + GitHub Desktop + VS Code；命令行示例以 PowerShell / Git Bash 为主。

---

## 0. 先记住这条主线

日常开发只需要先掌握这一条：

```text
开始工作
  ↓
Fetch / Pull
  ↓
VS Code 写代码、运行、测试
  ↓
GitHub Desktop 看 Changes / Diff
  ↓
Commit
  ↓
Push
  ↓
GitHub
```

一句话记忆：

> **先同步，再开发；提交前看 Diff；Commit 是本地版本，Push 才是上传。**

---

## 1. Git、GitHub、GitHub Desktop、VS Code 分别做什么

| 工具 | 主要职责 | 初学者可以这样理解 |
|---|---|---|
| **Git** | 本地版本管理系统 | 保存代码历史、分支、合并 |
| **GitHub** | 远程代码托管与协作平台 | 在线保存仓库、PR、Review、Issue |
| **GitHub Desktop** | Git 的图形界面客户端 | 看变化、Commit、Pull、Push、Branch |
| **VS Code** | 代码编辑器 | 写代码、运行、测试、解决冲突 |

推荐分工：

```text
VS Code
  └─ 写代码 / 测试 / 修改冲突

GitHub Desktop
  └─ Changes / Diff / Commit / Fetch / Pull / Push / Branch

GitHub.com
  └─ 远程仓库 / Pull Request / Review / Merge
```

---

## 2. 整个 Git 模型：先建立正确心智模型

Git 新手最容易混乱，是因为把“本地文件”“本地 Git 历史”和“GitHub”混成一个东西。

实际上可以拆成三层：

```text
① Working Tree（工作区）
   D:\Projects\你的项目
   你实际修改的文件
          │
          │ Commit
          ▼
② Local Repository（本地 Git 仓库）
   .git
   本地保存的 Commit 历史
          │
          │ Push
          ▼
③ Remote Repository（远程仓库）
   GitHub / origin
```

反方向：

```text
GitHub
  │
  │ Fetch / Pull
  ▼
本地 Git
  ▼
工作区
```

### 四个核心动作

| 操作 | 作用 | 会不会直接上传 GitHub |
|---|---|---:|
| **Fetch** | 检查并获取远程仓库的新信息 | ❌ |
| **Pull** | 把远程新提交整合到本地 | ❌ |
| **Commit** | 在本地保存一次版本快照 | ❌ |
| **Push** | 把本地 Commit 上传到 GitHub | ✅ |

> **Commit ≠ Push。**  
> Commit 之后代码可能仍然只存在于你的电脑。

---

## 3. 第一次使用 GitHub Desktop：该 Clone 还是 Add Existing Repository？

这是非常重要的第一步。

### 情况 A：GitHub 上有仓库，本地没有代码

使用：

**Clone a repository from the Internet**

Clone 会：

```text
GitHub 仓库
   ↓
下载完整项目 + Git 历史
   ↓
本地目录
```

Clone 时可以指定 **Local path**，例如：

```text
D:\Projects\Python\Epivra
```

### 情况 B：本地项目已经是 Git 仓库，而且已经 Push 到 GitHub

不要再 Clone。

使用：

**Add an Existing Repository from your local drive**

选择项目根目录，例如：

```text
D:\Projects\Python\Epivra
```

判断本地是否已经完整关联远程仓库：

```powershell
git status
git remote -v
```

理想结果类似：

```text
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

以及：

```text
origin  git@github.com:owner/repo.git (fetch)
origin  git@github.com:owner/repo.git (push)
```

这说明本地仓库已经完整关联 GitHub，无需再次 Clone。

### 软件安装目录和项目目录不是一回事

GitHub Desktop 本体通常由 Windows 安装到用户目录；真正占用空间、最值得规划的是代码目录。

推荐：

```text
D:\Projects\
├─ Python\
├─ JavaScript\
└─ Other\
```

项目可以自由放在 D 盘或其他盘，不需要跟 GitHub Desktop 软件放在一起。

---

## 4. GitHub Desktop 顶部几个区域分别是什么

### 📦 Current repository

当前正在管理哪个仓库。

切换仓库不会复制、删除或重新下载代码。

### 🌿 Current branch

当前所在分支，例如：

```text
main
feature/pdf-upload
fix/login-error
```

### 🔄 Fetch origin

检查远程仓库有没有新提交。

如果发现远程存在本地没有的提交，界面通常会进一步提供：

```text
Pull origin
```

可以这样记：

```text
Fetch = 看看远程有没有更新
Pull  = 把远程更新拿下来
Push  = 把本地提交传上去
```

---

## 5. Changes、Diff 和复选框

### 📝 Changes

Changes 表示：

> 从上一次 Commit 到现在，本地有哪些文件发生了变化。

常见状态：

| 标记 | 含义 |
|---|---|
| `+` | 新增文件 |
| `M` | 修改文件 |
| `-` / 删除状态 | 文件被删除 |

### ☑️ 文件前面的复选框

复选框决定：

> **这个文件要不要包含在“本次 Commit”里。**

例如：

```text
☑ backend/app.py
☑ frontend/App.tsx
☐ README.md
```

本次 Commit 只包含前两个文件。

取消勾选：

- 不会删除文件；
- 不会撤销修改；
- 只是“这次先不提交”。

### 🔍 Diff

提交前一定要看 Diff。

例如：

```diff
- timeout = 10
+ timeout = 30
```

一般：

- `-`：旧内容被删除；
- `+`：新内容被加入。

Diff 的意义不是“看看有没有红绿颜色”，而是回答：

> **我这次到底准备提交什么？**

如果你本来只改一个文件，却看到 `Changes 27`，应该先检查是否产生了日志、数据库、临时文件、构建产物等。

---

## 6. 一次完整的日常开发流程

### 第 1 步：开始工作前先同步

确认仓库和分支正确：

```text
Current repository = 正确项目
Current branch     = main 或目标分支
```

然后：

```text
Fetch origin
↓
如果有远程更新
↓
Pull origin
```

### 第 2 步：在 VS Code 写代码

正常：

- 修改文件；
- 新建文件；
- 运行程序；
- 跑测试。

### 第 3 步：回 GitHub Desktop 检查 Changes

重点检查：

- 是否只出现预期文件；
- 有没有 `.log`、`.env`、数据库、缓存；
- 有没有大文件；
- 有没有误改配置。

### 第 4 步：逐个看 Diff

确认：

- 改动逻辑正确；
- 没有调试代码；
- 没有敏感信息；
- 没有无关修改。

### 第 5 步：运行测试

例如：

```powershell
pytest
```

或：

```powershell
npm test
npm run dev
```

### 第 6 步：写 Commit Summary

好的 Summary 应该描述：

> **这次 Commit 做了什么。**

例如：

```text
feat: add PDF resume upload
fix: handle empty resume preview
docs: update local development guide
chore: ignore generated log files
```

### 第 7 步：Commit

```text
Commit to main
```

或者当前功能分支。

Commit 只保存到**本地 Git 历史**。

### 第 8 步：Push

Commit 后：

```text
Push origin
```

这一步才把新 Commit 上传到 GitHub。

---

## 7. Commit Summary 怎么写：推荐统一规则

推荐采用简化版 **Conventional Commits** 风格：

```text
type: 简短说明
```

或有明确范围时：

```text
type(scope): 简短说明
```

### 常用 type

| Type | 什么时候用 | 示例 |
|---|---|---|
| ✨ `feat` | 新功能 | `feat: add resume upload` |
| 🐛 `fix` | 修复 Bug | `fix: handle preview timeout` |
| 📚 `docs` | 只修改文档 | `docs: add Git workflow guide` |
| ♻️ `refactor` | 重构，不改变预期功能 | `refactor: simplify auth service` |
| ✅ `test` | 添加或修改测试 | `test: cover invalid PDF upload` |
| 🔧 `chore` | 工具、配置、依赖、杂项维护 | `chore: ignore log files` |
| ⚡ `perf` | 性能优化 | `perf: reduce vector query latency` |
| 🎨 `style` | 纯格式、排版、代码风格 | `style: format backend modules` |
| 🏗️ `build` | 构建系统或依赖相关 | `build: update frontend dependencies` |
| 🤖 `ci` | CI/CD 配置 | `ci: add test workflow` |

### Summary 的三个原则

1. **短**：一句话说明一个清晰动作；
2. **具体**：不要只写 `update`、`修改`、`fix`；
3. **一组相关修改一个 Commit**：不要把完全无关的事情混在一起。

不推荐：

```text
update
修改
new
test
fix
```

推荐：

```text
fix: handle missing resume data
docs: clarify local setup steps
feat: add interview session export
```

---

## 8. Branch：什么时候不要直接在 main 上开发

### main 是什么

可以把 `main` 理解成项目主线：

```text
A → B → C → D
            ↑
           main
```

### 开发明显的新功能时创建分支

例如：

```text
main
     feature/pdf-upload
```

推荐分支名：

| 类型 | 命名示例 |
|---|---|
| 新功能 | `feature/pdf-upload` |
| Bug 修复 | `fix/preview-crash` |
| 文档 | `docs/git-guide` |
| 重构 | `refactor/resume-parser` |
| 实验 | `experiment/new-reranker` |

### 什么时候可以直接 main

个人项目里很小的修改，例如：

- 修 README 错字；
- 改一个简单配置；
- 非破坏性的小修复。

### 什么时候推荐新分支

- 新功能；
- 大规模重构；
- 会修改很多文件；
- 方案还不确定；
- 预计开发多天；
- 多人协作。

---

## 9. Publish Branch、Push 和 Pull Request

新分支刚创建时，可能只存在本地：

```text
本地：
main
feature/pdf-upload

GitHub：
main
```

第一次上传新分支：

```text
Publish branch
```

以后继续上传新 Commit：

```text
Push origin
```

### Pull Request（PR）

PR 可以理解成：

> **这个分支已经开发完成，我申请把它合并进 main，请检查这些修改。**

方向通常是：

```text
feature/pdf-upload
        ↓
       main
```

GitHub 上常见：

```text
base: main
compare: feature/pdf-upload
```

不要把方向弄反。

PR 页面用于查看：

- 文件变化；
- Diff；
- Commit；
- 测试结果；
- Review；
- 冲突；
- 合并状态。

---

## 10. Merge、Squash、Rebase 的区别

假设功能分支有：

```text
D = Add upload UI
E = Fix upload bug
F = Fix typo
```

### Merge commit

保留原始分支历史：

```text
A → B → C ─────→ G
         \       /
          D → E → F
```

特点：历史完整，但图可能更复杂。

### Squash and merge

把多个小 Commit 压成一个：

```text
A → B → C → X
```

其中：

```text
X = feat: add PDF resume upload
```

适合一个功能分支里存在很多中间小 Commit 的情况。

### Rebase and merge

把功能分支 Commit 重新接到 main 最新位置：

```text
A → B → C → D' → E'
```

历史比较直，但涉及重写 Commit 关系。初学阶段知道概念即可，不需要主动依赖复杂 rebase 操作。

---

## 11. PR Merge 后别忘了本地 main 还是旧的

如果你在 GitHub 网页完成：

```text
Merge Pull Request
```

此时：

```text
GitHub main = 新版本
本地 main   = 可能还是旧版本
```

回 GitHub Desktop：

```text
切换 main
↓
Fetch origin
↓
Pull origin
```

确认同步以后，已完成使命的功能分支可以删除。

删除已合并分支：

> **不会删除已经进入 main 的代码。**

---

## 12. Merge Conflict：冲突到底是什么

冲突不是“Git 坏了”。

它只是表示：

> **Git 发现两边修改了同一位置，但无法判断最终代码应该是什么。**

例如：

本地：

```python
timeout = 30
```

远程：

```python
timeout = 60
```

可能看到：

```text
<<<<<<< HEAD
timeout = 30
=======
timeout = 60
>>>>>>> origin/main
```

这些符号表示两边的版本。

### 正确解决思路

不要机械地选择“我的”或“远程的”。

应该先判断真正正确的业务逻辑，最后把文件编辑成最终状态，例如：

```python
timeout = config.timeout
```

然后：

```text
保存文件
↓
确认冲突已解决
↓
完成 Merge Commit
↓
Push
```

### VS Code 常见按钮

| 按钮 | 含义 |
|---|---|
| Accept Current Change | 保留当前一侧 |
| Accept Incoming Change | 保留合并进来的一侧 |
| Accept Both Changes | 两边都保留 |

⚠️ 不要无脑点 **Accept Both**。两边同时保留可能产生重复或错误代码。

---

## 13. 如何减少冲突

最有效的方法很简单：

```text
开始开发前先 Fetch / Pull
↓
不同功能使用不同 Branch
↓
Commit 不要积累太久
↓
尽量让一个 Commit 聚焦一件事
```

不推荐：

```text
三天不 Pull
↓
一次改 100 多个文件
↓
一个超大 Commit
↓
直接 Push
```

---

## 14. 撤销：不同阶段用不同操作

这是最需要谨慎的一部分。

### 情况 1：修改了文件，还没 Commit

使用：

**Discard Changes**

含义：

> 丢弃当前本地修改，恢复到上一次 Commit。

⚠️ 它和“取消复选框”完全不同。

| 操作 | 修改还在吗 |
|---|---:|
| 取消 ☑ | ✅ 在，只是本次不提交 |
| Discard Changes | ❌ 修改被丢弃 |

### 情况 2：已经 Commit，但还没 Push

可以使用：

**Undo Commit**

效果：

```text
原来：
A → B → C

Undo 后：
A → B

C 中的修改重新回到 Changes
```

代码修改一般仍保留，只是撤回这个 Commit。

### 情况 3：已经 Push 到 GitHub

通常优先考虑：

**Revert**

Revert 不删除历史，而是新增一个“抵消旧修改”的 Commit：

```text
A → B → C → D
```

其中：

```text
D = 撤销 C 的效果
```

### 初学阶段不要为了“解决报错”随便使用

```bash
git reset --hard
git push --force
```

这些命令有合法用途，但可能丢失本地修改或重写远程历史。

---

## 15. .gitignore：哪些文件不该进入仓库

`.gitignore` 用来告诉 Git：

> **这些文件存在于项目中，但不要纳入版本管理。**

常见示例：

```gitignore
# Environment
.env
.env.*
!.env.example

# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Logs
logs/
*.log

# Local data
*.db
*.sqlite3

# IDE / OS
.idea/
.vscode/
.DS_Store
Thumbs.db
```

是否忽略 `.vscode/`、数据库文件等，要根据项目实际需要决定，不要机械复制模板。

### 一个重要例外

如果某个文件以前已经 Commit 过，后来才加入 `.gitignore`，Git 仍可能继续跟踪它。

例如：

```bash
git rm --cached debug.log
```

目录：

```bash
git rm -r --cached logs
```

`--cached` 表示：

> 从 Git 跟踪中移除，但本地文件保留。

---

## 16. 🔐 绝对不要提交密钥和敏感信息

特别注意：

- `.env`；
- API Key；
- GitHub Token；
- 云服务 Key；
- 数据库密码；
- SSH 私钥；
- 用户真实隐私数据。

如果凭证已经 Push 到 GitHub：

> **仅仅删文件并再次 Commit 不够。**

旧 Commit 中可能仍然包含秘密。

正确顺序：

```text
发现泄露
↓
立即吊销 / 轮换旧凭证
↓
生成新凭证
↓
再处理仓库历史
```

---

## 17. git status：最值得记住的一条命令

即使主要使用 GitHub Desktop，也建议保留：

```powershell
git status
```

理想状态：

```text
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

分别表示：

| 输出 | 含义 |
|---|---|
| `On branch main` | 当前在 main |
| `up to date with 'origin/main'` | 本地分支与远程追踪状态一致 |
| `working tree clean` | 当前没有未 Commit 的文件修改 |

注意：

> `working tree clean` 只代表“没有未 Commit 的修改”，不单独证明所有本地 Commit 都已经 Push。

---

## 18. 遇到问题时，应该想到哪个操作

| 你现在的问题 | 优先想到 |
|---|---|
| GitHub 上有没有新版本？ | 🔄 Fetch |
| GitHub 有新 Commit，要同步本地 | ⬇️ Pull |
| 想看本地改了哪些文件 | 📝 Changes |
| 想看具体哪几行变了 | 🔍 Diff |
| 只想暂时不提交某个文件 | 取消 ☑ |
| 保存一个本地版本 | 💾 Commit |
| 把 Commit 上传到 GitHub | ⬆️ Push |
| 开发明显的新功能 | 🌿 New Branch |
| 新分支第一次上传 | 🌐 Publish Branch |
| 功能准备进入 main | 🔀 Pull Request |
| PR 正式进入 main | ✅ Merge |
| 未 Commit 的修改不要了 | 🗑️ Discard Changes |
| 最近 Commit 错了且没 Push | ↩️ Undo Commit |
| 已 Push 的 Commit 需要撤销 | ⏪ Revert |
| 两边改了同一位置 | ⚠️ Resolve Conflict |
| 文件不应该被 Git 管理 | 🙈 `.gitignore` |
| 分支已经 Merge 完成 | 🧹 Delete Branch |
| 不确定当前仓库状态 | 🩺 `git status` |

---

## 19. 个人项目推荐工作流

### 小修改

```text
main
↓
Fetch / Pull
↓
修改
↓
测试
↓
看 Changes / Diff
↓
Commit
↓
Push
```

### 明显的新功能

```text
main
↓
Fetch / Pull
↓
New Branch
↓
feature/xxx
↓
开发
↓
测试
↓
Diff
↓
Commit
↓
继续开发 / Commit
↓
Publish / Push
↓
Pull Request
↓
Review
↓
Merge
↓
切回本地 main
↓
Fetch / Pull
↓
删除已完成分支
```

---

## 20. 多人协作时的基本结构

推荐：

```text
main
├─ feature/alice-task
├─ feature/bob-task
└─ fix/login-error
```

每个人：

```text
各自 Branch
↓
Commit
↓
Push
↓
Pull Request
↓
Review
↓
Merge
```

不要让多人长期直接在 `main` 上同时修改。

---

## 21. 提交前检查清单

Commit 前花几十秒检查：

- [ ] 当前 Repository 正确；
- [ ] 当前 Branch 正确；
- [ ] Changes 数量符合预期；
- [ ] 已查看主要文件 Diff；
- [ ] 没有 `.env`、Token、密码、私钥；
- [ ] 没有无意义的 `.log`、缓存、临时文件；
- [ ] 没有误提交大文件、数据库、构建产物；
- [ ] 代码已经运行或测试；
- [ ] Commit Summary 能准确描述这次修改。

Push 前再确认：

- [ ] Commit 内容完整；
- [ ] 如果远程可能有人更新，先 Fetch；
- [ ] 没有未处理的冲突；
- [ ] 当前分支就是你想 Push 的分支。

---

## 22. 最终心智地图

```text
                    GitHub
                  origin/main
                      ▲
                      │ Push
                      │
                 Local Commit
                      ▲
                      │ Commit
                      │
VS Code ──修改──→ Working Tree
                      ▲
                      │ Pull
                      │
                    GitHub
```

开发新功能：

```text
main
 │
 └── feature/xxx
          │
          ├── Commit
          ├── Commit
          ├── Push
          │
          └── Pull Request
                  │
                  ▼
                 main
```

---

## 23. 初学者真正需要形成的习惯

1. 🔄 **开工前同步**：先 Fetch，有更新再 Pull。
2. 🔍 **提交前看 Diff**：不要只看文件名。
3. 🧩 **一次 Commit 聚焦一件事**。
4. ✍️ **Summary 写清楚做了什么**，不要只写 `update`。
5. 🌿 **大功能使用 Branch**，不要让 main 长期处于半成品状态。
6. 🔐 **任何密钥都不要进入 Git 历史**。
7. ⚠️ **遇到冲突先理解两边代码，不要机械点按钮**。
8. 🧨 **不理解时不要随便用 `reset --hard` 或 `push --force`**。
9. 🩺 **状态不确定就先看 `git status`**。
10. ✅ **Merge PR 后记得回本地 main Fetch / Pull。**

---

## 速记卡

```text
Fetch   = 检查远程
Pull    = 远程 → 本地
Commit  = 保存本地版本
Push    = 本地 → 远程

Changes = 哪些文件变了
Diff    = 哪些行变了

Branch  = 独立开发线
PR      = 申请把分支合并进 main
Merge   = 正式合并

Discard = 丢弃未提交修改
Undo    = 撤回最近未 Push 的 Commit
Revert  = 用新 Commit 抵消已发布 Commit
```

> 日常开发不需要先掌握所有高级 Git 命令。把 **Pull → 开发 → Diff → Commit → Push** 这一条主线练熟，再正确使用 Branch / PR / Conflict / Revert，就已经足够覆盖绝大多数个人项目和基础团队协作场景。
