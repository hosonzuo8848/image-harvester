# -*- coding: utf-8 -*-
# GH runner 直连内阁 IIIF · webp+PDF 落 out/ · upload artifact
# 参考稳定版 hv.py page_urls · 无 R2 · 无 CF egress · runner 出口新鲜 IP
import os, sys, io, csv, json, time
import requests, img2pdf
from PIL import Image

WL = os.environ.get("WORKLIST", "worklist.csv")
OUT = os.environ.get("OUT", "out")
SHARD = int(os.environ.get("SHARD", "0"))
TOTAL = int(os.environ.get("TOTAL", "1"))
LIMIT = int(os.environ.get("LIMIT", "0"))

sess = requests.Session()
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Referer": "https://www.digital.archives.go.jp/",
})

def page_urls(m, size="max"):
    seqs = m.get("sequences") or []
    if seqs and seqs[0].get("canvases"):
        urls = []
        for c in seqs[0]["canvases"]:
            res = (c.get("images") or [{}])[0].get("resource", {})
            svc = res.get("service") or {}
            if isinstance(svc, list): svc = svc[0] if svc else {}
            sid = (svc.get("id") or svc.get("@id")) if isinstance(svc, dict) else None
            urls.append(f"{sid}/full/{size}/0/default.jpg" if sid else res.get("@id"))
        return urls
    return []

def one(iid, mfst_url):
    try:
        r = sess.get(mfst_url, timeout=60)
        if r.status_code != 200: return None, f"manifest {r.status_code}"
        urls = page_urls(r.json())
        if not urls: return None, "0页"
    except Exception as e:
        return None, f"manifest err {str(e)[:40]}"
    # 先访 img/{iid} 页面模拟浏览器行为(种 cookie / 触发 hotlink 检查)
    try:
        sess.get(f"https://www.digital.archives.go.jp/img/{iid}", timeout=30)
        time.sleep(0.5)
    except: pass
    imgs = []
    for u in urls:
        if not u: imgs.append(None); continue
        for _ in range(3):
            try:
                rr = sess.get(u, timeout=90, headers={"Referer": f"https://www.digital.archives.go.jp/img/{iid}"})
                if rr.status_code == 200 and "image" in rr.headers.get("content-type", ""):
                    imgs.append(rr.content); break
            except: time.sleep(1.5)
        else: imgs.append(None)
        time.sleep(0.3)  # 温和
    got = [b for b in imgs if b]
    if len(got) < len(urls) - 1: return None, f"缺 {len(got)}/{len(urls)}"
    return got, ""

rows = list(csv.DictReader(open(WL, encoding="utf-8-sig")))
jobs = [r for i, r in enumerate(rows) if i % TOTAL == SHARD]
if LIMIT: jobs = jobs[:LIMIT]
print(f"shard {SHARD}/{TOTAL} · {len(jobs)} 条", flush=True)
os.makedirs(OUT, exist_ok=True)

ok = fail = 0; t0 = time.time()
for i, row in enumerate(jobs, 1):
    iid = (row.get("id") or "").strip()
    mfst = (row.get("manifest") or "").strip()
    if not (iid and mfst): continue
    imgs, err = one(iid, mfst)
    if not imgs:
        fail += 1
        print(f"[{i}] {iid} FAIL {err}", flush=True)
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
    # 元数据供本地 puller 归位
    json.dump({"iid": iid, "num": row.get("num", ""), "book": row.get("book_name", ""), "冊": row.get("册序", ""), "pages": len(imgs)},
              open(os.path.join(d, "_meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
    ok += 1
    print(f"[{i}] {iid} OK {len(imgs)}页", flush=True)

print(f"\n=== 完 ok={ok} fail={fail} · {(time.time()-t0)/60:.1f}min ===", flush=True)
