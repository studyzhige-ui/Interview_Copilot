import os
import logging
import chromadb
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Document
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.readers.file import PyMuPDFReader
from app.rag.embeddings import init_rag_settings

logger = logging.getLogger(__name__)

# Initialize settings (LLM and Embeddings)
init_rag_settings()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROMA_DB_DIR = os.path.join(BASE_DIR, "data", "chroma_db")

async def ingest_document(file_path: str, source_type: str):
    """
    Async document ingestion pipeline using LlamaIndex and Chroma Vector Store.
    
    Args:
        file_path (str): The absolute or relative path to the local input document.
        source_type (str): The metadata source category (e.g. 'interview_qa').
    """
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} does not exist.")
            
        logger.info(f"Loading document: {file_path}")
        # Initialize robust PDF parser to prevent garbled text
        pdf_parser = PyMuPDFReader()
        
        # Override default file extractor for PDF
        reader = SimpleDirectoryReader(
            input_files=[file_path],
            file_extractor={".pdf": pdf_parser}
        )
        documents = reader.load_data()
        
        if not documents:
            logger.warning(f"No text extracted from {file_path}")
            return False
            
        # Metadata Management: Inject source type dynamically
        for doc in documents:
            doc.metadata["source_type"] = source_type
            
        logger.info(f"Extracted {len(documents)} document fragments. Applying Metadata: source_type={source_type}")
            
        # Initialize Vector Database (Chroma) Setup
        os.makedirs(CHROMA_DB_DIR, exist_ok=True)
        db = chromadb.PersistentClient(path=CHROMA_DB_DIR)
        chroma_collection = db.get_or_create_collection("interview_copilot_rag")
        
        # Context bridging
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
        # Process vectorization and store to Chroma
        logger.info("Vectorizing chunks and saving to Persistent Chroma DB...")
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=True
        )
        
        logger.info(f"Successfully ingrained '{file_path}' into the RAG vector store.")
        return True
        
    except Exception as e:
        logger.error(f"Failed to ingest document {file_path}: {e}")
        raise

async def ingest_text(text: str, source_type: str, custom_metadata: dict = None):
    """
    接收普通格式的纯文本变量，强行包裹 Metadata 羁绊，并自动塞入底层架构的 Chroma 向量持久层。
    与 Document 接口互补，专门用于保存用户修改后的私密【记忆库】碎片。
    """
    try:
        metadata = custom_metadata or {}
        metadata["source_type"] = source_type
        
        # 生成基于基类格式的虚拟 LlamaIndex 文档结构
        doc = Document(text=text, metadata=metadata)
        
        os.makedirs(CHROMA_DB_DIR, exist_ok=True)
        db = chromadb.PersistentClient(path=CHROMA_DB_DIR)
        chroma_collection = db.get_or_create_collection("interview_copilot_rag")
        
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
        logger.info(f"Vectorizing manual memory text segment and saving to DB...")
        
        # 由索引机制进行动态词切片并获取最终 Embedding
        index = VectorStoreIndex.from_documents(
            [doc],
            storage_context=storage_context
        )
        
        logger.info(f"Text fragment successfully ingrained with security rule '{source_type}'")
        return True
    except Exception as e:
        logger.error(f"Exception triggered while ingesting raw text fragment: {e}")
        raise
