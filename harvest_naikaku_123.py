# -*- coding: utf-8 -*-
# 航母正解:runner 直连内阁 contentDownload(新鲜Azure IP·不经CF worker)→ 合成PDF → 传123 → 下一本
#   ★2026-07-05 probe 实测:runner Azure IP 直连 contentDownload=200(2.28MB真货);IIIF单页=403(相反于本地)
#   ★禁写R2:直传123(PAN_CID_MAIN/PAN_SEC_MAIN 中医号)
#   ★幂等:传前查123目标目录该文件是否已存在
import os, sys, io, re, csv, json, time, zipfile, hashlib, threading
import requests
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WL     = os.environ.get("WORKLIST", "worklist_smoke.csv")
SHARD  = int(os.environ.get("SHARD", "0"))
TOTAL  = int(os.environ.get("TOTAL", "1"))
LIMIT  = int(os.environ.get("LIMIT", "0"))
BOOK_PAR = int(os.environ.get("BOOK_PAR", "4"))
H = "www.digital.archives.go.jp"
UA = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
      "Accept-Language":"ja,en;q=0.8","Accept":"*/*"}
PAN_ROOT_PATH = ["guji", "内阁医书"]   # 中医号 guji/内阁医书/{番号 书名}/

# ---------------- Pan(从 r2_to_123.py 复制·带限流退避·稳定) ----------------
B123 = "https://open-api.123pan.com"
class Pan:
    def __init__(self, cfg):
        self.cfg = cfg
        self.s = requests.Session(); self.s.trust_env = False
        ad = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
        self.s.mount("https://", ad)
        self.tok = None; self.lock = threading.Lock()
    def _login(self):
        r = self.s.post(B123 + "/api/v1/access_token", headers={"Platform": "open_platform"},
                        json={"clientID": self.cfg["client_id"], "clientSecret": self.cfg["client_secret"]}, timeout=60).json()
        self.tok = r.get("data", {}).get("accessToken")
        if not self.tok: raise RuntimeError("123 token 失败: " + str(r)[:200])
    def call(self, method, path, body=None, params=None, _retry=0):
        with self.lock:
            if not self.tok: self._login()
            tok = self.tok
        h = {"Platform": "open_platform", "Authorization": "Bearer " + tok}
        if body is not None: h["Content-Type"] = "application/json"
        try:
            r = self.s.request(method, B123 + path, headers=h, params=params,
                               data=json.dumps(body) if body is not None else None, timeout=90)
            j = r.json()
        except Exception:
            if _retry < 6: time.sleep(5*(_retry+1)); return self.call(method, path, body, params, _retry+1)
            raise
        code = j.get("code")
        if code == 0: return j
        msg = str(j.get("message", ""))
        if code == 401 or "token" in msg.lower():
            with self.lock: self.tok = None
            if _retry < 4: return self.call(method, path, body, params, _retry+1)
        if "频繁" in msg or "exceed" in msg.lower() or "limit" in msg.lower() or code in (429, 5066):
            if _retry < 12: time.sleep(min(90, 5*(_retry+1))); return self.call(method, path, body, params, _retry+1)
        raise RuntimeError(f"123 {path} code={code} {msg[:120]}")
    def list_dir(self, fid):
        out, last = [], 0
        while True:
            j = self.call("GET", "/api/v2/file/list", params={"parentFileId": fid, "limit": 100, "lastFileId": last})
            d = j.get("data", {}); out += d.get("fileList", []); last = d.get("lastFileId", -1)
            if last == -1: break
        return [x for x in out if x.get("trashed", 0) == 0]
    def mkdir(self, parent, name):
        j = self.call("POST", "/upload/v1/file/mkdir", body={"parentID": str(parent), "name": name})
        return j["data"]["dirID"]
    def upload_domain(self):
        with self.lock:
            if getattr(self, "_updom", None): return self._updom
        j = self.call("GET", "/upload/v2/file/domain"); dom = j["data"][0]
        with self.lock: self._updom = dom
        return dom
    def upload(self, parent, name, data, _retry=0):
        etag = hashlib.md5(data).hexdigest()
        try:
            dom = self.upload_domain()
            with self.lock:
                if not self.tok: self._login()
                tok = self.tok
            r = self.s.post(dom + "/upload/v2/file/single/create",
                headers={"Platform":"open_platform","Authorization":"Bearer "+tok},
                files={"file": (name, data, "application/octet-stream")},
                data={"parentFileID": str(parent), "filename": name, "etag": etag,
                      "size": str(len(data)), "duplicate": "2"}, timeout=300)
            j = r.json()
            if j.get("code") == 0 and (j["data"].get("completed") or j["data"].get("fileID")): return "ok"
            msg = str(j.get("message", ""))
            if "频繁" in msg or "exceed" in msg.lower() or j.get("code") in (429, 401):
                if _retry < 8: time.sleep(min(60, 5*(_retry+1))); return self.upload(parent, name, data, _retry+1)
            if _retry < 3: time.sleep(5*(_retry+1)); return self.upload(parent, name, data, _retry+1)
            raise RuntimeError(f"single/create code={j.get('code')} {msg[:80]}")
        except RuntimeError: raise
        except Exception:
            if _retry < 5: time.sleep(5*(_retry+1)); return self.upload(parent, name, data, _retry+1)
            raise
    def ensure_dir(self, path_names):
        """按名字链找/建目录·返回末级 fid"""
        fid = 0
        for nm in path_names:
            hit = [x for x in self.list_dir(fid) if x["filename"]==nm and x["type"]==1]
            fid = hit[0]["fileId"] if hit else self.mkdir(fid, nm)
        return fid

# ---------------- 内阁直连 contentDownload ----------------
S = requests.Session(); S.trust_env = True
def naj_list(iid):
    r = S.get(f"https://{H}/img/{iid}", headers=UA, timeout=40)
    if r.status_code != 200: raise RuntimeError(f"img HTTP{r.status_code}")
    m = re.search(r'var najContentList = (\[[\s\S]*?\]);', r.text)
    if not m: raise RuntimeError("no najContentList")
    return json.loads(m.group(1))
def dl_zip(iid, sel):
    body = "&".join("cid=" + quote("da12/"+str(x["id"]), safe="") for x in sel)
    r = S.post(f"https://{H}/contentDownload/{iid}?type=imageJpeg", data=body,
               headers={**UA,"Content-Type":"application/x-www-form-urlencoded",
                        "Referer":f"https://{H}/img/{iid}","Origin":f"https://{H}"}, timeout=300)
    if r.status_code != 200 or "zip" not in r.headers.get("Content-Type","").lower():
        raise RuntimeError(f"cd HTTP{r.status_code}")
    return r.content
def dl_book_pdf(iid):
    """整册 → PDF bytes(直连 contentDownload·分块≤100)"""
    import img2pdf
    lst = naj_list(iid)
    total = len(lst)
    if not total: raise RuntimeError("零页")
    imgs = []
    frm = 1
    while frm <= total:
        to = min(frm+99, total)
        content = dl_zip(iid, lst[frm-1:to])
        zf = zipfile.ZipFile(io.BytesIO(content))
        for n in sorted(zf.namelist()):
            if not n.endswith("/"): imgs.append(zf.read(n))
        frm = to + 1
    if len(imgs) < max(1, total-1): raise RuntimeError(f"页缺 {len(imgs)}/{total}")
    return img2pdf.convert(imgs), total

# ---------------- 主 ----------------
CID = os.environ.get("PAN_CID_MAIN"); SEC = os.environ.get("PAN_SEC_MAIN")
if not CID or not SEC:
    print("!! 缺 PAN_CID_MAIN/PAN_SEC_MAIN secret", flush=True); sys.exit(1)
pan = Pan({"client_id": CID, "client_secret": SEC})

rows = list(csv.DictReader(open(WL, encoding="utf-8-sig")))
jobs = [r for i, r in enumerate(rows) if i % TOTAL == SHARD]
if LIMIT: jobs = jobs[:LIMIT]
print(f"shard {SHARD}/{TOTAL} · {len(jobs)} 冊 · runner直连contentDownload→123", flush=True)

# 目标目录缓存(番号书名 → fid)· 幂等缓存
_dir_cache = {}; _dir_lock = threading.Lock()
def book_fid(folder_name):
    with _dir_lock:
        if folder_name in _dir_cache: return _dir_cache[folder_name]
    fid = pan.ensure_dir(PAN_ROOT_PATH + [folder_name])
    with _dir_lock: _dir_cache[folder_name] = fid
    return fid

lock = threading.Lock(); cnt = {"ok":0,"skip":0,"fail":0,"bytes":0}; t0 = time.time()
def worker(row):
    iid = (row.get("iid") or row.get("id") or "").strip()
    fname = (row.get("fname") or "").strip()
    folder = os.path.basename((row.get("夹名") or "").strip()) or fname
    if not iid or not fname: return
    pdf_name = fname + ".pdf"
    try:
        fid = book_fid(folder)
        # 幂等:目标目录已有该 PDF → skip
        exist = [x for x in pan.list_dir(fid) if x["filename"]==pdf_name and x["type"]==0]
        if exist:
            with lock: cnt["skip"] += 1
            print(f"  skip {pdf_name[:50]}", flush=True); return
        pdf_bytes, pages = dl_book_pdf(iid)
        pan.upload(fid, pdf_name, pdf_bytes)
        with lock:
            cnt["ok"] += 1; cnt["bytes"] += len(pdf_bytes)
            print(f"  OK {pdf_name[:50]} · {pages}页 · {len(pdf_bytes)//1024//1024}MB", flush=True)
    except Exception as e:
        with lock: cnt["fail"] += 1
        print(f"  FAIL {iid} · {str(e)[:80]}", flush=True)

with ThreadPoolExecutor(max_workers=BOOK_PAR) as ex:
    list(ex.map(worker, jobs))
el = time.time()-t0
print(f"\n=== 完 ok={cnt['ok']} skip={cnt['skip']} fail={cnt['fail']} · {cnt['bytes']//1024//1024}MB · {el/60:.1f}min ===", flush=True)
if cnt["ok"]==0 and cnt["fail"]>0:
    print("!! ok=0 全失败 · exit 1", flush=True); sys.exit(1)
