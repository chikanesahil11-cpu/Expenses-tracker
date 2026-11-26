from .models import UserSettings


def get_user_settings(request_or_user):
    """Return (and cache on request if given) the UserSettings for a user."""
    if hasattr(request_or_user, 'user'):
        request = request_or_user
        if not request.user.is_authenticated:
            return None
        cached = getattr(request, '_ledgerly_user_settings', None)
        if cached is not None:
            return cached
        settings_obj, _ = UserSettings.objects.get_or_create(user=request.user)
        request._ledgerly_user_settings = settings_obj
        return settings_obj

    if not request_or_user or not request_or_user.is_authenticated:
        return None
    settings_obj, _ = UserSettings.objects.get_or_create(user=request_or_user)
    return settings_obj


def user_preferences(request):
    """Expose currency, date format, week start, and theme preferences to all templates."""
    settings_obj = get_user_settings(request)
    if settings_obj is None:
        return {
            'user_settings': None,
            'currency_code': 'INR',
            'currency_symbol': '₹',
            'currency_locale': 'en-IN',
            'user_date_format': 'YYYY-MM-DD',
            'user_theme': 'dark',
        }

    return {
        'user_settings': settings_obj,
        'currency_code': settings_obj.currency,
        'currency_symbol': settings_obj.currency_symbol,
        'currency_locale': settings_obj.currency_locale,
        'user_date_format': settings_obj.date_format,
        'user_theme': settings_obj.theme_preference,
    }
