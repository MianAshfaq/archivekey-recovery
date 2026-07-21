from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass


# Ordered by observed usefulness. These are structural tokens, not a leaked
# password list. Users can add their own possible guesses and clues in the UI.
COMMON_NUMBERS = ("123", "1234", "786", "1", "12", "007", "000", "111")
COMMON_SEPARATORS = ("@", "", "_", "-", ".", "#", "!")
TRAILING_SYMBOLS = ("!", "@", "#", "%", "$", "&", "*", "+", "_")
LEET_SUBSTITUTIONS: dict[str, tuple[str, ...]] = {
    "a": ("@", "4"),
    "e": ("3",),
    "i": ("1",),
    "o": ("0",),
    "s": ("$", "5"),
    "t": ("7",),
}

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


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _guess_parts(value: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Extract reusable stems and observed structure from an uncertain guess."""
    value = value.strip()
    if not value:
        return (), (), (), ()

    number_matches = list(re.finditer(r"\d{1,8}", value))
    numbers = tuple(dict.fromkeys(match.group(0) for match in number_matches))
    symbol_chars = tuple(
        dict.fromkeys(char for char in value if not char.isalnum() and not char.isspace())
    )
    separators = tuple(
        dict.fromkeys(
            match.group(0)
            for match in re.finditer(r"(?<=[A-Za-z])[^A-Za-z0-9\s]+(?=\d)", value)
        )
    )

    stems: list[str] = []
    if number_matches:
        raw_prefix = value[: number_matches[0].start()].strip()
        if raw_prefix:
            stems.append(raw_prefix)
            cleaned_prefix = raw_prefix.rstrip("@_-.#!$%&*+ ")
            if cleaned_prefix:
                stems.append(cleaned_prefix)
    else:
        without_terminal_symbols = re.sub(r"[^A-Za-z0-9\s]+$", "", value).strip()
        if without_terminal_symbols:
            stems.append(without_terminal_symbols)

    alpha_words = re.findall(r"[A-Za-z]+", value)
    if alpha_words:
        stems.append("".join(alpha_words))
        if len(alpha_words) > 1:
            stems.append(" ".join(alpha_words))

    return tuple(dict.fromkeys(stems)), numbers, symbol_chars, separators


def _leet_variants(value: str, limit: int = 16) -> tuple[str, ...]:
    """Return bounded, explainable single-change and common all-change variants."""
    variants: list[str] = []
    lowered = value.casefold()
    for index, char in enumerate(lowered):
        for replacement in LEET_SUBSTITUTIONS.get(char, ()):
            variants.append(value[:index] + replacement + value[index + 1 :])
            if len(variants) >= limit:
                return tuple(dict.fromkeys(variants))

    primary = "".join(LEET_SUBSTITUTIONS.get(char.casefold(), (char,))[0] for char in value)
    if primary != value:
        variants.append(primary)
    return tuple(dict.fromkeys(variants[:limit]))


def _replace_match(value: str, match: re.Match[str], replacement: str) -> str:
    return value[: match.start()] + replacement + value[match.end() :]


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

    guesses = list(_clean_lines(exact))
    remembered_clues = list(_clean_lines(clues))

    observed_numbers: list[str] = []
    observed_symbols: list[str] = []
    observed_separators: list[str] = []
    guess_parts: list[tuple[str, tuple[str, ...]]] = []

    for index, value in enumerate(guesses):
        add(value, -100.0 + index * 0.001, "possible-guess")
        stems, numbers_found, symbols_found, separators_found = _guess_parts(value)
        guess_parts.append((value, stems))
        observed_numbers.extend(numbers_found)
        observed_symbols.extend(symbols_found)
        observed_separators.extend(separators_found)

    for clue in remembered_clues:
        if clue.isdigit():
            observed_numbers.append(clue)

    bases: list[tuple[str, float, str]] = []
    seen_bases: set[str] = set()

    def add_base(value: str, score: float, source: str) -> None:
        if value and value not in seen_bases:
            seen_bases.add(value)
            bases.append((value, score, source))

    # A possible guess is both a direct candidate and a structural seed. This
    # fixes the old behavior where the left-hand UI field was tested literally
    # but never mutated or mixed with the clue field.
    for guess_index, (_guess, stems) in enumerate(guess_parts):
        seed_cost = -8.0 + _rank_cost(guess_index, 0.08)
        for stem_index, stem in enumerate(stems):
            for variant_index, variant in enumerate(_case_variants(stem)):
                add_base(
                    variant,
                    seed_cost + stem_index * 0.12 + variant_index * 0.08,
                    "guess-seed",
                )

    for clue_index, clue in enumerate(remembered_clues):
        clue_cost = _rank_cost(clue_index, 0.12)
        for variant_index, variant in enumerate(_case_variants(clue)):
            add_base(variant, clue_cost + variant_index * 0.12, "clue")
        for alias_index, alias in enumerate(_acronyms(clue)):
            add_base(alias, clue_cost + 0.25 + alias_index * 0.08, "acronym")

    numbers = _ordered_unique(
        (*observed_numbers, *(str(year) for year in years), *COMMON_NUMBERS)
    )
    separators = _ordered_unique((*observed_separators, *COMMON_SEPARATORS))
    symbols = _ordered_unique((*observed_symbols, *TRAILING_SYMBOLS))

    # Direct mutations preserve the remembered guess's structure while varying
    # its most error-prone details: case, numeric token, separator, and ending.
    for guess_index, (guess, _stems) in enumerate(guess_parts):
        mutation_base = -20.0 + _rank_cost(guess_index, 0.06)
        for variant_index, variant in enumerate(_case_variants(guess)):
            add(variant, mutation_base + variant_index * 0.06, "guess-case-mutation")

        for number_match_index, number_match in enumerate(list(re.finditer(r"\d{1,8}", guess))[:2]):
            for number_index, number in enumerate(numbers[:48]):
                if number == number_match.group(0):
                    continue
                add(
                    _replace_match(guess, number_match, number),
                    mutation_base
                    + 0.35
                    + number_match_index * 0.08
                    + _rank_cost(number_index, 0.06),
                    "guess-number-mutation",
                )

        separator_matches = list(
            re.finditer(r"(?<=[A-Za-z])[^A-Za-z0-9\s]+(?=\d)", guess)
        )
        for separator_match in separator_matches[:2]:
            for separator_index, separator in enumerate(separators):
                if separator == separator_match.group(0):
                    continue
                add(
                    _replace_match(guess, separator_match, separator),
                    mutation_base + 0.48 + _rank_cost(separator_index, 0.06),
                    "guess-separator-mutation",
                )

        terminal = re.search(r"[^A-Za-z0-9\s]+$", guess)
        terminal_core = guess[: terminal.start()] if terminal else guess
        if terminal or (guess and guess[-1].isdigit()):
            for symbol_index, symbol in enumerate(symbols):
                for repeat in (1, 2, 3):
                    add(
                        terminal_core + symbol * repeat,
                        mutation_base
                        + 0.58
                        + (repeat - 1) * 0.18
                        + _rank_cost(symbol_index, 0.05),
                        "guess-ending-mutation",
                    )

    # Tier 1: direct bases and a high-probability human grammar:
    # STEM + separator + number + trailing symbol.
    for base, base_score, source in bases:
        add(base, base_score, source)
        for number_index, number in enumerate(numbers):
            number_cost = _rank_cost(number_index, 0.15)
            for separator_index, separator in enumerate(separators):
                separator_cost = _rank_cost(separator_index, 0.10)
                prefix = f"{base}{separator}{number}"
                add(prefix, base_score + 0.70 + number_cost + separator_cost, "stem+separator+number")
                for symbol_index, symbol in enumerate(symbols):
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

        # Leet substitutions are deliberately bounded so they improve coverage
        # without dominating the personalized grammar.
        for leet_index, leet in enumerate(_leet_variants(base)):
            add(
                leet,
                base_score + 2.6 + _rank_cost(leet_index, 0.08),
                "bounded-leet-mutation",
            )

    # Tier 2: reversals and leading symbols/numbers.
    for base, base_score, _source in bases:
        for number_index, number in enumerate(numbers):
            number_cost = _rank_cost(number_index, 0.15)
            for separator_index, separator in enumerate(separators):
                cost = base_score + 1.55 + number_cost + _rank_cost(separator_index, 0.10)
                add(f"{number}{separator}{base}", cost, "number+separator+stem")
                for symbol_index, symbol in enumerate(symbols[:5]):
                    symbol_cost = _rank_cost(symbol_index, 0.08)
                    add(f"{symbol}{base}{separator}{number}", cost + symbol_cost, "symbol+stem+number")

    # Tier 3: combinations of two remembered concepts.
    for left_index, (left, left_score, _left_source) in enumerate(bases):
        for right_index, (right, right_score, _right_source) in enumerate(bases):
            if left_index == right_index or left.casefold() == right.casefold():
                continue
            for separator_index, separator in enumerate(separators):
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
