"""Product catalogue capacity rules, not road/legal weight allowances.

The public catalogue labels gazel as a van up to 3.5 tonnes. Heavy/special
transport keeps the pre-existing 100 t upper bound until verified specifications
are supplied; this module does not assert that any load is road-legal.
"""
import math

from app.models.load import TruckType

TRUCK_TYPES = {item.value for item in TruckType}
TYPE_ALIASES = {"open": "bort", "autovoz": "auto", "lowboy": "other"}
TYPE_ALIASES.update({
    "тент": "tent", "ტენტი": "tent", "фургон": "gazel", "газель": "gazel",
    "фургон / газель": "gazel", "ფურგონი": "gazel", "борт": "bort",
    "бортовой": "bort", "ბორტიანი": "bort", "рефрижератор": "ref",
    "რეფრიჟერატორი": "ref", "контейнер": "container", "კონტეინერი": "container",
    "автовоз": "auto", "ავტოვოზი": "auto", "tanker": "cistern",
})


def canonical_truck_type(value):
    value = value.value if hasattr(value, "value") else value
    if isinstance(value, str):
        value = value.strip().lower()
    return TYPE_ALIASES.get(value, value)


def max_capacity_kg(truck_type):
    return 3500 if canonical_truck_type(truck_type) == "gazel" else 100000


def validate_transport_capacity(truck_type, capacity_kg):
    truck_type = canonical_truck_type(truck_type)
    if truck_type not in TRUCK_TYPES:
        raise ValueError("Выберите допустимый тип кузова")
    if isinstance(capacity_kg, bool):
        raise ValueError("Грузоподъёмность должна быть числом")
    try:
        capacity = float(capacity_kg)
    except (TypeError, ValueError):
        raise ValueError("Грузоподъёмность должна быть числом") from None
    maximum = max_capacity_kg(truck_type)
    if not math.isfinite(capacity) or capacity <= 0 or capacity > maximum:
        if truck_type == "gazel":
            raise ValueError("Для фургона до 3.5 т укажите грузоподъёмность больше 0 и не больше 3500 кг")
        raise ValueError("Грузоподъёмность должна быть больше 0 и не больше 100000 кг")
    return capacity


def capacity_metadata(truck_type, capacity_kg):
    try:
        validate_transport_capacity(truck_type, capacity_kg)
        valid, warning = True, None
    except ValueError as error:
        valid, warning = False, str(error)
    return {"capacity_valid": valid, "capacity_warning": warning,
            "max_capacity_kg": max_capacity_kg(truck_type)}
