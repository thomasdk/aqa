"""Offline o200k_base material-estimate contracts."""

from src.service.token_estimator import TOKENIZER_NAME, estimate_tokens


def test_estimate_tokens_handles_empty_german_unicode_and_large_text():
    assert TOKENIZER_NAME == "o200k_base"
    assert estimate_tokens("") == 0

    german = "Über die Größe des Materials: Grüße aus Köln."
    unicode_text = "こんにちは世界 — 👩🏽‍💻"
    assert estimate_tokens(german) > 0
    assert estimate_tokens(unicode_text) > 0

    large_text = ("Material mit mehreren Wörtern. " * 20_000).strip()
    assert estimate_tokens(large_text) > estimate_tokens(german)


def test_estimate_tokens_uses_the_bundled_bpe_for_plain_text():
    assert estimate_tokens("hello world") == 2
    assert estimate_tokens("AQA") == 2
    assert estimate_tokens("foo_bar") == 2
    assert estimate_tokens("don't stop") == 2
    assert estimate_tokens("We're") == 1
    assert estimate_tokens("a__b") == 3


def test_estimate_tokens_keeps_unicode_boundary_cases_stable():
    assert estimate_tokens("NASA McDONALD eBay") == 7
    assert estimate_tokens("0 12 123 1234 １２３٤٥٦") == 14
    assert estimate_tokens("Hello...?! /path/to/file\r\nnext\n\n") == 10
    assert estimate_tokens("a\x1cb\x1dc\x1ed\x1f e\x85f") == 12
