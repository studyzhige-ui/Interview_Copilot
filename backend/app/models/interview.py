from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.db.database import Base

class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    status = Column(String, default="PENDING", index=True)
    task_id = Column(String, nullable=True)
    upload_id = Column(String, ForeignKey("user_uploads.id"), nullable=True, index=True)
    resume_upload_id = Column(String, ForeignKey("user_uploads.id"), nullable=True, index=True)
    jd_text = Column(Text, nullable=True)
    file_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    upload = relationship("UserUpload", foreign_keys=[upload_id])
    resume_upload = relationship("UserUpload", foreign_keys=[resume_upload_id])
    transcripts = relationship("Transcript", back_populates="interview")
    analysis = relationship("AnalysisResult", back_populates="interview", uselist=False)

class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"))
    content = Column(Text)
    raw_text = Column(Text)

    interview = relationship("Interview", back_populates="transcripts")

class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"))
    score = Column(Float)
    feedback = Column(Text)
    improved_answer = Column(Text)

    interview = relationship("Interview", back_populates="analysis")

