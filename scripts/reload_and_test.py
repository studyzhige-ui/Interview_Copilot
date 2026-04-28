"""
Reload & Test Script
====================
1. 清空现有 Milvus collection 和 Docstore
2. 重新摄取 data/storage/uploads/ 中的所有 PDF
3. 对每个 PDF 执行检索测试，验证 Reranker 分数是否 >= RAG_MIN_SCORE
"""
import os
import sys
import shutil
import asyncio
import logging

# 将 backend 目录加入 Python 路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("reload_and_test")

# ============================================================
# 测试查询（每个 PDF 对应 3 个代表性问题）
# ============================================================
TEST_QUERIES = {
    "AI大模型": [
        "Transformer 的自注意力机制是如何工作的？",
        "大模型微调 LoRA 的原理是什么？",
        "什么是 RAG 检索增强生成？",
    ],
    "MySQL": [
        "MySQL 的 MVCC 多版本并发控制原理是什么？",
        "InnoDB 和 MyISAM 存储引擎有什么区别？",
        "MySQL 索引的底层数据结构是什么？",
    ],
    "Python": [
        "Python 的 GIL 全局解释器锁是什么？",
        "Python 中的装饰器是怎么实现的？",
        "Python 的垃圾回收机制是怎样的？",
    ],
    "Redis": [
        "Redis 的持久化机制 RDB 和 AOF 有什么区别？",
        "Redis 分布式锁是怎么实现的？",
        "Redis 的数据淘汰策略有哪些？",
    ],
    "后端场景": [
        "秒杀系统的高并发解决方案有哪些？",
        "分布式事务的解决方案有哪些？",
        "如何设计一个高可用的微服务架构？",
    ],
}

# 使用匿名测试用户
TEST_USER_ID = "test_user_reload"


async def main():
    from app.core.config import settings
    from app.rag.ingestion import _get_milvus_vector_store
    from app.rag.retriever import init_reranker

    # ============================================================
    # Step 1: 清空旧数据
    # ============================================================
    logger.info("=" * 60)
    logger.info("Step 1: 清空旧数据")
    logger.info("=" * 60)

    # 清空 Milvus collection（overwrite=True 会重建）
    logger.info("重建 Milvus collection（overwrite=True）...")
    _get_milvus_vector_store(overwrite=True)
    logger.info("Milvus collection 已清空并重建。")

    # 清空 Postgres Docstore 表
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS data_kvstore CASCADE;"))
            conn.execute(text("DROP TABLE IF EXISTS metadata_kvstore CASCADE;"))
        logger.info("PostgreSQL Docstore 表已清空。")
    except Exception as e:
        logger.warning(f"清空 PostgreSQL Docstore 表失败 (可能表还不存在): {e}")

    # ============================================================
    # Step 2: 重新摄取所有 PDF
    # ============================================================
    logger.info("=" * 60)
    logger.info("Step 2: 摄取 PDF 文件")
    logger.info("=" * 60)

    from app.rag.ingestion import ingest_document

    upload_dir = os.path.join(PROJECT_ROOT, "data", "storage", "uploads")
    if not os.path.exists(upload_dir):
        logger.error(f"上传目录不存在: {upload_dir}")
        return

    pdf_files = [f for f in os.listdir(upload_dir) if f.endswith(".pdf")]
    if not pdf_files:
        logger.error("未找到任何 PDF 文件。")
        return

    logger.info(f"找到 {len(pdf_files)} 个 PDF 文件:")
    for f in pdf_files:
        logger.info(f"  - {f}")

    for i, pdf_name in enumerate(pdf_files, 1):
        pdf_path = os.path.join(upload_dir, pdf_name)
        logger.info(f"\n[{i}/{len(pdf_files)}] 正在摄取: {pdf_name}")
        try:
            success = await ingest_document(
                file_path=pdf_path,
                source_type="interview_qa",
                user_id=TEST_USER_ID
            )
            if success:
                logger.info(f"  ✅ 摄取成功: {pdf_name}")
            else:
                logger.warning(f"  ⚠️ 文件为空或解析失败: {pdf_name}")
        except Exception as e:
            logger.error(f"  ❌ 摄取失败: {pdf_name} — {e}")

    # ============================================================
    # Step 3: 初始化 Reranker 并执行检索测试
    # ============================================================
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: 检索测试")
    logger.info("=" * 60)

    init_reranker()

    from app.rag.retriever import query_knowledge_base

    total_queries = 0
    passed_queries = 0
    failed_queries = 0
    all_scores = []

    min_score = settings.RAG_MIN_SCORE
    logger.info(f"阈值: RAG_MIN_SCORE = {min_score}\n")

    for topic, queries in TEST_QUERIES.items():
        logger.info(f"--- 主题: {topic} ---")
        for query in queries:
            total_queries += 1
            try:
                result = await query_knowledge_base(
                    query_str=query,
                    user_id=TEST_USER_ID,
                    source_type="interview_qa",
                    min_score=0.0  # 不在查询层过滤，我们手动检查分数
                )

                sources = result.get("sources", [])
                if not sources:
                    logger.warning(f"  Q: {query}")
                    logger.warning(f"     ❌ 无检索结果")
                    failed_queries += 1
                    continue

                top_score = sources[0]["score"]
                all_scores.append(top_score)

                passed = top_score >= min_score
                status = "✅" if passed else "❌"

                if passed:
                    passed_queries += 1
                else:
                    failed_queries += 1

                logger.info(f"  Q: {query}")
                logger.info(f"     {status} Top Score: {top_score:.4f}  (共 {len(sources)} 条结果)")

                # 打印 Top-3 分数
                for j, src in enumerate(sources[:3], 1):
                    snippet = src["text"][:80].replace("\n", " ")
                    logger.info(f"        #{j} score={src['score']:.4f} | {snippet}...")

            except Exception as e:
                logger.error(f"  Q: {query}")
                logger.error(f"     ❌ 检索异常: {e}")
                failed_queries += 1

    # ============================================================
    # 汇总报告
    # ============================================================
    logger.info("\n" + "=" * 60)
    logger.info("检索测试汇总报告")
    logger.info("=" * 60)
    logger.info(f"总查询数:     {total_queries}")
    logger.info(f"通过 (≥{min_score}):  {passed_queries}")
    logger.info(f"未通过 (<{min_score}): {failed_queries}")

    if all_scores:
        avg_score = sum(all_scores) / len(all_scores)
        max_score = max(all_scores)
        min_s = min(all_scores)
        logger.info(f"平均 Top Score: {avg_score:.4f}")
        logger.info(f"最高 Top Score: {max_score:.4f}")
        logger.info(f"最低 Top Score: {min_s:.4f}")

    pass_rate = (passed_queries / total_queries * 100) if total_queries > 0 else 0
    logger.info(f"\n通过率: {pass_rate:.1f}%")

    if pass_rate >= 90:
        logger.info("🎉 检索质量达标！")
    elif pass_rate >= 70:
        logger.warning("⚠️ 检索质量良好但有改进空间。")
    else:
        logger.error("❌ 检索质量不达标，需要排查。")


if __name__ == "__main__":
    asyncio.run(main())
