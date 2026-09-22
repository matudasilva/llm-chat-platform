"""Instantiate only the authored dev pool; no held-out path is imported or opened."""
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .dataset import LANGUAGES, load_dataset, load_pool, pool_structures, require, structure_strata
from .events import canonical_bytes, file_sha256
from .paths import DEV_DATASET, DEV_POOL


def uid(*parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, 'orq39/' + '/'.join(map(str, parts))))


def build_dataset(*, seed: int = 39, output: Path = DEV_DATASET) -> Path:
    """A seed changes filler order, while each bilingual pair retains one identity."""
    require(type(seed) is int and seed >= 0, 'seed must be a nonnegative integer')
    pool = load_pool(DEV_POOL)
    require(pool['pool'] == 'dev', 'dev pool required')
    slots = {s['id']: s for s in pool['slots']}
    values = {v['id']: v for v in pool['values']}
    templates = {t['id']: t for t in pool['question_templates']}
    fillers = {f['id']: f for f in pool['filler_topics']}
    cases: list[dict[str, Any]] = []
    rng = random.Random(seed)
    strata = structure_strata(pool)
    update_index = 0
    for index, (family, slot_id, value_ids, template_id, filler_ids) in enumerate(pool_structures(pool)):
        stratum = strata[(family, slot_id, template_id)]
        variant = update_index % 3
        if family == 'update':
            update_index += 1
        case_id = uid('dev', family, slot_id, template_id)
        order = list(filler_ids)
        rng.shuffle(order)
        for language in LANGUAGES:
            en = language == 'en'
            slot = slots[slot_id]
            label = slot['labels'][language]
            a, b, foreign, sibling = value_ids
            def surface(value: str) -> str:
                return values[value]['aliases'][language][0]
            def assertion(value: str, phrasing: int = 0) -> str:
                return slot['assertions'][language][phrasing].format(value=surface(value))
            tenant = uid(case_id, language, 'tenant')
            conversation = uid(case_id, language, 'conversation')
            turns: list[dict[str, Any]] = []
            def add(content: str, role: str = 'user') -> str:
                sequence = len(turns) + 1
                message_id = uid(conversation, sequence)
                turns.append({'message_id': message_id, 'sequence': sequence,
                              'role': role, 'content': content})
                return message_id
            def exchange(content: str) -> str:
                source = add(content)
                add('Noted.' if en else 'Anotado.', 'assistant')
                return source
            original = exchange(assertion(a))
            sources = [original]
            gold, stale = [a], []
            question = templates[template_id]['text' if stratum == 'lexical_anchor' else 'paraphrase'][language]
            if family == 'duplicate':
                sources.append(exchange(assertion(a, 1 if index % 2 else 0)))
            elif family == 'update':
                stale = [a]
                if variant == 2:
                    text = slot['retractions'][language].format(value=surface(a))
                    gold = []
                else:
                    prefix = (
                        ('I need to correct what I told you earlier. ' if en else
                         'Necesito corregir lo que te dije antes. ') if variant == 0 else
                        ('My situation has changed. This replaces what I told you before. ' if en else
                         'Mi situación ha cambiado. Esto sustituye lo que te dije antes. ')
                    )
                    text = prefix + assertion(b, 2)
                    gold = [b]
                sources = [exchange(text)]
            elif family == 'contradiction_trap':
                if index % 2:
                    exchange((f'What if my {label} were {surface(b)}? This is hypothetical.' if en else
                              f'¿Y si mi {label} fuera {surface(b)}? Es una hipótesis.'))
                else:
                    add('Offer a guess, without treating it as my statement.' if en else
                        'Ofrece una suposición sin tratarla como una afirmación mía.')
                    add(assertion(b), 'assistant')
            elif family == 'historical':
                sources = [exchange((f'At the workshop, a sign read: "{surface(b)}".' if en else
                                     f'En el taller, un cartel decía: "{surface(b)}".'))]
                gold = [b]
                question = templates[template_id]['variants'][family][language]
            elif family in ('no_memory', 'distractor'):
                question = templates[template_id]['variants'][family][language].format(value=surface(b))
                gold, sources = [b], []
            elif family == 'prohibited':
                gold, sources = [], []
                question = templates[template_id]['variants'][family][language]
            exchange(('This is a prohibited synthetic fixture: ' if en else
                      'Este es un marcador sintético prohibido: ') + pool['prohibited_fixtures'][0])
            for filler_id in order:
                exchange(fillers[filler_id]['text'][language])
            canaries = []
            for scope, value in [('foreign', foreign), ('sibling', sibling)]:
                other_conversation = uid(conversation, scope)
                canaries.append({'tenant_id': uid(tenant, 'foreign') if scope == 'foreign' else tenant,
                                 'conversation_id': other_conversation, 'value_id': value,
                                 'turns': [{'message_id': uid(other_conversation, n), 'sequence': n,
                                            'role': role, 'content': content}
                                           for n, role, content in [(1, 'user', assertion(value)),
                                                                   (2, 'assistant', 'Noted.' if en else 'Anotado.')]]})
            semantic = family not in ('no_memory', 'distractor', 'historical', 'prohibited')
            cases.append({'conceptual_case_id': case_id, 'language': language, 'tenant_id': tenant,
                          'conversation_id': conversation, 'family': family, 'slot': slot_id,
                          'value_set': list(value_ids), 'question_template_id': template_id,
                          'filler_topic_set': list(filler_ids), 'turns': turns, 'canaries': canaries,
                          'steps': [{'step_id': uid(conversation, 'step'), 'family': family,
                                     'after_sequence': len(turns), 'question': question,
                                     'gold_values': gold, 'stale_values': stale,
                                     'gold_source_message_ids': sources, 'semantic': semantic,
                                     'h3': family in ('no_memory', 'historical'), 'stale_eligible': bool(stale),
                                     'gold_decision': 'answer' if gold else 'abstain',
                                     'lexical_stratum': stratum if semantic else None}]})
            if not semantic:
                cases[-1]['steps'].append({
                    'step_id': uid(conversation, 'semantic-step'), 'family': 'stable_fact',
                    'after_sequence': len(turns), 'question': templates[template_id]['text' if stratum == 'lexical_anchor' else 'paraphrase'][language],
                    'gold_values': [a], 'stale_values': [], 'gold_source_message_ids': [original],
                    'lexical_stratum': stratum, 'semantic': True, 'h3': False, 'stale_eligible': False, 'gold_decision': 'answer',
                })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes({'schema_version': 'orq39-dataset-v1', 'seed': seed,
                                        'pool_sha256': file_sha256(DEV_POOL), 'cases': cases}) + b'\n')
    load_dataset(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=39)
    args = parser.parse_args()
    build_dataset(seed=args.seed)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
