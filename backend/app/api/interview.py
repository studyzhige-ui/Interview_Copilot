import os
import shutil
import uuid
import json
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException

from app.db.database import get_db
from app.models.interview import Interview, Transcript, AnalysisResult
from app.services.transcription_service import transcribe_media
from app.services.analysis_service import analyze_interview
from app.rag.ingestion import ingest_text

router = APIRouter()

# Resolve paths correctly assuming backend/app/api/interview.py
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")

@router.post("/upload/audio")
async def upload_audio(file: UploadFile = File(...)):
    # Ensure directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Generate a unique safe filename
    _, ext = os.path.splitext(file.filename)
    if not ext:
        ext = ".bin"
        
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    # Save the file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Return relative file path structured like "data/uploads/filename"
    relative_path = os.path.join("data", "uploads", unique_filename).replace("\\", "/")
    
    return {
        "status": "success",
        "file_path": relative_path
    }

class AnalyzeRequest(BaseModel):
    file_path: str

class MemorySaveRequest(BaseModel):
    question: str
    improved_answer: str

@router.post("/analyze")
async def analyze_interview_endpoint(request: AnalyzeRequest, db: Session = Depends(get_db)):
    """
    业务大闭环处理态：获取本地对话转录Mock -> 获取 DeepSeek 洗稿分析评价表式结果 -> 通过 SQLAlchemy 做主外键级联写入记录。
    此接口纯关系型操作提取评定，拒绝污染底层 RAG 向量池。
    """
    try:
        # 1. Pipeline 前置节点：模拟获取最终媒体文件转录
        transcript_text = await transcribe_media(request.file_path)
        
        # 2. 调用大模型：强制抽离并生成技术精锐问答组
        analysis_data = await analyze_interview(transcript_text)
        
        # 3. SQLAlchemy 持久层安全写库：面试本体 -> 录音副表 -> 回调分析表
        new_interview = Interview(user_id="root_copilot_demo_user")
        db.add(new_interview)
        db.commit()
        db.refresh(new_interview)
        
        new_transcript = Transcript(
            interview_id=new_interview.id,
            content=transcript_text,
            raw_text=transcript_text
        )
        db.add(new_transcript)
        
        # 直接把 JSON 的 list 深层打包到 text 字段存档（满足 PRD 文档要求的三层列簇）
        new_analysis = AnalysisResult(
            interview_id=new_interview.id,
            score=analysis_data.get("overall_score", 0),
            feedback=analysis_data.get("overall_feedback", ""),
            improved_answer=json.dumps(analysis_data.get("qa_list", []), ensure_ascii=False)
        )
        db.add(new_analysis)
        
        # 确保全部操作提交入盘
        db.commit()
        db.refresh(new_analysis)
        
        return {
            "status": "success",
            "interview_id": new_interview.id,
            "analysis": analysis_data
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/memory/save")
async def save_personal_memory(request: MemorySaveRequest):
    """
    完全解耦的后置强化逻辑：供前端用户确认或者手动修改完美答案后，合并吸收为 LlamaIndex RAG 的长期私有化记忆。
    """
    try:
        # 魔改封装长上下文
        combined_text = f"【曾经的受挫面经/问题】\n{request.question}\n\n【我的完美纠正回答策略】\n{request.improved_answer}"
        
        await ingest_text(
            text=combined_text, 
            source_type="personal_memory" # 最重要的源绑定锚点
        )
        
        return {
            "status": "success",
            "message": "这份知识点已经彻底融入私密矩阵！未来的 Agent 遇到类似的场景会瞬间唤醒这份回忆来协助您。"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
