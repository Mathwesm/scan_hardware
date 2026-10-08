"""Normalize printed identifiers and rank catalog candidates."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process

from scan_hardware.models.item import Category, Item, Match, ScanResult

_WORD_PATTERN = re.compile(r"[A-Z0-9]+")
_MIN_FUZZY_SCORE = 0.80
_MAX_MATCHES = 5
_MIN_REVISION_PREFIX_LENGTH = 8
_MIN_FUZZY_FRAGMENT_LENGTH = 5
_MAX_FUZZY_FRAGMENT_LENGTH = 32
_MIN_MODEL_DIGITS = 2
_FUZZY_CANDIDATES_PER_FRAGMENT = 30
_MAX_OBSERVATION_LINES = 4
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
    joined_codes = re.sub(r"(?<=[A-Z0-9])-(?=[A-Z0-9])", "", value.upper())
    words = _WORD_PATTERN.findall(joined_codes)
    fragments = {normalize_identifier(value)}
    for start in range(len(words)):
        for end in range(start + 1, min(start + 7, len(words)) + 1):
            fragments.add("".join(words[start:end]))
    return {fragment for fragment in fragments if len(fragment) >= MIN_IDENTIFIER_LENGTH}


def _score_fragment(target: str, fragment: str, similarity: float) -> float:
    """Prefer a complete printed code over a nearby different model."""
    if (
        len(fragment) >= _MIN_REVISION_PREFIX_LENGTH
        and target.startswith(fragment)
        and re.fullmatch(r"(?:R|REV)\d{1,3}", target[len(fragment) :])
    ):
        return 0.93
    return similarity / 100


def _observations(lines: list[str]) -> list[str]:
    """Join neighboring OCR lines in both readable orientations."""
    observations: list[str] = []
    for start in range(len(lines)):
        for width in range(1, min(_MAX_OBSERVATION_LINES, len(lines) - start) + 1):
            segment = lines[start : start + width]
            observations.append(" ".join(segment))
            if width > 1:
                observations.append(" ".join(reversed(segment)))
    return observations


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
    return sorted(
        exact_matches.values(),
        key=lambda match: (len(normalize_identifier(match.matched_identifier)), match.item.id),
        reverse=True,
    )


def _model_fragments(observations: list[str]) -> dict[str, str]:
    """Keep distinct code-like OCR spans and their shortest source observation."""
    fragments: dict[str, str] = {}
    for observed in observations:
        for fragment in _candidate_fragments(observed):
            if (
                _MIN_FUZZY_FRAGMENT_LENGTH <= len(fragment) <= _MAX_FUZZY_FRAGMENT_LENGTH
                and sum(character.isdigit() for character in fragment) >= _MIN_MODEL_DIGITS
                and any(character.isalpha() for character in fragment)
            ):
                previous = fragments.get(fragment)
                if previous is None or len(observed) < len(previous):
                    fragments[fragment] = observed
    return fragments


def _fuzzy_matches(observations: list[str], items: list[Item]) -> list[Match]:
    """Rank plausible identifiers using a bounded native-code similarity search."""
    has_gpu_label = bool(
        re.search(r"\b(?:GEFORCE|RADEON|GTX|RTX)\b", " ".join(observations).upper())
    )
    aliases: dict[str, list[tuple[Item, str]]] = {}
    for item in items:
        if has_gpu_label and item.category is not Category.GPU:
            continue
        for identifier in item.identifiers:
            aliases.setdefault(normalize_identifier(identifier), []).append((item, identifier))
    if not aliases:
        return []
    choices = list(aliases)
    best_matches: dict[str, Match] = {}
    for fragment, observed in _model_fragments(observations).items():
        candidates = process.extract(
            fragment,
            choices,
            scorer=fuzz.ratio,
            score_cutoff=_MIN_FUZZY_SCORE * 100,
            limit=_FUZZY_CANDIDATES_PER_FRAGMENT,
        )
        for target, similarity, _ in candidates:
            score = _score_fragment(target, fragment, similarity)
            for item, identifier in aliases[target]:
                candidate = Match(
                    item=item,
                    matched_identifier=identifier,
                    observed_text=observed,
                    score=score,
                    is_exact=False,
                )
                previous = best_matches.get(item.id)
                if previous is None or candidate.score > previous.score:
                    best_matches[item.id] = candidate
    return sorted(
        best_matches.values(), key=lambda match: (match.score, match.item.id), reverse=True
    )[:_MAX_MATCHES]


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

    matches = _fuzzy_matches(observations, items)
    status = "suggestions" if matches else "not_found"
    return ScanResult(status=status, detected_text=observed_text, matches=matches)
