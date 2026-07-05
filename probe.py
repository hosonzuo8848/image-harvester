# -*- coding: utf-8 -*-
# runner 直连内阁 IIIF(不经任何CF worker)· 验证新鲜Azure IP 内阁给不给200
import requests, sys
UA = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
iid = "4018608"
# 1. runner IP
try:
    ip = requests.get("http://api.ipify.org", timeout=15).text
    print(f"runner IP: {ip}", flush=True)
except Exception as e:
    print(f"IP获取失败: {e}", flush=True)
# 2. manifest
r = requests.get(f"https://www.digital.archives.go.jp/api/iiif/{iid}/manifest.json", headers=UA, timeout=30)
print(f"manifest: HTTP {r.status_code}", flush=True)
if r.status_code != 200:
    print(f"  body: {r.text[:200]}", flush=True); sys.exit(0)
m = r.json()
cv = m["sequences"][0]["canvases"]
print(f"  页数: {len(cv)}", flush=True)
first = cv[0]["images"][0]["resource"]["@id"]
print(f"  第1页URL: {first}", flush=True)
# 3. 单页图(决定成败)
r2 = requests.get(first, headers=UA, timeout=40)
print(f"单页图: HTTP {r2.status_code} · CT={r2.headers.get('Content-Type')} · {len(r2.content)//1024}KB", flush=True)
# 4. contentDownload(对比·本地是403)
import re, json
body = "&".join("cid="+requests.utils.quote("da12/"+str(x["id"])) for x in json.loads(re.search(r'var najContentList = (\[[\s\S]*?\]);', requests.get(f"https://www.digital.archives.go.jp/img/{iid}", headers=UA, timeout=20).text).group(1))[:3])
r3 = requests.post(f"https://www.digital.archives.go.jp/contentDownload/{iid}?type=imageJpeg", data=body, headers={**UA,"Content-Type":"application/x-www-form-urlencoded","Referer":f"https://www.digital.archives.go.jp/img/{iid}","Origin":"https://www.digital.archives.go.jp"}, timeout=60)
print(f"contentDownload: HTTP {r3.status_code} · {len(r3.content)//1024}KB", flush=True)
print("=== 结论 ===", flush=True)
print(f"IIIF可下={r2.status_code==200} · 整件可下={r3.status_code==200}", flush=True)
