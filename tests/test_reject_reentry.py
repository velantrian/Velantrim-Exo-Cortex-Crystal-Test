"""Explicit rejection + existing Immune guard: atomic, revocable, opt-in."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from core import audit, immune, imports, knowledge, memory, review, review_decision_store
from core.curator_auth import CuratorPrincipal, CuratorRole
from core.curator_runtime import reject_as_principal
from core.ingest import ingest
from core.l3_graph import get_l3_graph
from core.query_pipeline import query

A = 'The synthetic rejected marker Q7V9 has value 314159.'
B = 'The independent allowed marker B8K2 has value 271828.'
FID = 'ing:rejected-original'


def setup_case(monkeypatch):
    monkeypatch.setenv('VELANTRIM_DEMO_SEED', '0')
    monkeypatch.setenv('VELANTRIM_IMMUNE_BLOCK_SEVERITY', '0.5')
    memory.store_fact({'fact_id': FID, 'claim': A, 'source': 'test://source',
                       'confidence': .9, 'epistemic_state': 'Observed',
                       'claim_type': 'WORLD_FACT', 'source_status': 'EXTERNAL'})
    peer = knowledge.ingest_claims([{'claim': B, 'claim_type': 'WORLD_FACT', 'confidence': .9}],
                                   source='test://peer', source_content=B,
                                   source_sha256=knowledge.evidence.sha256(B))
    assert peer['accepted'] == 1
    assert peer['fact_ids'][0] in {f['fact_id'] for f in query(B)['facts']}
    return peer['fact_ids'][0]


def reject_block():
    return review.reject(FID, actor='test-owner', reason='explicit correction', block_reentry=True)


@pytest.mark.parametrize('route', ['same_id', 'new_id', 'text', 'file', 'normalized'])
def test_cross_path_reentry_blocked_with_allowed_neighbor(monkeypatch, tmp_path, route):
    peer = setup_case(monkeypatch)
    result = reject_block()
    assert result['rejected'] and result['reentry_pattern_id']
    if route in ('same_id', 'new_id', 'normalized'):
        claim = A.upper().replace('.', '!') if route == 'normalized' else A
        r = ingest(claim, fact_id=FID if route == 'same_id' else 'ing:new-id',
                   source='test://source', claim_type='WORLD_FACT',
                   source_status='EXTERNAL', confidence=.9)
        assert not r['accepted']
    elif route == 'text':
        assert knowledge.ingest_text(A, source='test://replay')['accepted'] == 0
    else:
        f = tmp_path/'retained.txt'; f.write_text(A)
        assert imports.import_file(str(f), source='test://replay')['accepted'] == 0
    assert memory.get_fact(FID)['epistemic_state'] == 'Collapsed'
    assert all(f.get('claim') != A for f in query(A)['facts'])
    assert peer in {f['fact_id'] for f in query(B)['facts']}
    assert audit.verify_audit_log()['ok']
    decisions = review_decision_store.get_review_decision(result['decision_id'])
    assert decisions['payload']['reentry_pattern_id'] == result['reentry_pattern_id']
    # Claim contents never enter the two audit events or decision payload.
    assert A not in json.dumps(audit.audit_log())
    assert A not in json.dumps(decisions['payload'])


def test_default_rejection_does_not_install_guard(monkeypatch):
    setup_case(monkeypatch)
    result = review.reject(FID)
    assert result['rejected'] and 'reentry_pattern_id' not in result
    assert immune.match_threat(A) is None
    r = ingest(A, fact_id='ing:allowed-new-id', source='test://source',
               source_status='EXTERNAL', claim_type='WORLD_FACT', confidence=.9)
    assert r['accepted']  # Freezes the unchanged record-level meaning of reject.


def test_explicit_revocation_allows_reentry_without_resurrecting_original(monkeypatch):
    setup_case(monkeypatch)
    result = reject_block()
    assert immune.forget_threat(result['reentry_pattern_id'], actor='test-owner')
    assert immune.match_threat(A) is None
    r = ingest(A, fact_id='ing:after-revocation', source='test://source',
               source_status='EXTERNAL', claim_type='WORLD_FACT', confidence=.9)
    assert r['accepted']
    assert memory.get_fact(FID)['epistemic_state'] == 'Collapsed'
    assert audit.verify_audit_log()['ok']


@pytest.mark.parametrize('failure', ['guard_audit', 'decision_audit', 'decision_insert'])
def test_failure_rolls_back_state_guard_and_both_audits(monkeypatch, failure):
    setup_case(monkeypatch)
    before = audit.audit_log()
    if failure == 'guard_audit':
        original = audit.append_event
        def fail(*a, **kw):
            original(*a, **kw)
            raise RuntimeError('synthetic audit failure')
        monkeypatch.setattr(audit, 'append_event', fail)
    elif failure == 'decision_audit':
        def fail(*a, **kw):
            raise RuntimeError('synthetic decision failure')
        monkeypatch.setattr(review_decision_store, '_append_audit_event_conn', fail)
    else:
        with memory._db() as c:
            review_decision_store._ensure_schema(c)
            c.execute("CREATE TRIGGER fail_decision BEFORE INSERT ON review_decisions BEGIN SELECT RAISE(ABORT, 'synthetic insert failure'); END")
    with pytest.raises(Exception, match='synthetic'):
        reject_block()
    assert memory.get_fact(FID)['epistemic_state'] == 'Observed'
    assert immune.list_threats() == []
    assert audit.audit_log() == before
    with memory._db() as c:
        # The initial schema creation may itself have rolled back.
        review_decision_store._ensure_schema(c)
        assert c.execute('SELECT count(*) FROM review_decisions').fetchone()[0] == 0
    assert audit.verify_audit_log()['ok']


@pytest.mark.parametrize('role,scope', [
    (CuratorRole.REVIEWER, 'fact:*'), (CuratorRole.CURATOR, 'fact:*'),
    (CuratorRole.ADMIN, 'fact:ing:rejected-original')])
def test_workspace_guard_requires_unscoped_admin(monkeypatch, role, scope):
    setup_case(monkeypatch)
    principal = CuratorPrincipal('reviewer', frozenset({role}), frozenset({scope}))
    result = reject_as_principal(principal, FID, reason='reject and block', block_reentry=True)
    assert result['authorized'] is False
    assert memory.get_fact(FID)['epistemic_state'] == 'Observed'
    assert immune.list_threats() == []


def test_admin_actor_comes_from_principal_and_cannot_be_spoofed(monkeypatch):
    setup_case(monkeypatch)
    principal = CuratorPrincipal('owner', frozenset({CuratorRole.ADMIN}), frozenset({'fact:*'}))
    assert not reject_as_principal(principal, FID, requested_actor='other', block_reentry=True)['authorized']
    r = reject_as_principal(principal, FID, reason='owner decision', block_reentry=True)
    assert r['authorized'] and r['rejected']
    assert immune.list_threats()[0]['actor'] == 'owner'


def test_restart_and_cli_guarded_rejection(monkeypatch, tmp_path):
    from core import l3_graph
    monkeypatch.setenv('VELANTRIM_L3_BACKEND', 'sqlite')
    monkeypatch.setenv('VELANTRIM_L3_PATH', str(tmp_path/'durable-l3.db'))
    l3_graph.reset_l3_graph()
    peer = setup_case(monkeypatch)
    env = dict(os.environ, VELANTRIM_DB=memory.SQLITE_PATH,
               VELANTRIM_CURATOR_ACTOR='cli-owner', VELANTRIM_CURATOR_ROLES='ADMIN',
               VELANTRIM_CURATOR_SCOPES='fact:*')
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, '-m', 'core.cli', 'review-reject', FID,
                        '--block-reentry', '--reason', 'explicit owner rejection'],
                       env=env, text=True, capture_output=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)['rejected']
    again = subprocess.run([sys.executable, '-m', 'core.cli', 'review-reject', FID,
                            '--block-reentry'], env=env, text=True, capture_output=True)
    assert again.returncode == 1 and not json.loads(again.stdout)['rejected']
    child = """from core import immune, audit
from core.ingest import ingest
assert immune.match_threat(%r)
r=ingest(%r, fact_id='ing:replay-after-restart', source='test://replay', confidence=.9, claim_type='WORLD_FACT', source_status='EXTERNAL')
assert not r['accepted']
assert audit.verify_audit_log()['ok']
from core.query_pipeline import query
assert %r in {f['fact_id'] for f in query(%r)['facts']}
assert all(f.get('claim') != %r for f in query(%r)['facts'])
""" % (A, A, peer, B, A, A)
    subprocess.run([sys.executable, '-c', child], env=env, check=True, capture_output=True, text=True)


@pytest.mark.parametrize('after_event', [False, True])
def test_crash_before_commit_keeps_original_and_allows_retry(monkeypatch, after_event):
    setup_case(monkeypatch)
    before = audit.audit_log()
    env = dict(os.environ, VELANTRIM_DB=memory.SQLITE_PATH,
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    code = """import os
from core import review, review_decision_store
original=review_decision_store._append_audit_event_conn
def crash(*a, **kw):
    if %r: original(*a, **kw)
    os._exit(71)
review_decision_store._append_audit_event_conn=crash
review.reject(%r, actor='owner', reason='explicit', block_reentry=True)
""" % (after_event, FID)
    r = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True)
    assert r.returncode == 71
    assert memory.get_fact(FID)['epistemic_state'] == 'Observed'
    assert immune.list_threats() == [] and audit.audit_log() == before
    assert reject_block()['rejected']


def test_guard_uses_current_block_policy_and_is_not_silently_disabled(monkeypatch):
    setup_case(monkeypatch)
    monkeypatch.setenv('VELANTRIM_IMMUNE_BLOCK_SEVERITY', '2')
    r = reject_block()
    assert not r['rejected']
    assert memory.get_fact(FID)['epistemic_state'] == 'Observed'
    assert immune.list_threats() == []


@pytest.mark.parametrize('value', ['yes', 1, None])
def test_opt_in_requires_boolean(monkeypatch, value):
    setup_case(monkeypatch)
    with pytest.raises(ValueError, match='bool'):
        review.reject(FID, block_reentry=value)
    assert memory.get_fact(FID)['epistemic_state'] == 'Observed'
    assert immune.list_threats() == []


def test_opt_in_requires_nonempty_reason(monkeypatch):
    setup_case(monkeypatch)
    with pytest.raises(ValueError, match='reason'):
        review.reject(FID, reason=' ', block_reentry=True)
    assert immune.list_threats() == []


def test_unblockable_claim_does_not_partially_reject(monkeypatch):
    setup_case(monkeypatch)
    memory.store_fact({'fact_id':'ing:punctuation', 'claim':'!!!', 'epistemic_state':'Observed'})
    result = review.reject('ing:punctuation', block_reentry=True)
    assert not result['rejected']
    assert memory.get_fact('ing:punctuation')['epistemic_state'] == 'Observed'
    assert immune.list_threats() == []


def test_restricted_fact_cannot_install_workspace_guard(monkeypatch):
    setup_case(monkeypatch)
    from core.compliance import restrict_processing
    restrict_processing(FID)
    assert not reject_block()['rejected']
    assert immune.list_threats() == []


def test_journal_replay_is_idempotent_and_checks_guard_mode(monkeypatch):
    setup_case(monkeypatch)
    first = reject_block()
    before = audit.audit_log()
    args = dict(decision_id=first['decision_id'], fact_id=FID, expected_revision=0,
                expected_state='Observed', candidate_path=('Collapsed',), event='review_reject',
                audit_detail={'actor':'test-owner'})
    replay = review_decision_store.stage_review_decision(**args, block_reentry=True)
    assert replay['ok'] and not replay['created']
    wrong = review_decision_store.stage_review_decision(**args, block_reentry=False)
    assert not wrong['ok'] and 'collision' in wrong['reason']
    assert audit.audit_log() == before
    assert len(immune.list_threats()) == 1


def test_journal_guard_mode_rejects_invalid_shape(monkeypatch):
    setup_case(monkeypatch)
    args = dict(decision_id='test-decision', fact_id=FID,
                expected_revision=memory.get_fact(FID)['revision'], expected_state='Observed',
                candidate_path=('Collapsed',), event='review_reject', audit_detail={'actor':'owner'})
    with pytest.raises(ValueError, match='bool'):
        review_decision_store.stage_review_decision(**args, block_reentry='yes')
    args['event']='review_approve'
    with pytest.raises(ValueError, match='only supported for rejection'):
        review_decision_store.stage_review_decision(**args, block_reentry=True)
    args['event']='review_reject';args['audit_detail']={}
    denied = review_decision_store.stage_review_decision(**args, block_reentry=True)
    assert not denied['ok'] and 'actor' in denied['reason']
    assert immune.list_threats() == []


def test_concurrent_duplicate_request_commits_one_guard_and_one_decision(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    setup_case(monkeypatch)
    original = review.get_fact
    barrier = threading.Barrier(2)
    def snapshot(fid):
        row = original(fid)
        if fid == FID:
            barrier.wait(timeout=10)
        return row
    monkeypatch.setattr(review, 'get_fact', snapshot)
    before = len(audit.audit_log())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reject_block(), range(2)))
    assert all(r['rejected'] for r in results)
    assert len({r['decision_id'] for r in results}) == 1
    assert len(immune.list_threats()) == 1
    assert len(audit.audit_log()) == before + 2
    assert audit.verify_audit_log()['ok']


def test_principal_runtime_does_not_coerce_opt_in(monkeypatch):
    setup_case(monkeypatch)
    admin = CuratorPrincipal('owner', frozenset({CuratorRole.ADMIN}))
    with pytest.raises(ValueError, match='bool'):
        reject_as_principal(admin, FID, block_reentry='false')
    assert immune.list_threats() == []


def test_cli_reports_failed_compound_decision_with_nonzero_status(monkeypatch, capsys):
    setup_case(monkeypatch)
    assert reject_block()['rejected']
    monkeypatch.setenv('VELANTRIM_CURATOR_ACTOR', 'owner')
    monkeypatch.setenv('VELANTRIM_CURATOR_ROLES', 'ADMIN')
    monkeypatch.setenv('VELANTRIM_CURATOR_SCOPES', 'fact:*')
    from core.cli import main
    assert main(['review-reject', FID, '--block-reentry']) == 1
    result = json.loads(capsys.readouterr().out)
    assert not result['rejected'] and 'not pending' in result['reason']
    assert len(immune.list_threats()) == 1
