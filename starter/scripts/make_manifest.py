"""Write a corpus manifest for an OpenStax PDF using the automatic content-page rule.

Run from starter/:
    python scripts/make_manifest.py ../data/anatomy-and-physiology-2e.pdf ../data/manifest_full_book.json \
        --source-id openstax-ap2e-full --license "CC BY-NC-SA 4.0 (stated on PDF page 4)" \
        --url https://openstax.org/details/books/anatomy-and-physiology-2e
"""
import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a plain script from starter/
from src.ingestion import content_pages, load_pdf  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("pdf", type=Path)
parser.add_argument("out", type=Path)
parser.add_argument("--source-id", required=True)
parser.add_argument("--license", required=True, help="licence as stated in the PDF; never guessed")
parser.add_argument("--url", required=True, help="where the PDF was downloaded")
args = parser.parse_args()

pages, problems = load_pdf(args.pdf, args.source_id, args.pdf.name)
counted = {p.page for p in content_pages(pages)}
sha256 = hashlib.sha256(args.pdf.read_bytes()).hexdigest()

chapters = []
for number in sorted({p.metadata["chapter"] for p in pages if p.metadata["chapter"] is not None}):
    in_chapter = [p for p in pages if p.metadata["chapter"] == number]
    kept = [{"page": p.page, "chars": len(p.text)} for p in in_chapter if p.page in counted]
    chapters.append({
        "chapter": number,
        "title": in_chapter[0].metadata["chapter_title"],
        "pdf_pages": [in_chapter[0].page, in_chapter[-1].page],
        "counted_pages": kept,
        "excluded_pages": [p.page for p in in_chapter if p.page not in counted],
        "counted_page_total": len(kept),
        "char_total": sum(k["chars"] for k in kept),
    })

manifest = {
    "source_id": args.source_id,
    "title": str((__import__("pypdf").PdfReader(args.pdf).metadata or {}).get("/Title") or args.pdf.stem),
    "source_path_or_url": f"data/{args.pdf.name}",
    "original_source_url": args.url,
    "license_or_permission": args.license,
    "accessed_at": date.today().isoformat(),
    "snapshot": {"physical_pages": len(pages), "sha256": sha256},
    "page_counting_rule": ("Automatic (src/ingestion.py content_pages): physical page numbers, 1-based. Count chapter "
                           "body pages; exclude front matter before the first 'CHAPTER N' page (cover, contents, "
                           "preface), each chapter's 'Key Terms' page up to the next chapter (glossary, summary, "
                           "review questions), everything from REFERENCES/INDEX on, and pages under 50 characters."),
    "front_matter_pages": [p.page for p in pages if p.metadata["chapter"] is None],
    "char_count_method": "len(normalized page text) after src/ingestion.py normalize_text",
    "filter_field": {"name": "chapter", "type": "int", "values": [c["chapter"] for c in chapters],
                     "source": "'CHAPTER N' line on each chapter's opening page"},
    "extraction_problems": problems,
    "chapters": chapters,
    "counted_page_total": len(counted),
}
args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"{args.out}: {len(pages)} physical pages, {len(counted)} counted, {len(chapters)} chapters")
