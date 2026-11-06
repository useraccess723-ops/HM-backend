"""
LangChain Document Processing and Persistent Chunking Service for StayFlow.

This service utilizes LangChain text splitters to split documents into structured,
searchable chunks and persistently saves them to the SQL database with full
relational integrity, deduplication, persistent vector embeddings, and strict tenant isolation.
"""

import hashlib
import io
import json
import logging
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, delete, and_, or_, func
from sqlalchemy.orm import Session

from langchain_core.documents import Document as LCDocument
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    CharacterTextSplitter,
    TokenTextSplitter,
)

from app.models.entities import KnowledgeDocument, DocumentChunk

logger = logging.getLogger("stayflow.langchain")

def utcnow():
    return datetime.now(timezone.utc)

def compute_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def extract_llm_response_text(response: Any) -> str:
    """Safely extracts text content from an LLM response (AIMessage, str, or dict)."""
    if response is None:
        return ""
    raw = getattr(response, "content", response)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                val = item.get("text") or item.get("content") or ""
                parts.append(str(val))
            elif hasattr(item, "text") and isinstance(item.text, str):
                parts.append(item.text)
            elif item is not None:
                parts.append(str(item))
        return "".join(parts).strip()
    if hasattr(raw, "text") and isinstance(raw.text, str):
        return raw.text
    return str(raw).strip() if raw is not None else ""

def generate_embedding_vector(text: str, dimensions: int = 64) -> List[float]:
    """
    Generate a deterministic normalized vector embedding for persistent storage and cosine similarity.
    This provides lightweight, persistent vector similarity search stored directly in SQL
    without requiring external paid vector database credentials or proprietary APIs.
    """
    if not text:
        return [0.0] * dimensions
    
    # Tokenize words and character 3-grams
    clean_text = text.lower().strip()
    words = re.findall(r"\w+", clean_text)
    
    vec = [0.0] * dimensions
    for i, word in enumerate(words):
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
        idx = h % dimensions
        weight = 1.0 + (1.0 / (1.0 + math.log(i + 1)))
        vec[idx] += weight
    
    # Character n-grams for typo tolerance
    for i in range(len(clean_text) - 2):
        trigram = clean_text[i:i+3]
        h = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16)
        idx = h % dimensions
        vec[idx] += 0.35

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [round(v / norm, 6) for v in vec]
    return vec

def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Calculate cosine similarity between two normalized vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    return max(0.0, min(1.0, dot))

class DocumentChunkingService:
    """Encapsulates LangChain text splitting and SQL database persistence."""

    @staticmethod
    def get_text_splitter(
        splitter_type: str = "recursive",
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        separators: Optional[List[str]] = None,
    ):
        """Build and configure the appropriate LangChain text splitter."""
        if separators is None:
            separators = ["\n\n", "\n", ". ", " ", ""]

        if splitter_type == "character":
            return CharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=separators[0] if separators else "\n\n",
            )
        elif splitter_type == "token":
            try:
                return TokenTextSplitter(
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            except Exception:
                pass  # Fall back to recursive if tokenizer library is absent

        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
            length_function=len,
        )

    @classmethod
    def process_and_persist_document(
        cls,
        db: Session,
        tenant_id: int,
        title: str,
        content: str,
        document_id: Optional[str] = None,
        source_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
        hotel_id: int = 1,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        splitter_type: str = "recursive",
        separators: Optional[List[str]] = None,
    ) -> Tuple[KnowledgeDocument, List[DocumentChunk]]:
        """
        Processes a document with LangChain, chunks it, and saves both document and all chunks
        persistently in the SQL database. Re-processing an existing document replaces its previous
        chunks to prevent duplicates.
        """
        if not title or not title.strip():
            raise ValueError("Document title cannot be empty")
        if not content or not content.strip():
            raise ValueError("Document content cannot be empty")

        clean_title = title.strip()
        clean_content = content.strip()
        doc_hash = compute_sha256(clean_content)
        meta_dict = metadata or {}

        # Generate or normalize document_id
        if not document_id or not document_id.strip():
            doc_uuid = uuid.uuid4().hex[:8].upper()
            document_id = f"DOC-{doc_uuid}"
        else:
            document_id = document_id.strip()

        chunk_config = {
            "splitter_type": splitter_type,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "separators": separators or ["\n\n", "\n", ". ", " ", ""],
        }

        # 1. Check if document already exists for this tenant
        doc_record = db.scalar(
            select(KnowledgeDocument).where(
                and_(
                    KnowledgeDocument.tenant_id == tenant_id,
                    KnowledgeDocument.document_id == document_id,
                )
            )
        )

        if doc_record:
            # Update existing document attributes
            doc_record.title = clean_title
            doc_record.content = clean_content
            doc_record.content_hash = doc_hash
            doc_record.source_type = source_type
            doc_record.hotel_id = hotel_id
            doc_record.metadata_json = json.dumps(meta_dict)
            doc_record.chunking_config_json = json.dumps(chunk_config)
            doc_record.status = "Processing"
            doc_record.updated_at = utcnow()

            # Prevent duplicate chunks: atomically remove old chunks before re-inserting
            db.execute(
                delete(DocumentChunk).where(
                    and_(
                        DocumentChunk.tenant_id == tenant_id,
                        DocumentChunk.document_ref_id == doc_record.id,
                    )
                )
            )
            db.flush()
        else:
            # Create new document record in Processing state
            doc_record = KnowledgeDocument(
                tenant_id=tenant_id,
                hotel_id=hotel_id,
                document_id=document_id,
                title=clean_title,
                source_type=source_type,
                content=clean_content,
                content_hash=doc_hash,
                chunk_count=0,
                chunking_config_json=json.dumps(chunk_config),
                metadata_json=json.dumps(meta_dict),
                status="Processing",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(doc_record)
            db.flush()  # generates doc_record.id

        try:
            # 2. Split using LangChain
            splitter = cls.get_text_splitter(
                splitter_type=splitter_type,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=separators,
            )

            lc_doc = LCDocument(
                page_content=clean_content,
                metadata={
                    "document_id": document_id,
                    "title": clean_title,
                    "source_type": source_type,
                    "tenant_id": tenant_id,
                    **meta_dict,
                },
            )

            lc_chunks = splitter.split_documents([lc_doc])

            if not lc_chunks:
                doc_record.status = "Failed"
                doc_record.chunk_count = 0
                db.commit()
                raise ValueError(f"LangChain splitting produced 0 chunks for document '{document_id}'.")

            # 3. Create persistent DocumentChunk records
            created_chunks: List[DocumentChunk] = []
            for idx, chunk in enumerate(lc_chunks):
                chunk_text = chunk.page_content.strip()
                if not chunk_text:
                    continue

                chunk_id = f"{document_id}-CHK-{idx:04d}"
                token_count = len(re.findall(r"\w+", chunk_text))
                
                # Persistent embedding for vector search
                embedding_vec = generate_embedding_vector(chunk_text)
                if not embedding_vec or len(embedding_vec) == 0:
                    raise RuntimeError(f"Embedding generation failed for chunk {chunk_id}.")
                
                chunk_metadata = {
                    **chunk.metadata,
                    "chunk_index": idx,
                    "total_chunks": len(lc_chunks),
                    "character_length": len(chunk_text),
                    "token_count": token_count,
                }

                db_chunk = DocumentChunk(
                    tenant_id=tenant_id,
                    hotel_id=hotel_id,
                    document_ref_id=doc_record.id,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    chunk_index=idx,
                    chunk_text=chunk_text,
                    token_count=token_count,
                    metadata_json=json.dumps(chunk_metadata),
                    embedding_json=json.dumps(embedding_vec),
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                db.add(db_chunk)
                created_chunks.append(db_chunk)

            if not created_chunks:
                doc_record.status = "Failed"
                doc_record.chunk_count = 0
                db.commit()
                raise ValueError(f"Document content produced 0 non-empty text chunks for '{document_id}'.")

            # Update chunk count and mark as Completed
            doc_record.chunk_count = len(created_chunks)
            doc_record.status = "Completed"
            db.commit()
            db.refresh(doc_record)

            logger.info(
                f"[LangChain] Successfully processed document '{document_id}' into {len(created_chunks)} persistent chunks for tenant {tenant_id}."
            )
            return doc_record, created_chunks
        except Exception as e:
            logger.error(f"[LangChain] Processing failed for document '{document_id}': {e}", exc_info=True)
            doc_record.status = "Failed"
            doc_record.chunk_count = 0
            db.commit()
            raise e

    @staticmethod
    def get_document(db: Session, tenant_id: int, document_id: str) -> Optional[KnowledgeDocument]:
        """Retrieve a document by ID with strict tenant isolation."""
        return db.scalar(
            select(KnowledgeDocument).where(
                and_(
                    KnowledgeDocument.tenant_id == tenant_id,
                    or_(
                        KnowledgeDocument.document_id == document_id,
                        KnowledgeDocument.id == (int(document_id) if document_id.isdigit() else -1),
                    ),
                )
            )
        )

    @staticmethod
    def list_documents(
        db: Session,
        tenant_id: int,
        skip: int = 0,
        limit: int = 100,
        source_type: Optional[str] = None,
    ) -> List[KnowledgeDocument]:
        """List documents with strict tenant isolation."""
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == tenant_id)
        if source_type:
            stmt = stmt.where(KnowledgeDocument.source_type == source_type)
        stmt = stmt.order_by(KnowledgeDocument.id.desc()).offset(skip).limit(limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_document_chunks(
        db: Session,
        tenant_id: int,
        document_id: str,
    ) -> List[DocumentChunk]:
        """Retrieve all persistent chunks for a document in index order."""
        stmt = (
            select(DocumentChunk)
            .where(
                and_(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.document_id == document_id,
                )
            )
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def delete_document(db: Session, tenant_id: int, document_id: str) -> bool:
        """
        Deletes the document and all associated persistent chunks via database CASCADE.
        Guarantees strict tenant isolation.
        """
        doc = db.scalar(
            select(KnowledgeDocument).where(
                and_(
                    KnowledgeDocument.tenant_id == tenant_id,
                    or_(
                        KnowledgeDocument.document_id == document_id,
                        KnowledgeDocument.id == (int(document_id) if document_id.isdigit() else -1),
                    ),
                )
            )
        )
        if not doc:
            return False

        db.delete(doc)  # cascade deletes all related DocumentChunk records in SQL
        db.commit()
        return True

    @staticmethod
    def search_chunks(
        db: Session,
        tenant_id: int,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.1,
        document_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Performs vector similarity search across persistent document chunks
        stored in the SQL database, strictly isolated to the specified tenant.
        """
        if not query or not query.strip():
            return []

        query_vec = generate_embedding_vector(query.strip())

        stmt = select(DocumentChunk).where(DocumentChunk.tenant_id == tenant_id)
        if document_id:
            doc_str = str(document_id).strip()
            if doc_str.isdigit():
                doc_ref_val = int(doc_str)
                stmt = stmt.where(
                    or_(
                        DocumentChunk.document_ref_id == doc_ref_val,
                        DocumentChunk.document_id == doc_str,
                    )
                )
            else:
                stmt = stmt.where(DocumentChunk.document_id == doc_str)

        all_chunks = list(db.scalars(stmt).all())

        results = []
        for chunk in all_chunks:
            chunk_vec = None
            if chunk.embedding_json:
                try:
                    chunk_vec = json.loads(chunk.embedding_json)
                except Exception:
                    pass

            # Calculate cosine similarity score
            score = cosine_similarity(query_vec, chunk_vec) if chunk_vec else 0.0

            # Lexical boost for direct keyword hits
            query_lower = query.lower()
            text_lower = chunk.chunk_text.lower()
            if query_lower in text_lower:
                score = min(1.0, score + 0.3)
            else:
                q_words = [w for w in re.findall(r"\w+", query_lower) if len(w) > 2]
                if q_words:
                    matches = sum(1 for w in q_words if w in text_lower)
                    score = min(1.0, score + (matches / len(q_words)) * 0.2)

            if score >= min_similarity:
                try:
                    meta = json.loads(chunk.metadata_json) if chunk.metadata_json else {}
                except Exception:
                    meta = {}

                results.append({
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                    "chunk_text": chunk.chunk_text,
                    "score": round(score, 4),
                    "token_count": chunk.token_count,
                    "metadata": meta,
                    "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
                })

        # Sort by similarity score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

    @classmethod
    def extract_text_from_file_bytes(cls, file_bytes: bytes, filename: str) -> str:
        """
        Extracts raw text content from uploaded files across supported formats:
        .pdf, .docx, .txt, .md, .csv, .json.
        """
        if not file_bytes:
            raise ValueError("Uploaded file is empty.")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in cls.ALLOWED_EXTENSIONS:
            allowed_str = ", ".join(sorted(cls.ALLOWED_EXTENSIONS))
            raise ValueError(f"Unsupported file format '{ext}'. Supported formats: {allowed_str}")

        text = ""
        if ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                pages_text = []
                for i, page in enumerate(reader.pages):
                    pt = page.extract_text()
                    if pt and pt.strip():
                        pages_text.append(pt.strip())
                text = "\n\n".join(pages_text)
            except Exception as e:
                raise ValueError(f"Failed to extract text from PDF '{filename}': {str(e)}")

        elif ext == ".docx":
            try:
                import docx
                doc = docx.Document(io.BytesIO(file_bytes))
                paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                text = "\n\n".join(paras)
            except Exception as e:
                raise ValueError(f"Failed to extract text from Word document '{filename}': {str(e)}")

        elif ext in {".txt", ".md", ".csv", ".json"}:
            try:
                text = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = file_bytes.decode("latin-1", errors="replace")

        text = text.strip()
        if not text:
            raise ValueError(f"No readable text could be extracted from '{filename}'.")

        return text

    @staticmethod
    def check_duplicate_document(
        db: Session,
        tenant_id: int,
        content_hash: str,
    ) -> Optional[KnowledgeDocument]:
        """
        Detects if an identical document (by SHA-256 content hash) has already been processed for this tenant.
        """
        return db.scalar(
            select(KnowledgeDocument).where(
                and_(
                    KnowledgeDocument.tenant_id == tenant_id,
                    KnowledgeDocument.content_hash == content_hash,
                )
            )
        )

    @classmethod
    def generate_rag_answer(
        cls,
        db: Session,
        tenant_id: int,
        question: str,
        document_id: Optional[str] = None,
        limit: int = 6,
        min_similarity: float = 0.05,
    ) -> Dict[str, Any]:
        """
        Executes the complete RAG answer generation pipeline:
        1. Retrieve top matching persisted chunks from SQL for this tenant.
        2. Build structured, grounded context.
        3. Determine if relevant chunks contain enough information to answer the question.
        4. Synthesize a single clear, natural, polite, guest-facing response using the configured LLM (or grounded conversational synthesizer).
        5. Strictly omit raw chunks, 'Customer:' prefixes, [Source X] brackets, and chunk IDs from the guest-facing answer.
        6. Return separate sources array for the Knowledge Sources audit section.
        """
        clean_q = (question or "").strip()
        unavailable_statement = (
            "I’m sorry, I can’t confirm that information from the hotel's approved knowledge documents at the moment. "
            "I can arrange for the hotel team to verify it for you."
        )

        if not clean_q:
            return {
                "question": "",
                "answer": "Please enter a question to inquire about the hotel's verified services and policies.",
                "has_context": False,
                "grounded": False,
                "sources_count": 0,
                "sources": [],
                "model_used": "StayFlow AI Assistant"
            }

        # 1. Retrieve tenant-isolated chunks
        matched_chunks = cls.search_chunks(
            db=db,
            tenant_id=tenant_id,
            query=clean_q,
            limit=limit,
            min_similarity=min_similarity,
            document_id=document_id,
        )

        # 2. Check if relevant context was found
        if not matched_chunks:
            return {
                "question": clean_q,
                "answer": unavailable_statement,
                "has_context": False,
                "grounded": False,
                "sources_count": 0,
                "sources": [],
                "model_used": "StayFlow AI Assistant"
            }

        # 3. Assemble sources with document title
        sources = []
        context_blocks = []
        for i, c in enumerate(matched_chunks):
            meta = c.get("metadata", {})
            doc_title = meta.get("title") or c.get("document_id")
            sources.append({
                "source_index": i + 1,
                "document_id": c["document_id"],
                "document_title": doc_title,
                "chunk_id": c["chunk_id"],
                "chunk_index": c["chunk_index"],
                "score": c["score"],
                "token_count": c["token_count"],
                "excerpt": c["chunk_text"][:260] + ("..." if len(c["chunk_text"]) > 260 else ""),
            })
            context_blocks.append(f"[Document: {doc_title} | Chunk: {c['chunk_id']}]\n{c['chunk_text']}")

        full_context = "\n\n".join(context_blocks)

        # 4. Check for LLM API keys (Gemini / OpenAI)
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")

        answer_text = None
        grounded = False
        model_name = "StayFlow Grounded Context Engine"

        if gemini_key:
            configured_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
            system_instruction = (
                "You are the StayFlow Hotel AI Knowledge Assistant handling guest inbound call inquiries.\n"
                "Your objective is to provide a single, natural, polite, concise, and professional guest-facing response "
                "based STRICTLY and ONLY on the verified hotel knowledge context provided below.\n\n"
                "CRITICAL CONVERSATIONAL RULES:\n"
                "1. Speak naturally as a courteous hotel representative on an inbound guest call.\n"
                "2. If the context contains call scripts or dialogues with 'Customer:' and 'Agent:', extract the factual hotel information and convey the answer directly. NEVER include 'Customer:', 'Agent:', or speaker labels in your response.\n"
                "3. NEVER include raw citations or source brackets such as '[Source 1]' or chunk IDs in your response. Source attribution is displayed separately in the UI.\n"
                "4. Ground your answer strictly in the provided documents. NEVER invent hotel facilities, prices, availability, policies, timings, or services that are not supported by the retrieved content.\n"
                f"5. If the retrieved context genuinely does not contain enough information to answer the question, respond ONLY with:\n'{unavailable_statement}'\n"
                "6. When providing confirmed hotel details, close with polite hotel inbound call etiquette (e.g., asking if the guest needs more details or assistance with continuing their reservation).\n"
                "7. DO NOT mention 'MURI' anywhere in your response."
            )
            user_prompt = (
                f"Retrieved Hotel Knowledge Context:\n{full_context}\n\n"
                f"Guest Inbound Question: {clean_q}\n\n"
                "Guest-Facing Response:"
            )
            # Primary: LangChain ChatGoogleGenerativeAI
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                from langchain_core.messages import SystemMessage, HumanMessage
                llm = ChatGoogleGenerativeAI(
                    model=configured_model,
                    google_api_key=gemini_key,
                    temperature=0.1,
                    max_retries=1
                )
                messages = [
                    SystemMessage(content=system_instruction),
                    HumanMessage(content=user_prompt)
                ]
                resp = llm.invoke(messages)
                raw_resp = extract_llm_response_text(resp)
                if raw_resp and raw_resp.strip():
                    answer_text = raw_resp.strip()
                    model_name = f"Google Gemini ({configured_model})"
            except Exception as e:
                logger.warning(f"LangChain ChatGoogleGenerativeAI notice: {e}")
                # Resilient fallback across Google Gemini models
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=gemini_key)
                    for target_m in ["gemini-3.1-flash-lite", "gemini-3.5-flash", configured_model]:
                        try:
                            model = genai.GenerativeModel(target_m)
                            full_genai_prompt = f"{system_instruction}\n\n{user_prompt}"
                            resp = model.generate_content(full_genai_prompt)
                            if resp and resp.text:
                                raw_resp = resp.text.strip()
                                if raw_resp:
                                    answer_text = raw_resp
                                    model_name = f"Google Gemini ({target_m})"
                                    break
                        except Exception as m_err:
                            logger.warning(f"Gemini {target_m} attempt notice: {m_err}")
                except Exception as e2:
                    logger.warning(f"Direct Gemini fallback notice: {e2}")

        if not answer_text and openai_key:
            try:
                import httpx
                resp = httpx.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are the StayFlow Hotel AI Knowledge Assistant. Speak as a courteous hotel representative on an inbound call. "
                                    "Ground your answer STRICTLY in the provided context. Do NOT invent information. "
                                    "Never include raw source tags like '[Source 1]' or dialogue labels like 'Customer:' or 'Agent:' in your answer. "
                                    f"If the context does not answer the question, reply with: '{unavailable_statement}'"
                                )
                            },
                            {"role": "user", "content": f"Context:\n{full_context}\n\nGuest Question: {clean_q}"}
                        ],
                        "temperature": 0.2
                    },
                    timeout=20
                )
                if resp.status_code == 200:
                    answer_text = resp.json()["choices"][0]["message"]["content"].strip()
                    model_name = "OpenAI GPT-4o-mini"
            except Exception as e:
                logger.warning(f"OpenAI generation fallback notice: {e}")

        # Grounded conversational synthesizer fallback if no external LLM key is configured
        if not answer_text:
            answer_text, grounded = cls._synthesize_grounded_answer(clean_q, matched_chunks)
            model_name = "StayFlow Grounded Context Engine"
        else:
            # Check if LLM signaled unavailable
            lower_ans = answer_text.lower()
            if any(phrase in lower_ans for phrase in [
                "cannot confirm", "can't confirm", "not available", "do not contain",
                "does not contain", "cannot find", "unable to find", "unconfirmed"
            ]):
                grounded = False
                answer_text = unavailable_statement
                sources = []
            else:
                grounded = True

        # Sanitize answer text (removes any [Source 1], 'Customer:', 'Agent:', 'MURI', etc.)
        answer_text = cls._sanitize_conversational_answer(answer_text)

        # If not grounded, do not expose unrelated sources
        if not grounded:
            sources = []

        return {
            "question": clean_q,
            "answer": answer_text,
            "has_context": bool(sources),
            "grounded": grounded,
            "sources_count": len(sources),
            "sources": sources,
            "model_used": model_name,
        }

    @classmethod
    def _sanitize_conversational_answer(cls, text: str) -> str:
        """
        Cleans raw document syntax, script labels, internal citation codes,
        and completely removes any branding like MURI from user-facing answers.
        """
        if not text:
            return ""
        # 1. Remove bracketed citations like [Source 1], [Source 1: Title], [Chunk DOC-01]
        text = re.sub(r"\[Source\s*\d+[^\]]*\]", "", text)
        text = re.sub(r"\[Chunk\s*[^\]]*\]", "", text)
        # 2. Remove script / speaker markers like 'Customer:', 'Agent:', 'Caller:', 'Staff:'
        text = re.sub(r"(?im)^(Customer|Guest|Caller|Inquirer|User)\s*:\s*", "", text)
        text = re.sub(r"(?im)^(Agent|Staff|Representative|Assistant)\s*:\s*", "", text)
        # Also remove inline speaker labels if embedded
        text = re.sub(r"(?i)\bCustomer\s*:\s*", "", text)
        text = re.sub(r"(?i)\bAgent\s*:\s*", "", text)
        # 3. Remove MURI branding completely from user-facing answer
        text = re.sub(r"\bMURI\b", "StayFlow AI", text)
        # 4. Remove leading bullet dashes left over from concats
        text = re.sub(r"^\s*[-*•]\s*", "", text, flags=re.MULTILINE)
        # 5. Clean up multiple blank lines and extra spaces
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _synthesize_grounded_answer(
        cls,
        question: str,
        matched_chunks: List[Dict[str, Any]]
    ) -> Tuple[str, bool]:
        """
        Synthesizes a polite, natural, conversational hotel inbound call response
        strictly grounded in the retrieved chunks without hallucinations or raw syntax.
        """
        unavailable_statement = (
            "I’m sorry, I can’t confirm that information from the hotel's approved knowledge documents at the moment. "
            "I can arrange for the hotel team to verify it for you."
        )

        q_lower = question.lower().strip()
        stop_words = {
            "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
            "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "can", "could", "should", "would", "will", "the",
            "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
            "with", "by", "from", "up", "about", "into", "over", "after", "hotel",
            "stayflow", "please", "tell", "me", "there", "some", "any", "i", "you"
        }
        q_keywords = [w for w in re.findall(r"\w+", q_lower) if w not in stop_words and len(w) > 2]

        # 1. Check for dialogue patterns in call script documents (e.g. Customer: ... / Agent: ...)
        dialogue_pattern = re.compile(
            r"(?:Customer|Guest|Caller|Inquirer|User)\s*:\s*(.*?)\n\s*(?:Agent|Staff|Representative|Assistant)\s*:\s*(.*?)(?=(?:\n\s*(?:Customer|Guest|Caller|Inquirer|User)\s*:|\Z))",
            re.DOTALL | re.IGNORECASE
        )

        best_dialogue_answer = None
        best_dialogue_score = 0
        for chunk in matched_chunks:
            text = chunk.get("chunk_text", "")
            for match in dialogue_pattern.finditer(text):
                cust_q = match.group(1).strip().lower()
                agent_a = match.group(2).strip()

                cust_q_words = set(re.findall(r"\w+", cust_q))
                score = 0
                for kw in q_keywords:
                    if kw in cust_q_words or kw in cust_q:
                        score += 3
                    elif kw in agent_a.lower():
                        score += 1

                # Direct phrase match bonus
                if q_lower in cust_q or cust_q in q_lower:
                    score += 6

                if score > best_dialogue_score and len(agent_a) > 15:
                    best_dialogue_score = score
                    best_dialogue_answer = agent_a

        # If a dialogue turn matched well, return the Agent's answer directly
        if best_dialogue_answer and best_dialogue_score >= 2:
            clean_answer = cls._sanitize_conversational_answer(best_dialogue_answer)
            return (clean_answer, True)

        # 2. Extract facts from non-dialogue sentences or informational sections
        scored_sentences = []
        for c_idx, chunk in enumerate(matched_chunks):
            # Clean out any script customer lines
            lines = chunk["chunk_text"].splitlines()
            cleaned_lines = []
            for l in lines:
                l_s = l.strip()
                if re.match(r"^(Customer|Guest|Caller|Inquirer|User)\s*:", l_s, re.I):
                    continue
                l_s = re.sub(r"^(Agent|Staff|Representative|Assistant)\s*:\s*", "", l_s, flags=re.I)
                if l_s:
                    cleaned_lines.append(l_s)

            clean_chunk_text = " ".join(cleaned_lines)
            raw_sentences = re.split(r"(?<=[.!?])\s+", clean_chunk_text)
            for s in raw_sentences:
                clean_s = s.strip()
                if len(clean_s) < 15 or len(clean_s) > 300:
                    continue
                s_lower = clean_s.lower()
                matches = sum(1 for kw in q_keywords if kw in s_lower)
                if matches > 0:
                    scored_sentences.append({
                        "sentence": clean_s,
                        "score": matches * (1.0 / (c_idx + 1)),
                    })

        scored_sentences.sort(key=lambda x: x["score"], reverse=True)

        # 3. If no matching facts were found, declare unavailable
        if not scored_sentences:
            return (unavailable_statement, False)

        selected_facts = []
        seen = set()
        for item in scored_sentences:
            simp = item["sentence"][:50].lower()
            if simp not in seen:
                seen.add(simp)
                selected_facts.append(item["sentence"])
            if len(selected_facts) >= 3:
                break

        facts_text = " ".join(selected_facts)
        if not facts_text.endswith((".", "!", "?")):
            facts_text += "."

        # Synthesize into a courteous inbound call answer
        natural_response = (
            f"Certainly. {facts_text} "
            "Please let me know if you would like more details about any of our facilities or if I can assist you with continuing your reservation."
        )
        return (natural_response, True)


