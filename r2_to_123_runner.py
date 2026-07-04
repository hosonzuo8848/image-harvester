# -*- coding: utf-8 -*-
# R2 → 123 中医号 直传 · runner上跑 · 本地零负担
# 用法: env R2_ENDPOINT/R2_KEY/R2_SECRET/PAN_CID/PAN_SEC + python r2_to_123_runner.py --prefix naj/ --limit 20
import os, sys, json, time, hashlib, threading, argparse
import boto3, requests

R2_ENDPOINT = os.environ["R2_ENDPOINT"]
R2_KEY = os.environ["R2_KEY"]
R2_SECRET = os.environ["R2_SECRET"]
PAN_CID = os.environ["PAN_CID"]
PAN_SEC = os.environ["PAN_SEC"]
BUCKET = os.environ.get("BUCKET", "guji-sea")
PAN_PARENT = os.environ.get("PAN_PARENT", "0")  # 目标父目录ID·"0"=中医号根

import urllib3
urllib3.disable_warnings()
from botocore.config import Config
s3 = boto3.client("s3", endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_KEY, aws_secret_access_key=R2_SECRET,
    region_name="auto", verify=False,
    config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}))

B123 = "https://open-api.123pan.com"
class Pan:
    def __init__(self):
        self.s = requests.Session(); self.tok = None; self.lock = threading.Lock()
        self._updom = None
    def _login(self):
        r = self.s.post(B123 + "/api/v1/access_token", headers={"Platform": "open_platform"},
            json={"clientID": PAN_CID, "clientSecret": PAN_SEC}, timeout=60).json()
        self.tok = r.get("data", {}).get("accessToken")
        if not self.tok: raise RuntimeError("123 token: " + str(r)[:200])
    def call(self, m, p, body=None, params=None, _r=0):
        with self.lock:
            if not self.tok: self._login()
            tok = self.tok
        h = {"Platform":"open_platform","Authorization":"Bearer "+tok}
        if body is not None: h["Content-Type"]="application/json"
        try:
            r = self.s.request(m, B123+p, headers=h, params=params,
                data=json.dumps(body) if body is not None else None, timeout=90)
            j = r.json()
        except Exception:
            if _r<6: time.sleep(5*(_r+1)); return self.call(m,p,body,params,_r+1)
            raise
        c = j.get("code")
        if c==0: return j
        msg = str(j.get("message",""))
        if c==401 or "token" in msg.lower():
            with self.lock: self.tok = None
            if _r<4: return self.call(m,p,body,params,_r+1)
        if "频繁" in msg or "exceed" in msg.lower() or c in (429,5066):
            if _r<12: time.sleep(min(90,5*(_r+1))); return self.call(m,p,body,params,_r+1)
        raise RuntimeError(f"123 {p} code={c} msg={msg[:120]}")
    def upload_domain(self):
        with self.lock:
            if self._updom: return self._updom
        j = self.call("GET","/upload/v2/file/domain")
        dom = j["data"][0]
        with self.lock: self._updom = dom
        return dom
    def upload(self, parent, name, data, _r=0):
        etag = hashlib.md5(data).hexdigest()
        dom = self.upload_domain()
        with self.lock:
            if not self.tok: self._login()
            tok = self.tok
        try:
            r = self.s.post(dom + "/upload/v2/file/single/create",
                headers={"Platform":"open_platform","Authorization":"Bearer "+tok},
                files={"file":(name,data,"application/octet-stream")},
                data={"parentFileID":str(parent),"filename":name,"etag":etag,
                    "size":str(len(data)),"duplicate":"2"}, timeout=180)
            j = r.json()
            if j.get("code")==0 and (j["data"].get("completed") or j["data"].get("fileID")):
                return "ok"
            msg = str(j.get("message",""))
            if "频繁" in msg or "exceed" in msg.lower() or j.get("code") in (429,401):
                if _r<8: time.sleep(min(60,5*(_r+1))); return self.upload(parent,name,data,_r+1)
            if _r<3: time.sleep(5*(_r+1)); return self.upload(parent,name,data,_r+1)
            raise RuntimeError(f"upload code={j.get('code')} {msg[:80]}")
        except RuntimeError: raise
        except Exception:
            if _r<5: time.sleep(5*(_r+1)); return self.upload(parent,name,data,_r+1)
            raise

def list_keys(prefix, limit):
    out = []; token = None
    while len(out) < limit:
        p = {"Bucket":BUCKET, "Prefix":prefix, "MaxKeys":min(1000, limit-len(out))}
        if token: p["ContinuationToken"] = token
        r = s3.list_objects_v2(**p)
        for o in r.get("Contents",[]):
            if o["Key"].endswith("/") or o["Key"].endswith(".done"): continue
            out.append(o["Key"])
            if len(out)>=limit: break
        if not r.get("IsTruncated"): break
        token = r.get("NextContinuationToken")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="naj/")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()
    pan = Pan()
    keys = list_keys(a.prefix, a.limit)
    print(f"待转 {len(keys)} keys · prefix={a.prefix} · parent={PAN_PARENT}", flush=True)
    ok = fail = del_r2 = 0; t0 = time.time()
    for i, k in enumerate(keys, 1):
        try:
            obj = s3.get_object(Bucket=BUCKET, Key=k)
            data = obj["Body"].read()
            sz_kb = len(data)//1024
            name = k.replace("/", "_")
            r = pan.upload(PAN_PARENT, name, data)
            if r == "ok":
                ok += 1
                # 传成功·立刻删R2(一个个转·一个个删·不积累)
                s3.delete_object(Bucket=BUCKET, Key=k)
                del_r2 += 1
                print(f"[{i}/{len(keys)}] OK+删R2 {sz_kb}KB {k[-50:]}", flush=True)
            else:
                print(f"[{i}/{len(keys)}] {r} {sz_kb}KB {k[-50:]}", flush=True)
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(keys)}] ERR {k[-50:]} {str(e)[:80]}", flush=True)
    el = time.time() - t0
    print(f"\n=== 完 传+删R2 {ok} · fail {fail} · {el/60:.1f}min ===", flush=True)

if __name__ == "__main__":
    main()
