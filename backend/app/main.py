import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import Base, engine
import app.models.interview  # 确保所有模型在表创建前挂载完备
from app.api import interview, rag, agent
from app.rag.embeddings import init_rag_settings
from app.services.transcription_service import init_whisper_model

logger = logging.getLogger("interview.copilot.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    掌控全局启动/切断的官方中枢事件环（Event Lifecycle）。
    将之前裸露在每个文件零散全局域内的重量级组件依次同步加载。
    """
    logger.info("====== Interview Copilot 舰桥核心引擎启动序列开始 ======")
    
    # [1] 数据库建库
    logger.info(">>> [1/3] 验证并建立 SQLite 文件主从表矩阵...")
    Base.metadata.create_all(bind=engine)
    
    # [2] 获取并连接大模型思维
    logger.info(">>> [2/3] 正在对标接管 LlamaIndex 设置、挂紧 DeepSeek 网点...")
    init_rag_settings()
    
    # [3] 本场高负载运算 - 模型推入运算资源显卡
    logger.info(">>> [3/3] 通知 GPU 线程下放 Whisper 解析模块缓存...")
    init_whisper_model()
    
    logger.info("====== All Sys-nodes Online. 核心全部待机，可随叫随到 ======")
    yield
    
    logger.info("====== 系统被安全杀停，释放显存及对应池... ======")

app = FastAPI(
    title="Interview Copilot API",
    description="Agent + RAG Backend for Interview Copilot",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(interview.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")

@app.get("/ping")
async def ping():
    return {"status": "ok"}
