# -*- coding: utf-8 -*-
# runner 快速检测 worklist 里 iid 是否有效(HEAD manifest)
# 输出 valid_iids.txt + dead_iids.txt
import os, csv, requests, time
from concurrent.futures import ThreadPoolExecutor

WL = os.environ.get("WORKLIST", "worklist_缺.csv")
SHARD = int(os.environ.get("SHARD", "0"))
TOTAL = int(os.environ.get("TOTAL", "1"))

sess = requests.Session()
sess.headers.update({"User-Agent": "Mozilla/5.0 Chrome/124.0"})

def check(row):
    iid = (row.get("id") or "").strip()
    mfst = (row.get("manifest") or "").strip()
    if not (iid and mfst): return iid, None
    try:
        r = sess.head(mfst, timeout=15, allow_redirects=True)
        return iid, r.status_code
    except Exception:
        return iid, 0

rows = list(csv.DictReader(open(WL, encoding="utf-8-sig")))
jobs = [r for i, r in enumerate(rows) if i % TOTAL == SHARD]
print(f"shard {SHARD}/{TOTAL} · {len(jobs)} iid", flush=True)

valid = []; dead = []; errs = []
t0 = time.time()
with ThreadPoolExecutor(30) as ex:
    for i, (iid, code) in enumerate(ex.map(check, jobs), 1):
        if code == 200: valid.append(iid)
        elif code == 404: dead.append(iid)
        else: errs.append((iid, code))
        if i % 200 == 0:
            print(f"  {i}/{len(jobs)} · 200={len(valid)} 404={len(dead)} 其它={len(errs)} · {(time.time()-t0)/60:.1f}min", flush=True)

os.makedirs("out", exist_ok=True)
open(f"out/valid_iids_{SHARD}.txt", "w").write("\n".join(valid))
open(f"out/dead_iids_{SHARD}.txt", "w").write("\n".join(dead))
open(f"out/other_iids_{SHARD}.txt", "w").write("\n".join(f"{i},{c}" for i, c in errs))
print(f"\n完 · 200={len(valid)} 404={len(dead)} 其它={len(errs)} · {(time.time()-t0)/60:.1f}min", flush=True)
