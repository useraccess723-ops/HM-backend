"""
Verification test script for LangChain document chunking, SQL persistence, and tenant isolation.
"""

import sys
import json
from app.database.connection import get_db, Base, engine
from app.models.entities import KnowledgeDocument, DocumentChunk, Tenant
from app.services.document_chunking_service import DocumentChunkingService

def run_tests():
    print("=" * 70)
    print("STARTING LANGCHAIN DOCUMENT CHUNKING VERIFICATION SUITE")
    print("=" * 70)

    # 1. Ensure tables exist
    Base.metadata.create_all(bind=engine)
    db = next(get_db())

    # Ensure test tenants exist
    t1 = db.query(Tenant).filter(Tenant.id == 1).first()
    if not t1:
        t1 = Tenant(id=1, name="StayFlow Grand Resort", slug="stayflow-grand", code="HOTEL-001")
        db.add(t1)
        db.commit()

    t2 = db.query(Tenant).filter(Tenant.id == 2).first()
    if not t2:
        t2 = Tenant(id=2, name="StayFlow Boutique Suites", slug="stayflow-boutique", code="HOTEL-002")
        db.add(t2)
        db.commit()

    print("[1] Confirmed DB readiness and active tenants: Tenant 1 and Tenant 2.")

    # 2. Test Document Processing and Persistent Chunk Creation
    sample_policy_doc = """StayFlow Hotel Comprehensive Guest Policies & Guidelines

1. Check-in and Check-out Procedures
Check-in time starts at 14:00 (2:00 PM) standard local time. Early check-in is subject to room availability upon arrival and may incur nominal day-use charges.
Check-out time is strictly 11:00 (11:00 AM). Late check-outs must be requested at least 4 hours in advance at the front desk.

2. Cancellation and Refund Policy
Guaranteed reservations may be cancelled without penalty up to 24 hours prior to the scheduled arrival date.
Cancellations made within 24 hours of check-in will be charged the first night's room rate plus applicable 12% GST tax.
No-shows will result in forfeiture of the entire advance deposit.

3. Dining, Breakfast & In-Room Amenities
Complimentary buffet breakfast is served daily between 07:00 and 10:30 in the Orchid Dining Hall.
24-hour in-room dining is available by dialing extension 9 from the room telephone.
All suites feature high-speed optical Wi-Fi, premium minibar, Nespresso coffee maker, and smart climate controls.

4. Security, Identification & Self-Registration
All guests must present government-issued photo ID (Aadhaar Card, Passport, or Driving License) upon check-in or complete digital self-registration via our QR portal.
"""

    doc_id = "DOC-POLICY-2026"
    doc_record, chunks = DocumentChunkingService.process_and_persist_document(
        db=db,
        tenant_id=1,
        title="StayFlow Guest Policy Manual 2026",
        content=sample_policy_doc,
        document_id=doc_id,
        source_type="policy",
        metadata={"department": "Front Office", "author": "Operations Director", "version": "2.4"},
        chunk_size=300,
        chunk_overlap=60,
    )

    print(f"\n[2] LangChain Document Processing Result:")
    print(f"    - Document ID: {doc_record.document_id}")
    print(f"    - Document Title: {doc_record.title}")
    print(f"    - Total Chunks Generated & Saved: {len(chunks)}")
    assert len(chunks) >= 3, f"Expected at least 3 chunks, got {len(chunks)}"

    # 3. Verify Database Persistence (simulate fresh session)
    db.close()
    db = next(get_db())

    persisted_chunks = DocumentChunkingService.get_document_chunks(db=db, tenant_id=1, document_id=doc_id)
    print(f"\n[3] Persistent SQL Retrieval Verification:")
    print(f"    - Chunks retrieved from database: {len(persisted_chunks)}")
    assert len(persisted_chunks) == len(chunks), "Chunk count mismatch in SQL database!"

    for c in persisted_chunks:
        assert c.chunk_id, "Missing chunk_id"
        assert c.document_id == doc_id, "Chunk document_id mismatch"
        assert c.chunk_index is not None, "Missing chunk_index"
        assert len(c.chunk_text) > 0, "Chunk text is empty"
        assert c.created_at is not None, "Missing created_at timestamp"
        assert c.embedding_json is not None, "Missing embedding_json vector"
        meta = json.loads(c.metadata_json)
        print(f"    [OK] Chunk #{c.chunk_index} ({c.chunk_id}): {len(c.chunk_text)} chars | Tokens: {c.token_count} | Meta: {meta.get('department')}")

    # 4. Test Deduplication / Idempotent Re-processing
    print(f"\n[4] Testing Deduplication (Re-processing Document '{doc_id}'):")
    updated_content = sample_policy_doc + "\n5. Spa and Fitness Center\nThe wellness center and rooftop infinity pool operate from 06:00 to 22:00 daily."
    
    updated_doc, updated_chunks = DocumentChunkingService.process_and_persist_document(
        db=db,
        tenant_id=1,
        title="StayFlow Guest Policy Manual 2026 (Updated)",
        content=updated_content,
        document_id=doc_id,
        source_type="policy",
        chunk_size=300,
        chunk_overlap=60,
    )

    db.close()
    db = next(get_db())
    recheck_chunks = DocumentChunkingService.get_document_chunks(db=db, tenant_id=1, document_id=doc_id)
    print(f"    - Chunks after re-processing: {len(recheck_chunks)}")
    assert len(recheck_chunks) == len(updated_chunks), "Duplicate chunks detected!"
    print("    [OK] No duplicate chunks created. Old chunks replaced cleanly.")

    # 5. Test Vector Similarity Search
    print(f"\n[5] Testing Vector Similarity Search on Persistent Chunks:")
    queries = ["cancellation 24 hours refund", "breakfast timing orchid hall", "spa fitness center rooftop pool"]
    for q in queries:
        matches = DocumentChunkingService.search_chunks(db=db, tenant_id=1, query=q, limit=2)
        print(f"    Query: '{q}' -> Top Match Score: {matches[0]['score'] if matches else 'None'}")
        if matches:
            top = matches[0]
            print(f"      [{top['chunk_id']}] Snippet: {top['chunk_text'][:90]}...")
            assert top['score'] > 0.1, "Expected positive similarity score"

    # 6. Test Strict Multi-Tenant Isolation
    print(f"\n[6] Testing Strict Multi-Tenant Isolation:")
    # Tenant 2 creates their own document
    t2_doc, t2_chunks = DocumentChunkingService.process_and_persist_document(
        db=db,
        tenant_id=2,
        title="Tenant 2 Confidential Executive Compensation",
        content="Tenant 2 Confidential Board Decisions and VIP rates. Room discounts 50% for partners.",
        document_id="DOC-T2-PRIVATE",
        source_type="confidential",
        chunk_size=200,
        chunk_overlap=30,
    )
    print(f"    - Tenant 2 created document: {t2_doc.document_id} with {len(t2_chunks)} chunks.")

    # Attempt to access Tenant 2 document as Tenant 1
    t1_attempt = DocumentChunkingService.get_document(db=db, tenant_id=1, document_id="DOC-T2-PRIVATE")
    print(f"    - Tenant 1 get_document('DOC-T2-PRIVATE'): {t1_attempt}")
    assert t1_attempt is None, "SECURITY VIOLATION: Tenant 1 was able to access Tenant 2 document!"

    # Attempt to search Tenant 2 chunks as Tenant 1
    t1_search = DocumentChunkingService.search_chunks(db=db, tenant_id=1, query="Executive Compensation VIP rates", limit=5)
    t2_leak = any(m["document_id"] == "DOC-T2-PRIVATE" for m in t1_search)
    print(f"    - Tenant 1 vector search leaked Tenant 2 chunks? {t2_leak}")
    assert not t2_leak, "SECURITY VIOLATION: Tenant 1 vector search leaked Tenant 2 chunks!"

    # Attempt to delete Tenant 2 document as Tenant 1
    del_leak = DocumentChunkingService.delete_document(db=db, tenant_id=1, document_id="DOC-T2-PRIVATE")
    print(f"    - Tenant 1 allowed to delete Tenant 2 document? {del_leak}")
    assert del_leak is False, "SECURITY VIOLATION: Tenant 1 was able to delete Tenant 2 document!"

    print("    [OK] Strict tenant isolation verified: Cross-tenant access is completely blocked.")

    # 7. Test Cascade Deletion
    print(f"\n[7] Testing Cascade Deletion of Document and Chunks:")
    del_ok = DocumentChunkingService.delete_document(db=db, tenant_id=1, document_id=doc_id)
    assert del_ok is True, "Failed to delete document"
    
    remaining_chunks = DocumentChunkingService.get_document_chunks(db=db, tenant_id=1, document_id=doc_id)
    assert len(remaining_chunks) == 0, "Chunks were not deleted by cascade!"
    print("    [OK] Document and all associated persistent chunks were deleted cleanly.")

    # Cleanup Tenant 2 document
    DocumentChunkingService.delete_document(db=db, tenant_id=2, document_id="DOC-T2-PRIVATE")

    db.close()
    print("\n" + "=" * 70)
    print("ALL LANGCHAIN PERSISTENT CHUNKING & ISOLATION TESTS PASSED (100%)")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
