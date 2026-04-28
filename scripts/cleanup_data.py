import os
import shutil
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 定义路径
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_ROOT = BASE_DIR / "data"
LEGACY_DATA_DIR = BASE_DIR / "backend" / "data"

# 目标子目录结构
DB_DIR = DATA_ROOT / "databases"
CACHE_DIR = DATA_ROOT / "cache"
LOG_DIR = DATA_ROOT / "logs"
EVAL_DIR = DATA_ROOT / "evaluation"
STORAGE_DIR = DATA_ROOT / "storage"

def migrate_folder(src: Path, dst: Path):
    """安全迁移文件夹"""
    if not src.exists():
        return

    logger.info(f"迁移目录: {src} -> {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        logger.warning(f"目标目录已存在: {dst}，尝试合并文件...")
        for item in src.iterdir():
            target_item = dst / item.name
            if target_item.exists():
                if item.is_dir():
                    shutil.copytree(item, target_item, dirs_exist_ok=True)
                    shutil.rmtree(item)
                else:
                    shutil.copy2(item, target_item)
                    item.unlink()
            else:
                shutil.move(str(item), str(target_item))
        shutil.rmtree(src)
    else:
        shutil.move(str(src), str(dst))

def migrate_file(src: Path, dst: Path):
    """安全迁移文件"""
    if not src.exists():
        return

    logger.info(f"迁移文件: {src} -> {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        logger.warning(f"目标文件已存在: {dst}，覆盖处理。")
        dst.unlink()
    shutil.move(str(src), str(dst))

def main():
    logger.info("开始数据清理与重构任务...")

    # 1. 确保目标根目录存在
    DATA_ROOT.mkdir(parents=True, exist_ok=True)

    # 2. 迁移核心数据库 (从旧位置到新层级)
    # 检查可能的源位置：root/data/xxx 或 backend/data/xxx
    for base in [DATA_ROOT, LEGACY_DATA_DIR]:
        migrate_folder(base / "chroma_db", DB_DIR / "chroma")
        migrate_folder(base / "docstore", DB_DIR / "docstore")

        # 3. 迁移缓存
        migrate_folder(base / "hf_cache", CACHE_DIR / "huggingface")
        migrate_folder(base / "torch_cache", CACHE_DIR / "torch")
        migrate_folder(base / "models", CACHE_DIR / "models")

        # 4. 迁移日志
        migrate_folder(base / "logs", LOG_DIR)

        # 5. 迁移评估文件
        migrate_folder(base / "eval_chroma_db", EVAL_DIR / "eval_chroma_db")
        if (base / "eval_dataset.jsonl").exists():
            migrate_file(base / "eval_dataset.jsonl", EVAL_DIR / "eval_dataset.jsonl")

        for eval_file in base.glob("eval_*.json"):
            migrate_file(eval_file, EVAL_DIR / eval_file.name)

        # 6. 迁移存储
        migrate_folder(base / "uploads", STORAGE_DIR / "uploads")
        migrate_folder(base / "fallback_storage", STORAGE_DIR / "fallback")

    # 7. 清理碎片
    junk_patterns = [
        "*.db-journal",
        "sqlite_probe_*",
        "tmp_sqlite_probe*",
        "tmp_chroma_probe*",
        ".pytest_cache"
    ]

    for base in [BASE_DIR, LEGACY_DATA_DIR, DATA_ROOT]:
        for pattern in junk_patterns:
            for junk in base.glob(pattern):
                logger.info(f"清理垃圾文件: {junk}")
                if junk.is_dir():
                    shutil.rmtree(junk)
                else:
                    junk.unlink()

    # 8. 处理留在 cache 根目录下的孤立 PDF (迁移至 storage)
    for pdf in CACHE_DIR.glob("*.pdf*"):
        migrate_file(pdf, STORAGE_DIR / "uploads" / pdf.name)

    logger.info("数据迁移与清理完成！")

    # 最后检查是否可以删除整个 legacy 文件夹
    if LEGACY_DATA_DIR.exists() and not any(LEGACY_DATA_DIR.iterdir()):
        logger.info(f"删除空的旧数据目录: {LEGACY_DATA_DIR}")
        LEGACY_DATA_DIR.rmdir()

if __name__ == "__main__":
    main()
