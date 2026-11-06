"""
Integration test for LangChain Document Chunking & RAG Answer Generation REST API.
"""

import io
import requests
import sys

BASE_URL = "http://127.0.0.1:8000"

def run_live_api_tests():
    print("=" * 70)
    print("TESTING LIVE REST API: FILE UPLOAD, LANGCHAIN CHUNKING & RAG GENERATION")
    print("=" * 70)

    # 1. Login to get authentication token
    login_res = requests.post(f"{BASE_URL}/api/auth/token", data={
        "username": "admin@hotel.com",
        "password": "Password@123"
    })
    if login_res.status_code != 200:
        print(f"Failed to log in: {login_res.status_code} {login_res.text}")
        sys.exit(1)

    token = login_res.json()["access_token"]
    headers = {
        "Authorization": f"Bearer {token}",
    }
    json_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    print("[1] Logged in successfully. Token acquired.")

    # 2. Test File Upload endpoint (multipart/form-data)
    file_content = (
        "StayFlow Grand Resort Guest Amenities and Dining Manual 2026.\n\n"
        "Dining Hours & Breakfast Service:\n"
        "Complimentary buffet breakfast is served from 07:00 AM to 10:30 AM at the Orchid Terrace.\n"
        "24-Hour In-Room Dining is available by dialing extension 9 from your room telephone.\n\n"
        "Swimming Pool and Fitness Wellness Center:\n"
        "The heated rooftop infinity swimming pool is open daily from 06:00 AM to 10:00 PM.\n"
        "Complimentary bathrobes, fresh towels, and sun loungers are provided at poolside.\n\n"
        "Wi-Fi and Technical Support:\n"
        "High-speed fiber optical Wi-Fi 'StayFlow_Guest' is complimentary throughout all rooms.\n"
        "No password is required; simply accept the terms of service on the captive login portal."
    ).encode("utf-8")

    upload_file = ("guest_amenities_manual.txt", io.BytesIO(file_content), "text/plain")
    upload_res = requests.post(
        f"{BASE_URL}/api/documents/upload",
        files={"file": upload_file},
        data={
            "title": "Guest Amenities & Dining Manual 2026",
            "document_id": "DOC-AMENITIES-2026",
            "source_type": "manual",
            "chunk_size": 250,
            "chunk_overlap": 50
        },
        headers=headers
    )
    assert upload_res.status_code == 200, f"Upload failed: {upload_res.status_code} {upload_res.text}"
    up_data = upload_res.json()
    print(f"\n[2] POST /api/documents/upload Success:")
    print(f"    - Status: {up_data['status']}")
    print(f"    - Document ID: {up_data['document']['document_id']}")
    print(f"    - Chunks Created & Persisted in SQL: {up_data['chunks_count']}")
    assert up_data["chunks_count"] >= 3, "Expected at least 3 chunks"

    # 3. Test Duplicate Upload Detection (uploading identical content again)
    print(f"\n[3] Testing Duplicate Upload Prevention:")
    dup_file = ("guest_amenities_copy.txt", io.BytesIO(file_content), "text/plain")
    dup_res = requests.post(
        f"{BASE_URL}/api/documents/upload",
        files={"file": dup_file},
        data={"title": "Duplicate File Test"},
        headers=headers
    )
    assert dup_res.status_code == 200
    dup_data = dup_res.json()
    print(f"    - Duplicate detection response: is_duplicate = {dup_data.get('is_duplicate')}")
    assert dup_data.get("is_duplicate") is True, "Expected duplicate detection flag to be True!"
    print(f"    [OK] Duplicate file upload prevented. Existing document ID cited: {dup_data['document']['document_id']}")

    # 4. Test RAG Answer Generation for In-Scope Question
    print(f"\n[4] Testing RAG Answer Generation (In-Scope Question):")
    q1 = "What are the timings for breakfast and swimming pool?"
    rag1_res = requests.post(
        f"{BASE_URL}/api/documents/rag/answer",
        json={"question": q1, "limit": 4},
        headers=json_headers
    )
    assert rag1_res.status_code == 200, f"RAG failed: {rag1_res.status_code} {rag1_res.text}"
    rag1 = rag1_res.json()
    print(f"    Question: {rag1['question']}")
    print(f"    Answer: {rag1['answer']}")
    print(f"    Grounded: {rag1.get('grounded')}")
    print(f"    Sources Cited: {rag1['sources_count']}")
    assert rag1.get("grounded") is True, "Expected grounded to be True"
    assert rag1["has_context"] is True
    assert rag1["sources_count"] > 0
    assert "[Source" not in rag1["answer"], "Answer must not expose raw [Source] brackets"
    assert "MURI" not in rag1["answer"], "Answer must not contain MURI branding"
    assert any("07:00" in s["excerpt"] or "06:00" in s["excerpt"] for s in rag1["sources"])
    print(f"    [OK] In-scope question successfully answered with verified source citations.")

    # 4b. Test Inbound Call Script Dialog Q&A (Hotel Management Inbound Call Script)
    script_content = (
        "Customer: What are the services available?\n"
        "Agent: Certainly. Our hotel offers room amenities, hotel facilities, and additional guest services. "
        "I can provide more details about the specific service or facility you're interested in. Would you like more details?\n\n"
        "Customer: What are the standard check-in and check-out timings?\n"
        "Agent: Our standard check-in time is 2:00 PM and check-out time is 11:00 AM.\n"
    ).encode("utf-8")
    script_file = ("hotel_inbound_script.txt", io.BytesIO(script_content), "text/plain")
    script_res = requests.post(
        f"{BASE_URL}/api/documents/upload",
        files={"file": script_file},
        data={"title": "Hotel Management Inbound Call Script", "document_id": "DOC-SCRIPT-2026"},
        headers=headers
    )
    assert script_res.status_code == 200
    print(f"\n[4b] Uploaded Inbound Call Script document. Testing conversational dialog extraction:")
    rag_script_res = requests.post(
        f"{BASE_URL}/api/documents/rag/answer",
        json={"question": "What are the services available?", "limit": 4},
        headers=json_headers
    )
    assert rag_script_res.status_code == 200
    rag_script = rag_script_res.json()
    print(f"    Question: {rag_script['question']}")
    print(f"    Answer: {rag_script['answer']}")
    print(f"    Grounded: {rag_script.get('grounded')}")
    assert rag_script.get("grounded") is True, "Expected script answer grounded to be True"
    assert "Customer:" not in rag_script["answer"], "Answer must not contain raw Customer: label"
    assert "Agent:" not in rag_script["answer"], "Answer must not contain raw Agent: label"
    assert "[Source" not in rag_script["answer"], "Answer must not contain [Source] citation brackets"
    assert "MURI" not in rag_script["answer"], "Answer must not contain MURI"
    assert "room amenities, hotel facilities" in rag_script["answer"].lower(), "Expected accurate services facts"
    print(f"    [OK] Inbound call script successfully synthesized into clean conversational response.")

    # 5. Test RAG Answer Generation for Out-of-Scope Question (No Hallucination)
    print(f"\n[5] Testing RAG Zero-Hallucination on Out-of-Scope Question:")
    q2 = "What are the international visa requirements for flying to Tokyo Japan?"
    rag2_res = requests.post(
        f"{BASE_URL}/api/documents/rag/answer",
        json={"question": q2, "limit": 4, "min_similarity": 0.25},
        headers=json_headers
    )
    assert rag2_res.status_code == 200
    rag2 = rag2_res.json()
    print(f"    Question: {rag2['question']}")
    print(f"    Answer: {rag2['answer']}")
    print(f"    Grounded: {rag2.get('grounded')}")
    assert rag2.get("grounded") is False, "Expected out-of-scope grounded to be False"
    normalized_ans = rag2["answer"].lower().replace("’", "'")
    assert "can't confirm that information" in normalized_ans or "cannot confirm" in normalized_ans
    print(f"    [OK] Correctly declared information unavailable without hallucinating.")

    # 6. Verify Chunks Retrieval
    chunks_res = requests.get(f"{BASE_URL}/api/documents/DOC-AMENITIES-2026/chunks", headers=headers)
    assert chunks_res.status_code == 200
    print(f"\n[6] GET /api/documents/DOC-AMENITIES-2026/chunks -> {len(chunks_res.json())} chunks verified in SQL.")

    # 7. Cleanup test documents
    requests.delete(f"{BASE_URL}/api/documents/DOC-AMENITIES-2026", headers=headers)
    requests.delete(f"{BASE_URL}/api/documents/DOC-SCRIPT-2026", headers=headers)
    print(f"\n[7] Cleanup -> Cascade deleted test documents.")

    print("\n" + "=" * 70)
    print("ALL LIVE END-TO-END RAG & DOCUMENT UPLOAD TESTS PASSED (100%)")
    print("=" * 70)

if __name__ == "__main__":
    run_live_api_tests()
