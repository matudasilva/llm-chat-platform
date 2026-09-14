"""BM25 ranking and skip-and-continue selection over the Mode B corpus.

ORQ-37 T16. Ports `experiments/long_context_conversational_memory/replay.py`'s
`rank_bm25`/`_pack_retrieved_events` into `app/`, reimplemented rather than
imported (AC23: no module under `app/` imports from `experiments/`).

Four constants equal `replay.py:19-22` by value (AC19). Three declared
divergences from the experiment, each already recorded in §Diseño 9:

1. **Document unit**: the experiment's unit is an `Event` (a whole exchange);
   ours is `CorpusEvent`, whose `document_text` already reproduces
   `Event.document_text()`'s `"\n".join(contents)` rule via `TurnUnit` (T10/T15).
2. **Tie-break**: the experiment's third key is
   `event.event_id.encode("utf-8")`, which has no analogue here --
   `CorpusEvent.event_id` is already `min(sequence) of the turn` (T15), so the
   tie-break is `(-score, event_id)`, a total order with no third key needed.
3. **Budget**: the experiment packs against a token budget
   (`E_RETRIEVED_TOKEN_BUDGET`, via a tokenizer encoding); this ORQ's combined
   budget (§Diseño 7) is characters throughout. AC29 packs against a character
   budget instead -- `BM25_TOP_K` is still checked BEFORE the size test, and
   an oversized event is skipped (not a `break`) so a later smaller one can
   still be admitted, exactly as `_pack_retrieved_events` does.

Not implemented here: `filter_event_scope`'s tenant/conversation filtering has
no analogue either -- `fetch_ordered` already returns exactly one owned
conversation (ADR-011 §2), so the corpus this ranks is already scoped by the
time it reaches this module.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from .retrieval_corpus import CorpusEvent

# Equal to replay.py:19-22 by value (AC19).
BM25_QUERY_TOKEN_CAP = 256
BM25_TOP_K = 5
BM25_K1 = 1.2
BM25_B = 0.75

_LEXICAL_TOKEN = re.compile(r"(?u)[^\W_]+")


def lexical_tokens(text: str) -> tuple[str, ...]:
    """NFKC-normalize, casefold, and split on the experiment's exact pattern."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(_LEXICAL_TOKEN.findall(normalized))


def query_tokens(text: str) -> tuple[str, ...]:
    """First-occurrence unique lexical tokens of `text`, capped at 256.

    Deduped THEN capped, in that order -- not "cap 256" -- matching
    `contextual_query_tokens`'s own declared order (§Diseño 9's divergence
    table).
    """
    seen: set[str] = set()
    unique: list[str] = []
    for token in lexical_tokens(text):
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return tuple(unique[:BM25_QUERY_TOKEN_CAP])


@dataclass(frozen=True, slots=True)
class RankedEvent:
    event: CorpusEvent
    score: float


def rank_events(
    events: Sequence[CorpusEvent], query: Sequence[str]
) -> tuple[RankedEvent, ...]:
    """Rank `events` by BM25 against `query`. Empty input yields empty output.

    The exact registered BM25 (`replay.py:316-364`): `average_length` and
    `document_frequency` are computed once over the WHOLE corpus, then scored
    per document. `average_length == 0` (an all-empty corpus) is a real input
    a caller might construct in a test but never in production -- `fetch_ordered`
    never returns empty-content messages -- so it raises rather than silently
    dividing by zero.
    """
    if not events:
        return ()
    document_tokens = {event.event_id: lexical_tokens(event.document_text) for event in events}
    average_length = sum(len(tokens) for tokens in document_tokens.values()) / len(events)
    if average_length == 0:
        raise ValueError("BM25 average document length is zero")
    document_frequency = Counter(
        token for tokens in document_tokens.values() for token in set(tokens)
    )
    document_count = len(events)
    normalized_query = tuple(query[:BM25_QUERY_TOKEN_CAP])

    ranked: list[RankedEvent] = []
    for event in events:
        tokens = document_tokens[event.event_id]
        frequencies = Counter(tokens)
        score = 0.0
        for term in normalized_query:
            frequency = frequencies[term]
            if not frequency:
                continue
            df = document_frequency[term]
            inverse_document_frequency = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * len(tokens) / average_length)
            score += inverse_document_frequency * frequency * (BM25_K1 + 1) / denominator
        if not math.isfinite(score):
            raise ValueError("BM25 produced a non-finite score")
        ranked.append(RankedEvent(event=event, score=score))

    # (-score, event_id): total, because event_id is unique per T15's
    # construction -- no third tie-break key is needed (see module docstring).
    ranked.sort(key=lambda item: (-item.score, item.event.event_id))
    return tuple(ranked)


def pack_selected_events(
    ranked: Sequence[RankedEvent],
    *,
    max_chars: int,
    excluded_ids: frozenset[int] = frozenset(),
) -> tuple[tuple[CorpusEvent, ...], int]:
    """Skip-and-continue selection against a CHARACTER budget (AC29).

    Reproduces `_pack_retrieved_events`'s control flow exactly: the
    `BM25_TOP_K` count check runs BEFORE the size test and `break`s (once
    `BM25_TOP_K` accepted events exist, ranking lower cannot change that); an
    oversized event is skipped with `continue`, not a `break`, so a later,
    smaller event can still be admitted.
    """
    accepted: list[CorpusEvent] = []
    used = 0
    for ranked_event in ranked:
        event = ranked_event.event
        if event.event_id in excluded_ids:
            continue
        if len(accepted) == BM25_TOP_K:
            break
        size = len(event.document_text)
        if size <= max_chars - used:
            accepted.append(event)
            used += size
    return tuple(accepted), used
