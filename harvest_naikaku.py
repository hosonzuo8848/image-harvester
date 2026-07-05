# -*- coding: utf-8 -*-
# 7-2/3 稳定版恢复:8 worker × 分段 ZIP + 冊级并行 = 50-120MB/s
# 短册:1 请求整册;长册:分段并行(?id&from&to)
import os, sys, io, csv, json, time, zipfile, threading, queue
import requests, img2pdf
from PIL import Image

WL = os.environ.get("WORKLIST", "worklist.csv")
OUT = os.environ.get("OUT", "out")
SHARD = int(os.environ.get("SHARD", "0"))
TOTAL = int(os.environ.get("TOTAL", "1"))
LIMIT = int(os.environ.get("LIMIT", "0"))
BOOK_PAR = int(os.environ.get("BOOK_PAR", "4"))     # 冊级并行
SEG_SIZE = int(os.environ.get("SEG_SIZE", "50"))    # 每段页数
SEG_PAR = int(os.environ.get("SEG_PAR", "8"))       # 段并行(=worker数)

WORKERS = [
    "naikaku-zip", "naikaku-mine",
    "naikaku-zip-2", "naikaku-zip-3", "naikaku-zip-4",
    "naikaku-zip-5", "naikaku-zip-6", "naikaku-zip-7",
]
BH = {"User-Agent": "Mozilla/5.0 Chrome/124.0"}

def S():
    s = requests.Session(); s.trust_env = True; return s

def dl_segment(iid, frm, to, wi):
    """?id&from&to 拿页范围 ZIP · worker 轮换"""
    last = None
    for k in range(len(WORKERS) * 2):
        w = WORKERS[(wi + k) % len(WORKERS)]
        url = f"https://{w}.hosonzuo.workers.dev/?id={iid}&from={frm}&to={to}"
        try:
            r = S().get(url, headers=BH, timeout=180)
            if r.status_code == 200 and "zip" in r.headers.get("content-type", ""):
                return r.content
            last = f"{w} HTTP{r.status_code}"
        except Exception as e:
            last = f"{w} {str(e)[:30]}"
        time.sleep(0.3)
    raise RuntimeError(f"段失败 {frm}-{to}: {last}")

def get_page_count(iid):
    """从内阁 img/{iid} 拿总页数"""
    import re
    r = S().get(f"https://www.digital.archives.go.jp/img/{iid}", headers=BH, timeout=60)
    m = re.search(r'var najContentList = (\[[\s\S]*?\]);', r.text)
    if not m: return 0
    return len(json.loads(m.group(1)))

def dl_book(iid, wi_base):
    """每册·8worker分段并行"""
    n = get_page_count(iid)
    if not n: raise RuntimeError("0页")
    # 分段 SEG_SIZE 页/段
    segs = []
    frm = 1
    while frm <= n:
        to = min(frm + SEG_SIZE - 1, n)
        segs.append((frm, to))
        frm = to + 1
    imgs_by_seg = [None] * len(segs)
    q = queue.Queue()
    for i, (a, b) in enumerate(segs): q.put((i, a, b))
    errs = []
    def w():
        while True:
            try: i, a, b = q.get_nowait()
            except queue.Empty: return
            try:
                data = dl_segment(iid, a, b, wi_base + i)
                zf = zipfile.ZipFile(io.BytesIO(data))
                names = sorted(x for x in zf.namelist() if not x.endswith("/"))
                imgs_by_seg[i] = [zf.read(x) for x in names]
            except Exception as e:
                errs.append(str(e)[:40])
                imgs_by_seg[i] = []
    ts = [threading.Thread(target=w) for _ in range(SEG_PAR)]
    [t.start() for t in ts]; [t.join() for t in ts]
    imgs = []
    for seg in imgs_by_seg: imgs.extend(seg or [])
    if len(imgs) < n - 1:
        raise RuntimeError(f"页数不足 {len(imgs)}/{n} · {errs[:2]}")
    return imgs

rows = list(csv.DictReader(open(WL, encoding="utf-8-sig")))
jobs = [r for i, r in enumerate(rows) if i % TOTAL == SHARD]
if LIMIT: jobs = jobs[:LIMIT]
print(f"shard {SHARD}/{TOTAL} · {len(jobs)} 条 · 冊{BOOK_PAR}×段{SEG_PAR} = {BOOK_PAR*SEG_PAR}并发", flush=True)
os.makedirs(OUT, exist_ok=True)
q = queue.Queue()
for i, r in enumerate(jobs): q.put((i, r))
lock = threading.Lock(); cnt = {"ok": 0, "fail": 0}; t0 = time.time()

def worker(bi):
    while True:
        try: i, row = q.get_nowait()
        except queue.Empty: return
        iid = (row.get("id") or "").strip()
        if not iid: continue
        try:
            imgs = dl_book(iid, bi * 8 + i)
        except Exception as e:
            with lock:
                cnt["fail"] += 1
                print(f"[{i+1}] {iid} FAIL {str(e)[:70]}", flush=True)
            continue
        d = os.path.join(OUT, iid); os.makedirs(d, exist_ok=True)
        for k, b in enumerate(imgs, 1):
            try:
                im = Image.open(io.BytesIO(b))
                if im.mode not in ("RGB", "L"): im = im.convert("RGB")
                im.save(os.path.join(d, f"page_{k:04d}.webp"), "WEBP", quality=82)
            except: pass
        jpgs = []
        for b in imgs:
            try:
                im = Image.open(io.BytesIO(b))
                if im.mode not in ("RGB", "L"): im = im.convert("RGB")
                bio = io.BytesIO(); im.save(bio, "JPEG", quality=88); jpgs.append(bio.getvalue())
            except: pass
        with open(os.path.join(d, f"{iid}.pdf"), "wb") as f:
            f.write(img2pdf.convert(jpgs))
        json.dump({"iid": iid, "num": row.get("num", ""), "book": row.get("book_name", ""),
                  "冊": row.get("册序", ""), "pages": len(imgs)},
                  open(os.path.join(d, "_meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
        with lock:
            cnt["ok"] += 1
            print(f"[{i+1}] {iid} OK {len(imgs)}页 · 累计ok={cnt['ok']}", flush=True)

ts = [threading.Thread(target=worker, args=(i,)) for i in range(BOOK_PAR)]
[t.start() for t in ts]; [t.join() for t in ts]
print(f"\n=== 完 ok={cnt['ok']} fail={cnt['fail']} · {(time.time()-t0)/60:.1f}min ===", flush=True)
