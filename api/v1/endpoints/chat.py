"""
Chat & Similar Files API endpoints
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None
    stream: bool = False


class SimilarRequest(BaseModel):
    file_path: str
    limit: int = 10


@router.post("")
def chat_with_files(req: ChatRequest):
    """Chat with your indexed files using RAG"""
    from searchium.services.chat_service import get_chat_service

    service = get_chat_service()
    result = service.chat(
        message=req.message,
        history=req.history,
        stream=req.stream,
    )
    return result


@router.post("/similar")
def find_similar(req: SimilarRequest):
    """Find files similar to a given file using semantic embeddings"""
    try:
        from searchium.services.typesense_client import get_typesense_client
        client = get_typesense_client()
        result = client.find_similar(req.file_path, limit=req.limit)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
