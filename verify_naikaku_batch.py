#!/usr/bin/env python3
# 内阁抓取后置校验闸(2026-07-14 立):
# harvest_artifact.py 早就把实抓页数写进 _meta.json(pages=len(imgs)),
# worklist_naikaku.csv 早就有期望页数(pages列)——两边数字一直摆在那,从没人对过。
# 件当冊(实抓远超预期)/ pagelist越界(实抓远少预期)/ 零页,都会在这一比就现形。
# 本脚本跑在每个 shard 里、每 6h cron 自动跑一次:超差率过阈值 → exit 1 判红,
# 不删产出(零删除)、只是把"这批可能有问题"从静默变成刺眼。
import os, csv, json, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # 防 Windows 本地测试 GBK 编码炸;Actions ubuntu 本就UTF-8,无副作用
except Exception:
    pass

WORKLIST = os.environ.get("WORKLIST", "worklist_naikaku.csv")
OUT = os.environ.get("OUT", "out")
TOL = float(os.environ.get("VERIFY_TOL", "0.15"))              # 单本容差 15%
FAIL_RATE = float(os.environ.get("VERIFY_FAIL_RATE", "0.10"))  # 本shard超差率 >10% 才判红

expected = {}
if os.path.exists(WORKLIST):
    with open(WORKLIST, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            p = (r.get("pages") or "").strip()
            iid = (r.get("id") or "").strip()
            if iid and p.isdigit():
                expected[iid] = int(p)

checked, suspects = 0, []
if os.path.isdir(OUT):
    for iid in sorted(os.listdir(OUT)):
        meta_path = os.path.join(OUT, iid, "_meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
        except Exception:
            continue
        actual = meta.get("pages")
        if actual is None:
            continue  # 这条产线的 _meta.json 不含 pages 字段,不是本闸校验范围
        checked += 1
        exp = expected.get(iid)
        if exp:
            ratio = abs(actual - exp) / exp
            if ratio > TOL:
                kind = "件当冊疑似·实抓远超预期" if actual > exp * 1.5 else "pagelist越界疑似·实抓远少预期"
                suspects.append({"id": iid, "expected": exp, "actual": actual, "ratio": round(ratio, 2), "flag": kind})
        elif actual == 0:
            suspects.append({"id": iid, "expected": None, "actual": 0, "ratio": 1.0, "flag": "零页"})

report = {"checked": checked, "suspect_count": len(suspects), "suspects": suspects,
          "tolerance": TOL, "fail_rate_threshold": FAIL_RATE}
if os.path.isdir(OUT):
    json.dump(report, open(os.path.join(OUT, "_verify_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

rate = (len(suspects) / checked) if checked else 0
print(f"校验: 核对{checked}本 · 可疑{len(suspects)}本 · 可疑率{rate:.1%}(容差{TOL:.0%}/判红阈值{FAIL_RATE:.0%})", flush=True)
for s in suspects[:30]:
    print(f"  ⚠️ {s['id']}: 预期{s['expected']}页 实抓{s['actual']}页 · {s['flag']}", flush=True)

if checked > 0 and rate > FAIL_RATE:
    print(f"\n❌ 可疑率{rate:.1%} 超阈值{FAIL_RATE:.0%} · 本 shard 判红(产出仍保留,_verify_report.json 已写入待查)", flush=True)
    sys.exit(1)
print("✅ 校验通过", flush=True)
