import os
import logging
import chromadb
from chromadb.utils import embedding_functions
from typing import Optional, Dict, Any

logger = logging.getLogger("AI_COACH")

class RagMemory:
    """
    Retrieval-Augmented Generation (RAG) Memory module.
    Sử dụng Local AI Model để chạy 100% offline trên máy chủ cục bộ.
    """
    def __init__(self, db_path: str = "data/chroma_db"):
        self.client = chromadb.PersistentClient(path=db_path)
        
        # Kích hoạt Local AI Model tích hợp sẵn của Chroma (Không cần Google API)
        self.embed_fn = embedding_functions.DefaultEmbeddingFunction()
        
        # Tạo bảng bộ nhớ mới (os_local_memory) để tương thích với model cục bộ
        self.collection = self.client.get_or_create_collection(
            name="os_local_memory",
            embedding_function=self.embed_fn
        )
        logger.info(f"[RAG] Memory Center loaded using Local AI Embeddings at {db_path}")

    def memorize(self, doc_id: str, content: str, domain: str, extra_meta: Optional[Dict[str, Any]] = None):
        """Lưu trữ ký ức mới vào vector database."""
        metadata = {"domain": domain}
        if extra_meta:
            metadata.update(extra_meta)
            
        self.collection.upsert(
            documents=[content],
            metadatas=[metadata],
            ids=[doc_id]
        )
        logger.debug(f"[RAG] Successfully memorized item: {doc_id}")

    def recall(self, query: str, domain: Optional[str] = None, n_results: int = 5):
        """Hồi tưởng ký ức dựa trên câu hỏi."""
        where_clause = {"domain": domain} if domain else None
        
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_clause
        )
        return results

rag_db = RagMemory()