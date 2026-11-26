from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from ..models import Budget, Transaction


def month_start(year, month, offset=0):
    absolute_month = year * 12 + month - 1 + offset
    new_year, new_month_index = divmod(absolute_month, 12)
    return date(new_year, new_month_index + 1, 1)


def month_range(month):
    start = month.replace(day=1)
    return start, month_start(start.year, start.month, 1)


def sum_amount(queryset):
    return queryset.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')


def parse_filter_date(value):
    """Return a valid ISO date for a list filter, or ``None`` if it is invalid."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def chart_data(transactions, category_source=None, months=6):
    """Build serialisable, user-specific datasets for the dashboard and report charts."""
    today = timezone.localdate()
    month_starts = [
        month_start(today.year, today.month, offset)
        for offset in range(-(months - 1), 1)
    ]

    grouped = (
        transactions.filter(date__gte=month_starts[0])
        .annotate(month=TruncMonth('date'))
        .values('month', 'transaction_type')
        .annotate(total=Sum('amount'))
    )

    monthly = {}
    for item in grouped:
        month_value = item['month']
        if hasattr(month_value, 'date'):
            month_value = month_value.date()
        monthly[(month_value.year, month_value.month, item['transaction_type'])] = float(item['total'])

    income = [
        monthly.get((entry.year, entry.month, Transaction.TransactionType.INCOME), 0)
        for entry in month_starts
    ]
    expenses = [
        monthly.get((entry.year, entry.month, Transaction.TransactionType.EXPENSE), 0)
        for entry in month_starts
    ]

    cat_qs = category_source if category_source is not None else transactions
    category_totals = (
        cat_qs.filter(transaction_type=Transaction.TransactionType.EXPENSE)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    return {
        'labels': [entry.strftime('%b') for entry in month_starts],
        'income': income,
        'expenses': expenses,
        'category_labels': [entry['category__name'] for entry in category_totals],
        'category_values': [float(entry['total']) for entry in category_totals],
    }


def _budget_status_label(percentage):
    if percentage >= 100:
        return 'over'
    if percentage >= 80:
        return 'warning'
    return 'on-track'


def budget_statuses(user, month):
    """Attach calculated spend/progress to a user's budgets for one month."""
    start, end = month_range(month)

    budgets = list(
        Budget.objects.filter(owner=user, month=start).select_related('category')
    )

    spending = {
        item['category_id']: item['total']
        for item in (
            Transaction.objects.filter(
                owner=user,
                transaction_type=Transaction.TransactionType.EXPENSE,
                date__gte=start,
                date__lt=end,
            )
            .values('category_id')
            .annotate(total=Sum('amount'))
        )
    }

    total_budget = Decimal('0.00')
    total_spent = Decimal('0.00')

    for budget in budgets:
        budget.spent = spending.get(budget.category_id, Decimal('0.00'))
        budget.percentage = (
            round(float((budget.spent / budget.amount) * 100), 1)
            if budget.amount
            else 0
        )
        budget.bar_percentage = min(100, budget.percentage)
        budget.remaining = max(Decimal('0.00'), budget.amount - budget.spent)
        budget.overspent = max(Decimal('0.00'), budget.spent - budget.amount)
        budget.is_over = budget.spent > budget.amount
        budget.status = _budget_status_label(budget.percentage)

        total_budget += budget.amount
        total_spent += budget.spent

    total_percentage = (
        round(float((total_spent / total_budget) * 100), 1)
        if total_budget
        else 0
    )

    return budgets, {
        'total_budget': total_budget,
        'total_spent': total_spent,
        'percentage': total_percentage,
        'bar_percentage': min(100, total_percentage),
        'remaining': max(Decimal('0.00'), total_budget - total_spent),
        'overspent': max(Decimal('0.00'), total_spent - total_budget),
        'status': _budget_status_label(total_percentage),
    }


def budget_warning(request, transaction):
    """Emit a warning or error flash message if an expense nears/exceeds its category budget."""
    if transaction.transaction_type != Transaction.TransactionType.EXPENSE:
        return

    month = transaction.date.replace(day=1)
    budget = Budget.objects.filter(
        owner=request.user,
        category=transaction.category,
        month=month,
    ).first()
    if not budget:
        return

    start, end = month_range(month)
    spent = sum_amount(
        Transaction.objects.filter(
            owner=request.user,
            category=transaction.category,
            transaction_type=Transaction.TransactionType.EXPENSE,
            date__gte=start,
            date__lt=end,
        )
    )
    percentage = (spent / budget.amount) * 100

    if percentage >= 100:
        messages.error(request, f'{budget.category.name} budget exceeded: {percentage:.0f}% used.')
    elif percentage >= 80:
        messages.warning(request, f'{budget.category.name} budget warning: {percentage:.0f}% used.')


def transaction_filters(request):
    """Parse query parameters and return filtered, ordered transactions plus normalized filter state."""
    transactions = Transaction.objects.filter(owner=request.user).select_related('category', 'account')

    search = request.GET.get('q', '').strip()
    transaction_type = request.GET.get('type', '')
    category_id = request.GET.get('category', '')
    account_id = request.GET.get('account', '')
    payment_method = request.GET.get('payment_method', '')
    start_date = parse_filter_date(request.GET.get('start_date', ''))
    end_date = parse_filter_date(request.GET.get('end_date', ''))
    sort = request.GET.get('sort', 'date_desc')

    if search:
        transactions = transactions.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(category__name__icontains=search)
        )
    if transaction_type in Transaction.TransactionType.values:
        transactions = transactions.filter(transaction_type=transaction_type)
    if category_id.isdigit():
        transactions = transactions.filter(category_id=category_id)
    if account_id.isdigit():
        transactions = transactions.filter(account_id=account_id)
    if payment_method in Transaction.PaymentMethod.values:
        transactions = transactions.filter(payment_method=payment_method)
    if start_date:
        transactions = transactions.filter(date__gte=start_date)
    if end_date:
        transactions = transactions.filter(date__lte=end_date)

    ordering = {
        'date_desc': ('-date', '-created_at'),
        'date_asc': ('date', 'created_at'),
        'amount_desc': ('-amount', '-date'),
        'amount_asc': ('amount', '-date'),
        'title': ('title', '-date'),
    }
    if sort not in ordering:
        sort = 'date_desc'

    return transactions.order_by(*ordering[sort]), {
        'q': search,
        'type': transaction_type,
        'category': category_id,
        'account': account_id,
        'payment_method': payment_method,
        'start_date': start_date.isoformat() if start_date else '',
        'end_date': end_date.isoformat() if end_date else '',
        'sort': sort,
    }


def report_metrics(user):
    """Compute all-time and year-to-date aggregate financial metrics for a user."""
    transactions = Transaction.objects.filter(owner=user).select_related('category')
    today = timezone.localdate()
    year_start = date(today.year, 1, 1)

    income = sum_amount(transactions.filter(transaction_type=Transaction.TransactionType.INCOME))
    expenses = sum_amount(transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE))
    year_income = sum_amount(
        transactions.filter(transaction_type=Transaction.TransactionType.INCOME, date__gte=year_start)
    )
    year_expenses = sum_amount(
        transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE, date__gte=year_start)
    )

    return transactions, {
        'income': income,
        'expenses': expenses,
        'balance': income - expenses,
        'transaction_count': transactions.count(),
        'year_income': year_income,
        'year_expenses': year_expenses,
        'year_balance': year_income - year_expenses,
        'savings_rate': round(float(((income - expenses) / income) * 100), 1) if income else 0,
    }


def build_dashboard_insights(highest_category, month_expenses, previous_expenses, today, symbol='₹'):
    """Build the three summary insight cards displayed on the dashboard."""
    spending_change = (
        round(float(((month_expenses - previous_expenses) / previous_expenses) * 100), 1)
        if previous_expenses
        else 0
    )
    return [
        {
            'title': 'Top spending category',
            'value': highest_category['category__name'] if highest_category else 'No spending yet',
            'detail': (
                f"{symbol}{highest_category['total']:,.2f} in selected period"
                if highest_category
                else 'Record an expense to unlock this insight.'
            ),
        },
        {
            'title': 'Monthly spending',
            'value': f"{symbol}{month_expenses:,.2f}",
            'detail': (
                f"{abs(spending_change):.1f}% "
                f"{'higher' if spending_change >= 0 else 'lower'} "
                "than last month"
                if previous_expenses
                else 'No previous-month comparison yet.'
            ),
        },
        {
            'title': 'Average daily spend',
            'value': f"{symbol}{(month_expenses / Decimal(max(today.day, 1))):,.2f}",
            'detail': 'Based on expenses recorded this month.',
        },
    ]
