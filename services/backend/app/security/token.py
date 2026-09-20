import hashlib
import hmac
import secrets


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(presented: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_token(presented).encode(), expected_hash.encode())


if __name__ == "__main__":
    token = generate_token()
    print(token)
    print(hash_token(token))
