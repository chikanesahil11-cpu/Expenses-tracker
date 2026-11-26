from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..context_processors import get_user_settings
from ..forms import (
    ApplicationSettingsForm,
    RegistrationForm,
    StyledPasswordChangeForm,
    UserProfileForm,
)
from ..models import (
    Account,
    Budget,
    RecurringTransaction,
    SavingsGoal,
    Transaction,
)


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Your account is ready. Welcome to Ledgerly!')
            return redirect('dashboard')
    else:
        form = RegistrationForm()

    return render(request, 'registration/register.html', {'form': form})


@login_required
def settings_view(request):
    """Multi-tab user, application, and data security settings."""
    user = request.user
    user_settings = get_user_settings(request)

    active_tab = request.GET.get('tab', 'profile')
    profile_form = UserProfileForm(instance=user)
    app_settings_form = ApplicationSettingsForm(instance=user_settings)
    password_form = StyledPasswordChangeForm(user=user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_profile':
            active_tab = 'profile'
            profile_form = UserProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect(f"{reverse('settings_view')}?tab=profile")

        elif action == 'update_preferences':
            active_tab = 'preferences'
            app_settings_form = ApplicationSettingsForm(request.POST, instance=user_settings)
            if app_settings_form.is_valid():
                saved_settings = app_settings_form.save()
                request.session['sync_theme'] = saved_settings.theme_preference
                messages.success(request, 'Preferences saved successfully.')
                return redirect(f"{reverse('settings_view')}?tab=preferences")

        elif action == 'change_password':
            active_tab = 'security'
            password_form = StyledPasswordChangeForm(user=user, data=request.POST)
            if password_form.is_valid():
                user_updated = password_form.save()
                update_session_auth_hash(request, user_updated)
                messages.success(request, 'Your password was successfully updated!')
                return redirect(f"{reverse('settings_view')}?tab=security")

    stats = {
        'transactions_count': Transaction.objects.filter(owner=user).count(),
        'accounts_count': Account.objects.filter(owner=user).count(),
        'budgets_count': Budget.objects.filter(owner=user).count(),
        'goals_count': SavingsGoal.objects.filter(owner=user).count(),
        'recurring_count': RecurringTransaction.objects.filter(owner=user).count(),
    }

    sync_theme = request.session.pop('sync_theme', None)

    return render(
        request,
        'expenses/settings.html',
        {
            'active_tab': active_tab,
            'profile_form': profile_form,
            'app_settings_form': app_settings_form,
            'password_form': password_form,
            'stats': stats,
            'user_settings': user_settings,
            'sync_theme': sync_theme,
        },
    )


@require_POST
@login_required
def account_delete_user(request):
    """Secure user account deletion with confirmation."""
    confirm_text = request.POST.get('confirm_text', '').strip()
    if confirm_text != request.user.username:
        messages.error(request, 'Confirmation username did not match. Account was not deleted.')
        return redirect(f"{reverse('settings_view')}?tab=security")

    user = request.user
    user.delete()
    messages.info(request, 'Your Ledgerly account and associated financial data have been permanently deleted.')
    return redirect('login')
