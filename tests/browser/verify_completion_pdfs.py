"""Verify actual PDF bytes downloaded through the isolated browser UI."""
import json
import re
import sys
import unicodedata
from pathlib import Path
from pypdf import PdfReader

def compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))

root = Path(sys.argv[1]).resolve()
manifest_path = root / "pdf-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assert len(manifest) == 8, f"Expected both source paths, roles and languages at two viewports, got {len(manifest)}"
report = []
for item in manifest:
    pdf = (root / item["file"]).resolve()
    assert pdf.parent == root and pdf.suffix == ".pdf", "Unsafe PDF artifact path"
    assert pdf.read_bytes().startswith(b"%PDF-")
    reader = PdfReader(pdf, strict=True)
    assert reader.pages, "Act must have a readable page"
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "\ufffd" not in text and "\x00" not in text, "Act contains unreadable replacement glyphs"
    normalized = compact(text)
    for field in ("deal_number", "from", "to", "description", "shipper", "carrier"):
        expected = item[field]
        assert expected and compact(expected) in normalized, f"{item['file']}: missing {field} {expected!r}"
    if item["language"] == "ge":
        assert any("\u10a0" <= char <= "\u10ff" for char in text), "Georgian act must contain Georgian labels"
    else:
        assert any("\u0400" <= char <= "\u04ff" for char in text), "Russian act must contain Cyrillic labels"
    assert str(int(item["weight"])) in re.sub(r"[\s,]", "", text), "Missing shipment weight"
    assert str(int(item["price"])) in re.sub(r"[\s,]", "", text), "Missing agreed price"
    report.append({"file": item["file"], "source": item["source"], "language": item["language"], "pages": len(reader.pages), "status": "passed"})
(root / "pdf-checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{len(report)} actual downloaded act PDFs passed content, participant, route, weight and language checks")
