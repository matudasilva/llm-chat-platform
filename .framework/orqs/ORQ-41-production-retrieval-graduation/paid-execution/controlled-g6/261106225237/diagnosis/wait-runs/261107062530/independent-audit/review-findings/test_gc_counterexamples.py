"""Passing assertions demonstrate initial GC evidence acceptance defects.

The initial validator module is preserved beside this probe so a later source
remediation cannot rewrite what this counterexample demonstrates.
"""
import copy
import importlib.util
from pathlib import Path
import pytest


def initial_validator():
    p=Path(__file__).with_name('wait_observer-initial.py')
    spec=importlib.util.spec_from_file_location('initial_wait_observer',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m.validate_request_intervals


def event(kind,identity,phase,at,thread=1):
    return dict(kind=kind,identity=identity,phase=phase,at_ns=at,thread=thread,
                request_id='r',context_owner='r')


@pytest.mark.parametrize('fault',['duplicate_complete_gc','backwards_same_key_gc'])
def test_initial_validator_accepts_invalid_completed_gc_cycle(fault):
    base=[event('sql',1,'start',1),event('sql',1,'stop',2)]
    for identity,start in [(2,3),(3,7)]:
        base += [event('sdk',identity,phase,start+i,1 if i in (0,3) else 2)
                 for i,phase in enumerate(('queued','entered','exited','returned'))]
    cycle=[event('gc','1:0','start',11),event('gc','1:0','stop',12)]
    invalid=(copy.deepcopy(cycle) if fault=='duplicate_complete_gc' else
             [event('gc','1:0','start',9),event('gc','1:0','stop',10)])
    assert sum(i['kind']=='gc'for i in initial_validator()(base+cycle+invalid,'r'))==2
