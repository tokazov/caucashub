"""
Генерация PDF документов: акт выполненных работ, договор перевозки.
Использует reportlab (легковесный, без внешних зависимостей).
"""
import io
from datetime import datetime
from typing import Optional

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
    import os, glob

    font_name = "MainFont"
    registered = False

    # Noto Sans поддерживает Georgian + Cyrillic
    noto_candidates = (
        glob.glob("/nix/store/*/share/fonts/truetype/noto/NotoSans-Regular.ttf") +
        glob.glob("/nix/store/*/share/fonts/noto/NotoSans-Regular.ttf") +
        glob.glob("/run/current-system/sw/share/fonts/*/NotoSans-Regular.ttf") +
        [
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    )

    for fp in noto_candidates:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont(font_name, fp))
                # Bold fallback (тот же шрифт)
                try:
                    bold_fp = fp.replace("Regular", "Bold").replace("regular", "bold")
                    if os.path.exists(bold_fp):
                        pdfmetrics.registerFont(TTFont(font_name + "-Bold", bold_fp))
                    else:
                        pdfmetrics.registerFont(TTFont(font_name + "-Bold", fp))
                except Exception:
                    pdfmetrics.registerFont(TTFont(font_name + "-Bold", fp))
                registered = True
                break
            except Exception:
                pass

    if not registered:
        font_name = "Helvetica"

    return rl_canvas, A4, colors, font_name


def generate_act_pdf(deal_data: dict) -> bytes:
    lang = deal_data.get("lang", "ru")
    if lang not in _I18N:
        lang = "ru"
    t = _I18N[lang]

    rl_canvas, A4, colors, font_name = _get_canvas()

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def draw_text(x, y, text, size=10, bold=False):
        fn = font_name + ("-Bold" if bold and font_name != "Helvetica" else "")
        try:
            c.setFont(fn, size)
        except Exception:
            c.setFont(font_name, size)
        c.drawString(x, y, str(text))

    def draw_line(y):
        c.setStrokeColor(colors.HexColor("#e0e0e0"))
        c.setLineWidth(0.5)
        c.line(40, y, w - 40, y)

    # ── Шапка ──────────────────────────────────────────────
    c.setFillColor(colors.HexColor("#1a1a2e"))
    c.rect(0, h - 70, w, 70, fill=1, stroke=0)

    c.setFillColor(colors.white)
    draw_text(40, h - 30, "CaucasHub", size=20, bold=True)
    c.setFillColor(colors.HexColor("#f7b731"))
    draw_text(155, h - 30, ".ge", size=20)

    c.setFillColor(colors.HexColor("#aaaaaa"))
    draw_text(40, h - 55, t["subtitle"], size=9)

    # ── Заголовок документа ────────────────────────────────
    c.setFillColor(colors.black)
    draw_text(40, h - 100, f"{t['act_title']} {deal_data.get('act_number','—')}", size=14, bold=True)

    date_str = ""
    if deal_data.get("completed_at"):
        try:
            dt = datetime.fromisoformat(str(deal_data["completed_at"]))
            date_str = dt.strftime("%d.%m.%Y")
        except Exception:
            date_str = str(deal_data.get("completed_at", ""))
    draw_text(40, h - 120, f"{t['date_label']} {date_str}   |   {t['id_label']} #{deal_data.get('deal_id','—')}", size=10)

    draw_line(h - 130)

    # ── Стороны ────────────────────────────────────────────
    y = h - 155
    draw_text(40, y, t["parties"], size=11, bold=True)

    y -= 20
    c.setFillColor(colors.HexColor("#f8f9fa"))
    c.roundRect(40, y - 55, (w - 90) / 2 - 5, 65, 4, fill=1, stroke=0)
    c.setFillColor(colors.black)
    draw_text(50, y - 8,  t["shipper"], size=8, bold=True)
    draw_text(50, y - 22, deal_data.get("shipper_name", "—"), size=10, bold=True)
    draw_text(50, y - 35, f"{t['inn']} {deal_data.get('shipper_inn','—')}", size=9)
    draw_text(50, y - 47, f"{t['phone']} {deal_data.get('shipper_phone','—')}", size=9)

    cx = 40 + (w - 90) / 2 + 5
    c.setFillColor(colors.HexColor("#f8f9fa"))
    c.roundRect(cx, y - 55, (w - 90) / 2 - 5, 65, 4, fill=1, stroke=0)
    c.setFillColor(colors.black)
    draw_text(cx + 10, y - 8,  t["carrier"], size=8, bold=True)
    draw_text(cx + 10, y - 22, deal_data.get("carrier_name", "—"), size=10, bold=True)
    draw_text(cx + 10, y - 35, f"{t['inn']} {deal_data.get('carrier_inn','—')}", size=9)
    draw_text(cx + 10, y - 47, f"{t['phone']} {deal_data.get('carrier_phone','—')}", size=9)

    y -= 75
    draw_line(y)

    # ── Детали перевозки ───────────────────────────────────
    y -= 20
    draw_text(40, y, t["details"], size=11, bold=True)

    rows = [
        (t["route"],     f"{deal_data.get('from_city','—')} → {deal_data.get('to_city','—')}"),
        (t["cargo"],     deal_data.get("cargo_desc", "—")),
        (t["weight"],    f"{deal_data.get('weight_kg','—')} {t['kg']}"),
        (t["truck"],     deal_data.get("truck_type", "—")),
        (t["load_date"], _fmt_date(deal_data.get("loading_at"))),
        (t["del_date"],  _fmt_date(deal_data.get("delivered_at"))),
    ]

    y -= 15
    for label, value in rows:
        c.setFillColor(colors.HexColor("#666666"))
        draw_text(40, y, label + ":", size=9)
        c.setFillColor(colors.black)
        draw_text(200, y, value, size=9)
        y -= 16

    draw_line(y - 5)
    y -= 25

    # ── Стоимость ──────────────────────────────────────────
    price = deal_data.get("agreed_price", 0)
    currency = deal_data.get("currency", "GEL")
    cur_sym = "GEL " if currency == "GEL" else "USD "

    c.setFillColor(colors.HexColor("#1a1a2e"))
    c.roundRect(40, y - 35, w - 80, 45, 4, fill=1, stroke=0)
    c.setFillColor(colors.white)
    draw_text(55, y - 10, t["cost"], size=10)
    draw_text(55, y - 27, f"{cur_sym}{price:,.2f} {currency}", size=16, bold=True)

    y -= 55
    draw_line(y)

    # ── Подписи ────────────────────────────────────────────
    y -= 25
    draw_text(40, y, t["signatures"], size=11, bold=True)

    y -= 20
    half = (w - 80) // 2
    for label, name in [(t["sig_shipper"], deal_data.get("shipper_name","_________________")),
                        (t["sig_carrier"], deal_data.get("carrier_name","_________________"))]:
        x = 40 if label == t["sig_shipper"] else 40 + half + 10
        draw_text(x, y,      label + ":", size=9, bold=True)
        draw_text(x, y - 15, name, size=9)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        c.line(x, y - 40, x + half - 20, y - 40)
        draw_text(x, y - 52, t["sig_line"], size=7)

    # ── Подвал ─────────────────────────────────────────────
    c.setFillColor(colors.HexColor("#f0f2f5"))
    c.rect(0, 0, w, 35, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#888888"))
    draw_text(40, 20, f"{t['footer']}  |  {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC", size=7)

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
