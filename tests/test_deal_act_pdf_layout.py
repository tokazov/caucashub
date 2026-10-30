"""Render-command regressions for the actual bilingual act PDF generator."""
from datetime import datetime, timezone
from decimal import Decimal

from contextlib import contextmanager
import unittest
from unittest.mock import patch
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from app import pdf_utils


@contextmanager
def recording():
    recorded = []
    original_canvas = canvas.Canvas

    class RecordingCanvas(original_canvas):
        def drawString(self, x, y, text, *args, **kwargs):
            recorded.append({
                "page": self._pageNumber, "x": x, "y": y, "text": str(text),
                "font": self._fontname, "size": self._fontsize,
                "color": self._fillColorObj.rgb(),
            })
            return super().drawString(x, y, text, *args, **kwargs)

    with patch.object(canvas, "Canvas", RecordingCanvas):
        yield recorded


def sample(lang):
    return {
        "lang": lang, "act_number": "CH-2026-0042", "deal_id": 42,
        "completed_at": datetime(2026, 10, 27, 12, tzinfo=timezone.utc),
        "shipper_name": "ООО Груз Кавкасия", "shipper_inn": "404123456",
        "shipper_phone": "+995599920001",
        "carrier_name": "შპს კავკასიის ტრანსპორტი", "carrier_inn": "404123457",
        "carrier_phone": "+995599920002", "from_city": "თბილისი", "to_city": "Батуми",
        "cargo_desc": "Строительные материалы / სამშენებლო მასალები",
        "weight_kg": 3000, "truck_type": "Тент / ტენტი",
        "agreed_price": Decimal("520.45"), "currency": "GEL",
        "loading_at": datetime(2026, 10, 25, tzinfo=timezone.utc),
        "delivered_at": datetime(2026, 10, 27, tzinfo=timezone.utc),
    }


def assert_inside_page(drawing):
    width, height = A4
    for op in drawing:
        assert 39.9 <= op["x"], op
        assert op["x"] + pdfmetrics.stringWidth(op["text"], op["font"], op["size"]) <= width - 39.9, op
        assert 10 <= op["y"] <= height - 10, op


def check_signature_labels_and_names_are_visible_after_price_block(lang, drawing):
    data = sample(lang)
    result = pdf_utils.generate_act_pdf(data)
    assert result.startswith(b"%PDF-")
    signature = next(op for op in drawing if op["text"] == pdf_utils._I18N[lang]["signatures"])
    assert signature["color"] == (0, 0, 0)
    later = drawing[drawing.index(signature):]
    for name in (data["shipper_name"], data["carrier_name"]):
        op = next(item for item in later if item["text"] == name)
        assert op["color"] == (0, 0, 0)
    assert len([op for op in drawing if op["text"] == "520.45 GEL"]) == 1
    assert not any(op["text"].startswith("GEL ") for op in drawing)
    assert_inside_page(drawing)


def check_long_names_route_and_cargo_wrap_without_losing_content(lang, drawing):
    data = sample(lang)
    data["shipper_name"] = "ООО Международная транспортная компания Кавказские грузовые перевозки и логистика"
    data["carrier_name"] = "შპს საერთაშორისო სატრანსპორტო კომპანია კავკასიის გადაზიდვები და ლოგისტიკა"
    data["from_city"] = "Тбилиси, проспект Давида Агмашенебели 125, склад № 4"
    data["to_city"] = "Батуми, улица Георгия Леонидзе 78, разгрузка через северный въезд"
    words = [f"груз{i}" if i % 2 else f"ტვირთი{i}" for i in range(240)]
    data["cargo_desc"] = " ".join(words)
    pdf_utils.generate_act_pdf(data)
    rendered = " ".join(op["text"] for op in drawing)
    assert set(words) <= set(rendered.split())
    assert data["shipper_name"] in rendered
    assert data["carrier_name"] in rendered
    assert_inside_page(drawing)
    assert max(op["page"] for op in drawing) > 1


def check_unbroken_cargo_tokens_stay_inside_value_column(lang, drawing):
    data = sample(lang)
    token = "ტვირთიABCDE" * 65
    data["cargo_desc"] = token
    pdf_utils.generate_act_pdf(data)
    pieces = [op for op in drawing if op["x"] == 200 and "ABCDE" in op["text"]]
    assert len(pieces) > 1
    # Compare all actual value lines, including a tail shorter than one marker.
    start = next(i for i, op in enumerate(drawing) if op["x"] == 200 and token.startswith(op["text"]))
    end = next(i for i in range(start + 1, len(drawing)) if drawing[i]["text"] == pdf_utils._I18N[lang]["weight"] + ":")
    actual = "".join(op["text"] for op in drawing[start:end] if op["x"] == 200)
    assert actual == token
    assert_inside_page(drawing)


def check_continued_pages_keep_document_identity_and_footer(lang, drawing):
    data = sample(lang)
    data["cargo_desc"] = "очень длинное описание ტვირთი " * 160
    pdf_utils.generate_act_pdf(data)
    pages = sorted({op["page"] for op in drawing})
    assert len(pages) > 1
    for page in pages:
        text = " ".join(op["text"] for op in drawing if op["page"] == page)
        assert data["act_number"] in text
        assert "CaucasHub" in text
        assert pdf_utils._I18N[lang]["footer"] in text
    assert_inside_page(drawing)


def check_bundled_font_contains_real_alphabet_glyphs(lang, drawing):
    data = sample(lang)
    pdf_utils.generate_act_pdf(data)
    for op in drawing:
        face = pdfmetrics.getFont(op["font"]).face
        assert hasattr(face, "charToGlyph"), "Bilingual documents require the bundled Unicode font"
        for char in op["text"]:
            if char.isalpha():
                assert ord(char) in face.charToGlyph, (op["font"], char)


def check_domain_suffix_does_not_overlap_brand(drawing):
    pdf_utils.generate_act_pdf(sample("ru"))
    brand = next(op for op in drawing if op["text"] == "CaucasHub")
    suffix = next(op for op in drawing if op["text"] == ".ge")
    assert suffix["x"] > brand["x"] + pdfmetrics.stringWidth(brand["text"], brand["font"], brand["size"])


class TestDealActPdfLayout(unittest.TestCase):
    def check_languages(self, check):
        for lang in ("ru", "ge"):
            with self.subTest(lang=lang), recording() as drawing:
                check(lang, drawing)

    def test_signatures_remain_visible(self):
        self.check_languages(check_signature_labels_and_names_are_visible_after_price_block)

    def test_long_content_wraps(self):
        self.check_languages(check_long_names_route_and_cargo_wrap_without_losing_content)

    def test_long_unbroken_tokens_wrap(self):
        self.check_languages(check_unbroken_cargo_tokens_stay_inside_value_column)

    def test_continued_pages_have_identity(self):
        self.check_languages(check_continued_pages_keep_document_identity_and_footer)

    def test_bundled_unicode_alphabets(self):
        self.check_languages(check_bundled_font_contains_real_alphabet_glyphs)

    def test_mtavruli_legal_names_preserve_case_in_parties_and_signatures(self):
        for lang in ("ru", "ge"):
            with self.subTest(lang=lang), recording() as drawing:
                data = sample(lang)
                data["shipper_name"] = "ᲒᲘᲝᲠᲒᲘ ᲙᲐᲞᲐᲜᲐᲫᲔ"
                data["carrier_name"] = 'შპს „ᲙᲐᲕᲙᲐᲡᲘᲐ 2026“'
                pdf_utils.generate_act_pdf(data)
                for name in (data["shipper_name"], data["carrier_name"]):
                    copies = [op for op in drawing if op["text"] == name]
                    assert len(copies) == 2, "Legal name must be complete in both party and signature blocks"
                    assert {op["font"] for op in copies} == {"GeorgianFont", "GeorgianFont-Bold"}
                    for op in copies:
                        glyphs = pdfmetrics.getFont(op["font"]).face.charToGlyph
                        assert all(ord(char) in glyphs for char in name)
                assert_inside_page(drawing)


    def test_very_long_saved_company_names_are_complete_on_continued_pages(self):
        # Settings currently accepts longer names than registration's 200-char bound.
        for lang in ("ru", "ge"):
            with self.subTest(lang=lang), recording() as drawing:
                data = sample(lang)
                data["shipper_name"] = "ОООГруз" * 720
                data["carrier_name"] = "გადამზიდველი" * 500
                pdf_utils.generate_act_pdf(data)
                right = 40 + (A4[0] - 90) / 2 + 15
                for role, x in (("shipper", 50), ("carrier", right)):
                    actual = "".join(op["text"] for op in drawing
                                     if op["x"] == x and op["size"] == 10 and op["font"].endswith("-Bold"))
                    assert actual == data[role + "_name"]
                signatures_start = next(i for i, op in enumerate(drawing)
                                        if op["text"] == pdf_utils._I18N[lang]["signatures"])
                for role, x in (("shipper", 40), ("carrier", 40 + (A4[0] - 80) / 2 + 10)):
                    actual = "".join(op["text"] for op in drawing[signatures_start:]
                                     if op["x"] == x and op["size"] == 9
                                     and not op["font"].endswith("-Bold") and op["color"] == (0, 0, 0))
                    assert actual == data[role + "_name"]
                assert_inside_page(drawing)
                assert max(op["page"] for op in drawing) >= 4

    def test_logo_has_separate_domain_suffix(self):
        with recording() as drawing:
            check_domain_suffix_does_not_overlap_brand(drawing)


if __name__ == "__main__":
    unittest.main()
