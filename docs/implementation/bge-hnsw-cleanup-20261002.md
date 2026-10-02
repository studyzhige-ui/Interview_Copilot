# BGE 主线、HNSW 补迁及 Qwen 清理（2026-10-02）

本轮在 `codex/integrate-local-work-20261001` 的独立工作树完成。原 main 的全部
1216 个检查点文件逐一按 Git 内容哈希复核，零差异，暂存区为空。
恢复点仍为 `codex/checkpoint-local-20261001`（`a364152`）。

## 根因与最终检索路径

项目一直是混合检索：**BGE-M3 dense + BM25 → RRF → bge-reranker-v2-m3**。
HNSW 是 dense 通道的近邻索引；精确 dense 搜索也属于同一混合流程。
先前迁入遗漏了本地 HNSW，并把原表布局称为“旧 HNSW”，容易误解为算法已废弃。
实际差异是原本地 `rag_vec_*` 独立表和远端 `retrieval_entries` 规范投影的存储布局。

只建索引不能修复遗漏：原授权 MATERIALIZED 查询阻止 HNSW 排序扫描；直接展开
多表 JOIN 后，优化器又因重复身份约束低估候选数，仍选精确排序。现使用同一完整
规范 JOIN 先收敛授权块 ID，dense 基表在该 ID 集合内按向量距离检索。
不改变文档/块/文件的用户、发布状态、内容哈希与私有会话附件范围。

## HNSW 部署合同

- 每个用户、语义代际及构建参数组合拥有独立的部分表达式索引；不同用户和
  不同维数不共享图。IP、COSINE、L2 分别使用正确的 pgvector 操作类。
- 迁入原参数：M=16、ef_construction=200、ef_search=100；最大迭代扫描 20000。
  严格顺序迭代需要 pgvector >= 0.8；当前测试镜像为 0.8.6。
- HTTP 和检索不执行 DDL。维护命令串行防止重复建图；无 `IF NOT EXISTS` 掩盖
  无效索引。显式 HNSW 模式下非空资料缺图或候选容量不足会报不可用。
- 按用户动态创建的图不在 ORM 元数据中。隔离库确认 Alembic 原本会将它们
  列为 `remove_index`；现仅排除规范表上符合项目命名规则的运维 HNSW 索引。
  真实 PostgreSQL 对照确认图被保留，普通索引及同前缀 B-tree 仍参与比较。
- 物理策略不改变 BGE 向量空间。v3 身份中的历史 `dense_index_type=EXACT` 冻结，
  物理模式由 `PGVECTOR_DENSE_INDEX_TYPE` 控制；切换不要求再次 Embedding。
  评测合同单独记录实际模式与 HNSW 参数。
- 部署默认 `exact`，先准备各资料所有者的图，再设 `hnsw` 并重启 API/Worker。
  新用户、新语义代际或 M/ef_construction 变更需要对应图。ef_search 不要求重建。

```bash
# 先预览；将 1 换成实际规范资料所有者的数字 ID。
python scripts/prepare_rag_hnsw.py --user-pk 1
# 在维护窗口显式建图，不调用模型、不改源资料。
python scripts/prepare_rag_hnsw.py --user-pk 1 --apply
```

随后在部署配置设置 `PGVECTOR_DENSE_INDEX_TYPE=hnsw`。实际业务数据库及 `.env`
本轮未改动，没有执行上述业务维护命令。小语料时 PostgreSQL 可选择较便宜的
精确计划；HNSW 是近似检索，启用实际库前需对真实 BGE 召回和延迟作质量对照。
[pgvector 官方 HNSW、过滤与迭代扫描说明](https://github.com/pgvector/pgvector#hnsw)。

`evaluation/compare_local_models.py` 的 `--profile` 只有 `bge`；另支持
`--dense-index-type hnsw --prepare-hnsw`，只允许在受保护的 `rag_compare*` 评测库
准备图。规范块和 planner 保持冻结，输出记录配置，不复用身份不匹配的历史结论。

## Qwen 删除范围与语音影响

删除生产 ASR、ForcedAligner、TTS、IPC 角色/协议、文件证据 collector、模型 vendor
及 curated 适配；种子目录删除 113 个 Qwen 条目。评测删除 Qwen embedding/rerank
数学实现、模型配置、交叉运行阶段；前端删除对应 vendor 色卡及本地预设音色。
旧独立 broker 的 transcription/alignment/synthesis 配置会拒绝加载，须在新运行
目录按当前 BGE/可选 Pyannote 命令准备。无自动兼容或下载。

保留共享 PCM 哈希/容量校验、WhisperX 转写/词级证据和 Pyannote。实时 ASR 窗口
复用既有 WhisperX 单工 worker；临时 WAV 由 worker 持有至完成，取消等待不提前删除。
WhisperX 上传仍按整段解码，未声称具备已删除的长录音窗口编排或原生流式能力。

TTS 默认 `disabled`。自动审批拒绝将其默认切为 Edge，理由是会把面试文本发送到
外部目的地；最终保留原有显式 `edge` 选择，受 `AUXILIARY_MODEL_POLICY` 控制，
`local_only` 禁止它。HTTP 使用实际 MP3 格式。实时媒体原要求 24 kHz WAV，当前
没有替代的本地生产合成适配，明确返回不可用；文字面试和录音转写继续可用。

历史审核、评测报告及原检查点保留。它们不表示当前分支仍可执行 Qwen 适配。

## 验证证据

前端完整 93 个测试文件、381 项测试通过；TypeScript、ESLint、生产构建通过。
后端完整 Linux 回归为 **2411 passed、14 skipped、0 failed**（656.58s），
对应源码 `0f4dcb7390b0ba73bdd0fb66cc94533e46887439`。随后仅追加运维索引
迁移比较规则，以及删除 Qwen 后 MTRAG 两条独立任务记录的计数断言纠正。
最终源码 `ca79df895adec755b06106cab70a794de435edee` 的迁移链、HNSW、
规范 PostgreSQL 检索及架构回归 **38 passed**，MTRAG 离线 **15 passed**，
`jieba_search`/PostgreSQL **12 passed**。这次后续修复未重复整套后端回归。
固定 Ruff 0.16.2 全范围 lint 通过，包含 Alembic 入口的 918 文件格式检查通过。

HNSW 测试使用 1500 个本用户向量、3000 个更近的异用户向量及一个私有附件；
不强制 PostgreSQL planner。IP、COSINE、L2 均在实际 EXPLAIN 计划中使用
对应 HNSW 索引，合成 Recall@10 均为 **1.0**；发布状态和私有附件过滤通过。
这些结果验证算子、执行路径与隔离，不能替代真实 BGE 模型的质量和延迟验收。

14 项跳过为：9 个真实浏览器场景、1 个下载语料合同、1 个真实 BGE 模型场景、
1 个可选 aiortc/WebRTC 场景、2 个 S3 HTTP 场景。
首轮完整运行中的两条退役语音客户端测试已删除，复测后完整后端无失败；
独立 MTRAG 的旧四行断言也已修复，最终 15 项通过。
[版本、源码哈希及 JUnit 摘要](../reports/bge-hnsw-cleanup-2026-10-02/validation.json)
记录各阶段的结果，不把旧报告视为当前源码的质量证据。

所有数据库、Redis、FFmpeg 解码在标识清晰的一次性隔离环境内执行。
没有调用付费模型、真实 GPU、Supabase 登录，也未迁移或删除业务资料/下载的权重。

Windows 定向检查为 234 passed、17 skipped、14 failed；失败为既有 Linux/WSL2
限制和 Windows symlink 权限，不能作为支持这些合同的运行环境验收。
本轮以 Linux 回归验证相同原始行为。
