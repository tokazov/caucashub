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
    signature_label = "მხარეთა ხელმოწერები" if item["language"] == "ge" else "ПОДПИСИ СТОРОН"
    assert compact(signature_label) in normalized, "Missing signature section"
    signatures = normalized.split(compact(signature_label), 1)[1]
    for role in ("shipper", "carrier"):
        name = item[role]
        assert any("\u10a0" <= char <= "\u10ff" or "\u1c90" <= char <= "\u1cbf" for char in name), "Expected explicitly configured Georgian legal name"
        assert not re.search(r"[a-zA-Z\u0400-\u04ff]", name), "Legal name must not fall back to a registration name"
        assert normalized.count(compact(name)) >= 2, f"{item['file']}: legal name missing from body or signatures"
        assert compact(name) in signatures, f"{item['file']}: {role} name missing from signature section"
        display = item.get("registration_" + role)
        if display and display != name:
            assert compact(display) not in normalized, "Registration name leaked into official participant fields"
    if item["language"] == "ge":
        assert any("\u10a0" <= char <= "\u10ff" for char in text), "Georgian act must contain Georgian labels"
    else:
        assert any("\u0400" <= char <= "\u04ff" for char in text), "Russian act must contain Cyrillic labels"
    assert str(int(item["weight"])) in re.sub(r"[\s,]", "", text), "Missing shipment weight"
    assert str(int(item["price"])) in re.sub(r"[\s,]", "", text), "Missing agreed price"
    report.append({"file": item["file"], "source": item["source"], "language": item["language"], "pages": len(reader.pages), "status": "passed"})
(root / "pdf-checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{len(report)} actual downloaded act PDFs passed content, participant, route, weight and language checks")
