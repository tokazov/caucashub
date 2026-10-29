"""Canonical city identities and conservative country-based route scope.

Exact aliases bridge historical RU/EN/KA labels. No prefix guesses are used to
assign a country or backfill a stored record. Read filters never modify data.
"""
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from types import SimpleNamespace
from sqlalchemy import select, and_, or_, false, case, literal, func
from app.models.city import City
from app.services.cities_seed import CITIES_SEED
from app.services.geo_mapping import GEO_MAPPING_RU_EN

EXTRA_NAMES = {
    "Цероване": ("Tserovani", "წეროვანი"),
    "Ереван": ("Yerevan", "ერევანი"), "Гюмри": ("Gyumri", "გიუმრი"),
    "Ванадзор": ("Vanadzor", "ვანაძორი"), "Баку": ("Baku", "ბაქო"),
    "Гянджа": ("Ganja", "განჯა"), "Стамбул": ("Istanbul", "სტამბული"),
    "Анкара": ("Ankara", "ანკარა"), "Измир": ("Izmir", "იზმირი"),
    "Трабзон": ("Trabzon", "ტრაბზონი"), "Карс": ("Kars", "ყარსი"),
    "Эрзурум": ("Erzurum", "ერზრუმი"), "Самсун": ("Samsun", "სამსუნი"),
    "Москва": ("Moscow", "მოსკოვი"), "Ростов-на-Дону": ("Rostov-on-Don", "დონის როსტოვი"),
    "Краснодар": ("Krasnodar", "კრასნოდარი"), "Сочи": ("Sochi", "სოჭი"),
    "Владикавказ": ("Vladikavkaz", "ვლადიკავკაზი"),
    "Минеральные Воды": ("Mineralnye Vody", "მინერალური წყლები"),
    "Ставрополь": ("Stavropol", "სტავროპოლი"), "Алматы": ("Almaty", "ალმათი"),
    "Астана": ("Astana", "ასტანა"), "Тегеран": ("Tehran", "თეირანი"),
    "Тебриз": ("Tabriz", "თავრიზი"), "Одесса": ("Odesa", "ოდესა"),
    "Минск": ("Minsk", "მინსკი"), "Варшава": ("Warsaw", "ვარშავა"),
    "Берлин": ("Berlin", "ბერლინი"),
}
# Explicit country-tagged city/town catalog mirrored from frontend CITIES.
# Countries are reviewed static data, never inferred from a free-text query.
# English spellings use existing geo_mapping/conventional names or Georgian
# transliteration. Existing seed identities keep their stable canonical keys.
UI_CITY_CATALOG = [
    ('Марнеули', 'Marneuli', 'მარნეული', 'GE', 41.4667, 44.8),
    ('Болниси', 'Bolnisi', 'ბოლნისი', 'GE', 41.45, 44.5167),
    ('Гардабани', 'Gardabani', 'გარდაბანი', 'GE', 41.35, 45.0833),
    ('Дманиси', 'Dmanisi', 'დმანისი', 'GE', 41.3333, 44.2),
    ('Тетри Цкаро', 'Tetri Tskaro', 'თეთრი წყარო', 'GE', 41.55, 44.4667),
    ('Цалка', 'Tsalka', 'წალკა', 'GE', 41.5833, 44.1),
    ('Манглиси', 'Manglisi', 'მანგლისი', 'GE', 41.6833, 44.4167),
    ('Казрети', 'Kazreti', 'ყაზრეთი', 'GE', 41.4, 44.4167),
    ('Душети', 'Dusheti', 'დუშეთი', 'GE', 42.0833, 44.7),
    ('Пасанаури', 'Pasanauri', 'პასანაური', 'GE', 42.35, 44.6833),
    ('Жинвали', 'Jinvali', 'ჟინვალი', 'GE', 42.15, 44.8333),
    ('Степанцминда', 'Stepantsminda', 'სტეფანწმინდა', 'GE', 42.6583, 44.6397),
    ('Ананури', 'Ananuri', 'ანანური', 'GE', 42.0667, 44.7),
    ('Млета', 'Mleta', 'მლეთა', 'GE', 42.45, 44.5333),
    ('Ахалгори', 'Akhalgori', 'ახალგორი', 'GE', 42.2833, 44.5667),
    ('Гудаури', 'Gudauri', 'გუდაური', 'GE', 42.4833, 44.4833),
    ('Ахмета', 'Akhmeta', 'ახმეტა', 'GE', 42.03, 45.21),
    ('Сигнахи', 'Sighnaghi', 'სიღნაღი', 'GE', 41.6167, 45.9167),
    ('Гурджаани', 'Gurjaani', 'გურჯაანი', 'GE', 41.7453, 45.7931),
    ('Кварели', 'Kvareli', 'ყვარელი', 'GE', 41.9667, 45.8167),
    ('Лагодехи', 'Lagodekhi', 'ლაგოდეხი', 'GE', 41.8333, 46.2833),
    ('Дедоплисцкаро', 'Dedoplistskaro', 'დედოფლისწყარო', 'GE', 41.4667, 46.1),
    ('Сагареджо', 'Sagarejo', 'საგარეჯო', 'GE', 41.7333, 45.3333),
    ('Цинандали', 'Tsinandali', 'წინანდალი', 'GE', 41.85, 45.5167),
    ('Напареули', 'Napareuli', 'ნაფარეული', 'GE', 41.8833, 45.65),
    ('Тианети', 'Tianeti', 'თიანეთი', 'GE', 42.1167, 45.0167),
    ('Бодбе', 'Bodbe', 'ბოდბე', 'GE', 41.6667, 45.8833),
    ('Шилда', 'Shilda', 'შილდა', 'GE', 41.95, 45.95),
    ('Велисцихе', 'Velistsikhe', 'ველისციხე', 'GE', 41.8, 45.3833),
    ('Матани', 'Matani', 'მატანი', 'GE', 41.9, 45.6333),
    ('Карели', 'Kareli', 'ქარელი', 'GE', 41.9667, 43.8167),
    ('Цхинвали', 'Tskhinvali', 'ცხინვალი', 'GE', 42.2167, 43.9667),
    ('Сурами', 'Surami', 'სურამი', 'GE', 42.0333, 43.55),
    ('Агара', 'Agara', 'აგარა', 'GE', 41.9167, 43.7333),
    ('Хвелосани', 'Khvelosani', 'ხველოსანი', 'GE', 41.9833, 43.9),
    ('Аспиндза', 'Aspindza', 'ასპინძა', 'GE', 41.5333, 43.25),
    ('Адигени', 'Adigeni', 'ადიგენი', 'GE', 41.65, 42.7833),
    ('Ниноцминда', 'Ninotsminda', 'ნინოწმინდა', 'GE', 41.2167, 43.5833),
    ('Абастумани', 'Abastumani', 'აბასთუმანი', 'GE', 41.7333, 42.8333),
    ('Бакуриани', 'Bakuriani', 'ბაკურიანი', 'GE', 41.75, 43.5167),
    ('Вале', 'Vale', 'ვალე', 'GE', 41.55, 43.15),
    ('Хертвиси', 'Khertvisi', 'ხერთვისი', 'GE', 41.5667, 43.1167),
    ('Вардзиа', 'Vardzia', 'ვარძია', 'GE', 41.3833, 43.2333),
    ('Поцхо-Эцери', 'Potskho Etseri', 'პოცხო-ეწერი', 'GE', 41.6833, 42.9167),
    ('Самтредиа', 'Samtredia', 'სამტრედია', 'GE', 42.15, 42.35),
    ('Зестафони', 'Zestafoni', 'ზესტაფონი', 'GE', 42.1, 43.05),
    ('Ткибули', 'Tkibuli', 'ტყიბული', 'GE', 42.35, 42.9833),
    ('Тержола', 'Terjola', 'თერჯოლა', 'GE', 42.1167, 43.0),
    ('Сачхере', 'Sachkhere', 'საჩხერე', 'GE', 42.35, 43.4),
    ('Чиатура', 'Chiatura', 'ჭიათურა', 'GE', 42.2833, 43.2833),
    ('Хони', 'Khoni', 'ხონი', 'GE', 42.3167, 42.6),
    ('Багдати', 'Baghdati', 'ბაღდათი', 'GE', 42.0833, 42.8333),
    ('Вани', 'Vani', 'ვანი', 'GE', 42.1, 42.5167),
    ('Харагаули', 'Kharagauli', 'ხარაგაული', 'GE', 42.0167, 43.2),
    ('Шорапани', 'Shorapani', 'შორაპანი', 'GE', 42.15, 43.1),
    ('Зеда Горди', 'Zeda Gordi', 'ზედა გორდი', 'GE', 42.2167, 42.55),
    ('Симонети', 'Simoneti', 'სიმონეთი', 'GE', 42.0667, 43.15),
    ('Ланчхути', 'Lanchkhuti', 'ლანჩხუთი', 'GE', 41.9833, 42.25),
    ('Чохатаури', 'Chokhatauri', 'ჩოხატაური', 'GE', 41.9667, 42.4333),
    ('Шекветили', 'Shekvetili', 'შეკვეთილი', 'GE', 41.7667, 41.9667),
    ('Уреки', 'Ureki', 'ურეკი', 'GE', 41.95, 41.95),
    ('Кобулети', 'Kobuleti', 'ქობულეთი', 'GE', 41.8167, 41.7833),
    ('Хуло', 'Khulo', 'ხულო', 'GE', 41.5833, 42.4833),
    ('Шуахеви', 'Shuakhevi', 'შუახევი', 'GE', 41.5, 42.3833),
    ('Кеда', 'Keda', 'კედა', 'GE', 41.45, 42.2667),
    ('Сарпи', 'Sarpi', 'სარფი', 'GE', 41.4, 41.55),
    ('Гонио', 'Gonio', 'გონიო', 'GE', 41.5, 41.6167),
    ('Чакви', 'Chakvi', 'ჩაქვი', 'GE', 41.6833, 41.6833),
    ('Цихисдзири', 'Tsikhisdziri', 'ციხისძირი', 'GE', 41.7167, 41.7),
    ('Квариати', 'Kvariati', 'კვარიათი', 'GE', 41.55, 41.5833),
    ('Махинджаури', 'Makhinjauri', 'მახინჯაური', 'GE', 41.65, 41.65),
    ('Зеленый Мыс', 'Mtsvane Kontskhi', 'მწვანე კონცხი', 'GE', 41.6667, 41.6333),
    ('Диди Аджара', 'Didi Achara', 'დიდი აჭარა', 'GE', 41.5667, 42.5833),
    ('Хоби', 'Khobi', 'ხობი', 'GE', 42.3167, 41.9),
    ('Абаша', 'Abasha', 'აბაშა', 'GE', 42.2, 42.2),
    ('Мартвили', 'Martvili', 'მარტვილი', 'GE', 42.4333, 42.35),
    ('Чхороцку', 'Chkhorotsku', 'ჩხოროწყუ', 'GE', 42.4667, 42.1667),
    ('Цаленджиха', 'Tsalenjikha', 'წალენჯიხა', 'GE', 42.6, 42.0667),
    ('Анаклиа', 'Anaklia', 'ანაკლია', 'GE', 42.3833, 41.5667),
    ('Джвари', 'Jvari', 'ჯვარი', 'GE', 42.6833, 42.15),
    ('Ингири', 'Ingiri', 'ინგირი', 'GE', 42.45, 41.8333),
    ('Амбролаури', 'Ambrolauri', 'ამბროლაური', 'GE', 42.5167, 43.15),
    ('Они', 'Oni', 'ონი', 'GE', 42.5833, 43.4333),
    ('Цагери', 'Tsageri', 'წაგერი', 'GE', 42.5667, 42.7167),
    ('Лентехи', 'Lentekhi', 'ლენტეხი', 'GE', 42.7833, 42.7167),
    ('Шови', 'Shovi', 'შოვი', 'GE', 42.65, 43.5),
    ('Местиа', 'Mestia', 'მესტია', 'GE', 43.05, 42.7167),
    ('Ушгули', 'Ushguli', 'უშგული', 'GE', 43.1167, 42.8667),
    ('Хаиши', 'Khaishi', 'ხაიში', 'GE', 42.8167, 42.4833),
    ('Мазери', 'Mazeri', 'მაზერი', 'GE', 43.1167, 42.6667),
    ('Бурса', 'Bursa', 'ბურსა', 'TR', 40.1885, 29.061),
    ('Адана', 'Adana', 'ადანა', 'TR', 37.0, 35.3213),
    ('Газиантеп', 'Gaziantep', 'გაზიანთეფი', 'TR', 37.0662, 37.3833),
    ('Мерсин', 'Mersin', 'მერსინი', 'TR', 36.8121, 34.6415),
    ('Конья', 'Konya', 'ქონია', 'TR', 37.8667, 32.4833),
    ('Ван', 'Van', 'ვანი', 'TR', 38.4891, 43.4089),
    ('Диярбакыр', 'Diyarbakir', 'დიარბაქირი', 'TR', 37.9144, 40.2306),
    ('Ризе', 'Rize', 'რიზე', 'TR', 41.0201, 40.5234),
    ('Артвин', 'Artvin', 'არტვინი', 'TR', 41.1828, 41.8183),
    ('Хопа', 'Hopa', 'ხოფა', 'TR', 41.4086, 41.4139),
    ('Сарыкамыш', 'Sarikamis', 'სარიქამიში', 'TR', 40.3339, 42.5869),
    ('Абовян', 'Abovyan', 'აბოვიანი', 'AM', 40.2686, 44.6328),
    ('Капан', 'Kapan', 'ყაფანი', 'AM', 39.2072, 46.405),
    ('Мегри', 'Meghri', 'მეგრი', 'AM', 38.9047, 46.2339),
    ('Сумгайыт', 'Sumgait', 'სუმგაითი', 'AZ', 40.5897, 49.6686),
    ('Нахчыван', 'Nakhchivan', 'ნახჭევანი', 'AZ', 39.2092, 45.4117),
    ('Лянкяран', 'Lankaran', 'ლენქორანი', 'AZ', 38.7529, 48.848),
    ('Гах', 'Qakh', 'ღახი', 'AZ', 41.4258, 46.9322),
    ('Загатала', 'Zaqatala', 'ზაქათალა', 'AZ', 41.6331, 46.6408),
    ('Балакен', 'Balakan', 'ბალაქანი', 'AZ', 41.7239, 46.4047),
    ('Шеки', 'Shaki', 'შაქი', 'AZ', 41.1994, 47.1706),
    ('Нальчик', 'Nalchik', 'ნალჩიკი', 'RU', 43.4986, 43.6156),
    ('Махачкала', 'Makhachkala', 'მახაჩყალა', 'RU', 42.9849, 47.5047),
    ('Грозный', 'Grozny', 'გროზნო', 'RU', 43.3178, 45.6984),
    ('Новороссийск', 'Novorossiysk', 'ნოვოროსიისკი', 'RU', 44.7239, 37.7685),
    ('Черкесск', 'Cherkessk', 'ჩერქესკი', 'RU', 44.2286, 42.0606),
    ('Астрахань', 'Astrakhan', 'ასტრახანი', 'RU', 46.3497, 48.0408),
    ('Волгоград', 'Volgograd', 'ვოლგოგრადი', 'RU', 48.708, 44.5133),
    ('Саратов', 'Saratov', 'სარატოვი', 'RU', 51.5924, 46.0342),
    ('Казань', 'Kazan', 'ყაზანი', 'RU', 55.8304, 49.0661),
    ('Екатеринбург', 'Yekaterinburg', 'ეკატერინბურგი', 'RU', 56.8389, 60.6057),
    ('Новосибирск', 'Novosibirsk', 'ნოვოსიბირსკი', 'RU', 54.9924, 82.9086),
    ('Воронеж', 'Voronezh', 'ვორონეჟი', 'RU', 51.672, 39.1843),
    ('Самара', 'Samara', 'სამარა', 'RU', 53.2038, 50.1606),
    ('Пермь', 'Perm', 'პერმი', 'RU', 58.0105, 56.2502),
    ('Уфа', 'Ufa', 'უფა', 'RU', 54.7388, 55.9721),
    ('Челябинск', 'Chelyabinsk', 'ჩელიაბინსკი', 'RU', 55.1644, 61.4368),
    ('Харьков', 'Kharkiv', 'ხარკოვი', 'UA', 49.9935, 36.2304),
    ('Днепр', 'Dnipro', 'დნეპრი', 'UA', 48.4647, 35.0462),
    ('Запорожье', 'Zaporizhzhia', 'ზაპოროჟიე', 'UA', 47.8388, 35.1396),
    ('Львов', 'Lviv', 'ლვოვი', 'UA', 49.8397, 24.0297),
    ('Актау', 'Aktau', 'აქტაუ', 'KZ', 43.6528, 51.1978),
    ('Актобе', 'Aktobe', 'აქტობე', 'KZ', 50.2839, 57.1669),
    ('Атырау', 'Atyrau', 'ათირაუ', 'KZ', 47.0945, 51.9236),
    ('Урумчи', 'Urumqi', 'ურუმჩი', 'CN', 43.8256, 87.6168),
    ('Кашгар', 'Kashgar', 'ქაშგარი', 'CN', 39.4704, 75.9895),
    ('Ардебиль', 'Ardabil', 'არდებილი', 'IR', 38.2498, 48.2933),
    ('Астара', 'Astara', 'ასტარა', 'IR', 38.4272, 48.8722),
    ('Рим', 'Rome', 'რომი', 'IT', 41.9028, 12.4964),
    ('Милан', 'Milan', 'მილანი', 'IT', 45.4654, 9.1859),
    ('Амстердам', 'Amsterdam', 'ამსტერდამი', 'NL', 52.3676, 4.9041),
    ('Прага', 'Prague', 'პრაღა', 'CZ', 50.0755, 14.4378),
    ('Братислава', 'Bratislava', 'ბრატისლავა', 'SK', 48.1486, 17.1077),
    ('Белград', 'Belgrade', 'ბელგრადი', 'RS', 44.8125, 20.4612),
    ('Санкт-Петербург', 'Saint Petersburg', 'სანქტ-პეტერბურგი', 'RU', 59.9343, 30.3351),
    ('Шымкент', 'Shymkent', 'შიმქენთი', 'KZ', 42.3, 69.6),
    ('Ташкент', 'Tashkent', 'ტაშქენტი', 'UZ', 41.2995, 69.2401),
    ('Самарканд', 'Samarkand', 'სამარყანდი', 'UZ', 39.6542, 66.9597),
    ('Киев', 'Kyiv', 'კიევი', 'UA', 50.4501, 30.5234),
    ('Дубай', 'Dubai', 'დუბაი', 'AE', 25.2048, 55.2708),
    ('Абу-Даби', 'Abu Dhabi', 'აბუ-დაბი', 'AE', 24.4539, 54.3773),
    ('Бухарест', 'Bucharest', 'ბუქარესტი', 'RO', 44.4268, 26.1025),
    ('София', 'Sofia', 'სოფია', 'BG', 42.6977, 23.3219),
    ('Афины', 'Athens', 'ათენი', 'GR', 37.9838, 23.7275),
]
# These old UI entries are regions or have inconsistent/unverified labels.
# Keep them out of publication until the source dictionary is corrected.
UI_CITY_REVIEW_REQUIRED = {
    "Лесели": "Russian label conflicts with Georgian Lechkhumi region",
    "Цхваришвилеби": "Russian and Georgian labels identify different names",
    "Лигонаки": "Location identity requires owner/source review",
    "Набегови": "Russian and Georgian spelling requires source review",
}
EXTRA_ALIASES = {
    "Тбилиси": ["Tiflis", "Тифлис"],
    "Батуми": ["Батум", "Batum", "ბათუმ"],
    "Кутаиси": ["Kutais", "Кутаис"],
    "Мцхета": ["Mts'khet'a", "Mtsheta"],
    "Цероване": ["Tserovani", "Tserovaani"],
    "Одесса": ["Odessa"], "Москва": ["Moskva"], "Ереван": ["Erevan"],
    "Стамбул": ["İstanbul"],
    "Ростов-на-Дону": ["როსტოვ-დონზე"],
    "Тебриз": ["თებრიზი"],
}

def normalized_city(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = re.sub(r"^(?:г[.]?|город|city|ქ[.]?|ქალაქი)\s+", "", text)
    return re.sub(r"[\W_]+", " ", text.split(",")[0]).strip()

@dataclass
class CityIdentity:
    key: str
    name_ru: str
    name_ge: str | None
    name_en: str
    country_iso: str
    lat: float | None = None
    lon: float | None = None
    is_popular: bool = False
    id: int | None = None
    aliases: set = field(default_factory=set)

    def public_aliases(self):
        return sorted({name for name in (self.name_ru, self.name_ge, self.name_en, *self.aliases) if name})

    def public(self):
        return dict(id=self.id, canonical_key=self.key, name_ru=self.name_ru,
                    name_ge=self.name_ge, name_en=self.name_en,
                    country_iso=self.country_iso, lat=self.lat, lon=self.lon,
                    is_popular=self.is_popular, aliases=self.public_aliases())

class CityRegistry:
    def __init__(self, records=()):
        self.by_key, self.by_id = {}, {}
        for row in CITIES_SEED:
            extra = EXTRA_NAMES.get(row["name_ru"], (None, None))
            en = extra[0] or GEO_MAPPING_RU_EN.get(row["name_ru"].casefold(), row["name_ru"])
            ge = row.get("name_ge") or extra[1]
            self._add(row["name_ru"], en, ge, row["country_iso"],
                      row.get("lat"), row.get("lon"), row.get("is_popular", False))
        for ru, en, ge, country, lat, lon in UI_CITY_CATALOG:
            self._add(ru, en, ge, country, lat, lon)
        self._reindex()
        for record in records:
            country = record.country_iso.strip().upper() if isinstance(record.country_iso, str) else ""
            if not re.fullmatch(r"[A-Z]{2}", country):
                self.by_id[record.id] = None
                continue
            identity = self.resolve(record.name_ru) or self.resolve(record.name_ge)
            if identity and identity.country_iso != country:
                # A dictionary row contradicting a known city is not a country proof.
                self.by_id[record.id] = None
                continue
            if identity:
                identity.id = min(identity.id, record.id) if identity.id is not None else record.id
                identity.lat, identity.lon = record.lat, record.lon
                identity.is_popular = bool(record.is_popular)
                identity.aliases.update(filter(None, map(normalized_city, (record.name_ru, record.name_ge))))
            else:
                key = country.lower() + ":db-" + str(record.id)
                identity = CityIdentity(key, record.name_ru, record.name_ge,
                                        record.name_ru, country,
                                        record.lat, record.lon, bool(record.is_popular), record.id)
                identity.aliases = set(filter(None, map(normalized_city, (record.name_ru, record.name_ge))))
                self.by_key[key] = identity
            self.by_id[record.id] = identity
        self._reindex()

    def _add(self, ru, en, ge, country, lat=None, lon=None, popular=False):
        key = country.lower() + ":" + normalized_city(en).replace(" ", "-")
        identity = CityIdentity(key, ru, ge, en, country, lat, lon, popular)
        identity.aliases = set(filter(None, map(normalized_city,
            [ru, en, ge, *EXTRA_ALIASES.get(ru, [])])))
        self.by_key[key] = identity

    def _reindex(self):
        self.aliases = defaultdict(set)
        for identity in self.by_key.values():
            self.aliases[identity.key].add(identity.key)
            for alias in identity.aliases:
                self.aliases[alias].add(identity.key)

    def resolve(self, value=None, city_id=None, city_key=None):
        if city_id is not None:
            return self.by_id.get(city_id)
        if city_key:
            return self.by_key.get(city_key)
        keys = self.aliases.get(normalized_city(value), set())
        return self.by_key[next(iter(keys))] if len(keys) == 1 else None

    def endpoint(self, value, city_id=None):
        by_label = self.resolve(value)
        if city_id is not None:
            identity = self.by_id.get(city_id)
            if not identity or normalized_city(value) not in identity.aliases:
                return None
            return identity
        return by_label

    def search(self, value, country=None, popular_only=False):
        needle = normalized_city(value)
        found = [c for c in self.by_key.values()
                 if (not country or c.country_iso == country.upper())
                 and (not popular_only or c.is_popular)
                 and (not needle or any(a.startswith(needle) for a in c.aliases))]
        return sorted(found, key=lambda c: (not c.is_popular, c.name_ru))

_canonical_registry = CityRegistry()

def same_city(left, right):
    """Match complete aliases; unknown labels only match the same normalized text."""
    a, b = _canonical_registry.resolve(left), _canonical_registry.resolve(right)
    if a or b:
        return bool(a and b and a.key == b.key)
    from app.services.route_locations import catalogue_key_for_alias
    left_place, right_place = catalogue_key_for_alias(left), catalogue_key_for_alias(right)
    if left_place or right_place:
        return bool(left_place and right_place and left_place == right_place)
    left_key, right_key = normalized_city(left), normalized_city(right)
    return bool(left_key and right_key and left_key == right_key)

def endpoint_match_value(listing, side):
    """A renamed checkpoint still matches by its saved canonical object key."""
    location = getattr(listing, side + '_location', None)
    if location and location.get('kind') == 'border_checkpoint':
        return location.get('key') or location.get('label', '')
    return getattr(listing, side + '_city', '') or ''

async def city_registry(db):
    records = (await db.execute(select(City))).scalars().all()
    return CityRegistry(records)

def route_scope(origin, destination):
    if not origin or not destination:
        return "unverified"
    if origin.country_iso == destination.country_iso == "GE":
        return "local"
    if origin.country_iso != destination.country_iso:
        return "intl"
    return "other"

def public_route_metadata(listing, registry=None):
    registry = registry or _canonical_registry
    origin = registry.endpoint(listing.from_city, getattr(listing, "from_city_id", None)) if registry.by_id else registry.resolve(listing.from_city)
    destination = registry.endpoint(listing.to_city, getattr(listing, "to_city_id", None)) if registry.by_id else registry.resolve(listing.to_city)
    locations = {side: getattr(listing, side + "_location", None) for side in ("from", "to")}
    if locations["from"]:
        origin = SimpleNamespace(country_iso=locations["from"]["country_iso"], key=locations["from"].get("settlement_key"), public_aliases=lambda: locations["from"].get("aliases", [locations["from"]["label"]]))
    if locations["to"]:
        destination = SimpleNamespace(country_iso=locations["to"]["country_iso"], key=locations["to"].get("settlement_key"), public_aliases=lambda: locations["to"].get("aliases", [locations["to"]["label"]]))
    return {
        "from_location": locations["from"], "to_location": locations["to"],
        "from_city_id": getattr(listing, "from_city_id", None),
        "to_city_id": getattr(listing, "to_city_id", None),
        "from_city_key": origin.key if origin else None,
        "to_city_key": destination.key if destination else None,
        "from_country_iso": origin.country_iso if origin else None,
        "to_country_iso": destination.country_iso if destination else None,
        "route_scope": route_scope(origin, destination),
        "from_city_aliases": origin.public_aliases() if origin else [],
        "to_city_aliases": destination.public_aliases() if destination else [],
    }

def _pair_clause(text_column, id_column, values):
    groups = defaultdict(list)
    for text, city_id in values:
        groups[city_id].append(text)
    clauses = [and_(id_column.is_(None) if city_id is None else id_column == city_id,
                    text_column.in_(texts)) for city_id, texts in groups.items()]
    return or_(*clauses) if clauses else false()

async def _endpoint_pairs(db, text_column, id_column):
    return (await db.execute(select(text_column, id_column).distinct())).all()

async def city_filter_clause(db, registry, text_column, id_column, text=None, city_id=None, city_key=None):
    identity = registry.resolve(text, city_id, city_key)
    if city_id is not None and identity is None:
        raise ValueError("Неизвестный идентификатор города")
    if city_key and identity is None:
        raise ValueError("Неизвестный идентификатор города")
    if identity and text and normalized_city(text) not in identity.aliases:
        raise ValueError("Город и его идентификатор не совпадают")
    if city_id is not None and city_key and identity.key != city_key:
        raise ValueError("Идентификаторы города не совпадают")
    pairs = await _endpoint_pairs(db, text_column, id_column)
    if identity:
        values = [(name, pk) for name, pk in pairs
                  if (registry.endpoint(name, pk) or CityIdentity("", "", None, "", "")).key == identity.key]
    else:
        needle = normalized_city(text)
        keys = {c.key for c in registry.search(text)} if needle else set()
        values = [(name, pk) for name, pk in pairs
                  if (registry.endpoint(name, pk) and registry.endpoint(name, pk).key in keys)
                  or (not registry.endpoint(name, pk) and needle and needle in normalized_city(name))]
    return _pair_clause(text_column, id_column, values)

async def route_scope_clause(db, registry, model, scope):
    expressions = []
    for prefix in ("from", "to"):
        text_column, id_column = getattr(model, prefix + "_city"), getattr(model, prefix + "_city_id")
        groups = defaultdict(list)
        for name, pk in await _endpoint_pairs(db, text_column, id_column):
            identity = registry.endpoint(name, pk)
            if identity:
                groups[identity.country_iso].append((name, pk))
        legacy = case(*[(_pair_clause(text_column, id_column, values), country)
                       for country, values in groups.items()], else_=None) if groups else literal(None)
        location = getattr(model, prefix + "_location", None)
        expressions.append(func.coalesce(location["country_iso"].as_string(), legacy) if location is not None else legacy)
    origin, destination = expressions
    return and_(origin == "GE", destination == "GE") if scope == "local" else and_(origin.is_not(None), destination.is_not(None), origin != destination)

async def resolve_publication_city(db, registry, text, city_id=None, city_key=None):
    identity = registry.resolve(text, city_id, city_key)
    if (city_id is not None or city_key) and identity is None:
        raise ValueError("Неизвестный идентификатор города")
    if identity and normalized_city(text) not in identity.aliases:
        raise ValueError("Город и его идентификатор не совпадают")
    if city_id is not None and city_key and identity.key != city_key:
        raise ValueError("Идентификаторы города не совпадают")
    if not identity:
        raise ValueError("Не удалось однозначно определить город. Выберите город из списка или обратитесь в поддержку / აირჩიეთ ქალაქი სიიდან ან მიმართეთ მხარდაჭერას")
    if identity.id is None:
        record = City(name_ru=identity.name_ru, name_ge=identity.name_ge,
                      country_iso=identity.country_iso, lat=identity.lat, lon=identity.lon,
                      is_popular=identity.is_popular)
        db.add(record)
        await db.flush()
        identity.id = record.id
        registry.by_id[record.id] = identity
    return identity.name_ru, identity.id

async def apply_publication_cities(db, data, existing=None):
    if any(data.get(side + "_location") or (getattr(existing, side + "_location", None) if existing else None) for side in ("from", "to")):
        from app.services.route_locations import apply_route_locations
        return await apply_route_locations(db, data, existing)
    registry = await city_registry(db)
    for prefix in ("from", "to"):
        name_field, id_field, key_field = prefix + "_city", prefix + "_city_id", prefix + "_city_key"
        if existing is not None and not any(field in data for field in (name_field, id_field, key_field)):
            continue
        name = data.get(name_field) or (getattr(existing, name_field) if existing else "")
        city_id = data.get(id_field) if id_field in data else None
        city_key = data.pop(key_field, None)
        if (existing is not None and city_id is None and not city_key
                and normalized_city(name) == normalized_city(getattr(existing, name_field))
                and registry.endpoint(name, getattr(existing, id_field, None)) is None):
            # An unchanged legacy unknown endpoint may be kept during an owner
            # edit/cancellation. It remains unverified; do not infer or replace
            # its identity. New/changed unknown endpoints must be selected again.
            data[name_field] = getattr(existing, name_field)
            data[id_field] = getattr(existing, id_field, None)
            continue
        data[name_field], data[id_field] = await resolve_publication_city(db, registry, name, city_id, city_key)
    if existing is None:
        scope = route_scope(registry.endpoint(data["from_city"], data["from_city_id"]),
                            registry.endpoint(data["to_city"], data["to_city_id"]))
        if scope == "other":
            raise ValueError("В пилоте доступны перевозки внутри Грузии и международные маршруты. Внутренний маршрут другой страны пока не поддерживается / პილოტში სხვა ქვეყნის შიდა მარშრუტი ჯერ არ არის მხარდაჭერილი")
    return registry
