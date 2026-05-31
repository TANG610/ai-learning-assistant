"""
LangChain-backed RAG chain for the chat endpoint.

This module keeps LangChain as a thin orchestration layer. Retrieval, user
scoping, reranking, and source metadata still come from the existing services.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

import config
from models.database import ConversationDAO, DocumentDAO
from services.claude_service import LLMService, get_current_model
from services.document_service import DocumentService


def get_doc_name(doc_id):
    if not doc_id:
        return "Unknown document"
    try:
        doc = DocumentDAO.get_by_id(doc_id)
        if not doc:
            return f"Document {doc_id}"
        return doc.get("title") or doc.get("filename") or f"Document {doc_id}"
    except Exception:
        return f"Document {doc_id}"


@dataclass
class HybridRetrieverAdapter:
    """Adapter from the local hybrid retriever to LangChain document inputs."""

    document_id: Optional[int] = None
    top_k: int = field(default_factory=lambda: config.RAG_TOP_K)
    user_id: Optional[int] = None
    score_threshold: float = field(default_factory=lambda: config.RAG_SCORE_THRESHOLD)
    context_max_chars: int = field(default_factory=lambda: config.RAG_CONTEXT_MAX_CHARS)
    doc_name_resolver: Callable[[Any], str] = get_doc_name

    last_raw_results: list[dict[str, Any]] = field(default_factory=list, init=False)
    last_sources: list[dict[str, Any]] = field(default_factory=list, init=False)
    last_debug: dict[str, Any] = field(default_factory=dict, init=False)

    def search(self, query: str, document_cls=None) -> list[Any]:
        raw_results = DocumentService.hybrid_search_documents(
            query,
            self.document_id,
            top_k=self.top_k,
            user_id=self.user_id,
        )
        self.last_raw_results = raw_results
        self.last_sources = []
        docs = []
        accepted_chars = 0

        for rank, item in enumerate(raw_results, start=1):
            source = self._source_from_result(rank, item)
            self.last_debug.setdefault("results", [])
            self.last_debug["results"].append(source)

            if not source["accepted"]:
                continue
            if accepted_chars >= self.context_max_chars:
                source["accepted"] = False
                source["reason"] = "context_limit"
                continue

            content = item.get("text") or ""
            remaining = max(0, self.context_max_chars - accepted_chars)
            if len(content) > remaining:
                content = content[:remaining]
                source["content"] = content
                source["char_count"] = len(content)
                source["reason"] = "truncated_to_context_limit"

            accepted_chars += len(content)
            self.last_sources.append(source)
            if document_cls is None:
                docs.append(content)
            else:
                docs.append(document_cls(page_content=content, metadata=self._metadata_from_source(source)))

        self.last_debug = self.build_debug(query)
        return docs

    def as_langchain_retriever(self):
        modules = load_langchain_modules()
        Document = modules["Document"]
        RunnableLambda = modules["RunnableLambda"]

        def retrieve(inputs):
            if isinstance(inputs, dict):
                query = inputs.get("input") or inputs.get("question") or inputs.get("query") or ""
            else:
                query = str(inputs or "")
            return self.search(query, document_cls=Document)

        return RunnableLambda(retrieve)

    def build_debug(self, query: str, fallback_reason: str = None) -> dict[str, Any]:
        debug = {
            "query": query,
            "document_id": self.document_id,
            "search_scope": "all_documents" if self.document_id is None else "single_document",
            "top_k": self.top_k,
            "score_threshold": self.score_threshold,
            "context_max_chars": self.context_max_chars,
            "rag_engine": "langchain",
            "results": [
                self._source_from_result(rank, item)
                for rank, item in enumerate(self.last_raw_results, start=1)
            ],
            "accepted_count": len(self.last_sources),
        }
        if fallback_reason:
            debug["fallback_reason"] = fallback_reason
        return debug

    def _source_from_result(self, rank: int, item: dict[str, Any]) -> dict[str, Any]:
        score = float(item.get("score") or 0)
        accepted = score > self.score_threshold
        text = item.get("text") or ""
        return {
            "rank": rank,
            "doc_id": item.get("doc_id"),
            "doc_name": self.doc_name_resolver(item.get("doc_id")),
            "chunk_index": item.get("chunk_index"),
            "title_path": item.get("title_path") or "",
            "score": score,
            "rerank_score": item.get("rerank_score", score),
            "vector_score": item.get("vector_score"),
            "keyword_score": item.get("keyword_score"),
            "bm25_score": item.get("bm25_score"),
            "retrieval_sources": item.get("retrieval_sources", []),
            "matched_terms": item.get("matched_terms", []),
            "distance": item.get("distance"),
            "accepted": accepted,
            "reason": "sent_to_llm" if accepted else "below_threshold",
            "char_count": len(text),
            "preview": text[:180].replace("\n", " "),
            "content": text,
        }

    @staticmethod
    def _metadata_from_source(source: dict[str, Any]) -> dict[str, Any]:
        return {
            "doc_id": source.get("doc_id"),
            "doc_name": source.get("doc_name"),
            "chunk_index": source.get("chunk_index"),
            "title_path": source.get("title_path") or "",
            "score": source.get("score"),
            "rerank_score": source.get("rerank_score"),
            "vector_score": source.get("vector_score"),
            "keyword_score": source.get("keyword_score"),
            "bm25_score": source.get("bm25_score"),
            "retrieval_sources": source.get("retrieval_sources", []),
            "matched_terms": source.get("matched_terms", []),
            "distance": source.get("distance"),
        }


class RagChainService:
    """LangChain RAG facade used by chat routes."""

    def __init__(self, llm_service: LLMService = None):
        self.llm_service = llm_service or LLMService()

    def answer(self, conversation_id: int, user_message: str, document_id: int = None, user_id: int = None) -> dict[str, Any]:
        modules = load_langchain_modules()
        chain, retriever = self._build_chain(modules, document_id, user_id)
        result = chain.invoke({
            "input": user_message,
            "chat_history": self._history_messages(modules, conversation_id),
        })
        reply = coerce_content(result.get("answer", ""))
        ConversationDAO.add_message(conversation_id, "user", user_message, user_id=user_id)
        ConversationDAO.add_message(
            conversation_id,
            "assistant",
            reply,
            source_chunks=[source.get("content", "") for source in retriever.last_sources],
            user_id=user_id,
        )
        return {
            "reply": reply,
            "sources": retriever.last_sources,
            "source_count": len(retriever.last_sources),
            "retrieval_debug": retriever.build_debug(user_message),
        }

    def answer_stream(self, conversation_id: int, user_message: str, document_id: int = None, user_id: int = None) -> Iterable[dict[str, Any]]:
        modules = load_langchain_modules()
        chain, retriever = self._build_chain(modules, document_id, user_id)
        full_reply = ""
        for chunk in chain.stream({
            "input": user_message,
            "chat_history": self._history_messages(modules, conversation_id),
        }):
            piece = extract_answer_chunk(chunk)
            if piece:
                full_reply += piece
                yield {"chunk": piece}

        ConversationDAO.add_message(conversation_id, "user", user_message, user_id=user_id)
        ConversationDAO.add_message(
            conversation_id,
            "assistant",
            full_reply,
            source_chunks=[source.get("content", "") for source in retriever.last_sources],
            user_id=user_id,
        )
        yield {
            "done": True,
            "sources": retriever.last_sources,
            "retrieval_debug": retriever.build_debug(user_message),
        }

    def _build_chain(self, modules: dict[str, Any], document_id: int = None, user_id: int = None):
        retriever = HybridRetrieverAdapter(
            document_id=document_id,
            top_k=config.RAG_TOP_K,
            user_id=user_id,
            score_threshold=config.RAG_SCORE_THRESHOLD,
            context_max_chars=config.RAG_CONTEXT_MAX_CHARS,
        )
        prompt = modules["ChatPromptTemplate"].from_messages([
            ("system", self._system_prompt()),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
        ])
        qa_chain = modules["create_stuff_documents_chain"](self._chat_model(modules), prompt)
        chain = modules["create_retrieval_chain"](retriever.as_langchain_retriever(), qa_chain)
        return chain, retriever

    def _chat_model(self, modules: dict[str, Any]):
        provider = resolve_current_provider()
        if not provider.get("api_key"):
            raise RuntimeError("LLM API key is not configured")
        return modules["ChatOpenAI"](
            api_key=provider["api_key"],
            base_url=provider["base_url"],
            model=provider["model"],
            max_tokens=provider["max_tokens"],
            temperature=float(provider.get("temperature", 0.7)),
        )

    def _history_messages(self, modules: dict[str, Any], conversation_id: int):
        messages = []
        for item in ConversationDAO.get_messages(conversation_id):
            role = item.get("role")
            content = item.get("content") or ""
            if role == "user":
                messages.append(modules["HumanMessage"](content=content))
            elif role == "assistant":
                messages.append(modules["AIMessage"](content=content))
            elif role == "system":
                messages.append(modules["SystemMessage"](content=content))
        return messages

    def _system_prompt(self) -> str:
        return (
            self.llm_service.system_prompt
            + "\n\nUse the retrieved context to answer the user. If the context is insufficient, say so clearly.\n\n{context}"
        )


def load_langchain_modules() -> dict[str, Any]:
    try:
        from langchain.chains.combine_documents import create_stuff_documents_chain
        from langchain.chains.retrieval import create_retrieval_chain
        from langchain_core.documents import Document
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.runnables import RunnableLambda
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        raise RuntimeError(f"LangChain RAG dependencies are unavailable: {exc}") from exc

    return {
        "AIMessage": AIMessage,
        "ChatOpenAI": ChatOpenAI,
        "ChatPromptTemplate": ChatPromptTemplate,
        "Document": Document,
        "HumanMessage": HumanMessage,
        "RunnableLambda": RunnableLambda,
        "SystemMessage": SystemMessage,
        "create_retrieval_chain": create_retrieval_chain,
        "create_stuff_documents_chain": create_stuff_documents_chain,
    }


def resolve_current_provider() -> dict[str, Any]:
    current = get_current_model()
    for provider in config.MODEL_PROVIDERS or []:
        provider_id = provider.get("name", "").lower().replace(" ", "-")
        if provider_id == current:
            return {
                "api_key": provider.get("api_key", ""),
                "base_url": provider.get("base_url", ""),
                "model": provider.get("model", current),
                "max_tokens": config.LLM_MAX_TOKENS if provider.get("type", "text") == "text" else 4096,
            }

    return {
        "api_key": config.LLM_API_KEY,
        "base_url": config.LLM_BASE_URL,
        "model": current or config.LLM_MODEL,
        "max_tokens": config.LLM_MAX_TOKENS,
    }


def extract_answer_chunk(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return coerce_content(chunk.get("answer", ""))
    return coerce_content(chunk)


def coerce_content(value: Any) -> str:
    if value is None:
        return ""
    content = getattr(value, "content", None)
    if content is not None:
        return str(content)
    return str(value)
