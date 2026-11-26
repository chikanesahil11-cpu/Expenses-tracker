import calendar as py_calendar
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from ..context_processors import get_user_settings
from ..models import SavingsGoal, Transaction, UserSettings
from ..services import (
    budget_statuses,
    build_dashboard_insights,
    build_financial_report_pdf,
    chart_data,
    month_range,
    month_start,
    parse_filter_date,
    report_metrics,
    sum_amount,
)


def _resolve_dashboard_range(request, today, month_start_date, next_month_date, previous_start, previous_end, first_day_of_week):
    """Resolve active timeframe query parameters into (range_param, start_date, end_date, range_label)."""
    range_param = request.GET.get('range', 'all').strip().lower()
    start_date = None
    end_date = None
    range_label = 'All time'

    if range_param == 'today':
        start_date = today
        end_date = today
        range_label = 'Today'
    elif range_param == 'this_week':
        offset = (today.weekday() + 1) % 7 if first_day_of_week == UserSettings.DayOfWeek.SUNDAY else today.weekday()
        start_date = today - timedelta(days=offset)
        end_date = start_date + timedelta(days=6)
        range_label = 'This week'
    elif range_param == 'this_month':
        start_date = month_start_date
        end_date = next_month_date - timedelta(days=1)
        range_label = today.strftime('%B %Y')
    elif range_param == 'last_month':
        start_date = previous_start
        end_date = previous_end - timedelta(days=1)
        range_label = previous_start.strftime('%B %Y')
    elif range_param == 'this_year':
        start_date = date(today.year, 1, 1)
        end_date = date(today.year, 12, 31)
        range_label = str(today.year)
    elif range_param == 'custom':
        custom_s = parse_filter_date(request.GET.get('start_date'))
        custom_e = parse_filter_date(request.GET.get('end_date'))
        if custom_s or custom_e:
            start_date = custom_s
            end_date = custom_e
            s_str = custom_s.strftime('%d %b %Y') if custom_s else 'Start'
            e_str = custom_e.strftime('%d %b %Y') if custom_e else 'Now'
            range_label = f'{s_str} – {e_str}'
    else:
        range_param = 'all'

    return range_param, start_date, end_date, range_label


@login_required
def dashboard(request):
    user_settings = get_user_settings(request)
    transactions = Transaction.objects.filter(owner=request.user).select_related('category')

    today = timezone.localdate()
    this_month = today.replace(day=1)
    curr_month_start, next_month = month_range(this_month)
    previous_start, previous_end = month_range(month_start(today.year, today.month, -1))

    range_param, start_date, end_date, range_label = _resolve_dashboard_range(
        request,
        today,
        curr_month_start,
        next_month,
        previous_start,
        previous_end,
        user_settings.first_day_of_week,
    )

    filtered_transactions = transactions
    if start_date:
        filtered_transactions = filtered_transactions.filter(date__gte=start_date)
    if end_date:
        filtered_transactions = filtered_transactions.filter(date__lte=end_date)

    all_time_income = sum_amount(transactions.filter(transaction_type=Transaction.TransactionType.INCOME))
    all_time_expenses = sum_amount(transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE))
    all_time_balance = all_time_income - all_time_expenses

    if range_param != 'all':
        income = sum_amount(filtered_transactions.filter(transaction_type=Transaction.TransactionType.INCOME))
        expenses = sum_amount(filtered_transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE))
        balance = income - expenses
        tx_count = filtered_transactions.count()
    else:
        income = all_time_income
        expenses = all_time_expenses
        balance = all_time_balance
        tx_count = transactions.count()

    savings_rate = round(float((balance / income) * 100), 1) if income > 0 else 0

    month_expenses_qs = transactions.filter(
        transaction_type=Transaction.TransactionType.EXPENSE,
        date__gte=curr_month_start,
        date__lt=next_month,
    )
    month_expenses = sum_amount(month_expenses_qs)
    previous_expenses = sum_amount(
        transactions.filter(
            transaction_type=Transaction.TransactionType.EXPENSE,
            date__gte=previous_start,
            date__lt=previous_end,
        )
    )

    highest_category = (
        (filtered_transactions if range_param != 'all' else month_expenses_qs)
        .filter(transaction_type=Transaction.TransactionType.EXPENSE)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
        .first()
    )

    budgets, budget_summary = budget_statuses(request.user, this_month)
    insights = build_dashboard_insights(
        highest_category,
        month_expenses,
        previous_expenses,
        today,
        symbol=user_settings.currency_symbol,
    )

    return render(
        request,
        'expenses/dashboard.html',
        {
            'total_income': income,
            'total_expenses': expenses,
            'balance': balance,
            'all_time_balance': all_time_balance,
            'all_time_income': all_time_income,
            'all_time_expenses': all_time_expenses,
            'savings_rate': savings_rate,
            'transaction_count': tx_count,
            'all_transaction_count': transactions.count(),
            'recent_transactions': transactions[:5],
            'chart_data': chart_data(transactions, category_source=filtered_transactions),
            'budget_summary': budget_summary,
            'budget_highlights': budgets[:3],
            'goals': SavingsGoal.objects.filter(owner=request.user).order_by('target_date', 'created_at')[:3],
            'insights': insights,
            'current_month_label': today.strftime('%B %Y'),
            'active_range': range_param,
            'range_label': range_label,
            'custom_start': request.GET.get('start_date', ''),
            'custom_end': request.GET.get('end_date', ''),
        },
    )


@login_required
def reports(request):
    transactions, metrics = report_metrics(request.user)
    _, budget_summary = budget_statuses(request.user, timezone.localdate().replace(day=1))

    top_categories = list(
        transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:7]
    )

    total_exp = metrics['expenses']
    for cat in top_categories:
        cat['percentage'] = round(float((cat['total'] / total_exp) * 100), 1) if total_exp > 0 else 0

    account_breakdown = list(
        transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE, account__isnull=False)
        .values('account__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    return render(
        request,
        'expenses/reports.html',
        {
            **metrics,
            'chart_data': chart_data(transactions, months=12),
            'budget_summary': budget_summary,
            'top_categories': top_categories,
            'account_breakdown': account_breakdown,
            'current_year': timezone.localdate().year,
        },
    )


@login_required
def financial_report_pdf(request):
    user_settings = get_user_settings(request)
    return build_financial_report_pdf(request.user, currency_code=user_settings.currency)


@login_required
def transaction_calendar(request):
    """Interactive monthly transaction calendar view with daily summaries."""
    user_settings = get_user_settings(request)
    today = timezone.localdate()

    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if not (1 <= month <= 12):
            year, month = today.year, today.month
    except (ValueError, TypeError):
        year, month = today.year, today.month

    current_month_date = date(year, month, 1)
    curr_month_start, next_month = month_range(current_month_date)
    prev_month_date = month_start(year, month, -1)
    next_month_date = month_start(year, month, 1)

    month_transactions = Transaction.objects.filter(
        owner=request.user,
        date__gte=curr_month_start,
        date__lt=next_month,
    ).select_related('category', 'account')

    daily_data = {}
    for tx in month_transactions:
        day_stats = daily_data.setdefault(
            tx.date.day,
            {'income': Decimal('0.00'), 'expense': Decimal('0.00'), 'count': 0},
        )
        if tx.transaction_type == Transaction.TransactionType.INCOME:
            day_stats['income'] += tx.amount
        else:
            day_stats['expense'] += tx.amount
        day_stats['count'] += 1

    month_income = sum((item['income'] for item in daily_data.values()), Decimal('0.00'))
    month_expense = sum((item['expense'] for item in daily_data.values()), Decimal('0.00'))
    month_net = month_income - month_expense

    starts_sunday = user_settings.first_day_of_week == UserSettings.DayOfWeek.SUNDAY
    cal = py_calendar.Calendar(firstweekday=6 if starts_sunday else 0)
    weekday_headers = (
        ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        if starts_sunday
        else ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    )

    month_matrix = []
    for week in cal.monthdatescalendar(year, month):
        week_data = []
        for d in week:
            is_current_month = d.month == month
            day_stats = daily_data.get(d.day) if is_current_month else None
            net = (day_stats['income'] - day_stats['expense']) if day_stats else Decimal('0.00')
            week_data.append({
                'date': d,
                'day': d.day,
                'is_current_month': is_current_month,
                'is_today': d == today,
                'income': day_stats['income'] if day_stats else Decimal('0.00'),
                'expense': day_stats['expense'] if day_stats else Decimal('0.00'),
                'net': net,
                'count': day_stats['count'] if day_stats else 0,
            })
        month_matrix.append(week_data)

    selected_date = parse_filter_date(request.GET.get('date', ''))
    if not selected_date or selected_date.month != month or selected_date.year != year:
        selected_date = today if (today.year == year and today.month == month) else curr_month_start

    selected_day_transactions = month_transactions.filter(date=selected_date)
    selected_day_income = sum_amount(
        selected_day_transactions.filter(transaction_type=Transaction.TransactionType.INCOME)
    )
    selected_day_expense = sum_amount(
        selected_day_transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE)
    )

    return render(
        request,
        'expenses/calendar.html',
        {
            'year': year,
            'month': month,
            'current_month_label': current_month_date.strftime('%B %Y'),
            'prev_month': prev_month_date,
            'next_month': next_month_date,
            'today': today,
            'weekday_headers': weekday_headers,
            'month_matrix': month_matrix,
            'month_income': month_income,
            'month_expense': month_expense,
            'month_net': month_net,
            'selected_date': selected_date,
            'selected_day_transactions': selected_day_transactions,
            'selected_day_income': selected_day_income,
            'selected_day_expense': selected_day_expense,
            'selected_day_net': selected_day_income - selected_day_expense,
        },
    )
