from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass


# Ordered by observed usefulness. These are structural tokens, not a leaked
# password list. Users can add their own exact values and clues in the UI.
COMMON_NUMBERS = ("123", "1234", "786", "1", "12", "007", "000", "111")
COMMON_SEPARATORS = ("@", "", "_", "-", ".", "#", "!")
TRAILING_SYMBOLS = ("!", "@", "#", "%", "$", "&", "*", "+", "_")

# Small, transparent context expansions. They make abbreviations searchable
# when the user remembers a place but not whether its short form was used.
CONTEXT_ALIASES: dict[str, tuple[str, ...]] = {
    "united arab emirates": ("UAE",),
    "united kingdom": ("UK", "GB"),
    "united states": ("USA", "US"),
    "european union": ("EU",),
    "new york": ("NY", "NYC"),
    "los angeles": ("LA", "LAX"),
}


@dataclass(frozen=True)
class Candidate:
    value: str
    score: float
    rule: str


def _case_variants(value: str) -> tuple[str, ...]:
    value = value.strip()
    if not value:
        return ()
    variants = (value, value.lower(), value.upper(), value.capitalize(), value.title())
    return tuple(dict.fromkeys(variants))


def _clean_lines(values: Iterable[str]) -> Iterator[str]:
    for raw in values:
        value = raw.strip()
        if value:
            yield value


def _acronyms(value: str) -> tuple[str, ...]:
    words = re.findall(r"[A-Za-z0-9]+", value)
    output: list[str] = []
    if len(words) >= 2:
        output.append("".join(word[0] for word in words).upper())
    compact_caps = "".join(char for char in value if char.isupper())
    if len(compact_caps) >= 2:
        output.append(compact_caps)
    output.extend(CONTEXT_ALIASES.get(value.casefold().strip(), ()))
    return tuple(dict.fromkeys(item for item in output if item))


def _rank_cost(index: int, scale: float = 0.2) -> float:
    """Small negative-log-style cost: common components remain earlier."""
    return math.log2(index + 2) * scale


def generate_ranked_candidates(
    exact: Iterable[str],
    clues: Iterable[str],
    years: Iterable[int] = (),
    max_candidates: int = 250_000,
) -> list[Candidate]:
    """Build a probability-ordered grammar of personalized password candidates.

    Scores are relative search costs, not claimed universal probabilities. Lower
    scores are tried first. The grammar focuses on human constructions such as
    ``acronym@number%`` instead of enumerating the full character space.
    """
    if max_candidates < 1:
        return []

    pool_limit = max(5_000, max_candidates * 3)
    pool: dict[str, tuple[float, int, str]] = {}
    sequence = 0

    def add(value: str, score: float, rule: str) -> None:
        nonlocal sequence
        if not value:
            return
        previous = pool.get(value)
        if previous is None:
            if len(pool) >= pool_limit:
                return
            pool[value] = (score, sequence, rule)
            sequence += 1
        elif score < previous[0]:
            pool[value] = (score, previous[1], rule)

    for index, value in enumerate(_clean_lines(exact)):
        add(value, -100.0 + index * 0.001, "exact")

    bases: list[tuple[str, float, str]] = []
    seen_bases: set[str] = set()

    def add_base(value: str, score: float, source: str) -> None:
        if value and value not in seen_bases:
            seen_bases.add(value)
            bases.append((value, score, source))

    for clue_index, clue in enumerate(_clean_lines(clues)):
        clue_cost = _rank_cost(clue_index, 0.12)
        for variant_index, variant in enumerate(_case_variants(clue)):
            add_base(variant, clue_cost + variant_index * 0.12, "clue")
        for alias_index, alias in enumerate(_acronyms(clue)):
            add_base(alias, clue_cost + 0.25 + alias_index * 0.08, "acronym")

    numbers = list(dict.fromkeys((*COMMON_NUMBERS, *(str(year) for year in years))))

    # Tier 1: direct bases and a high-probability human grammar:
    # STEM + separator + number + trailing symbol.
    for base, base_score, source in bases:
        add(base, base_score, source)
        for number_index, number in enumerate(numbers):
            number_cost = _rank_cost(number_index, 0.15)
            for separator_index, separator in enumerate(COMMON_SEPARATORS):
                separator_cost = _rank_cost(separator_index, 0.10)
                prefix = f"{base}{separator}{number}"
                add(prefix, base_score + 0.70 + number_cost + separator_cost, "stem+separator+number")
                for symbol_index, symbol in enumerate(TRAILING_SYMBOLS):
                    symbol_cost = _rank_cost(symbol_index, 0.08)
                    add(
                        prefix + symbol,
                        base_score
                        + 0.82
                        + number_cost
                        + separator_cost
                        + symbol_cost,
                        "stem+separator+number+symbol",
                    )
                    # Repeated terminal punctuation is a distinct human pattern,
                    # not just an accidental duplicate. Keep runs bounded so the
                    # grammar gains coverage without exploding combinatorially.
                    add(
                        prefix + symbol * 2,
                        base_score + 1.02 + number_cost + separator_cost + symbol_cost,
                        "stem+separator+number+repeated-symbol",
                    )
                    add(
                        prefix + symbol * 3,
                        base_score + 1.32 + number_cost + separator_cost + symbol_cost,
                        "stem+separator+number+repeated-symbol",
                    )

    # Tier 2: reversals and leading symbols/numbers.
    for base, base_score, _source in bases:
        for number_index, number in enumerate(numbers):
            number_cost = _rank_cost(number_index, 0.15)
            for separator_index, separator in enumerate(COMMON_SEPARATORS):
                cost = base_score + 1.55 + number_cost + _rank_cost(separator_index, 0.10)
                add(f"{number}{separator}{base}", cost, "number+separator+stem")
                for symbol_index, symbol in enumerate(TRAILING_SYMBOLS[:5]):
                    symbol_cost = _rank_cost(symbol_index, 0.08)
                    add(f"{symbol}{base}{separator}{number}", cost + symbol_cost, "symbol+stem+number")

    # Tier 3: combinations of two remembered concepts.
    for left_index, (left, left_score, _left_source) in enumerate(bases):
        for right_index, (right, right_score, _right_source) in enumerate(bases):
            if left_index == right_index or left.casefold() == right.casefold():
                continue
            for separator_index, separator in enumerate(COMMON_SEPARATORS):
                combined = f"{left}{separator}{right}"
                combined_score = 2.2 + left_score + right_score + _rank_cost(separator_index, 0.10)
                add(combined, combined_score, "stem+separator+stem")
                for number_index, number in enumerate(numbers[:6]):
                    add(
                        f"{combined}{separator or '@'}{number}",
                        combined_score + 0.45 + _rank_cost(number_index, 0.15),
                        "two-stems+number",
                    )

    ranked = [Candidate(value, score, rule) for value, (score, _seq, rule) in pool.items()]
    ranked.sort(key=lambda item: (item.score, pool[item.value][1]))
    return ranked[:max_candidates]


def generate_candidates(
    exact: Iterable[str],
    clues: Iterable[str],
    years: Iterable[int] = (),
    max_candidates: int = 250_000,
) -> list[str]:
    """Backward-compatible string-only view of the ranked candidate grammar."""
    return [
        candidate.value
        for candidate in generate_ranked_candidates(exact, clues, years, max_candidates)
    ]
