"""Checks for the independent audit and failures discovered by stress validation."""
from pathlib import Path
import sys
from copy import deepcopy

import numpy as np
import pytest
from scipy.optimize import OptimizeResult

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import validate_optimizer as validation
from backend.logistics import Model
from backend.optimization import SolverConfig, OptimizationError


def test_integer_objective_lock_uses_actual_integer_not_raw_solver_fun(monkeypatch):
    calls=[]
    def almost_integer(c,**kwargs):
        calls.append(kwargs)
        if len(calls)==2:
            assert kwargs['constraints'][-1].ub[0]>=1
        x=np.array([.9999996 if len(calls)==1 else 1.])
        return OptimizeResult(status=0,x=x,fun=float(c@x),mip_gap=0.)
    monkeypatch.setattr('backend.logistics.milp',almost_integer)
    model=Model();q=model.var('integer',1,True);model.constraint({q:1},1,1)
    x,obj=model.solve([('first',{q:1}),('second',{q:1})],SolverConfig())
    assert x[0]==1 and obj['first']==1
    assert model.stage_reports[0]['raw_solver_objective']<1


def test_time_limit_incumbent_is_still_refused(monkeypatch):
    monkeypatch.setattr('backend.logistics.milp',lambda *a,**kw:OptimizeResult(status=1,x=np.array([1.]),fun=1.,message='Time limit'))
    model=Model();q=model.var('q',1,True)
    with pytest.raises(OptimizationError,match='did not prove'):
        model.solve([('stage',{q:1})],SolverConfig())


@pytest.mark.parametrize('fleet,lead',[(2,0),(3,0),(1,14)])
def test_previously_infeasible_later_stage_with_feasible_integer_plan(fleet,lead):
    u=validation.fixture((100,100,100,100),fleet=fleet)
    u['logistics']['procurement_lead_days']={i:lead for i in validation.ITEMS}
    r=validation.solve(u)
    a=validation.audit(u,r)
    assert a['passed'],a['failures']
    assert all(s['status']==0 for s in r['model_info']['solver_stages'])


def test_auditor_rejects_eight_corruptions_of_a_valid_plan():
    u=validation.fixture((10,10,10,10));before=deepcopy(u)
    r=validation.solve(u)
    assert validation.audit(u,r)['passed']
    assert all(p['detected'] for p in validation.mutation_checks(u,r))
    assert u==before


@pytest.mark.parametrize('name,u',list(validation.oracle_cases(8)))
def test_independent_exhaustive_cargo_enumeration(name,u):
    truth,_=validation.enumerated_truth(u)
    r=validation.solve(u)
    assert validation.score(u,r)==pytest.approx(truth,abs=3e-5)


@pytest.mark.parametrize('name,u',list(validation.benchmarks()))
def test_baseline_is_itself_feasible_under_same_inputs(name,u):
    result=validation.greedy(u)
    finding=validation.audit(u,result)
    assert finding['passed'],finding['failures']


def test_failed_run_preserves_evidence_and_reports_failure(monkeypatch,tmp_path):
    def fail(_):
        raise OptimizationError('forced solver failure')
    monkeypatch.setattr(validation,'solve',fail)
    monkeypatch.setattr(validation,'greedy',fail)
    monkeypatch.setattr(validation,'OUTPUT',tmp_path)
    monkeypatch.setattr(sys,'argv',['validate_optimizer.py','--quick','--skip-official','--output',str(tmp_path)])
    assert validation.main()==1
    import json
    evidence=json.loads((tmp_path/'evidence.json').read_text(encoding='utf-8'))
    assert evidence['failures'] and evidence['passed']==0 and evidence['mutations']==[]
    assert '검증 실패가 있어' in (tmp_path/'report.md').read_text(encoding='utf-8')
