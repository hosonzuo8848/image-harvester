# -*- coding: utf-8 -*-
# 7-2/3 稳定版恢复:8 worker 集群 + contentDownload 整件 ZIP(1请求/册)
# GET https://{worker}.hosonzuo.workers.dev/?id={iid} → application/zip 整册
import os, sys, io, csv, json, time, zipfile
import requests, img2pdf
from PIL import Image

WL = os.environ.get("WORKLIST", "worklist.csv")
OUT = os.environ.get("OUT", "out")
SHARD = int(os.environ.get("SHARD", "0"))
TOTAL = int(os.environ.get("TOTAL", "1"))
LIMIT = int(os.environ.get("LIMIT", "0"))

WORKERS = [
    "naikaku-zip", "naikaku-mine",
    "naikaku-zip-2", "naikaku-zip-3", "naikaku-zip-4",
    "naikaku-zip-5", "naikaku-zip-6", "naikaku-zip-7",
]

sess = requests.Session()
sess.headers.update({"User-Agent": "Mozilla/5.0 Chrome/124.0"})

def dl_zip(iid, wi):
    last = None
    for k in range(len(WORKERS) * 2):
        w = WORKERS[(wi + k) % len(WORKERS)]
        url = f"https://{w}.hosonzuo.workers.dev/?id={iid}"
        try:
            r = sess.get(url, timeout=180)
            if r.status_code == 200 and "zip" in r.headers.get("content-type", ""):
                return r.content
            last = f"{w} HTTP{r.status_code}"
        except Exception as e:
            last = f"{w} {str(e)[:40]}"
        time.sleep(0.5)
    raise RuntimeError(f"全 worker 失败: {last}")

rows = list(csv.DictReader(open(WL, encoding="utf-8-sig")))
jobs = [r for i, r in enumerate(rows) if i % TOTAL == SHARD]
if LIMIT: jobs = jobs[:LIMIT]
print(f"shard {SHARD}/{TOTAL} · {len(jobs)} 条 · 8worker集群", flush=True)
os.makedirs(OUT, exist_ok=True)

ok = fail = 0; t0 = time.time()
for i, row in enumerate(jobs, 1):
    iid = (row.get("id") or "").strip()
    if not iid: continue
    try:
        zip_bytes = dl_zip(iid, SHARD + i)
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = sorted(n for n in zf.namelist() if not n.endswith("/"))
        imgs = [zf.read(n) for n in names]
        if not imgs: raise RuntimeError("空ZIP")
    except Exception as e:
        fail += 1
        print(f"[{i}] {iid} FAIL {str(e)[:80]}", flush=True); continue
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
    ok += 1
    print(f"[{i}] {iid} OK {len(imgs)}页", flush=True)

print(f"\n=== 完 ok={ok} fail={fail} · {(time.time()-t0)/60:.1f}min ===", flush=True)
