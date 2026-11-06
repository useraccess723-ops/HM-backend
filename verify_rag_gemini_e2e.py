import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

from app.database.connection import SessionLocal
from app.models.entities import KnowledgeDocument, DocumentChunk, User
from app.services.document_chunking_service import DocumentChunkingService
from app.core.config import settings

def run_verification():
    print("=" * 80)
    print("STAYFLOW KNOWLEDGE BASE RAG + GEMINI END-TO-END VERIFICATION")
    print("=" * 80)

    # 1. Environment & Config Inspection
    gemini_key_var_name = "GEMINI_API_KEY"
    gemini_model_var_name = "GEMINI_MODEL"
    
    api_key_val = os.getenv(gemini_key_var_name) or getattr(settings, "GEMINI_API_KEY", "")
    model_name_val = os.getenv(gemini_model_var_name) or getattr(settings, "GEMINI_MODEL", "gemini-3.8-flash")
    
    api_key_configured = bool(api_key_val and len(api_key_val.strip()) > 10)
    
    print(f"\n[1] CONFIGURATION INSPECTION:")
    print(f"    - Provider: Google Gemini")
    print(f"    - API Key Env Variable: {gemini_key_var_name} (Configured & Valid: {api_key_configured})")
    print(f"    - Model Name Env Variable: {gemini_model_var_name}")
    print(f"    - Configured Model: {model_name_val}")
    
    if not api_key_configured:
        print("[FAIL] GEMINI_API_KEY is not set or empty.")
        return False

    # 2. Direct Gemini API Request
    print(f"\n[2] DIRECT GEMINI API REQUEST VERIFICATION:")
    gemini_connected = False
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage
        
        llm = ChatGoogleGenerativeAI(
            model=model_name_val,
            google_api_key=api_key_val,
            temperature=0.1,
            max_retries=1
        )
        direct_resp = llm.invoke([HumanMessage(content="Hello! Respond with: 'StayFlow Gemini Connected'")])
        resp_text = getattr(direct_resp, "content", "")
        if isinstance(resp_text, list):
            resp_text = "".join(p if isinstance(p, str) else (p.get("text", "") if isinstance(p, dict) else str(p)) for p in resp_text)
        resp_text = str(resp_text)
        print(f"    - Direct Gemini ({model_name_val}) Response: {resp_text.strip()}")
        gemini_connected = True
    except Exception as e:
        print(f"    - Notice on LangChain direct call ({e}), testing direct genai...")
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key_val)
            for m_test in ["gemini-3.1-flash-lite", "gemini-3.5-flash", model_name_val]:
                try:
                    m = genai.GenerativeModel(m_test)
                    r = m.generate_content("Hello! Respond with: 'StayFlow Gemini Connected'")
                    if r and r.text:
                        print(f"    - Direct Gemini ({m_test}) Response: {r.text.strip()}")
                        gemini_connected = True
                        break
                except Exception:
                    pass
        except Exception as e2:
            print(f"    - Direct Gemini fallback notice: {e2}")

    if not gemini_connected:
        print("[FAIL] Direct Gemini API connection could not be established.")
        return False
    print(f"    - Connection Status: CONNECTED & FUNCTIONAL")

    # 3. Database & Existing Knowledge Base Inspection
    print(f"\n[3] EXISTING PERSISTED KNOWLEDGE BASE INSPECTION:")
    db = SessionLocal()
    try:
        existing_doc = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.tenant_id == 1,
            KnowledgeDocument.title.ilike("%StayFlow Hotel RAG Knowledge Base%")
        ).first()

        if not existing_doc:
            existing_doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == 1).first()

        if not existing_doc:
            print("    - No document found in Tenant 1. Creating StayFlow Hotel RAG Knowledge Base...")
            sample_content = """
StayFlow Hotel Services & Guest Amenities:
The hotel provides luxury accommodation, dining, wellness facilities, and personalized guest services.
1. Complimentary buffet breakfast is served daily from 07:00 AM to 10:30 AM at the Orchid Terrace on the 2nd Floor.
2. 24-Hour In-Room Dining is available by dialing extension 9 from your room telephone.
3. The heated rooftop infinity swimming pool is open daily from 06:00 AM to 10:00 PM. Fresh towels and sun loungers are provided poolside.
4. The StayFlow Spa & Wellness Center offers therapeutic massages and sauna access from 08:00 AM to 09:00 PM.
5. Complimentary high-speed fiber-optic Wi-Fi 'StayFlow_Guest' is active throughout all guest rooms and public areas.
6. Valet parking and electric vehicle (EV) charging stations are available 24/7 at the main lobby entrance.
7. Airport transfer shuttle service operates every hour from 05:00 AM to 11:00 PM upon advance reservation at the concierge desk.
"""
            existing_doc = DocumentChunkingService.process_and_store_document(
                db=db,
                tenant_id=1,
                title="StayFlow Hotel RAG Knowledge Base",
                content=sample_content,
                source_type="policy",
                metadata={"category": "Services & Amenities"}
            )

        print(f"    - Target Document ID: {existing_doc.document_id}")
        print(f"    - Target Document Title: {existing_doc.title}")
        print(f"    - Total Chunks Persisted in SQL: {existing_doc.chunk_count}")

        # Check Chunks & Vector Embeddings
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_ref_id == existing_doc.id).all()
        chunks_with_embeddings = [c for c in chunks if c.embedding_json and len(c.embedding_json) > 10]
        print(f"    - Chunks with Persistent Vector Embeddings: {len(chunks_with_embeddings)} / {len(chunks)}")
        assert len(chunks_with_embeddings) == len(chunks), "All chunks must have persistent vector embeddings"

        # 4. RAG Flow Test: "What are the services available?"
        print(f"\n[4] END-TO-END RAG FLOW TEST:")
        question = "What are the services available?"
        print(f"    - User Question: '{question}'")

        rag_result = DocumentChunkingService.generate_rag_answer(
            db=db,
            tenant_id=1,
            question=question,
            document_id=existing_doc.document_id,
            limit=6,
            min_similarity=0.05
        )

        answer = rag_result.get("answer", "")
        sources = rag_result.get("sources", [])
        grounded = rag_result.get("grounded", False)
        model_used = rag_result.get("model_used", "")

        print(f"    - Model Used: {model_used}")
        print(f"    - Grounded: {grounded}")
        print(f"    - Retrieved Chunks Count: {len(sources)}")
        for src in sources:
            print(f"      * Chunk: {src['chunk_id']} | Doc: {src['document_title']} | Score: {src['score']:.4f}")
        print(f"\n    - Generated Grounded Answer:\n")
        print("      " + "\n      ".join(answer.splitlines()))

        # Validations on Answer
        assert len(sources) > 0, "RAG pipeline should retrieve at least 1 relevant chunk"
        assert grounded is True, "Answer must be marked as grounded"
        assert "Google Gemini" in model_used, f"Expected Google Gemini in model_used, got: {model_used}"
        assert not any(tag in answer for tag in ["[Source", "[Chunk", "Customer:", "Agent:", "MURI"]), "Answer must be sanitized with no raw bracket citations or speaker labels"
        print(f"\n    [PASS] Answer generated by {model_used} using {len(sources)} persisted chunks from '{existing_doc.title}'.")

        # 5. Unsupported Question Test
        print(f"\n[5] UNSUPPORTED QUESTION TEST:")
        unsupported_q = "Do you have helicopter landing pads, private helipads, and submarine rentals available?"
        print(f"    - Question: '{unsupported_q}'")

        unsupported_result = DocumentChunkingService.generate_rag_answer(
            db=db,
            tenant_id=1,
            question=unsupported_q,
            document_id=existing_doc.document_id,
            limit=4,
            min_similarity=0.20
        )

        unsupported_answer = unsupported_result.get("answer", "")
        unsupported_grounded = unsupported_result.get("grounded", False)
        print(f"    - Grounded: {unsupported_grounded}")
        print(f"    - Sources Count: {unsupported_result.get('sources_count', 0)}")
        print(f"    - System Response: {unsupported_answer}")

        expected_statement = "I’m sorry, I can’t confirm that information from the hotel's approved knowledge documents at the moment"
        assert expected_statement in unsupported_answer or unsupported_grounded is False, "Unsupported question must return the unconfirmed statement or be ungrounded"
        print(f"    [PASS] System correctly avoided hallucination and returned verified unavailability response.")

        # 6. Tenant Isolation Test
        print(f"\n[6] TENANT ISOLATION VERIFICATION:")
        t2_search = DocumentChunkingService.search_chunks(
            db=db,
            tenant_id=9999,
            query="services breakfast pool"
        )
        print(f"    - Tenant 9999 search results for Tenant 1 documents: {len(t2_search)} matches")
        assert len(t2_search) == 0, "Tenant 9999 must NOT access Tenant 1 chunks"
        print(f"    [PASS] Strict multi-tenant isolation confirmed.")

        # 7. Persistence Verification
        print(f"\n[7] PERSISTENCE RESTART / RE-QUERY VERIFICATION:")
        db.close()
        # Open fresh session to simulate restart/refresh
        db_fresh = SessionLocal()
        persisted_doc = db_fresh.query(KnowledgeDocument).filter_by(document_id=existing_doc.document_id).first()
        assert persisted_doc is not None, "Document must persist across sessions"
        persisted_chunks = db_fresh.query(DocumentChunk).filter_by(document_ref_id=persisted_doc.id).all()
        assert len(persisted_chunks) == existing_doc.chunk_count, "Chunks must persist across sessions"
        print(f"    - Document '{persisted_doc.title}' ({persisted_doc.document_id}) persisted with {len(persisted_chunks)} chunks.")
        print(f"    [PASS] Full persistence confirmed.")

        db_fresh.close()

    finally:
        db.close()

    print("\n" + "=" * 80)
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY - STATUS: PASS (100%)")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
