#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IA(Internet Archive)全文云端并发 harvest worker
- 每个 shard 处理 identifiers 的一个切片,调用 ia-egress-{1,2,3} Worker(CF 付费·全新命名·不撞现有生产worker)
- Worker 侧一次请求做完:metadata 判公版 → 下载 _djvu.txt → PUT R2 guyaofang-assets/text/ia/
- 幂等:Worker /ia 默认跳过已存在 key(force=false),客户端也可选提前用 /exists 过滤(省一次 Worker 调用)
- 温和限速:archive.org 全局限流,起步保守 sleep,遇 429/502 自动退避,不猛冲
- 请求计数:定期读 /count 心跳打印,便于云端日志监控(防死循环爆炸请求数)
"""
import os, sys, json, time, argparse, urllib.request, urllib.error, urllib.parse

IDS_FILE = os.path.join(os.path.dirname(__file__), "ia_identifiers.json")

# 3 个全新命名 egress worker(全新部署,不碰任何现有生产 worker)
WORKERS = [
    "https://ia-egress-1.hosonzuo.workers.dev",
    "https://ia-egress-2.hosonzuo.workers.dev",
    "https://ia-egress-3.hosonzuo.workers.dev",
]

R2_PREFIX = "text/ia/"


def http_get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "ia-harvest-worker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if e.fp else ""
        return e.code, body
    except Exception as e:
        return 0, str(e)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--total", type=int, required=True)
    ap.add_argument("--sleep", type=float, default=float(os.environ.get("IA_SLEEP", "0.6")),
                     help="每个 identifier 请求间隔秒数(温和限速,默认0.6s)")
    ap.add_argument("--max-per-shard", type=int, default=int(os.environ.get("IA_MAX_PER_SHARD", "0")),
                     help="单 shard 最多处理数(0=不限;死循环防护建议设上限)")
    args = ap.parse_args()

    with open(IDS_FILE, encoding="utf-8") as f:
        all_ids = json.load(f)

    # 按 shard 切片(与内閣 hv.py 分片手法一致:i % total == shard)
    my_ids = [ident for i, ident in enumerate(all_ids) if i % args.total == args.shard]
    if args.max_per_shard > 0:
        my_ids = my_ids[: args.max_per_shard]

    print(f"[shard {args.shard}/{args.total}] 本片 identifier 数: {len(my_ids)}", flush=True)

    ok = skipped_exist = skipped_no_djvu = skipped_not_pd = skipped_short = fail = 0
    consec_fail = 0
    req_count = 0  # 本 shard 累计真实请求数(死循环防护:异常爆炸时能及时发现)

    for i, ident in enumerate(my_ids, 1):
        worker = WORKERS[i % len(WORKERS)]  # 轮询 3 节点,分散出口 IP、分散配额
        key = f"{R2_PREFIX}{ident}.txt"
        url = f"{worker}/ia?id={urllib.parse.quote(ident)}&key={urllib.parse.quote(key)}"

        status, body = http_get(url, timeout=50)
        req_count += 1

        if status == 200:
            try:
                j = json.loads(body)
            except Exception:
                j = {}
            if j.get("skipped"):
                reason = j.get("reason", "")
                if reason == "no_djvu_txt":
                    skipped_no_djvu += 1
                elif reason == "not_public_domain":
                    skipped_not_pd += 1
                elif reason == "too_short":
                    skipped_short += 1
                else:
                    skipped_exist += 1  # 幂等:R2已存在
            elif j.get("ok"):
                ok += 1
                consec_fail = 0
            else:
                fail += 1
        else:
            fail += 1
            consec_fail += 1

        if (i % 50) == 0 or i == len(my_ids):
            print(
                f"[shard {args.shard}] {i}/{len(my_ids)} 落{ok} 跳已存{skipped_exist} "
                f"剔无全文{skipped_no_djvu} 剔非公版{skipped_not_pd} 剔过短{skipped_short} 败{fail} "
                f"· 真实请求数{req_count}",
                flush=True,
            )

        # 死循环/异常爆炸防护:连续失败过多(archive.org 可能触发限流或封锁),立即熔断退出,别硬重试
        if consec_fail >= 15:
            print(f"[shard {args.shard}] ⚠️ 连续失败 {consec_fail} 次,熔断停止(疑似限流/封锁),立即退出别硬冲", flush=True)
            break

        time.sleep(args.sleep)

    print(
        f"=== shard {args.shard}/{args.total} 完成 · 落{ok} 跳已存{skipped_exist} "
        f"剔无全文{skipped_no_djvu} 剔非公版{skipped_not_pd} 剔过短{skipped_short} 败{fail} "
        f"· 真实请求数{req_count} ===",
        flush=True,
    )


if __name__ == "__main__":
    main()
