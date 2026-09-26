from cryptography.fernet import Fernet

from mercury.security.crypto import TokenCipher


def test_tokens_are_ciphertext_and_rotate_between_keys():
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    original = TokenCipher((old_key,)).encrypt({"refresh_token": "fixture-secret"})
    assert "fixture-secret" not in original
    rotated = TokenCipher((new_key, old_key)).rotate(original)
    assert rotated != original
    assert (
        TokenCipher((new_key,)).decrypt(rotated)["refresh_token"] == "fixture-secret"  # noqa: S105 - deliberately invented test value
    )
