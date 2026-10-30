import threading
from concurrent.futures import ThreadPoolExecutor
from core import immune, memory, review
from core.ingest import ingest


def test_guard_committed_after_screen_before_promotion_must_block(monkeypatch):
    marker='The synthetic signal RACE27 has value 746.'
    fid='ing:pending-race27'
    memory.store_fact({'fact_id':fid,'claim':marker,'source':'test://race','confidence':.9,
                       'epistemic_state':'Observed','claim_type':'WORLD_FACT','source_status':'EXTERNAL'})
    screened=threading.Event();resume=threading.Event(); original=immune.screen
    def paused(text, *args, **kwargs):
        result=original(text,*args,**kwargs)
        if text==marker and kwargs.get('fact_id')=='ing:incoming-race27':
            screened.set()
            assert resume.wait(10)
        return result
    monkeypatch.setattr(immune,'screen',paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(ingest,marker,fact_id='ing:incoming-race27',source='test://race',
                            confidence=.9,claim_type='WORLD_FACT',source_status='EXTERNAL')
        try:
            assert screened.wait(10)
            assert review.reject(fid,actor='owner',reason='reject',block_reentry=True)['rejected']
        finally:
            resume.set()
        result=pending.result(timeout=10)
    assert not result['accepted'], 'in-flight write promoted after owner guard was committed'


def test_guard_blocks_inflight_ingest_across_processes(monkeypatch):
    import os, subprocess, sys
    marker='The synthetic signal CROSS46 has value 789.'
    fid='ing:pending-cross46'
    memory.store_fact({'fact_id':fid,'claim':marker,'source':'test://race','confidence':.9,
                       'epistemic_state':'Observed','claim_type':'WORLD_FACT','source_status':'EXTERNAL'})
    env=dict(os.environ, VELANTRIM_DB=memory.SQLITE_PATH, PYTHONPATH=os.getcwd())
    script='''import sys
from core import immune
from core.ingest import ingest
original=immune.screen
def paused(text,*a,**kw):
 result=original(text,*a,**kw)
 print("READY",flush=True)
 sys.stdin.readline()
 return result
immune.screen=paused
r=ingest(%r,fact_id="ing:cross-replay",source="test://race",confidence=.9,claim_type="WORLD_FACT",source_status="EXTERNAL")
print("BLOCKED" if not r["accepted"] else "ACCEPTED",flush=True)
''' % marker
    with subprocess.Popen([sys.executable,'-u','-c',script],env=env,text=True,
                          stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as child:
        try:
            assert child.stdout.readline().strip()=='READY'
            assert review.reject(fid,actor='owner',reason='reject',block_reentry=True)['rejected']
            out,err=child.communicate('\n',timeout=15)
        finally:
            if child.poll() is None:
                child.kill();child.wait()
    assert child.returncode==0,err
    assert out.strip()=='BLOCKED'


def test_unrelated_fact_remains_admissible(monkeypatch):
    rejected='The synthetic marker BLOCK44 is false.'
    allowed='The unrelated synthetic marker OK45 is true.'
    fid='ing:original-block44'
    memory.store_fact({'fact_id':fid,'claim':rejected,'source':'test://race','confidence':.9,
                       'epistemic_state':'Observed','claim_type':'WORLD_FACT','source_status':'EXTERNAL'})
    assert review.reject(fid,actor='owner',reason='reject',block_reentry=True)['rejected']
    result=ingest(allowed,fact_id='ing:allowed-ok45',source='test://race',confidence=.9,
                  claim_type='WORLD_FACT',source_status='EXTERNAL')
    assert result['accepted']


def test_existing_manual_guard_also_fences_inflight_ingest(monkeypatch):
    marker='The synthetic signal MANUAL2 has value 425.'
    screened=threading.Event();resume=threading.Event();original=immune.screen
    def paused(text,*args,**kwargs):
        result=original(text,*args,**kwargs)
        if text==marker:
            screened.set();assert resume.wait(10)
        return result
    monkeypatch.setattr(immune,'screen',paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(ingest,marker,fact_id='ing:manual-race2',source='test://race',
                            confidence=.9,claim_type='WORLD_FACT',source_status='EXTERNAL')
        try:
            assert screened.wait(10)
            immune.record_threat(marker,threat_type='manual',severity=1,actor='owner')
        finally:
            resume.set()
        assert not pending.result(timeout=10)['accepted']


def test_locked_guard_matching_respects_floor_and_empty_input(monkeypatch):
    monkeypatch.setenv('VELANTRIM_IMMUNE_BLOCK_SEVERITY', '0.5')
    immune.record_threat('synthetic banned 314', severity=0.1, actor='owner')
    with memory._db() as conn:
        memory.begin_immediate(conn)
        assert not immune._reentry_guard_matches_conn(conn, '!!!')
        assert not immune._reentry_guard_matches_conn(conn, 'synthetic banned 314')
    immune.record_threat('synthetic banned 314', severity=1.0, actor='owner')
    with memory._db() as conn:
        memory.begin_immediate(conn)
        assert immune._reentry_guard_matches_conn(conn, 'synthetic banned 314')
        assert not immune._reentry_guard_matches_conn(conn, 'different allowed 315')
