"""OCR the images inside a PDF's counted pages with PaddleOCR; save the text as JSON for src/run.py.

Runs in its own Python 3.12 venv (PaddlePaddle has no build for Python 3.14). From starter/:
    .venv-ocr\\Scripts\\python.exe scripts/ocr_images.py ../data/anatomy-and-physiology-2e_70pages.pdf ../data/manifest.json
writes ../data/ocr_<pdf name>.json. Results are saved after every page, so an interrupted run resumes.
"""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pymupdf
from paddleocr import PaddleOCR

MIN_SCORE = 0.5  # drop recognitions the model itself is unsure about
MIN_SIDE = 64  # skip icons and decorations smaller than this (pixels)
DET_MODEL, REC_MODEL = "PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"

parser = argparse.ArgumentParser()
parser.add_argument("pdf", type=Path)
parser.add_argument("manifest", type=Path, help="only the manifest's counted pages are read")
args = parser.parse_args()
out_path = args.pdf.with_name(f"ocr_{args.pdf.stem}.json")

pdf_sha256 = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
counted = sorted(p["page"] for ch in manifest["chapters"] for p in ch["counted_pages"])

result = {
    "pdf": args.pdf.name, "pdf_sha256": pdf_sha256,
    "engine": {"paddleocr": version("paddleocr"), "paddlepaddle": version("paddlepaddle"),
               "det_model": DET_MODEL, "rec_model": REC_MODEL, "device": "cpu", "min_score": MIN_SCORE},
    "pages": {},
}
if out_path.exists():  # resume a run of the same PDF
    previous = json.loads(out_path.read_text(encoding="utf-8"))
    if previous.get("pdf_sha256") == pdf_sha256:
        result["pages"] = previous["pages"]

# enable_mkldnn=False: Paddle 3.x's oneDNN path fails on Windows CPUs ("ConvertPirAttribute2RuntimeAttribute")
ocr = PaddleOCR(lang="en", text_detection_model_name=DET_MODEL, text_recognition_model_name=REC_MODEL,
                use_doc_orientation_classify=False, use_doc_unwarping=False,
                use_textline_orientation=False, enable_mkldnn=False)
doc = pymupdf.open(args.pdf)
started = time.perf_counter()
todo = [n for n in counted if str(n) not in result["pages"]]
print(f"{len(counted)} counted pages, {len(todo)} left to OCR")

for done, number in enumerate(todo, 1):
    page = doc[number - 1]
    figures = []
    for image in page.get_images(full=True):
        xref, width, height = image[0], image[2], image[3]
        if min(width, height) < MIN_SIDE:
            continue
        pix = pymupdf.Pixmap(doc, xref)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        if pix.n != 3:  # grayscale / CMYK -> RGB
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
        t = time.perf_counter()
        found = ocr.predict(rgb[:, :, ::-1].copy())[0]  # PaddleOCR expects BGR
        lines = [{"text": text, "score": round(float(score), 3), "top": float(np.min(poly[:, 1])),
                  "left": float(np.min(poly[:, 0]))}
                 for text, score, poly in zip(found["rec_texts"], found["rec_scores"], found["rec_polys"])
                 if score >= MIN_SCORE and text.strip()]
        lines.sort(key=lambda line: (round(line["top"] / 20), line["left"]))  # rough reading order
        rects = page.get_image_rects(xref)
        figures.append({
            "xref": xref, "size": [width, height],
            "rect": [round(v, 1) for v in rects[0]] if rects else None,
            "text": " ".join(line["text"] for line in lines),
            "lines": [{"text": line["text"], "score": line["score"]} for line in lines],
            "seconds": round(time.perf_counter() - t, 2),
        })
    result["pages"][str(number)] = figures
    result["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    words = sum(len(f["text"].split()) for f in figures)
    print(f"[{done}/{len(todo)}] page {number}: {len(figures)} images, {words} words "
          f"({time.perf_counter() - started:.0f}s elapsed)", flush=True)

images = [f for figs in result["pages"].values() for f in figs]
print(f"done: {len(images)} images, {sum(1 for f in images if f['text'])} with text -> {out_path}")
