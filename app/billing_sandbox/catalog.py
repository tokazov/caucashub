"""Server-owned test catalogue; prices are proposals, not live offers."""
from dataclasses import asdict, dataclass

DAY = 86_400
PROJECTS = frozenset({"caucashub", "techrent"})


@dataclass(frozen=True)
class Product:
    code: str
    title: str
    kind: str
    price_tetri: int
    duration_seconds: int
    currency: str = "GEL"
    enabled: bool = True

    def public(self):
        return asdict(self)


PRODUCTS = (
    Product("pro", "Pro — тестовые 30 дней", "subscription", 4900, 30 * DAY),
    Product("business", "Business — функции команды ещё не готовы", "subscription",
            14900, 30 * DAY, enabled=False),
    Product("promote_24h", "Продвижение — 24 часа", "boost", 500, DAY),
    Product("promote_72h", "Продвижение — 3 дня", "boost", 1200, 3 * DAY),
    Product("promote_168h", "Продвижение — 7 дней", "boost", 2500, 7 * DAY),
)


def products_for(project):
    # TechRent has a separate namespace, but no approved products yet.
    if project not in PROJECTS:
        raise ValueError("Unknown sandbox project")
    return PRODUCTS if project == "caucashub" else ()
