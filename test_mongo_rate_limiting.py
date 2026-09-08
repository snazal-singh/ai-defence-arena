import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO)

from controllers.external_mongo_connection import (
    _mask_uri_credentials,
    _mongo_rate_limiter,
    attach_server,
)

TEST_SESSION = "test_rate_limiting_session"


def test_credential_masking():
    print("\n--- 1. Testing Credential Masking ---")
    uri1 = "mongodb://user123:SecretPass!99@cluster0.example.com:27017/mydb"
    masked1 = _mask_uri_credentials(uri1)
    print("Original:", uri1)
    print("Masked  :", masked1)
    assert "SecretPass!99" not in masked1, "Password leaked in masked URI!"
    assert "user123:***@" in masked1, "Username/mask pattern incorrect!"

    uri2 = "mongodb+srv://admin_user:SuperSecureP@ssword@atlas.mongodb.net/analytics"
    masked2 = _mask_uri_credentials(uri2)
    print("Original:", uri2)
    print("Masked  :", masked2)
    assert "SuperSecureP@ssword" not in masked2, "Password leaked in SRV masked URI!"

    err_msg = "Could not connect to mongodb+srv://db_user:my_secret_token@host.com: ServerSelectionTimeoutError"
    masked_err = _mask_uri_credentials(err_msg)
    print("Error msg original:", err_msg)
    print("Error msg masked  :", masked_err)
    assert "my_secret_token" not in masked_err, "Password leaked in error message!"
    print("PASSED: Credential masking tests.")


def test_rate_limiting_and_cooldown():
    print("\n--- 2. Testing Rate Limiting & Cooldown Lockout ---")
    _mongo_rate_limiter.reset_all()

    # Unreachable public Mongo URI (will fail connection test)
    unreachable_uri = "mongodb://192.0.2.1:27017/nonexistent_db"
    server_name = "Test Server"

    # Attempt 1 (Failure 1)
    print("Attempt 1...")
    ok1, msg1, srv1 = attach_server(TEST_SESSION, unreachable_uri, server_name)
    assert not ok1, f"Expected attempt 1 to fail, got: {msg1}"
    print(f"Attempt 1 result: ok={ok1}, msg='{msg1}'")

    # Attempt 2 (Failure 2)
    print("Attempt 2...")
    ok2, msg2, srv2 = attach_server(TEST_SESSION, unreachable_uri, server_name)
    assert not ok2, f"Expected attempt 2 to fail, got: {msg2}"
    print(f"Attempt 2 result: ok={ok2}, msg='{msg2}'")

    # Attempt 3 (Failure 3 - Triggers Cooldown)
    print("Attempt 3...")
    ok3, msg3, srv3 = attach_server(TEST_SESSION, unreachable_uri, server_name)
    assert not ok3, f"Expected attempt 3 to fail, got: {msg3}"
    print(f"Attempt 3 result: ok={ok3}, msg='{msg3}'")

    # Attempt 4 (Immediate Lockout Response)
    print("Attempt 4 (Should be rate-limited immediately)...")
    ok4, msg4, srv4 = attach_server(TEST_SESSION, unreachable_uri, server_name)
    assert not ok4, "Attempt 4 should be rejected"
    assert "Too many consecutive connection failures" in msg4 or "locked out" in msg4, (
        f"Unexpected rate limit message: {msg4}"
    )
    print(f"Attempt 4 rate-limited successfully: '{msg4}'")

    # Reset limiter and verify retry is allowed again
    _mongo_rate_limiter.reset_all()
    print("Limiter state reset.")
    ok5, msg5, srv5 = attach_server(TEST_SESSION, unreachable_uri, server_name)
    assert not ok5
    assert "Too many consecutive" not in msg5, f"Limiter should have allowed retry after reset, got: {msg5}"
    print(f"Retry after reset returned expected network failure: '{msg5}'")

    print("PASSED: Rate limiting & cooldown lockout tests.")


if __name__ == "__main__":
    print("========================================")
    print("RUNNING MONGODB RATE LIMITING & MASKING TESTS")
    print("========================================")
    test_credential_masking()
    test_rate_limiting_and_cooldown()
    print("\n========================================")
    print("ALL RATE LIMITING & MASKING TESTS PASSED!")
    print("========================================")
