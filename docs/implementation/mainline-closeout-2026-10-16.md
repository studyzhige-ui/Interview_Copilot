# 主线收口：2026-10-16

本轮停止扩展功能，统一收口现有工作区：Agent 生命周期、职业工作区、语音/录音、前端页面、数据库迁移、依赖及相关测试文档一起进入 main。

## 冗余和入口复核

- 后端 517 个模块从 API、worker、运维脚本、迁移和明确子进程入口分析，全部可达。模型探测、推理 child、Docling 子进程及迁移 schema policy 均有实际入口，不误删动态加载模块。
- 前端 import/export/dynamic import 图和 TypeScript 引用分析未发现新的可确认无用产品模块。`PdfPreview` 是懒加载入口，`shared-protocol-compatibility.ts` 是编译期合同，保留。
- 已删除的旧录音结构化、speaker identity 以及旧页面没有残留产品 import。保留有工具、历史数据和迁移合同用途的旧 schema/模型，不因命名含 legacy 就删除。
- 上轮已经移除不再需要的 refund_step，复用现有工具、上下文、记忆 owner，不增加并行实现。
- 修正 Python 包的资源匹配，确保无扩展名的 LICENSE/NOTICE 随上下文模板一起打包。

这证明当前入口和已核实调用链一致，不是对动态语言所有可能执行路径作“绝对零死代码”的数学保证。未发现需要继续扩大重构范围的确定性重复实现。

## 当前验收

| 检查 | 结果 |
|---|---|
| Linux 后端 + 真实临时 PostgreSQL | 268 passed，1 skipped；未包含 release/browser/model_acceptance |
| 前端测试 | 35 passed |
| 桌面测试 | 4 passed |
| 前端 lint、类型检查、生产构建 | 通过；按需 PDF chunk 体积警告保留 |
| Python Ruff + format | 通过，650 文件格式检查 |
| Python compileall | 通过 |
| Pydantic snapshot 与两份 TypeScript 生成合同 | 通过 |
| Python wheel | 构建成功；LICENSE/NOTICE 存在，无已删除的 Python 模块混入 |

测试使用隔离代码副本，没有把测试通过表述为运行服务已更新。当前提交不包含凭据、测试数据库、模型权重、构建产物或本地诊断输出。

## Git 收口方式

开始时分支为 `codex/mainline-convergence`，HEAD `0029187`；已刷新远端，`origin/main` 为 `812bf76` 且是当前分支祖先。保留现有提交历史，正常推进 main，不重写或强推历史。已有检查点保留作恢复依据，不构成第二套产品实现。
