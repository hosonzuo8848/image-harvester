# 云端(GH Actions)实测:真实大PDF -> 逐页WebP 转换耗时基准
# 目的:回答"几十万个PDF转webp工作量有多大、能不能用API/自动化搞定"这个真实规模问题
import os, sys, time, requests

PAN = "https://open-api.123pan.com"
PCID = os.environ["PAN_CID"]
PSEC = os.environ["PAN_SEC"]
FILE_ID = int(os.environ.get("FILE_ID", "37384870"))

S = requests.Session()
r = S.post(PAN + "/api/v1/access_token", headers={"Platform": "open_platform"},
           json={"clientID": PCID, "clientSecret": PSEC}, timeout=30)
tok = (r.json().get("data") or {}).get("accessToken")
if not tok:
    sys.exit("token failed: " + r.text[:300])
h = {"Authorization": "Bearer " + tok, "Platform": "open_platform"}

r2 = S.get(PAN + f"/api/v1/file/download_info?fileId={FILE_ID}", headers=h, timeout=30)
url = r2.json()["data"]["downloadUrl"]

print("downloading sample pdf...", flush=True)
t0 = time.time()
resp = S.get(url, timeout=180)
resp.raise_for_status()
pdf_bytes = resp.content
dl_time = time.time() - t0
print(f"downloaded {len(pdf_bytes)/1024/1024:.1f} MB in {dl_time:.1f}s ({len(pdf_bytes)/1024/1024/dl_time:.1f} MB/s)", flush=True)

with open("sample.pdf", "wb") as f:
    f.write(pdf_bytes)

import fitz  # PyMuPDF
import io
from PIL import Image
doc = fitz.open("sample.pdf")
n_pages = doc.page_count
print(f"page_count = {n_pages}", flush=True)

os.makedirs("out_webp", exist_ok=True)

# 先测前20页(或全部,取小值)得每页耗时率,再推算整本/整批需要多久
sample_n = min(20, n_pages)
t1 = time.time()
total_webp_bytes = 0
for i in range(sample_n):
    page = doc[i]
    # 150 DPI 渲染(阅读器实际用的分辨率量级,不是极限画质)
    pix = page.get_pixmap(dpi=150)
    webp_path = f"out_webp/page_{i+1:04d}.webp"
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img.save(webp_path, "WEBP", quality=85)
    total_webp_bytes += os.path.getsize(webp_path)
render_time = time.time() - t1

per_page_sec = render_time / sample_n
avg_webp_kb = total_webp_bytes / sample_n / 1024

print(f"渲染{sample_n}页耗时: {render_time:.2f}s, 每页{per_page_sec:.3f}s, 平均每张webp {avg_webp_kb:.1f}KB", flush=True)
print(f"推算:整本{n_pages}页转换约需 {per_page_sec*n_pages:.1f}s ({per_page_sec*n_pages/60:.1f}分钟)", flush=True)

doc.close()

summary = {
    "sample_file_id": FILE_ID,
    "pdf_size_mb": round(len(pdf_bytes)/1024/1024, 1),
    "download_time_sec": round(dl_time, 1),
    "total_pages_in_this_pdf": n_pages,
    "sampled_pages": sample_n,
    "render_time_for_sample_sec": round(render_time, 2),
    "per_page_sec": round(per_page_sec, 3),
    "avg_webp_kb": round(avg_webp_kb, 1),
    "estimated_full_pdf_conversion_sec": round(per_page_sec * n_pages, 1),
    "estimated_full_pdf_conversion_min": round(per_page_sec * n_pages / 60, 1),
}
import json
with open("benchmark_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("SUMMARY_JSON:", json.dumps(summary, ensure_ascii=False))
