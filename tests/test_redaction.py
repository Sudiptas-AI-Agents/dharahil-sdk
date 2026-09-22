from dharahil.redaction import MASK, redact


def test_prose_with_long_words_is_not_redacted():
    text = "The container was successfully created but the configuration never loaded."
    out, report = redact({"diagnosis": text})
    assert out["diagnosis"] == text
    assert report["fields"] == []


def test_hex_hash_masked_in_place():
    out, report = redact({"msg": "Deployed image a3f9c2e1b7d4f8e6a1c2b3d4 to prod"})
    assert out["msg"] == f"Deployed image {MASK} to prod"
    assert report["fields"] == [{"key": "msg", "reason": "high_entropy"}]


def test_known_prefixes_masked():
    out, _ = redact({
        "a": "key sk-proj-abcdefghijklmnop done",
        "b": "xoxb-1234567890-abcdefghij",
        "c": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.sig",
    })
    assert out["a"] == f"key {MASK} done"
    assert out["b"] == MASK
    assert out["c"].startswith(MASK)


def test_secret_keys_masked_even_when_short():
    out, report = redact({"password": "hunter2", "api_token": "x", "user": "bob"})
    assert out == {"password": MASK, "api_token": MASK, "user": "bob"}
    assert {f["key"] for f in report["fields"]} == {"password", "api_token"}


def test_nested_structures_walked():
    out, report = redact({"auth": {"token": "abc"}, "items": [{"secret": "s"}, "plain text"]})
    assert out == {"auth": {"token": MASK}, "items": [{"secret": MASK}, "plain text"]}
    assert {f["key"] for f in report["fields"]} == {"auth.token", "items[0].secret"}


def test_email_and_url_untouched():
    out, _ = redact({"to": "user123@example.com", "link": "https://example.com/some_path1"})
    assert out == {"to": "user123@example.com", "link": "https://example.com/some_path1"}
