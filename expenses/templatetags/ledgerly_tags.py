from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

DATE_FORMAT_MAP = {
    'YYYY-MM-DD': '%Y-%m-%d',
    'DD/MM/YYYY': '%d/%m/%Y',
    'MM/DD/YYYY': '%m/%d/%Y',
    'DD Mon YYYY': '%d %b %Y',
}


@register.filter
def user_date(value, date_format='YYYY-MM-DD'):
    """Format a date/datetime using the user's preferred UserSettings.date_format."""
    if not value:
        return ''
    fmt = DATE_FORMAT_MAP.get(date_format, '%d %b %Y')
    try:
        return value.strftime(fmt)
    except AttributeError:
        return str(value)


@register.filter
def money(value, symbol='₹'):
    """Format a decimal/number with 2 decimals and the active currency symbol."""
    if value is None or value == '':
        value = Decimal('0.00')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return f'{symbol}0.00'

    sign = '−' if amount < 0 else ''
    return f'{sign}{symbol}{abs(amount):,.2f}'


@register.filter
def money_whole(value, symbol='₹'):
    """Format a decimal/number rounded to whole units with the active currency symbol."""
    if value is None or value == '':
        value = Decimal('0')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return f'{symbol}0'

    sign = '−' if amount < 0 else ''
    return f'{sign}{symbol}{abs(amount):,.0f}'
