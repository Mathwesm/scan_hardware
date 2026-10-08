"""Normalize printed identifiers and rank catalog candidates."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from scan_hardware.models.item import Item, Match, ScanResult

_WORD_PATTERN = re.compile(r"[A-Z0-9]+")
_MIN_FUZZY_SCORE = 0.82
_MAX_MATCHES = 5
MIN_IDENTIFIER_LENGTH = 4


def normalize_identifier(value: str) -> str:
    """Remove punctuation and accents while retaining letters and digits.

    Args:
        value: Identifier or OCR text to normalize.

    Returns:
        Uppercase ASCII letters and digits.
    """
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return "".join(_WORD_PATTERN.findall(ascii_text.upper()))


def _candidate_fragments(value: str) -> set[str]:
    """Build contiguous OCR token spans to tolerate surrounding label text."""
    words = _WORD_PATTERN.findall(value.upper())
    fragments = {normalize_identifier(value)}
    for start in range(len(words)):
        for end in range(start + 1, min(start + 7, len(words)) + 1):
            fragments.add("".join(words[start:end]))
    return {fragment for fragment in fragments if len(fragment) >= MIN_IDENTIFIER_LENGTH}


def _score_identifier(identifier: str, observed: str) -> tuple[float, bool]:
    """Compare a catalog identifier with one OCR line."""
    target = normalize_identifier(identifier)
    fragments = _candidate_fragments(observed)
    if target in fragments:
        return 1.0, True

    score = max(
        (SequenceMatcher(None, target, fragment).ratio() for fragment in fragments),
        default=0.0,
    )
    return score, False


def _observations(lines: list[str]) -> list[str]:
    """Join nearby OCR fragments that may belong to one printed model name."""
    return [
        " ".join(lines[start : start + width])
        for start in range(len(lines))
        for width in range(1, min(3, len(lines) - start) + 1)
    ]


def _exact_matches(observations: list[str], items: list[Item]) -> list[Match]:
    """Find exact aliases before running expensive fuzzy comparisons."""
    fragments = [(observed, _candidate_fragments(observed)) for observed in observations]
    all_fragments = set().union(*(values for _, values in fragments))
    exact_matches: dict[str, Match] = {}
    for item in items:
        for identifier in item.identifiers:
            target = normalize_identifier(identifier)
            if target not in all_fragments:
                continue
            for observed, values in fragments:
                if target in values:
                    exact_matches[item.id] = Match(
                        item=item,
                        matched_identifier=identifier,
                        observed_text=observed,
                        score=1.0,
                        is_exact=True,
                    )
                    break
    return sorted(exact_matches.values(), key=lambda match: match.item.id, reverse=True)


def match_items(observed_text: list[str], items: list[Item]) -> ScanResult:
    """Return exact hits first, then bounded fuzzy suggestions.

    Args:
        observed_text: OCR lines or user-supplied text.
        items: Items in the local catalog.

    Returns:
        Scan result with status and ordered candidate evidence.
    """
    observations = _observations(observed_text)
    exact_matches = _exact_matches(observations, items)
    if exact_matches:
        return ScanResult(
            status="matched", detected_text=observed_text, matches=exact_matches[:_MAX_MATCHES]
        )

    best_matches: dict[str, Match] = {}
    for item in items:
        for identifier in item.identifiers:
            for observed in observations:
                score, is_exact = _score_identifier(identifier, observed)
                if score < _MIN_FUZZY_SCORE:
                    continue
                candidate = Match(
                    item=item,
                    matched_identifier=identifier,
                    observed_text=observed,
                    score=score,
                    is_exact=is_exact,
                )
                previous = best_matches.get(item.id)
                if previous is None or (candidate.is_exact, candidate.score) > (
                    previous.is_exact,
                    previous.score,
                ):
                    best_matches[item.id] = candidate

    matches = sorted(
        best_matches.values(),
        key=lambda match: (match.is_exact, match.score, match.item.id),
        reverse=True,
    )[:_MAX_MATCHES]
    status = (
        "matched" if matches and matches[0].is_exact else "suggestions" if matches else "not_found"
    )
    return ScanResult(status=status, detected_text=observed_text, matches=matches)
