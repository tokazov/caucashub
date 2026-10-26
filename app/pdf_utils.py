"""
Генерация PDF документов: акт выполненных работ, договор перевозки.
Использует reportlab (легковесный, без внешних зависимостей).
"""
import io
from datetime import datetime

# ── i18n словарь ──────────────────────────────────────────────────────────────
_I18N = {
    "ru": {
        "subtitle":    "caucashub.ge  |  Биржа грузов и транспорта Кавказа",
        "act_title":   "АКТ ВЫПОЛНЕННЫХ РАБОТ №",
        "date_label":  "Дата:",
        "id_label":    "ID сделки:",
        "parties":     "СТОРОНЫ СДЕЛКИ",
        "shipper":     "ГРУЗОВЛАДЕЛЕЦ",
        "carrier":     "ПЕРЕВОЗЧИК",
        "inn":         "ИНН:",
        "phone":       "Тел:",
        "details":     "ДЕТАЛИ ПЕРЕВОЗКИ",
        "route":       "Маршрут",
        "cargo":       "Описание груза",
        "weight":      "Вес груза",
        "kg":          "кг",
        "truck":       "Тип кузова",
        "load_date":   "Дата загрузки",
        "del_date":    "Дата доставки",
        "cost":        "СТОИМОСТЬ УСЛУГ:",
        "signatures":  "ПОДПИСИ СТОРОН",
        "sig_shipper": "Грузовладелец",
        "sig_carrier": "Перевозчик",
        "sig_line":    "Подпись / ხელმოწერა",
        "footer":      "Документ сгенерирован автоматически платформой CaucasHub.ge",
    },
    "ge": {
        "subtitle":    "caucashub.ge  |  სატვირთო ბირჟა კავკასიაში",
        "act_title":   "შესრულებული სამუშაოს აქტი №",
        "date_label":  "თარიღი:",
        "id_label":    "გარიგების ID:",
        "parties":     "გარიგების მხარეები",
        "shipper":     "დამტვირთველი",
        "carrier":     "გადამზიდველი",
        "inn":         "საიდ. კოდი:",
        "phone":       "ტელ:",
        "details":     "გადაზიდვის დეტალები",
        "route":       "მარშრუტი",
        "cargo":       "ტვირთის აღწერა",
        "weight":      "ტვირთის წონა",
        "kg":          "კგ",
        "truck":       "ძარის ტიპი",
        "load_date":   "დატვირთვის თარიღი",
        "del_date":    "მიტანის თარიღი",
        "cost":        "მომსახურების ღირებულება:",
        "signatures":  "მხარეთა ხელმოწერები",
        "sig_shipper": "დამტვირთველი",
        "sig_carrier": "გადამზიდველი",
        "sig_line":    "Подпись / ხელმოწერა",
        "footer":      "დოკუმენტი ავტომატურად გენერირებულია CaucasHub.ge პლატფორმის მიერ",
    },
}


def _get_canvas():
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os
    import glob

    font_name = "MainFont"
    registered = False

    # Приоритет 1: шрифт в репо (app/fonts/) — гарантированно есть на Railway
    _here = os.path.dirname(os.path.abspath(__file__))
    bundled_regular = os.path.join(_here, "fonts", "DejaVuSans.ttf")
    bundled_bold    = os.path.join(_here, "fonts", "DejaVuSans-Bold.ttf")

    candidates = []
    if os.path.exists(bundled_regular):
        candidates.append((bundled_regular, bundled_bold if os.path.exists(bundled_bold) else bundled_regular))

    # Приоритет 2: системные шрифты (Noto → DejaVu → liberation)
    system_fonts = (
        glob.glob("/nix/store/*/share/fonts/truetype/noto/NotoSans-Regular.ttf") +
        glob.glob("/nix/store/*/share/fonts/noto/NotoSans-Regular.ttf") +
        [
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
    )
    for fp in system_fonts:
        if os.path.exists(fp):
            bold_fp = fp.replace("Regular", "Bold").replace("regular", "bold")
            candidates.append((fp, bold_fp if os.path.exists(bold_fp) else fp))

    for fp, bold_fp in candidates:
        try:
            pdfmetrics.registerFont(TTFont(font_name, fp))
            pdfmetrics.registerFont(TTFont(font_name + "-Bold", bold_fp))
            registered = True
            break
        except Exception:
            pass

    if not registered:
        font_name = "Helvetica"

    return rl_canvas, A4, colors, font_name



def _wrapped_lines(value, font_name: str, size: float, width: float) -> list[str]:
    """Wrap Unicode text without clipping or discarding long, unbroken values."""
    from reportlab.pdfbase import pdfmetrics

    text = "—" if value is None or value == "" else str(value)
    lines = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}" if current else word
            if pdfmetrics.stringWidth(candidate, font_name, size) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            # Addresses and identifiers can contain tokens with no spaces.
            for char in word:
                if current and pdfmetrics.stringWidth(current + char, font_name, size) > width:
                    lines.append(current)
                    current = ""
                current += char
        lines.append(current)
    return lines or ["—"]


def generate_act_pdf(deal_data: dict) -> bytes:
    from reportlab.pdfbase import pdfmetrics

    lang = deal_data.get("lang", "ru")
    if lang not in _I18N:
        lang = "ru"
    t = _I18N[lang]
    rl_canvas, A4, colors, font_name = _get_canvas()
    bold_font = font_name + "-Bold" if font_name != "Helvetica" else font_name

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    bottom_margin = 65
    y = h - 155

    def draw_text(x, baseline, text, size=10, bold=False):
        c.setFont(bold_font if bold else font_name, size)
        c.drawString(x, baseline, str(text))

    def draw_line(baseline):
        c.setStrokeColor(colors.HexColor("#e0e0e0"))
        c.setLineWidth(0.5)
        c.line(40, baseline, w - 40, baseline)

    def footer():
        c.setFillColor(colors.HexColor("#f0f2f5"))
        c.rect(0, 0, w, 35, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#888888"))
        text = f"{t['footer']}  |  {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC"
        for index, line in enumerate(_wrapped_lines(text, font_name, 7, w - 80)):
            draw_text(40, 23 - index * 9, line, size=7)

    def header():
        c.setFillColor(colors.HexColor("#1a1a2e"))
        c.rect(0, h - 70, w, 70, fill=1, stroke=0)
        c.setFillColor(colors.white)
        draw_text(40, h - 30, "CaucasHub", size=20, bold=True)
        c.setFillColor(colors.HexColor("#f7b731"))
        brand_end = 40 + pdfmetrics.stringWidth("CaucasHub", bold_font, 20)
        draw_text(brand_end + 2, h - 30, ".ge", size=20)
        c.setFillColor(colors.HexColor("#aaaaaa"))
        draw_text(40, h - 55, t["subtitle"], size=9)
        c.setFillColor(colors.black)
        draw_text(40, h - 100, f"{t['act_title']} {deal_data.get('act_number','—')}", size=14, bold=True)
        date_str = _fmt_date(deal_data.get("completed_at"))
        draw_text(40, h - 120, f"{t['date_label']} {date_str}   |   {t['id_label']} #{deal_data.get('deal_id','—')}", size=10)
        draw_line(h - 130)

    def new_page():
        nonlocal y
        footer()
        c.showPage()
        header()
        y = h - 155

    def ensure_space(height):
        if y - height < bottom_margin:
            new_page()

    header()

    # Keep both original party columns. Even a long saved company name or
    # legacy contact value is wrapped and continued, rather than clipped.
    column_width = (w - 90) / 2 - 25
    party_content = []
    for role in ("shipper", "carrier"):
        content = [(line, 10, True, 13) for line in _wrapped_lines(deal_data.get(role + "_name"), bold_font, 10, column_width)]
        for key, label in (("inn", t["inn"]), ("phone", t["phone"])):
            value = f"{label} {deal_data.get(role + '_' + key, '—')}"
            content.extend((line, 9, False, 12) for line in _wrapped_lines(value, font_name, 9, column_width))
        party_content.append(content)
    cursors = [0, 0]
    while any(cursors[i] < len(party_content[i]) for i in (0, 1)):
        available_height = y - bottom_margin - 68
        if available_height < 37:
            new_page()
            continue
        chunks = []
        for index, content in enumerate(party_content):
            chunk, used = [], 0
            while cursors[index] < len(content):
                item = content[cursors[index]]
                if used + item[3] > available_height:
                    break
                chunk.append(item)
                used += item[3]
                cursors[index] += 1
            chunks.append(chunk)
        party_height = max(65, 28 + max(sum(item[3] for item in chunk) for chunk in chunks))
        c.setFillColor(colors.black)
        draw_text(40, y, t["parties"], size=11, bold=True)
        y -= 20
        top = y + 10
        for index, role in enumerate(("shipper", "carrier")):
            x = 40 if index == 0 else 40 + (w - 90) / 2 + 5
            c.setFillColor(colors.HexColor("#f8f9fa"))
            c.roundRect(x, top - party_height, (w - 90) / 2 - 5, party_height, 4, fill=1, stroke=0)
            c.setFillColor(colors.black)
            draw_text(x + 10, top - 14, t[role], size=8, bold=True)
            baseline = top - 29
            for text, size, bold, line_height in chunks[index]:
                draw_text(x + 10, baseline, text, size=size, bold=bold)
                baseline -= line_height
        y = top - party_height - 20
        if any(cursors[i] < len(party_content[i]) for i in (0, 1)):
            new_page()

    draw_line(y)
    y -= 20
    c.setFillColor(colors.black)
    draw_text(40, y, t["details"], size=11, bold=True)
    y -= 18
    rows = [
        (t["route"], f"{deal_data.get('from_city','—')} → {deal_data.get('to_city','—')}"),
        (t["cargo"], deal_data.get("cargo_desc", "—")),
        (t["weight"], f"{deal_data.get('weight_kg','—')} {t['kg']}"),
        (t["truck"], deal_data.get("truck_type", "—")),
        (t["load_date"], _fmt_date(deal_data.get("loading_at"))),
        (t["del_date"], _fmt_date(deal_data.get("delivered_at"))),
    ]

    for label, value in rows:
        labels = _wrapped_lines(label + ":", font_name, 9, 150)
        values = _wrapped_lines(value, font_name, 9, w - 240)
        count = max(len(labels), len(values))
        index = 0
        while index < count:
            if y < bottom_margin + 20:
                new_page()
                c.setFillColor(colors.black)
                draw_text(40, y, t["details"], size=11, bold=True)
                y -= 18
            available = max(1, int((y - bottom_margin) // 12) + 1)
            chunk = min(count - index, available)
            for offset in range(chunk):
                baseline = y - offset * 12
                line_index = index + offset
                c.setFillColor(colors.HexColor("#666666"))
                if line_index < len(labels):
                    draw_text(40, baseline, labels[line_index], size=9)
                c.setFillColor(colors.black)
                if line_index < len(values):
                    draw_text(200, baseline, values[line_index], size=9)
            y -= max(16, chunk * 12 + 4)
            index += chunk
            if index < count:
                new_page()
                c.setFillColor(colors.black)
                draw_text(40, y, t["details"], size=11, bold=True)
                y -= 18

    # The original price block, without a duplicated currency prefix.
    ensure_space(90)
    draw_line(y - 5)
    y -= 25
    c.setFillColor(colors.HexColor("#1a1a2e"))
    c.roundRect(40, y - 35, w - 80, 45, 4, fill=1, stroke=0)
    c.setFillColor(colors.white)
    draw_text(55, y - 10, t["cost"], size=10)
    draw_text(55, y - 27, f"{deal_data.get('agreed_price', 0):,.2f} {deal_data.get('currency', 'GEL')}", size=16, bold=True)
    y -= 55
    draw_line(y)

    half = (w - 80) / 2
    signature_names = [
        _wrapped_lines(deal_data.get("shipper_name"), font_name, 9, half - 20),
        _wrapped_lines(deal_data.get("carrier_name"), font_name, 9, half - 20),
    ]
    name_index = 0
    name_count = max(map(len, signature_names))
    while name_index < name_count:
        available_lines = int((y - bottom_margin - 100) // 12)
        if available_lines < 1:
            new_page()
            continue
        chunk_count = min(name_count - name_index, available_lines)
        y -= 25
        # The price block leaves white fill; reset it before signatures.
        c.setFillColor(colors.black)
        draw_text(40, y, t["signatures"], size=11, bold=True)
        y -= 20
        for index, role in enumerate(("sig_shipper", "sig_carrier")):
            x = 40 if index == 0 else 40 + half + 10
            draw_text(x, y, t[role] + ":", size=9, bold=True)
            chunk = signature_names[index][name_index:name_index + chunk_count]
            for line_index, line in enumerate(chunk):
                draw_text(x, y - 15 - line_index * 12, line, size=9)
            if name_index + chunk_count == name_count:
                line_y = y - 30 - chunk_count * 12
                c.setStrokeColor(colors.black)
                c.setLineWidth(0.5)
                c.line(x, line_y, x + half - 20, line_y)
                draw_text(x, line_y - 12, t["sig_line"], size=7)
        name_index += chunk_count
        if name_index < name_count:
            new_page()

    footer()
    c.save()
    return buf.getvalue()


def _fmt_date(val) -> str:
    if not val:
        return "—"
    try:
        dt = datetime.fromisoformat(str(val))
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return str(val)
