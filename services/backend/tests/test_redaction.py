import pytest

from app.redaction import HOLD_BACK_CHARS, REDACTED, Redactor
from app.security.token import generate_token, hash_token

SECRETS = [
    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
    "sk-abcdefghijklmnopqrstuvwxyz0123456789",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "AKIAABCDEFGHIJKLMNOP",
    "xoxb-1234567890-abcdefghij",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_secret_formats_are_redacted(secret):
    redacted = Redactor().redact(f"here is my key {secret} please keep it")

    assert secret not in redacted
    assert REDACTED in redacted


def test_bearer_and_authorization_headers_are_redacted():
    text = "curl -H 'Authorization: Bearer abc123def456ghi789' and Authorization: rawsecretvalue99"

    redacted = Redactor().redact(text)

    assert "abc123def456ghi789" not in redacted
    assert "rawsecretvalue99" not in redacted


def test_key_value_secrets_keep_the_label_and_hide_the_value():
    redacted = Redactor().redact("password: hunter2hunter2 and API_KEY=zzzzzzzzzzzz")

    assert "hunter2hunter2" not in redacted
    assert "zzzzzzzzzzzz" not in redacted
    assert "password" in redacted and "API_KEY" in redacted


def test_private_key_block_is_redacted():
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy\n-----END RSA PRIVATE KEY-----"

    assert "MIIBOgIBAAJB" not in Redactor().redact(f"my key:\n{block}\nthanks")


def test_exact_known_secret_is_redacted_even_without_a_known_format():
    redacted = Redactor(known_secrets=["plain-credential-value"]).redact("x plain-credential-value y")

    assert redacted == f"x {REDACTED} y"


def test_short_known_secrets_are_ignored_to_avoid_mangling_text():
    assert Redactor(known_secrets=["abc"]).redact("abc def") == "abc def"


def test_greenloop_token_is_recognized_by_its_hash_without_knowing_it():
    token = generate_token()
    redactor = Redactor(token_hash=hash_token(token))

    redacted = redactor.redact(f"the token is {token}, ok?")

    assert token not in redacted
    other = generate_token()
    assert other in redactor.redact(f"an unrelated random string {other}")


def test_plain_text_is_untouched():
    text = "Meet at 5pm. The password policy is strong. Token ring networks are old."

    assert Redactor().redact(text) == text


def stream_in_chunks(redactor: Redactor, text: str, size: int) -> str:
    stream = redactor.stream()
    output = "".join(stream.feed(text[i : i + size]) for i in range(0, len(text), size))
    return output + stream.flush()


@pytest.mark.parametrize("chunk_size", [1, 3, 7, 50])
def test_streaming_redaction_catches_secrets_split_across_chunks(chunk_size):
    filler = "word " * 200
    secret = SECRETS[0]
    text = f"{filler}my key is {secret} and then more text {filler}"

    output = stream_in_chunks(Redactor(), text, chunk_size)

    assert secret not in output
    assert "and then more text" in output


@pytest.mark.parametrize("chunk_size", [1, 5, 40])
def test_streaming_redaction_handles_label_then_value_split(chunk_size):
    filler = "lorem ipsum " * 60
    text = f"{filler}Authorization: Bearer supersecrettokenvalue123 {filler}"

    assert "supersecrettokenvalue123" not in stream_in_chunks(Redactor(), text, chunk_size)


def test_streaming_matches_batch_redaction_for_clean_text():
    text = "The quick brown fox. " * 100

    assert stream_in_chunks(Redactor(), text, 13) == Redactor().redact(text)


def test_stream_holds_back_only_a_bounded_tail():
    stream = Redactor().stream()

    total = HOLD_BACK_CHARS * 4
    early = stream.feed("a " * (total // 2))

    assert total - 2 * HOLD_BACK_CHARS < len(early) <= total - HOLD_BACK_CHARS
    assert len(early) + len(stream.flush()) == total


def test_structlog_processor_redacts_nested_values():
    from app.redaction import redact_event_dict

    processor = redact_event_dict(Redactor())

    result = processor(None, "info", {"event": "x", "detail": {"key": ["Bearer abcdefghijk12345"]}})

    assert "abcdefghijk12345" not in str(result)
