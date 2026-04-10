"""
Генерация PDF документов: акт выполненных работ, договор перевозки.
Использует reportlab (легковесный, без внешних зависимостей).
"""
import io
from datetime import datetime
from typing import Optional


def _get_canvas():
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    # Шрифты с поддержкой кириллицы И грузинского
    # Noto Sans поддерживает все скрипты включая грузинский
    # Bundled DejaVu fonts (committed to repo) — always available, support Cyrillic
    font_name = "MainFont"
    registered = False
    _here = os.path.dirname(os.path.abspath(__file__))
    bundled_regular = os.path.join(_here, "fonts", "DejaVuSans.ttf")
    bundled_bold    = os.path.join(_here, "fonts", "DejaVuSans-Bold.ttf")

    if os.path.exists(bundled_regular):
        try:
            pdfmetrics.registerFont(TTFont("MainFont", bundled_regular))
            if os.path.exists(bundled_bold):
                pdfmetrics.registerFont(TTFont("MainFont-Bold", bundled_bold))
            registered = True
        except Exception:
            pass

    if not registered:
        # Fallback: search system fonts
        import glob
        for fp in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ] + glob.glob("/nix/store/*/share/fonts/truetype/noto/NotoSans-Regular.ttf"):
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont(font_name, fp))
                    registered = True
                    break
                except Exception:
                    pass

    if not registered:
        font_name = "Helvetica"

    return rl_canvas, A4, colors, font_name


def generate_act_pdf(deal_data: dict) -> bytes:
    """
    Генерирует PDF акт выполненных работ.
    deal_data: {
        act_number, deal_id, completed_at,
        shipper_name, shipper_inn, shipper_phone, shipper_email,
        carrier_name, carrier_inn, carrier_phone, carrier_email,
        from_city, to_city, cargo_desc, weight_kg,
        truck_type, agreed_price, currency,
        loading_at, delivered_at,
    }
    """
    rl_canvas, A4, colors, font_name = _get_canvas()

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def draw_text(x, y, text, size=10, bold=False):
        if bold:
            try:
                c.setFont(font_name + "-Bold", size)
            except Exception:
                try:
                    c.setFont(font_name, size)
                except Exception:
                    c.setFont("Helvetica-Bold", size)
        else:
            try:
                c.setFont(font_name, size)
            except Exception:
                c.setFont("Helvetica", size)
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
    draw_text(40, h - 55, "caucashub.ge  |  Биржа грузов и транспорта Кавказа", size=9)

    # ── Заголовок документа ────────────────────────────────
    c.setFillColor(colors.black)
    draw_text(40, h - 100, f"АКТ ВЫПОЛНЕННЫХ РАБОТ № {deal_data.get('act_number','—')}", size=14, bold=True)

    date_str = ""
    if deal_data.get("completed_at"):
        try:
            dt = datetime.fromisoformat(str(deal_data["completed_at"]))
            date_str = dt.strftime("%d.%m.%Y")
        except Exception:
            date_str = str(deal_data.get("completed_at", ""))
    draw_text(40, h - 120, f"Дата: {date_str}   |   ID сделки: #{deal_data.get('deal_id','—')}", size=10)

    draw_line(h - 130)

    # ── Стороны ────────────────────────────────────────────
    y = h - 155
    draw_text(40, y, "СТОРОНЫ СДЕЛКИ", size=11, bold=True)

    y -= 20
    # Грузовладелец
    c.setFillColor(colors.HexColor("#f8f9fa"))
    c.roundRect(40, y - 55, (w - 90) / 2 - 5, 65, 4, fill=1, stroke=0)
    c.setFillColor(colors.black)
    draw_text(50, y - 8,  "ГРУЗОВЛАДЕЛЕЦ", size=8, bold=True)
    draw_text(50, y - 22, deal_data.get("shipper_name", "—"), size=10, bold=True)
    draw_text(50, y - 35, f"ИНН: {deal_data.get('shipper_inn','—')}", size=9)
    draw_text(50, y - 47, f"Тел: {deal_data.get('shipper_phone','—')}", size=9)

    # Перевозчик
    cx = 40 + (w - 90) / 2 + 5
    c.setFillColor(colors.HexColor("#f8f9fa"))
    c.roundRect(cx, y - 55, (w - 90) / 2 - 5, 65, 4, fill=1, stroke=0)
    c.setFillColor(colors.black)
    draw_text(cx + 10, y - 8,  "ПЕРЕВОЗЧИК", size=8, bold=True)
    draw_text(cx + 10, y - 22, deal_data.get("carrier_name", "—"), size=10, bold=True)
    draw_text(cx + 10, y - 35, f"ИНН: {deal_data.get('carrier_inn','—')}", size=9)
    draw_text(cx + 10, y - 47, f"Тел: {deal_data.get('carrier_phone','—')}", size=9)

    y -= 75
    draw_line(y)

    # ── Детали перевозки ───────────────────────────────────
    y -= 20
    draw_text(40, y, "ДЕТАЛИ ПЕРЕВОЗКИ", size=11, bold=True)

    rows = [
        ("Маршрут",         f"{deal_data.get('from_city','—')} → {deal_data.get('to_city','—')}"),
        ("Описание груза",  deal_data.get("cargo_desc", "—")),
        ("Вес груза",       f"{deal_data.get('weight_kg','—')} кг"),
        ("Тип кузова",      deal_data.get("truck_type", "—")),
        ("Дата загрузки",   _fmt_date(deal_data.get("loading_at"))),
        ("Дата доставки",   _fmt_date(deal_data.get("delivered_at"))),
    ]

    y -= 15
    for label, value in rows:
        c.setFillColor(colors.HexColor("#666666"))
        draw_text(40, y, label + ":", size=9)
        c.setFillColor(colors.black)
        draw_text(180, y, value, size=9)
        y -= 16

    draw_line(y - 5)
    y -= 25

    # ── Стоимость ──────────────────────────────────────────
    price = deal_data.get("agreed_price", 0)
    currency = deal_data.get("currency", "GEL")
    cur_sym = "₾" if currency == "GEL" else "$"

    c.setFillColor(colors.HexColor("#1a1a2e"))
    c.roundRect(40, y - 35, w - 80, 45, 4, fill=1, stroke=0)
    c.setFillColor(colors.white)
    draw_text(55, y - 10, "СТОИМОСТЬ УСЛУГ:", size=10)
    draw_text(55, y - 27, f"{cur_sym}{price:,.2f} {currency}", size=16, bold=True)

    y -= 55
    draw_line(y)

    # ── Подписи ────────────────────────────────────────────
    y -= 25
    draw_text(40, y, "ПОДПИСИ СТОРОН", size=11, bold=True)

    y -= 20
    half = (w - 80) // 2
    for label, name in [("Грузовладелец", deal_data.get("shipper_name","_________________")),
                        ("Перевозчик",    deal_data.get("carrier_name","_________________"))]:
        x = 40 if label == "Грузовладелец" else 40 + half + 10
        draw_text(x, y,      label + ":", size=9, bold=True)
        draw_text(x, y - 15, name, size=9)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        c.line(x, y - 40, x + half - 20, y - 40)
        draw_text(x, y - 52, "Подпись / ხელმოწერა", size=7)

    # ── Подвал ─────────────────────────────────────────────
    c.setFillColor(colors.HexColor("#f0f2f5"))
    c.rect(0, 0, w, 35, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#888888"))
    draw_text(40, 20, f"Документ сгенерирован автоматически платформой CaucasHub.ge  |  {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC", size=7)

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
