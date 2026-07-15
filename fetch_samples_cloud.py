# 云端(GH Actions runner)拉取123真实页面样图,只下载不处理
# 本机到123 CDN的TLS连接不稳(SSLEOFError反复复现,含走1082代理仍相同),
# 改用已验证可用的云端网络环境取图,规避本机网络问题,不做本地反复救火。
import os, sys, requests

PAN = "https://open-api.123pan.com"
PCID = os.environ["PAN_CID"]
PSEC = os.environ["PAN_SEC"]
PAN_DIR_ID = os.environ.get("PAN_DIR_ID", "36780084")
MAX_PAGES = int(os.environ.get("MAX_PAGES", "8"))

S = requests.Session()
r = S.post(PAN + "/api/v1/access_token", headers={"Platform": "open_platform"},
           json={"clientID": PCID, "clientSecret": PSEC}, timeout=30)
tok = (r.json().get("data") or {}).get("accessToken")
if not tok:
    sys.exit("access_token failed: " + r.text[:300])
h = {"Authorization": "Bearer " + tok, "Platform": "open_platform"}

r2 = S.get(PAN + f"/api/v2/file/list?parentFileId={PAN_DIR_ID}&limit=100", headers=h, timeout=30)
kids = [k for k in r2.json()["data"]["fileList"] if k.get("type") == 0]
kids.sort(key=lambda k: k["filename"])
kids = kids[:MAX_PAGES]
if not kids:
    sys.exit(f"{PAN_DIR_ID} 下没找到页面文件")
print(f"取到 {len(kids)} 页: {[k['filename'] for k in kids]}", flush=True)

out_dir = "samples"
os.makedirs(out_dir, exist_ok=True)
ok = 0
for k in kids:
    for attempt in (1, 2):
        try:
            r3 = S.get(PAN + f"/api/v1/file/download_info?fileId={k['fileId']}", headers=h, timeout=30)
            data = r3.json().get("data") or {}
            url = data.get("downloadUrl")
            if not url:
                print(f"跳过(拿不到downloadUrl,attempt {attempt}): {k['filename']} resp={r3.text[:200]}", flush=True)
                continue
            resp = S.get(url, timeout=60)
            resp.raise_for_status()
            fp = os.path.join(out_dir, k["filename"])
            open(fp, "wb").write(resp.content)
            print("saved:", fp, len(resp.content), "bytes", flush=True)
            ok += 1
            break
        except Exception as e:
            print(f"失败(attempt {attempt}): {k['filename']} {e}", flush=True)

print(f"DONE {ok}/{len(kids)} pages -> {out_dir}", flush=True)
if ok == 0:
    sys.exit("一页都没下下来")
