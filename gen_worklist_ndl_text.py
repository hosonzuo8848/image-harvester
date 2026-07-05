#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# NDL 古籍全文 worklist 生成器:枚举中医/古籍关键词 x 翻页 -> 取 isClassic=true 的 id -> 去重 -> CSV
# 直连 NDL API(CloudFront CDN,实测无需代理、无限流、无封IP),本地生成后 commit 进仓库供各 shard 读取同一份清单。
# opsec: CSV 只留 id + isClassic + hit_keyword(英文/罗马字段名,书名标题不落公开仓,防止 public 仓堆中文正文)。
import csv
import sys
import time

import requests

BASE = "https://lab.ndl.go.jp/dl/api/book/search"
PAGE_SIZE = 100
SLEEP = 0.3          # 温和:每次翻页请求间隔,不猛戳
MAX_FROM = 3000       # 单关键词最多翻到 from=3000(NDL 搜索深翻页会截断/变慢,超出的量其它关键词也能覆盖到)

# 中医/古籍关键词(繁体正字 + 常见异体字),医书+古籍都要
KEYWORDS = [
    "傷寒", "傷寒論", "金匱", "金匱要略", "本草", "本草綱目", "醫方", "醫方類聚",
    "針灸", "鍼灸", "素問", "靈樞", "難經", "温病", "溫病", "脈經", "脉經",
    "醫學", "醫案", "養生", "黄帝内経", "黄帝內經", "傷寒雑病論", "傷寒雜病論",
    "本草經", "神農本草經", "千金方", "千金要方", "外臺秘要", "諸病源候論",
    "醫宗金鑑", "湯液", "藥性", "本草衍義", "傷寒明理論", "傷寒論注",
    "婦人科", "小兒科", "痘疹", "瘡瘍", "眼科", "外科", "内科", "本草綱目啓蒙",
    "醫心方", "頓醫抄", "萬病回春", "醫學正伝", "醫學正傳", "本草和名",
]


def search(session, keyword, frm, size=PAGE_SIZE):
    r = session.get(BASE, params={"keyword": keyword, "from": frm, "pageSize": size}, timeout=40)
    r.raise_for_status()
    return r.json()


def main():
    s = requests.Session()
    s.trust_env = False  # 直连,不走系统代理

    seen = {}  # id -> first-hit keyword (for stats only, not written to CSV title)
    total_requests = 0

    for kw in KEYWORDS:
        frm = 0
        kw_found = 0
        while True:
            try:
                j = search(s, kw, frm)
            except Exception as e:
                print(f"[{kw}] from={frm} FAIL {str(e)[:60]}", flush=True)
                break
            total_requests += 1
            hit = j.get("hit", 0)
            lst = j.get("list", [])
            if not lst:
                break
            for it in lst:
                if it.get("isClassic"):
                    bid = str(it.get("id") or "").strip()
                    if bid and bid not in seen:
                        seen[bid] = kw
                        kw_found += 1
            frm += PAGE_SIZE
            if frm >= hit or frm >= MAX_FROM:
                break
            time.sleep(SLEEP)
        print(f"[{kw}] hit_total={j.get('hit', 0) if 'j' in dir() else '?'} new_classic_ids={kw_found} cumulative_unique={len(seen)}", flush=True)

    out_path = "worklist_ndl_text.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id"])
        for bid in seen:
            w.writerow([bid])

    print(f"\n=== done: {len(seen)} unique isClassic ids -> {out_path} ({total_requests} search requests) ===", flush=True)


if __name__ == "__main__":
    main()
