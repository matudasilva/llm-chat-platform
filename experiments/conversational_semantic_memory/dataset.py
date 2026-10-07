"""Strict offline records keep provenance, scope and analysis membership explicit."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .events import canonical_bytes, sha256_hex

LANGUAGES = ('en', 'es')
FAMILIES = ('stable_fact', 'duplicate', 'update', 'contradiction_trap',
            'distractor', 'isolation_canary', 'no_memory', 'historical', 'prohibited')
KINDS = ('fact', 'preference', 'constraint', 'decision', 'goal')


def normalize(value: str) -> str:
    return unicodedata.normalize('NFKC', value).casefold()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def keys(raw: Any, expected: str) -> None:
    require(isinstance(raw, dict) and set(raw) == set(expected.split()),
            f'unexpected fields; expected {expected}')


def nonempty(value: Any) -> str:
    require(isinstance(value, str) and bool(value.strip()), 'expected nonempty string')
    return value


def identifier(value: Any) -> str:
    value = nonempty(value)
    require(str(UUID(value)) == value, 'expected canonical UUID')
    return value


def strings(value: Any) -> tuple[str, ...]:
    require(isinstance(value, list), 'expected string array')
    result = tuple(nonempty(item) for item in value)
    require(len(result) == len(set(result)), 'duplicate array entries')
    return result


def integer(value: Any) -> int:
    require(type(value) is int and value >= 0, 'expected nonnegative integer')
    return value


def read_json(path: Path) -> Any:
    return decode_json(path.read_text(encoding='utf-8'))


def decode_json(data: str | bytes) -> Any:
    """Keep duplicate-key rejection identical for files and audited pool bytes."""
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f'duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda value: require(False, f'invalid JSON: {value}'))


@dataclass(frozen=True)
class Message:
    message_id: str
    sequence: int
    role: str
    content: str

    @classmethod
    def parse(cls, raw: Any) -> Message:
        keys(raw, 'message_id sequence role content')
        require(raw['role'] in ('user', 'assistant'), 'invalid role')
        return cls(identifier(raw['message_id']), integer(raw['sequence']),
                   raw['role'], nonempty(raw['content']))


@dataclass(frozen=True)
class Canary:
    tenant_id: str
    conversation_id: str
    value_id: str
    turns: tuple[Message, ...]


@dataclass(frozen=True)
class Step:
    step_id: str
    family: str
    after_sequence: int
    question: str
    gold_values: tuple[str, ...]
    stale_values: tuple[str, ...]
    gold_source_message_ids: tuple[str, ...]
    semantic: bool
    h3: bool
    stale_eligible: bool
    gold_decision: str
    lexical_stratum: str | None

    @classmethod
    def parse(cls, raw: Any) -> Step:
        keys(raw, 'step_id family after_sequence question gold_values stale_values '
                  'gold_source_message_ids semantic h3 stale_eligible gold_decision lexical_stratum')
        require(raw['family'] in FAMILIES, 'invalid family')
        for flag in ('semantic', 'h3', 'stale_eligible'):
            require(type(raw[flag]) is bool, f'invalid {flag}')
        require(raw['gold_decision'] in ('answer', 'abstain'), 'invalid decision')
        require(raw['lexical_stratum'] in STRATA if raw['semantic'] else raw['lexical_stratum'] is None,
                'invalid lexical stratum')
        result = cls(identifier(raw['step_id']), raw['family'], integer(raw['after_sequence']),
                     nonempty(raw['question']), strings(raw['gold_values']),
                     strings(raw['stale_values']), strings(raw['gold_source_message_ids']),
                     raw['semantic'], raw['h3'], raw['stale_eligible'], raw['gold_decision'], raw['lexical_stratum'])
        require(bool(result.gold_values) == (result.gold_decision == 'answer'), 'gold decision mismatch')
        require(not set(result.gold_values) & set(result.stale_values), 'gold/stale overlap')
        require(result.stale_eligible == bool(result.stale_values), 'stale eligibility mismatch')
        require(not (result.semantic and result.h3), 'analysis sets must not overlap')
        require(result.h3 == (result.family in ('no_memory', 'historical')), 'H3 family mismatch')
        require(not result.semantic or bool(result.gold_source_message_ids), 'missing semantic provenance')
        return result


@dataclass(frozen=True)
class Case:
    conceptual_case_id: str
    language: str
    tenant_id: str
    conversation_id: str
    family: str
    slot: str
    value_set: tuple[str, ...]
    question_template_id: str
    filler_topic_set: tuple[str, ...]
    turns: tuple[Message, ...]
    steps: tuple[Step, ...]
    canaries: tuple[Canary, ...]

    @property
    def structural_fingerprint(self) -> str:
        return fingerprint(self.family, self.slot, self.value_set,
                           self.question_template_id, self.filler_topic_set)


def fingerprint(family: str, slot: str, values: tuple[str, ...],
                template: str, fillers: tuple[str, ...]) -> str:
    """Ignore identity and language so relabelled duplicates remain duplicates."""
    return sha256_hex(canonical_bytes([family, slot, sorted(values), template, sorted(fillers)]))


def parse_case(raw: Any) -> Case:
    keys(raw, 'conceptual_case_id language tenant_id conversation_id family slot value_set '
              'question_template_id filler_topic_set turns steps canaries')
    require(raw['language'] in LANGUAGES, 'invalid language')
    require(raw['family'] in FAMILIES, 'invalid family')
    require(isinstance(raw['turns'], list) and bool(raw['turns']), 'missing turns')
    turns = tuple(Message.parse(message) for message in raw['turns'])
    require([m.sequence for m in turns] == list(range(1, len(turns) + 1)), 'noncontiguous sequence')
    by_id = {m.message_id: m for m in turns}
    require(len(by_id) == len(turns), 'duplicate message id')
    require(isinstance(raw['steps'], list) and bool(raw['steps']), 'missing steps')
    steps = tuple(Step.parse(step) for step in raw['steps'])
    require(len({s.step_id for s in steps}) == len(steps), 'duplicate step id')
    require(any(s.semantic for s in steps), 'every conceptual case requires a semantic step')
    values = strings(raw['value_set'])
    require(bool(values), 'empty value universe')
    for step in steps:
        require(any(s.family == raw['family'] for s in steps), 'case family not exercised')
        require(step.after_sequence in {m.sequence for m in turns}, 'step outside timeline')
        require(set(step.gold_values + step.stale_values) <= set(values), 'unknown value')
        for source in step.gold_source_message_ids:
            require(source in by_id, 'unknown source message')
            require(by_id[source].role == 'user', 'source must be user')
            require(by_id[source].sequence <= step.after_sequence, 'future source message')
    require(isinstance(raw['canaries'], list) and len(raw['canaries']) == 2, 'two isolation scopes required')
    canaries = []
    tenant, conversation = identifier(raw['tenant_id']), identifier(raw['conversation_id'])
    for canary in raw['canaries']:
        keys(canary, 'tenant_id conversation_id value_id turns')
        require(isinstance(canary['turns'], list), 'invalid canary turns')
        messages = tuple(Message.parse(m) for m in canary['turns'])
        require(len(messages) == 2 and [m.role for m in messages] == ['user', 'assistant']
                and [m.sequence for m in messages] == [1, 2], 'invalid canary turn')
        item = Canary(identifier(canary['tenant_id']), identifier(canary['conversation_id']),
                      nonempty(canary['value_id']), messages)
        require(item.conversation_id != conversation, 'canary in target scope')
        require(item.value_id in values, 'unknown canary value')
        require(all(item.value_id not in s.gold_values + s.stale_values for s in steps),
                'canary collides with target values')
        canaries.append(item)
    require(sum(c.tenant_id == tenant for c in canaries) == 1, 'missing sibling or foreign tenant')
    require(len({c.conversation_id for c in canaries}) == 2, 'duplicate canary conversation')
    require(len({c.value_id for c in canaries}) == 2, 'duplicate canary value')
    return Case(identifier(raw['conceptual_case_id']), raw['language'], tenant, conversation,
                raw['family'], nonempty(raw['slot']), values, nonempty(raw['question_template_id']),
                strings(raw['filler_topic_set']), turns, steps, tuple(canaries))


@dataclass(frozen=True)
class Dataset:
    seed: int
    pool_sha256: str
    cases: tuple[Case, ...]


def validate_pairing(cases: tuple[Case, ...]) -> None:
    groups: dict[str, list[Case]] = {}
    fingerprints: dict[str, str] = {}
    conversations: set[str] = set()
    message_ids: set[str] = set()
    for case in cases:
        groups.setdefault(case.conceptual_case_id, []).append(case)
        owner = fingerprints.setdefault(case.structural_fingerprint, case.conceptual_case_id)
        require(owner == case.conceptual_case_id, 'structural duplicate under different id')
        for conversation, messages in [(case.conversation_id, case.turns)] + [
                (c.conversation_id, c.turns) for c in case.canaries]:
            require(conversation not in conversations, 'conversation reused')
            conversations.add(conversation)
            for message in messages:
                require(message.message_id not in message_ids, 'message id reused')
                message_ids.add(message.message_id)
    for pair in groups.values():
        require(sorted(c.language for c in pair) == list(LANGUAGES), 'EN/ES one-to-one pairing required')
        require(len({c.structural_fingerprint for c in pair}) == 1, 'paired structure differs')
        def step_shape(case: Case) -> list[Any]:
            return [(s.family, s.after_sequence, s.gold_values, s.stale_values, s.semantic, s.h3,
                     s.stale_eligible, s.gold_decision, s.lexical_stratum,
                     tuple(next(m.sequence for m in case.turns if m.message_id == source)
                           for source in s.gold_source_message_ids)) for s in case.steps]
        require(step_shape(pair[0]) == step_shape(pair[1]), 'paired step semantics differ')


def load_dataset(path: Path) -> Dataset:
    raw = read_json(path)
    keys(raw, 'schema_version seed pool_sha256 cases')
    require(raw['schema_version'] == 'orq39-dataset-v1', 'unknown dataset schema')
    seed = integer(raw['seed'])
    digest = nonempty(raw['pool_sha256'])
    require(len(digest) == 64 and all(c in '0123456789abcdef' for c in digest), 'invalid pool digest')
    require(isinstance(raw['cases'], list) and bool(raw['cases']), 'missing cases')
    cases = tuple(parse_case(case) for case in raw['cases'])
    validate_pairing(cases)
    return Dataset(seed, digest, cases)


def load_pool(path: Path) -> dict[str, Any]:
    """Reject malformed references before any instantiation or capacity count."""
    return parse_pool(read_json(path))


def parse_pool(pool: Any) -> dict[str, Any]:
    import re

    keys(pool, 'schema_version pool slots values question_templates filler_topics prohibited_fixtures')
    require(pool['schema_version'] == 'orq39-pool-v1', 'unknown pool schema')
    require(pool['pool'] in ('dev', 'heldout'), 'invalid pool name')
    for collection in ('slots', 'values', 'question_templates', 'filler_topics'):
        require(isinstance(pool[collection], list) and bool(pool[collection]), f'empty {collection}')
        ids = [nonempty(item['id']) for item in pool[collection]]
        require(len(ids) == len(set(ids)), f'duplicate {collection} id')
    def bilingual(raw: Any, aliases: bool = False) -> None:
        keys(raw, 'en es')
        for language in LANGUAGES:
            if aliases:
                require(bool(strings(raw[language])), 'empty aliases')
            else:
                nonempty(raw[language])
    value_ids = {v['id'] for v in pool['values']}
    for value in pool['values']:
        keys(value, 'id aliases')
        bilingual(value['aliases'], True)
    for slot in pool['slots']:
        keys(slot, 'id kind labels value_ids families key_terms assertions retractions')
        require(bool(re.fullmatch('[a-z][a-z0-9_]*', slot['id'])), 'invalid slot key')
        require(slot['kind'] in KINDS, 'invalid attribute kind')
        bilingual(slot['labels'])
        bilingual(slot['key_terms'], True)
        bilingual(slot['assertions'], True)
        bilingual(slot['retractions'])
        require(all(len(v) >= 3 for v in slot['assertions'].values()), 'three assertions required')
        require(len(strings(slot['value_ids'])) == 4 and set(slot['value_ids']) <= value_ids,
                'slot requires initial, replacement and two canary values')
        require(bool(strings(slot['families'])) and set(slot['families']) <= set(FAMILIES), 'invalid families')
    slots = {s['id'] for s in pool['slots']}
    for template in pool['question_templates']:
        keys(template, 'id slot text variants paraphrase')
        keys(template['variants'], 'historical no_memory distractor prohibited')
        for variant in template['variants'].values():
            bilingual(variant)
        require(template['slot'] in slots, 'unknown template slot')
        bilingual(template['text'])
        bilingual(template['paraphrase'])
    require({t['slot'] for t in pool['question_templates']} == slots, 'missing slot question')
    for filler in pool['filler_topics']:
        keys(filler, 'id text')
        bilingual(filler['text'])
    require(bool(strings(pool['prohibited_fixtures'])), 'missing prohibited fixtures')
    require(all(re.fullmatch(r'SYNTHETIC-PROHIBITED-[A-Z]{3,12}-[0-9a-f]{8}', item)
                for item in pool['prohibited_fixtures']), 'invalid prohibited fixture')
    return pool


def pool_structures(pool: dict[str, Any]) -> tuple[tuple[str, str, tuple[str, ...], str, tuple[str, ...]], ...]:
    """The pool grammar permits each declared family, slot and matching template.

    Values are an ordered lifecycle bundle, never permuted to inflate capacity.
    All filler topics form one set; seed changes order only, not identity.
    """
    fillers = tuple(sorted(f['id'] for f in pool['filler_topics']))
    return tuple((family, slot['id'], tuple(slot['value_ids']), template['id'], fillers)
                 for slot in pool['slots'] for family in slot['families']
                 for template in pool['question_templates'] if template['slot'] == slot['id'])


STRATA = ('lexical_anchor', 'paraphrase')
PARAPHRASE_MAX_OVERLAP = 0.25
# Function words only: domain terms must remain visible to the diagnostic.
STOPWORDS = {
    'en': frozenset('a an the i me my we our you your it its this that these those '
                    'is am are was were be been do does did have has had to of in on at '
                    'for from with and or but as what which where when how would should '
                    'will can could please now'.split()),
    'es': frozenset('a al el la los las un una unos unas yo me mi mis nosotros nuestro '
                    'tú te tu tus se su sus lo le les que qué cuál cuáles dónde cómo '
                    'cuándo de del en por para con y o pero es son era ser he ha hay '
                    'debo debe deben puede puedo ahora'.split()),
}


def content_tokens(text: str, language: str) -> set[str]:
    from app.core.domain.bm25_ranking import lexical_tokens

    return set(lexical_tokens(text)) - STOPWORDS[language]


def lexical_measure(question: str, evidence: str, slot: dict[str, Any],
                    language: str) -> tuple[float, set[str]]:
    query = content_tokens(question, language)
    require(bool(query), 'question has no content tokens')
    shared = query & content_tokens(evidence, language)
    key_tokens = content_tokens(' '.join(slot['key_terms'][language]), language)
    require(bool(key_tokens), 'slot has no content key terms')
    return len(shared) / len(query), shared & key_tokens


def structure_strata(pool: dict[str, Any]) -> dict[tuple[str, str, str], str]:
    """Balance semantic step families, sharing each assignment across languages."""
    result = {}
    # Alternating odd-family starts keeps the aggregate exactly balanced.
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for family, slot, _, template, _ in pool_structures(pool):
        semantic_family = family if family in ('stable_fact', 'duplicate', 'update',
                                               'contradiction_trap', 'isolation_canary') else 'stable_fact'
        groups.setdefault(semantic_family, []).append((family, slot, template))
    start = 0
    for entries in groups.values():
        for index, entry in enumerate(entries):
            result[entry] = STRATA[(start + index) % 2]
        start = (start + len(entries)) % 2
    return result
