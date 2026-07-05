# -*- coding: utf-8 -*-
# 7-2/3 稳定版:runner 只拿 ZIP 存 out/ · 本地 puller 拉 artifact 后解压+合成
# 关键:直接 GET /?id={iid} 单请求整册 · 8 worker 冊级并行
import os, sys, csv, json, time, threading, queue
import requests

WL = os.environ.get("WORKLIST", "worklist.csv")
OUT = os.environ.get("OUT", "out")
SHARD = int(os.environ.get("SHARD", "0"))
TOTAL = int(os.environ.get("TOTAL", "1"))
LIMIT = int(os.environ.get("LIMIT", "0"))
BOOK_PAR = int(os.environ.get("BOOK_PAR", "8"))    # 冊级并行 · 每 worker 一册

WORKERS = [
    "naikaku-zip", "naikaku-mine",
    "naikaku-zip-2", "naikaku-zip-3", "naikaku-zip-4",
    "naikaku-zip-5", "naikaku-zip-6", "naikaku-zip-7",
]
BH = {"User-Agent": "Mozilla/5.0 Chrome/124.0"}

def S():
    s = requests.Session(); s.trust_env = True; return s

def dl_zip(iid, wi):
    """8 worker 轮换拿整册 ZIP"""
    last = None
    for k in range(len(WORKERS) * 2):
        w = WORKERS[(wi + k) % len(WORKERS)]
        url = f"https://{w}.hosonzuo.workers.dev/?id={iid}"
        try:
            r = S().get(url, headers=BH, timeout=300)
            if r.status_code == 200 and "zip" in r.headers.get("content-type", ""):
                return r.content, w
            last = f"{w} HTTP{r.status_code}"
        except Exception as e:
            last = f"{w} {str(e)[:30]}"
        time.sleep(0.5)
    raise RuntimeError(last)

rows = list(csv.DictReader(open(WL, encoding="utf-8-sig")))
jobs = [r for i, r in enumerate(rows) if i % TOTAL == SHARD]
if LIMIT: jobs = jobs[:LIMIT]
print(f"shard {SHARD}/{TOTAL} · {len(jobs)} 条 · 冊{BOOK_PAR}并行 · runner只拿ZIP", flush=True)
os.makedirs(OUT, exist_ok=True)

q = queue.Queue()
for i, r in enumerate(jobs): q.put((i, r))
lock = threading.Lock(); cnt = {"ok": 0, "fail": 0, "bytes": 0}; t0 = time.time()

def worker(wid):
    while True:
        try: i, row = q.get_nowait()
        except queue.Empty: return
        iid = (row.get("id") or "").strip()
        if not iid: continue
        try:
            zip_bytes, wname = dl_zip(iid, wid + i)
        except Exception as e:
            with lock: cnt["fail"] += 1
            print(f"[{i+1}] {iid} FAIL {str(e)[:70]}", flush=True); continue
        # 存 ZIP + meta · 本地 puller 处理
        d = os.path.join(OUT, iid); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{iid}.zip"), "wb") as f: f.write(zip_bytes)
        json.dump({
            "iid": iid, "num": row.get("num", ""), "book": row.get("book_name", ""),
            "冊": row.get("册序", ""), "size_kb": len(zip_bytes)//1024, "worker": wname
        }, open(os.path.join(d, "_meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
        with lock:
            cnt["ok"] += 1
            cnt["bytes"] += len(zip_bytes)
            el = time.time() - t0
            mbps = (cnt["bytes"] / 1024 / 1024) / el if el > 0 else 0
            print(f"[{i+1}] {iid} OK {len(zip_bytes)//1024}KB via {wname} · 累计ok={cnt['ok']} · {mbps:.1f}MB/s", flush=True)

ts = [threading.Thread(target=worker, args=(i,)) for i in range(BOOK_PAR)]
[t.start() for t in ts]; [t.join() for t in ts]
el = time.time() - t0
mbps = (cnt["bytes"] / 1024 / 1024) / el if el > 0 else 0
print(f"\n=== 完 ok={cnt['ok']} fail={cnt['fail']} · {cnt['bytes']//1024//1024}MB · {el/60:.1f}min · {mbps:.2f}MB/s ===", flush=True)

# 假绿止血(2026-07-05):全部失败却绿色 success 骗人 → ok=0 时红色报警
if cnt["ok"] == 0 and cnt["fail"] > 0:
    print("!! ok=0 全失败 · exit 1 暴露红色", flush=True)
    sys.exit(1)
