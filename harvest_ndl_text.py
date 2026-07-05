#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# NDL 古籍全文采集(Actions runner 直连,不存 R2/D1)-> out/(供 upload-artifact)
# 照 harvest_artifact.py 的 shard/artifact 模式:runner 海外IP直连 NDL(CloudFront CDN,实测无需代理无限流)。
# 全文接口:fulltext-json/{id} 返回坐标块数组,按 page 分组、组内按 (rectY,rectX) 排序、拼 contents 成整页文本。
import argparse
import csv
import json
import os
import time

import requests

BASE = "https://lab.ndl.go.jp/dl/api/book"
UA = {"User-Agent": "Mozilla/5.0 (compatible; GujiArchive/1.0)"}


def fetch_json(session, url, timeout=60, tries=3):
    last_status = None
    for a in range(tries):
        try:
            r = session.get(url, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last_status = r.status_code
        except Exception as e:
            last_status = str(e)[:50]
        time.sleep(2 * (a + 1))
    raise RuntimeError(f"HTTP fail: {last_status}")


def pull_fulltext(session, bid):
    """拉 fulltext-json,按 page 分组、组内按 (rectY,rectX) 排序、拼 contents 成整页文本"""
    j = fetch_json(session, f"{BASE}/fulltext-json/{bid}")
    blocks = j.get("list", []) if isinstance(j, dict) else (j or [])
    pages = {}
    for b in blocks:
        pages.setdefault(b.get("page", 0), []).append(b)
    parts = []
    for pg in sorted(pages):
        bl = sorted(pages[pg], key=lambda b: (b.get("rectY", 0), b.get("rectX", 0)))
        parts.append("".join(b.get("contents", "") or "" for b in bl))
    text = "\n".join(parts)
    return text, len(pages)


def one(session, bid, out_dir):
    try:
        text, npages = pull_fulltext(session, bid)
    except Exception as e:
        print(f"{bid}: FAIL {str(e)[:70]}", flush=True)
        return False
    if not text.strip():
        print(f"{bid}: 零文本(全文接口无内容)", flush=True)
        return False
    d = os.path.join(out_dir, bid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{bid}.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    meta = {"id": bid, "pages": npages, "chars": len(text), "source": "ndl_fulltext"}
    with open(os.path.join(d, "_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f"{bid}: {npages}页 {len(text)}字 OK", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worklist", default="worklist_ndl_text.csv")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--total", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.worklist, encoding="utf-8-sig")))
    jobs = [r["id"].strip() for i, r in enumerate(rows) if r.get("id", "").strip() and i % a.total == a.shard]
    if a.limit:
        jobs = jobs[: a.limit]
    print(f"shard {a.shard}/{a.total}: 分到 {len(jobs)} 本", flush=True)

    os.makedirs(a.out, exist_ok=True)
    s = requests.Session()
    s.trust_env = False  # 直连 NDL,不走系统代理(CloudFront CDN,实测无限流无封IP)

    ok, fail = 0, 0
    t0 = time.time()
    for i, bid in enumerate(jobs, 1):
        if one(s, bid, a.out):
            ok += 1
        else:
            fail += 1
        if i % 20 == 0:
            print(f"  进度 {i}/{len(jobs)} · ok={ok} fail={fail}", flush=True)
        time.sleep(0.2)  # 温和:每本间隔,不猛戳

    print(f"\n=== shard {a.shard} 完 ok={ok} fail={fail} · {(time.time()-t0)/60:.1f}min ===", flush=True)


if __name__ == "__main__":
    main()
