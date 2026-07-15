import os, sys, requests

PAN = "https://open-api.123pan.com"
PCID = os.environ["PAN_CID"]; PSEC = os.environ["PAN_SEC"]
FID = os.environ.get("FID", "36780084")

r = requests.post(PAN + "/api/v1/access_token", headers={"Platform": "open_platform"},
                   json={"clientID": PCID, "clientSecret": PSEC}, timeout=30)
tok = (r.json().get("data") or {}).get("accessToken")
print("token ok:", bool(tok), r.json().get("message") if not tok else "")
if not tok:
    sys.exit(1)

h = {"Authorization": "Bearer " + tok, "Platform": "open_platform"}

# 直接查这个fileId是文件/文件夹/根本不存在(用detail接口,不行就试list当父目录看有没有子项)
r2 = requests.get(PAN + f"/api/v1/file/detail?fileID={FID}", headers=h, timeout=30)
print("detail:", r2.status_code, r2.text[:500])

r3 = requests.get(PAN + f"/api/v2/file/list?parentFileId={FID}&limit=20", headers=h, timeout=30)
print("as-parent-list:", r3.status_code, r3.text[:800])
