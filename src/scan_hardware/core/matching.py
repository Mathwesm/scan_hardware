"""Normalize printed identifiers and rank catalog candidates."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process

from scan_hardware.curation import verified_board_revisions
from scan_hardware.models.item import Category, Item, Match, ScanResult

_WORD_PATTERN = re.compile(r"[A-Z0-9]+")
_B550_OCR_PATTERN = re.compile(r"B[S5]{2}[O0]")
_BOARD_FAMILY_WORDS = ("PRIME", "TUF", "GAMING")
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


def _identifier_aliases(item: Item, identifier: str) -> set[str]:
    """Include a printed model code without a catalog-added brand prefix."""
    normalized = normalize_identifier(identifier)
    aliases = {normalized}
    brand = normalize_identifier(item.brand)
    if normalized.startswith(brand) and len(normalized) - len(brand) >= MIN_IDENTIFIER_LENGTH:
        aliases.add(normalized[len(brand) :])
    return aliases


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
            aliases = _identifier_aliases(item, identifier)
            if all_fragments.isdisjoint(aliases):
                continue
            for observed, values in fragments:
                if not values.isdisjoint(aliases):
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


def _verified_revision_matches(observations: list[str], items: list[Item]) -> list[Match]:
    """Confirm a model family only when its manufacturer-listed PCB revision is read."""
    revisions = verified_board_revisions()
    matches: list[Match] = []
    for item in items:
        board = revisions.get(item.id)
        if board is None or normalize_identifier(item.model) != normalize_identifier(
            board.catalog_model
        ):
            continue
        model_code = normalize_identifier(board.model_code)
        for revision in board.pcb_revisions:
            exact_suffix = f"{model_code}REV{normalize_identifier(revision)}"
            observed = next(
                (
                    line
                    for line in observations
                    if normalize_identifier(line).endswith(exact_suffix)
                ),
                None,
            )
            if observed is not None:
                matches.append(
                    Match(
                        item=item,
                        matched_identifier=f"{board.model_code} REV {revision}",
                        observed_text=observed,
                        score=1.0,
                        is_exact=True,
                    )
                )
                break
    return matches


def _model_fragments(observations: list[str]) -> dict[str, tuple[str, bool]]:
    """Keep code-like OCR spans and track corrected B550 readings."""
    fragments: dict[str, tuple[str, bool]] = {}
    for observed in observations:
        for raw in _candidate_fragments(observed):
            corrected = _B550_OCR_PATTERN.sub("B550", raw)
            for fragment, was_corrected in {(raw, False), (corrected, corrected != raw)}:
                if (
                    _MIN_FUZZY_FRAGMENT_LENGTH <= len(fragment) <= _MAX_FUZZY_FRAGMENT_LENGTH
                    and sum(character.isdigit() for character in fragment) >= _MIN_MODEL_DIGITS
                    and any(character.isalpha() for character in fragment)
                ):
                    previous = fragments.get(fragment)
                    if previous is None or (was_corrected, len(observed)) < (
                        previous[1],
                        len(previous[0]),
                    ):
                        fragments[fragment] = (observed, was_corrected)
    return fragments


def _fuzzy_aliases(item: Item, identifier: str) -> set[str]:
    """Include the board code alone for fuzzy suggestions without confirming it."""
    aliases = _identifier_aliases(item, identifier)
    if item.category is Category.MOTHERBOARD:
        for alias in tuple(aliases):
            position = alias.find("B550")
            if position > 0 and len(alias) - position >= _MIN_FUZZY_FRAGMENT_LENGTH:
                aliases.add(alias[position:])
    return aliases


def _available_fuzzy_choices(choices: list[str], observed: str, was_corrected: bool) -> list[str]:
    """Restrict OCR-corrected B550 codes to the observed motherboard family."""
    if not was_corrected:
        return choices
    family_words = [word for word in _BOARD_FAMILY_WORDS if word in observed.upper()]
    return [
        choice
        for choice in choices
        if "B550" in choice and all(word in choice for word in family_words)
    ]


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
            for alias in _fuzzy_aliases(item, identifier):
                aliases.setdefault(alias, []).append((item, identifier))
    if not aliases:
        return []
    choices = list(aliases)
    best_matches: dict[str, Match] = {}
    for fragment, (observed, was_corrected) in _model_fragments(observations).items():
        available = _available_fuzzy_choices(choices, observed, was_corrected)
        candidates = process.extract(
            fragment,
            available,
            scorer=fuzz.ratio,
            score_cutoff=_MIN_FUZZY_SCORE * 100,
            limit=_FUZZY_CANDIDATES_PER_FRAGMENT,
        )
        for target, similarity, _ in candidates:
            score = (
                min(_score_fragment(target, fragment, similarity), 0.93)
                if was_corrected
                else _score_fragment(target, fragment, similarity)
            )
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
    revision_matches = _verified_revision_matches(observations, items)
    if revision_matches:
        return ScanResult(status="matched", detected_text=observed_text, matches=revision_matches)

    exact_matches = _exact_matches(observations, items)
    if exact_matches:
        return ScanResult(
            status="matched", detected_text=observed_text, matches=exact_matches[:_MAX_MATCHES]
        )

    matches = _fuzzy_matches(observations, items)
    status = "suggestions" if matches else "not_found"
    return ScanResult(status=status, detected_text=observed_text, matches=matches)
