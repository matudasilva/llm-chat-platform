"""Independent scalar-copy and unexpected alias-graph controls; no I/O."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from app.core.observability import context_evidence as c1


def test_exact_approved_source_delta_and_snapshot_body_unchanged():
    source=Path(c1.__file__).read_text()
    start=source.index('def _copy_window_receipts(')
    end=source.index('def window_materialized(',start)
    original=source[:start]+source[end:]
    assert original.count('_copy_window_receipts(')==3
    original=original.replace('_copy_window_receipts(state.window)','copy.deepcopy(state.window)')
    original=original.replace('_copy_window_receipts(kept)','copy.deepcopy(kept)')
    proposal=Path('.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106130053-rev2/diagnosis/receipt-copy-proposal/revision2/result.json')
    assert hashlib.sha256(original.encode()).hexdigest()==json.loads(proposal.read_text())['source_sha256']
    assert 'return copy.deepcopy(dict(instance_id=self.instance_id,' in source


def test_distinct_equal_rows_remain_distinct_and_scalars_share_only_immutable_values():
    text='unicode á 漢字 '+str(123456789012345678901234567890)
    first={'key':text,'n':123456789012345678901234567890,'flag':True,'optional':None}
    second=dict(first);rows=[first,second]
    actual=c1._copy_window_receipts(rows)
    assert actual==copy.deepcopy(rows)
    assert actual is not rows and actual[0] is not first and actual[1] is not second
    assert actual[0] is not actual[1]
    actual[0]['key']='changed'
    assert rows[0]['key']==rows[1]['key']==actual[1]['key']==text


def test_nested_shared_graph_falls_back_without_breaking_aliases():
    inner={'values':[1,2]};rows=[{'nested':inner},{'nested':inner}]
    actual=c1._copy_window_receipts(rows)
    assert actual[0]['nested'] is actual[1]['nested'] and actual[0]['nested'] is not inner
    actual[0]['nested']['values'].append(3)
    assert inner['values']==[1,2] and actual[1]['nested']['values']==[1,2,3]


def test_scalar_subclass_custom_copy_is_honored():
    class Number(int):
        def __deepcopy__(self,memo):return {'copied_subclass':int(self)}
    rows=[{'chars':Number(7)}]
    actual=c1._copy_window_receipts(rows)
    assert actual==copy.deepcopy(rows)==[{'chars':{'copied_subclass':7}}]


def test_fallback_copy_exception_is_not_replaced_or_silenced_by_helper():
    original=RuntimeError('controlled fallback failure')
    class Dict(dict):
        def __deepcopy__(self,memo):raise original
    with pytest.raises(RuntimeError) as raised:c1._copy_window_receipts([Dict(key='x')])
    assert raised.value is original
