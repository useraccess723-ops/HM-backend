from app.core.security import hash_password, verify_password

def test_password_hash_roundtrip():
    encoded=hash_password("correct horse battery")
    assert encoded != "correct horse battery"
    assert verify_password("correct horse battery", encoded)
    assert not verify_password("incorrect", encoded)
