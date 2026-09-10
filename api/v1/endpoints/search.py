"""
Unified Search API endpoint
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    page: int = 1
    per_page: int = 10
    filter_by: Optional[str] = None
    sort_by: str = "modified_time:desc"
    semantic: bool = False


@router.post("")
def search_files(req: SearchRequest):
    """Search indexed files with fuzzy + semantic matching"""
    try:
        from searchium.services.typesense_client import get_typesense_client
        client = get_typesense_client()
        results = client.search_files(
            query=req.query,
            page=req.page,
            per_page=req.per_page,
            filter_by=req.filter_by,
            sort_by=req.sort_by,
            semantic=req.semantic,
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def search_files_get(
    q: str = "",
    page: int = 1,
    per_page: int = 10,
    semantic: bool = False,
):
    """Search indexed files (GET)"""
    try:
        from searchium.services.typesense_client import get_typesense_client
        client = get_typesense_client()
        results = client.search_files(
            query=q,
            page=page,
            per_page=per_page,
            semantic=semantic,
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
