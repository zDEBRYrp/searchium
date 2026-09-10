"""
File Indexer component (optimized with batch upserts)
"""

import hashlib
import mimetypes
import os
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

from searchium.api.models.operations import CrawlOperation, OperationType
from searchium.core.logging import logger
from searchium.services.extraction.extractor import get_extractor
from searchium.services.typesense_client import get_typesense_client

BATCH_SIZE = 200


class FileIndexer:
    """
    Handles indexing of files with batch optimization.
    """

    def __init__(self):
        self.typesense = get_typesense_client()
        self.extractor = get_extractor()
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def reset(self):
        self._stop_event.clear()

    def index_file(
        self, operation: CrawlOperation, progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        if self._stop_event.is_set():
            return False

        if operation.operation == OperationType.DELETE:
            return self._handle_delete_operation(operation)
        else:
            return self._handle_create_edit_operation(operation, progress_callback)

    def _handle_create_edit_operation(
        self, operation: CrawlOperation, progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        file_path = operation.file_path

        if not self._check_file_accessibility(file_path)[0]:
            return False

        max_size_mb = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
        max_size_bytes = max_size_mb * 1024 * 1024
        if operation.file_size and operation.file_size > max_size_bytes:
            return False

        # Fast change detection: use mtime + size instead of MD5
        try:
            stat = os.stat(file_path)
            mtime = int(stat.st_mtime)
            fsize = stat.st_size
        except OSError:
            return False

        existing_doc = self.typesense.get_doc_by_path(file_path)
        if existing_doc:
            existing_mtime = existing_doc.get("modified_time", 0)
            existing_size = existing_doc.get("file_size", 0)
            if existing_mtime == mtime and existing_size == fsize:
                return True

        # Extract content
        document_content = self.extractor.extract(file_path)

        # Chunking
        from searchium.services.chunker import chunk_text, generate_chunk_hash, get_chunk_config

        chunk_size, overlap = get_chunk_config()
        content_chunks = chunk_text(document_content.content, chunk_size, overlap)
        total_chunks = len(content_chunks)

        # Build all documents for this file
        documents = []
        file_hash = f"{mtime}_{fsize}"
        file_ext = Path(file_path).suffix.lower()
        mime_type = document_content.metadata.get("mime_type") or mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        modified_time = int(operation.modified_time) if operation.modified_time is not None else mtime
        created_time = int(operation.created_time) if operation.created_time is not None else 0

        meta = document_content.metadata or {}
        title = meta.get("title", "") or ""
        description = meta.get("description", "") or ""
        author = meta.get("author", "") or ""
        subject = meta.get("subject", "") or ""
        keywords = meta.get("keywords", []) or []
        comments = meta.get("comments", "") or ""
        revision = meta.get("revision", "") or ""
        doc_created = meta.get("created_date", "") or ""
        doc_modified = meta.get("modified_date", "") or ""
        now_ms = int(__import__("time").time() * 1000)

        for chunk_index, chunk_content in enumerate(content_chunks):
            chunk_hash = generate_chunk_hash(file_path, chunk_index, chunk_content)
            doc_id = f"{file_path}_{chunk_index}"
            documents.append({
                "id": doc_id,
                "file_path": file_path,
                "file_name": Path(file_path).name,
                "content": chunk_content,
                "chunk_index": chunk_index,
                "chunk_total": total_chunks,
                "chunk_hash": chunk_hash,
                "file_extension": file_ext,
                "file_size": fsize,
                "mime_type": mime_type,
                "modified_time": modified_time,
                "created_time": created_time,
                "file_hash": file_hash,
                "title": title,
                "description": description,
                "author": author,
                "subject": subject,
                "keywords": keywords,
                "comments": comments,
                "revision": revision,
                "document_created_date": doc_created,
                "document_modified_date": doc_modified,
                "content_type": mime_type,
                "indexed_at": now_ms,
            })

        # Bulk upsert in one API call
        result = self.typesense.bulk_index_chunks(documents)
        if not result.get("success"):
            logger.warning(f"Partial indexing for {file_path}: {result.get('indexed', 0)}/{total_chunks}")
        return True

    def _handle_delete_operation(self, operation: CrawlOperation) -> bool:
        try:
            self.typesense.remove_from_index(operation.file_path)
            return True
        except Exception as e:
            logger.error(f"Error deleting {operation.file_path} from index: {e}")
            return False

    def _check_file_accessibility(self, file_path: str) -> Tuple[bool, str]:
        if not os.path.exists(file_path):
            return False, "File does not exist"
        if not os.path.isfile(file_path):
            return False, "Path is not a file"
        if not os.access(file_path, os.R_OK):
            return False, "File is not readable"
        return True, "File is accessible"
