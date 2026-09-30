"""Offline, clearly labelled token estimates for user-entered material."""

from __future__ import annotations

import base64
import binascii
import hashlib
import heapq
import unicodedata
from functools import lru_cache
from pathlib import Path

TOKENIZER_NAME = "o200k_base"
_ASSET_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
_ASSET_PATH = Path(__file__).resolve().parents[2] / "data" / "tokenizers" / "o200k_base.tiktoken"


class TokenEstimatorUnavailable(RuntimeError):
    """The bundled vocabulary is unavailable or failed integrity verification."""


@lru_cache(maxsize=1)
def _mergeable_ranks() -> dict[bytes, int]:
    try:
        payload = _ASSET_PATH.read_bytes()
    except OSError as exc:
        raise TokenEstimatorUnavailable("Bundled token vocabulary is unavailable") from exc
    if hashlib.sha256(payload).hexdigest() != _ASSET_SHA256:
        raise TokenEstimatorUnavailable("Bundled token vocabulary failed integrity verification")

    try:
        ranks: dict[bytes, int] = {}
        rank_values: set[int] = set()
        for encoded, raw_rank in (line.split() for line in payload.splitlines()):
            token = base64.b64decode(encoded, validate=True)
            rank = int(raw_rank)
            if token in ranks or rank in rank_values:
                raise ValueError("duplicate vocabulary entry")
            ranks[token] = rank
            rank_values.add(rank)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise TokenEstimatorUnavailable("Bundled token vocabulary is malformed") from exc
    if any(bytes((byte,)) not in ranks for byte in range(256)):
        raise TokenEstimatorUnavailable("Bundled token vocabulary is incomplete")
    return ranks


_WHITESPACE = frozenset(
    "\t\n\v\f\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)
_CONTRACTIONS = ("'s", "'t", "'re", "'ve", "'m", "'ll", "'d")


def _category(character: str) -> str:
    return unicodedata.category(character)


def _is_letter(character: str) -> bool:
    return _category(character).startswith("L")


def _is_number(character: str) -> bool:
    return _category(character).startswith("N")


def _is_upperish(character: str) -> bool:
    return _category(character) in {"Lu", "Lt", "Lm", "Lo", "Mn", "Mc", "Me"}


def _is_lowerish(character: str) -> bool:
    return _category(character) in {"Ll", "Lm", "Lo", "Mn", "Mc", "Me"}


def _consume_contraction(text: str, position: int) -> int:
    for contraction in _CONTRACTIONS:
        end = position + len(contraction)
        if text[position:end].lower() == contraction:
            return end
    return position


def _word_end(text: str, position: int, *, require_lowerish: bool) -> int | None:
    """Match the first two o200k word alternatives from ``position``."""
    body_starts = [position]
    if (
        position + 1 < len(text)
        and text[position] not in "\r\n"
        and not _is_letter(text[position])
        and not _is_number(text[position])
    ):
        body_starts.insert(0, position + 1)

    for body_start in body_starts:
        cursor = body_start
        if require_lowerish:
            while cursor < len(text) and _is_upperish(text[cursor]):
                cursor += 1
            lower_start = cursor
            while cursor < len(text) and _is_lowerish(text[cursor]):
                cursor += 1
            if cursor == lower_start:
                continue
        else:
            upper_start = cursor
            while cursor < len(text) and _is_upperish(text[cursor]):
                cursor += 1
            if cursor == upper_start:
                continue
            while cursor < len(text) and _is_lowerish(text[cursor]):
                cursor += 1
        return _consume_contraction(text, cursor)
    return None


def _word_piece_end(text: str, position: int) -> int | None:
    """Return the end of a word-like pre-tokenization piece."""

    return _word_end(text, position, require_lowerish=True) or _word_end(
        text, position, require_lowerish=False
    )


def _number_piece_end(text: str, position: int) -> int | None:
    """Return the end of a bounded numeric pre-tokenization piece."""

    if not _is_number(text[position]):
        return None
    end = position + 1
    while end < len(text) and end - position < 3 and _is_number(text[end]):
        end += 1
    return end


def _punctuation_piece_end(text: str, position: int) -> int | None:
    """Return the end of punctuation and its attached line separators."""

    punctuation_start = position + 1 if text[position] == " " else position
    end = punctuation_start
    while (
        end < len(text)
        and text[end] not in _WHITESPACE
        and not _is_letter(text[end])
        and not _is_number(text[end])
    ):
        end += 1
    if end == punctuation_start:
        return None
    while end < len(text) and text[end] in "\r\n/":
        end += 1
    return end


def _whitespace_piece_end(text: str, position: int) -> int | None:
    """Return the end selected by the whitespace pre-tokenization rule."""

    whitespace_end = position
    while whitespace_end < len(text) and text[whitespace_end] in _WHITESPACE:
        whitespace_end += 1
    if whitespace_end == position:
        return None
    final_newline_end = -1
    cursor = position
    while cursor < whitespace_end:
        if text[cursor] in "\r\n":
            while cursor < whitespace_end and text[cursor] in "\r\n":
                cursor += 1
            final_newline_end = cursor
        else:
            cursor += 1
    if final_newline_end >= 0:
        return final_newline_end
    if whitespace_end == len(text) or whitespace_end - position == 1:
        return whitespace_end
    return whitespace_end - 1


def _iter_pieces(text: str):
    """Yield a stdlib-only approximation of o200k's Unicode pre-tokenization."""

    position = 0
    while position < len(text):
        end = (
            _word_piece_end(text, position)
            or _number_piece_end(text, position)
            or _punctuation_piece_end(text, position)
            or _whitespace_piece_end(text, position)
        )
        if end is None:
            end = position + 1
        yield text[position:end]
        position = end


@lru_cache(maxsize=8_192)
def _count_piece(piece: bytes) -> int:
    """Return the BPE token count for one pre-tokenized UTF-8 byte string."""
    if not piece:
        return 0
    parts = [bytes((byte,)) for byte in piece]
    ranks = _mergeable_ranks()
    following = [index + 1 for index in range(len(parts))]
    following[-1] = -1
    previous = [index - 1 for index in range(len(parts))]
    active = [True] * len(parts)
    candidates: list[tuple[int, int, int]] = []

    def add_candidate(left: int, right: int) -> None:
        if left < 0 or right < 0:
            return
        rank = ranks.get(parts[left] + parts[right])
        if rank is not None:
            heapq.heappush(candidates, (rank, left, right))

    for index in range(len(parts) - 1):
        add_candidate(index, index + 1)

    token_count = len(parts)
    while candidates:
        rank, left, right = heapq.heappop(candidates)
        if (
            not active[left]
            or not active[right]
            or following[left] != right
            or ranks.get(parts[left] + parts[right]) != rank
        ):
            continue
        parts[left] += parts[right]
        active[right] = False
        following[left] = following[right]
        if following[right] >= 0:
            previous[following[right]] = left
        token_count -= 1
        add_candidate(previous[left], left)
        add_candidate(left, following[left])
    return token_count


def estimate_tokens(text: str) -> int:
    """Estimate tokens with the locally bundled o200k_base BPE vocabulary."""
    return sum(_count_piece(piece.encode("utf-8")) for piece in _iter_pieces(text or ""))


__all__ = ["TOKENIZER_NAME", "TokenEstimatorUnavailable", "estimate_tokens"]
