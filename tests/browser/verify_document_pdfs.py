"""Validate real API-downloaded Georgian-name PDFs; rendering is separate local QA."""
import json
import re
import sys
import unicodedata
from pathlib import Path
from pypdf import PdfReader

root = Path(sys.argv[1]).resolve()
items = json.loads((root / 'pdf-manifest.json').read_text(encoding='utf-8'))
assert len(items) == 4
assert {(item['source'], item['language']) for item in items} == {(source, language) for source in ('cargo', 'transport') for language in ('ru', 'ge')}
def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))
report = []
for item in items:
    pdf = (root / item['file']).resolve()
    assert pdf.parent == root and pdf.suffix == '.pdf'
    reader = PdfReader(pdf, strict=True)
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    assert '\ufffd' not in text and '\x00' not in text
    normalized = compact(text)
    signature = 'მხარეთა ხელმოწერები' if item['language'] == 'ge' else 'ПОДПИСИ СТОРОН'
    assert compact(signature) in normalized
    tail = normalized.split(compact(signature), 1)[1]
    for role in ('shipper', 'carrier'):
        name = compact(item[role])
        assert normalized.count(name) >= 2, (item['file'], role, 'body/signature missing')
        assert name in tail
        assert compact(item['registration_' + role]) not in normalized
    assert compact(item['deal_number']) in normalized
    assert 'TEST' in text
    fonts = [str(font.get_object().get('/BaseFont', '')) for page in reader.pages for font in page.get('/Resources').get_object().get('/Font', {}).get_object().values()]
    assert any('NotoSansGeorgian' in font for font in fonts), 'Bundled Georgian/Mtavruli font missing'
    report.append({'file': item['file'], 'pages': len(reader.pages), 'both_names_in_body_and_signatures': True, 'mtavruli_font_embedded': True})
(root / 'pdf-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('4 actual downloaded PDFs passed Georgian names, signatures, registration-name exclusion and embedded-font checks')
