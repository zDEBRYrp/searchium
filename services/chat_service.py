"""
Chat with Files - RAG pipeline using LLM + Typesense search

Provides conversational AI over indexed documents.
Supports OpenAI, Anthropic, or any OpenAI-compatible API.
"""

import json
import os
from typing import Any, Dict, Generator, Optional

from searchium.core.logging import logger


class ChatService:
    """RAG-based chat over indexed files."""

    def __init__(self):
        self._client = None
        self._provider = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        openai_key = os.getenv("OPENAI_API_KEY", "")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        chat_model = os.getenv("CHAT_MODEL", "")

        if chat_model or openai_key:
            try:
                import httpx
                self._provider = "openai"
                self._api_key = openai_key
                self._base_url = openai_base
                self._model = chat_model or "gpt-4o-mini"
                self._client = True
                logger.info(f"Chat using OpenAI-compatible API: {self._model}")
                return self._client
            except Exception as e:
                logger.error(f"Failed to init OpenAI client: {e}")

        if anthropic_key:
            try:
                import httpx
                self._provider = "anthropic"
                self._api_key = anthropic_key
                self._model = os.getenv("CHAT_MODEL", "claude-sonnet-4-20250514")
                self._client = True
                logger.info(f"Chat using Anthropic: {self._model}")
                return self._client
            except Exception as e:
                logger.error(f"Failed to init Anthropic client: {e}")

        logger.warning("No LLM API key configured. Chat requires OPENAI_API_KEY or ANTHROPIC_API_KEY")
        self._client = False
        return self._client

    def _search_context(self, query: str, max_results: int = 5) -> str:
        """Search Typesense for relevant context"""
        try:
            from searchium.services.typesense_client import get_typesense_client
            client = get_typesense_client()

            results = client.client.collections[client.collection_name].documents.search(
                {
                    "q": query,
                    "query_by": "content,title,description,subject,keywords",
                    "per_page": max_results,
                    "include_fields": "file_path,file_name,content,chunk_index",
                }
            )

            context_parts = []
            for hit in results.get("hits", []):
                doc = hit.get("document", {})
                file_name = doc.get("file_name", "unknown")
                content = doc.get("content", "")[:2000]
                context_parts.append(f"[{file_name}]: {content}")

            return "\n\n".join(context_parts) if context_parts else "No relevant documents found."
        except Exception as e:
            logger.error(f"Context search error: {e}")
            return "Error searching documents."

    def chat(
        self,
        message: str,
        history: Optional[list] = None,
        stream: bool = False,
    ) -> Any:
        """Chat with files using RAG"""
        client = self._get_client()
        if not client:
            return {"error": "No LLM API configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."}

        context = self._search_context(message)

        system_prompt = (
            "You are a helpful assistant that answers questions about the user's files. "
            "Use the provided document context to answer questions. "
            "If the context doesn't contain relevant information, say so. "
            "Always cite which file(s) you're referencing.\n\n"
            f"Document context:\n{context}"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history[-10:]:
                messages.append(msg)
        messages.append({"role": "user", "content": message})

        try:
            import httpx

            if self._provider == "openai":
                with httpx.Client(timeout=60) as c:
                    resp = c.post(
                        f"{self._base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={"model": self._model, "messages": messages, "stream": stream},
                    )
                    resp.raise_for_status()

                    if stream:
                        return self._stream_openai(resp)

                    data = resp.json()
                    return {"response": data["choices"][0]["message"]["content"]}

            elif self._provider == "anthropic":
                with httpx.Client(timeout=60) as c:
                    resp = c.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": self._api_key,
                            "anthropic-version": "2023-06-01",
                        },
                        json={
                            "model": self._model,
                            "max_tokens": 4096,
                            "system": system_prompt,
                            "messages": [{"role": "user", "content": message}],
                            "stream": stream,
                        },
                    )
                    resp.raise_for_status()

                    if stream:
                        return self._stream_anthropic(resp)

                    data = resp.json()
                    return {"response": data["content"][0]["text"]}

        except Exception as e:
            logger.error(f"Chat error: {e}")
            return {"error": str(e)}

    def _stream_openai(self, resp) -> Generator:
        for line in resp.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except Exception:
                    continue

    def _stream_anthropic(self, resp) -> Generator:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "content_block_delta":
                        yield event.get("delta", {}).get("text", "")
                except Exception:
                    continue


_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
