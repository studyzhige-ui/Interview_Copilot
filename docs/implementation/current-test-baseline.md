# 当前主线测试基线（2026-10-11 重建）

用户要求删除全部旧测试、按当前项目重写必要测试。旧测试、辅助文件和被合并的重复测试执行器共 424 项已封存到项目外的
`D:/Projects/Archives/Interview_Copilot-20261011/retired-tests.zip`；完整源码可从
`checkpoint/before-capability-and-tests-rebuild-20261011` 和同目录 Git bundle 恢复。
当前测试不沿用历史测试数量，也不代表覆盖旧套件的全部场景。

## 必须运行的合同

- 简历：单次模型请求同时提取资料候选与原文分段，连续完整覆盖、类型合法、版本隔离、跨用户隔离、默认/归档。
- Agent：工具结果完整留存和分页回读，压缩不破坏 call/result 配对，写入授权策略。
- 音频：真实 FFmpeg 解码及坏文件失败，分数时长与窗口覆盖，交换标签后的说话人身份连续性，私有 socket 请求绑定、取消与释放。
- 数据：从空 PostgreSQL 迁移至 head、Alembic 元数据一致，真实 pgvector exact/HNSW 的租户、代次、软删除边界。
- 文件与额度：Linux create-only/路径隔离，未知执行保留预约而非错误退款。
- 前端与桌面：账号切换隔离、嵌套弹窗、展示精度、桌面回调与自有数据目录。

Linux 主合同入口：

```bash
TEST_PG_ADMIN_URL=postgresql://.../postgres REQUIRE_TEST_POSTGRES=1 \
python -m pytest backend/tests --ignore=backend/tests/browser \
  --ignore=backend/tests/model_acceptance --ignore=backend/tests/test_s3_http.py
npm run test:run --prefix frontend
npm test --prefix desktop
```

PostgreSQL 测试仅创建/删除唯一命名的临时库。禁止指向无建库权限的业务连接；不会清空业务库。
`evaluation/career_agent_os_eval.py` 绑定当前合同文件并检查本轮 JUnit 实际执行；跳过不算通过。
该 gate 不再声称通过旧 VS01 十五场景或可直接发布。

## 独立验收

- `IC_RUN_BROWSER=1 pytest backend/tests/browser`：真实 Chromium 打开当前生产构建，验证认证页面和表单；不等于完整业务浏览器端到端验证。
- `REQUIRE_TEST_S3=1` 加 TEST_S3_* 后运行 `test_s3_http.py`：真实签名 HTTP、不可覆盖、范围读取与删除。
- `IC_REAL_RECORDING_DIR` 指向原始录音夹后运行 `backend/tests/model_acceptance`：真实 WhisperX、对齐模型、broker 子进程和 Pyannote；缺少输入时明确跳过，不算模型验证成功。
- 桌面 CI 保留打包完整性、真实 Docker 启停/重启和数据保留；Windows 脚本验证打包进程启动与单实例，不再冒称已验证安装后的协议注册。

未覆盖所有历史邀请恢复、邮件提供者、实时媒体、外部账号、GPU 显存及 Windows 安装/卸载场景。
这些限制是测试覆盖边界，不表示删除了对应产品功能。后续功能变更应围绕实际风险补充合同，
不能用更少测试的通过率替代完整产品验收。


## 本轮执行记录

- 最终核心测试 **63 passed**，在独立 Linux 容器、一次性 PostgreSQL 中运行；模型调用在需要的合同处使用明确替身，不把这些结果算作模型质量。
- 真实模型验收最终 **1 passed**（102.29 秒），原始录音 SHA-256 为
  `969e90d75a1717934eab076d3357004b07f2d2e678bd8ffda45b14d1b6fe8502`。
  121.617375 秒、393 个归一化字符、6 次 broker 完成请求，无插入/删除和边界重复，
  仍有 2 处同音字替换；身份连续为 speaker_001。该样本是单说话人合成录音，
  不代表多说话人真实访谈总体准确率；交换窗口标签的身份匹配另有确定性测试。
- 前端 13 项、桌面核心 4 项、真实 Chromium 1 项、真实 S3 HTTP 1 项通过。
  PostgreSQL 的迁移与 Alembic check 通过；前端 build/lint、Ruff 和 shared/realtime wire 导出检查通过。
- Windows 安装包和整套 Docker 桌面启停脚本本轮仅完成静态检查，没有把未执行的 CI 作业算作通过。
- 没有调用付费 LLM 检验简历语义分段质量，也没有修改业务数据库或触发历史简历重解析。
  上线需执行 0074 迁移并重启使用 v2 音频合同的 broker；已有简历用原有重解析入口补齐分段。
