import logging
import torch
from llama_index.core import Settings
from llama_index.llms.openai import OpenAI
from llama_index.llms.deepseek import DeepSeek
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from app.core.config import settings

logger = logging.getLogger(__name__)

def init_rag_settings():
    """
    Initialize global LlamaIndex Settings.
    """
    try:
        # 1. 动态检测设备
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Detecting hardware: Using {device.upper()} for embeddings.")

        # LLM configured to use DeepSeek using OpenAI compatible class
        llm = DeepSeek(
            model="deepseek-reasoner",
            api_key=settings.DEEPSEEK_API_KEY
        )
        
        # BAAI BGE embedding model from HuggingFace
        embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-zh-v1.5",device=device)
        
        # Apply configurations globally
        Settings.llm = llm
        Settings.embed_model = embed_model
        
        logger.info("RAG Settings successfully initialized with DeepSeek and HuggingFaceEmbedding.")
    except Exception as e:
        logger.error(f"Failed to initialize RAG settings: {e}")
        raise
