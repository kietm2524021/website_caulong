from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def dotsep(value):
    if value in (None, ""):
        return "0"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    rounded = int(number.quantize(Decimal("1")))
    return f"{rounded:,}".replace(",", ".")
