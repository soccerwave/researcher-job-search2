import csv
import gzip
import time
from pathlib import Path
from sources import madrid_idi_history as history

def _write(path: Path, rows: list[dict]):
    fields=["source","id","title","company","url","full_detail","detail_status","detail_age_days","availability_as_of","last_seen","detail_resolved_url","trusted_full_detail_url"]
    with gzip.open(path,"wt",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def _row(job_id="A1", title="Researcher", company="Institute"):
    return {"source":"Madrid I+D+i","id":job_id,"title":title,"company":company,"url":f"https://example.test/{job_id}"}

def test_prefill_exact_recent_match_only(tmp_path, monkeypatch):
    p=tmp_path/"h.csv.gz"
    _write(p,[{"source":"Madrid I+D+i","id":"A1","title":"Researcher","company":"Institute","url":"https://example.test/A1","full_detail":"trusted detail","detail_status":"OK","detail_age_days":"0","availability_as_of":"2026-10-04","last_seen":"2026-10-04","detail_resolved_url":"https://example.test/A1","trusted_full_detail_url":"https://example.test/A1"}])
    monkeypatch.setenv("MADRID_HISTORY_CANONICAL_PATH",str(p))
    hit=_row(); changed=_row(title="Senior Researcher"); diag={}
    hits,misses=history._prefill_recent_history([hit,changed],diag)
    assert hits==[hit] and misses==[changed]
    assert hit["detail_status"]=="CACHE" and hit["detail_fetch_status"]=="CACHE_PREFILL"
    assert diag["historical_prefill_used"]==1 and diag["historical_prefill_rejected"]==1

def test_prefill_respects_effective_age(tmp_path, monkeypatch):
    p=tmp_path/"h.csv.gz"
    _write(p,[{"source":"Madrid I+D+i","id":"A1","title":"Researcher","company":"Institute","url":"https://example.test/A1","full_detail":"old detail","detail_status":"CACHE","detail_age_days":"2","availability_as_of":"2026-10-03","last_seen":"2026-10-03","detail_resolved_url":"https://example.test/A1","trusted_full_detail_url":"https://example.test/A1"}])
    monkeypatch.setenv("MADRID_HISTORY_CANONICAL_PATH",str(p))
    import datetime
    monkeypatch.setattr(history,"date",type("FixedDate",(),{"today":staticmethod(lambda:datetime.date(2026,10,4))}))
    row=_row(); diag={}; hits,misses=history._prefill_recent_history([row],diag)
    assert hits==[] and misses==[row]
    assert diag["historical_detail_cache_expired"]==1

def test_final_rescue_only_transient_misses(monkeypatch):
    rows=[{**_row("A1"),"detail_status":"POEM_RELAY_HTTP_504"},{**_row("A2"),"detail_status":"OK","full_detail":"good"},{**_row("A3"),"detail_status":"POEM_RELAY_HTTP_503"}]
    calls=[]
    monkeypatch.setattr(time,"sleep",lambda *_:None)
    monkeypatch.setattr(history.base,"_resolve_detail_row",lambda i,row,timeout:(calls.append(row["id"]) or (i,"fresh detail","OK",row["url"],"poem_api")))
    diag={"detail_failed":2,"detail_success":1,"detail_status_counts":{"POEM_RELAY_HTTP_504":1,"POEM_RELAY_HTTP_503":1,"OK":1},"poem_api_success":0,"detail_resolved_via_poem_api":0,"detail_resolved_via_poem":0}
    history._rescue_remaining_fresh_misses(rows,diag)
    assert sorted(calls)==["A1","A3"]
    assert diag["final_rescue_attempts"]==2 and diag["final_rescue_success"]==2
    assert diag["detail_failed"]==0 and diag["detail_success"]==3
