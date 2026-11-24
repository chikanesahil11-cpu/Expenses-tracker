
import calendar as py_calendar
import csv
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Q, Sum, Count
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    AccountForm,
    ApplicationSettingsForm,
    BudgetForm,
    RecurringTransactionForm,
    RegistrationForm,
    SavingsGoalForm,
    StyledPasswordChangeForm,
    TransactionForm,
    TransactionImportForm,
    UserProfileForm,
)
from .models import (
    Account,
    Budget,
    Category,
    RecurringTransaction,
    SavingsGoal,
    Transaction,
    UserSettings,
)


def _month_start(year, month, offset=0):
    absolute_month = year * 12 + month - 1 + offset
    new_year, new_month_index = divmod(absolute_month, 12)
    return date(new_year, new_month_index + 1, 1)


def _month_range(month):
    start = month.replace(day=1)
    return start, _month_start(start.year, start.month, 1)


def _sum_amount(queryset):
    return queryset.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')


def _parse_filter_date(value):
    """Return a valid ISO date for a list filter, or ``None`` if it is invalid."""
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _chart_data(transactions, category_source=None, months=6):
    """Build serialisable, user-specific datasets for the dashboard charts."""
    today = timezone.localdate()
    month_starts = [
        _month_start(today.year, today.month, offset)
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

        monthly[
            (month_value.year, month_value.month, item['transaction_type'])
        ] = float(item['total'])

    income = [
        monthly.get(
            (entry.year, entry.month, Transaction.TransactionType.INCOME), 0
        )
        for entry in month_starts
    ]

    expenses = [
        monthly.get(
            (entry.year, entry.month, Transaction.TransactionType.EXPENSE), 0
        )
        for entry in month_starts
    ]

    cat_qs = category_source if category_source is not None else transactions
    category_totals = (
        cat_qs.filter(
            transaction_type=Transaction.TransactionType.EXPENSE
        )
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    return {
        'labels': [entry.strftime('%b') for entry in month_starts],
        'income': income,
        'expenses': expenses,
        'category_labels': [
            entry['category__name'] for entry in category_totals
        ],
        'category_values': [
            float(entry['total']) for entry in category_totals
        ],
    }


def _budget_statuses(user, month):
    """Attach calculated spend/progress to a user's budgets for one month."""
    start, end = _month_range(month)

    budgets = list(
        Budget.objects.filter(
            owner=user,
            month=start
        ).select_related('category')
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
        budget.spent = spending.get(
            budget.category_id,
            Decimal('0.00')
        )

        budget.percentage = (
            round(float((budget.spent / budget.amount) * 100), 1)
            if budget.amount else 0
        )

        budget.bar_percentage = min(100, budget.percentage)
        budget.remaining = max(
            Decimal('0.00'),
            budget.amount - budget.spent
        )

        budget.status = (
            'over' if budget.percentage >= 100
            else 'warning' if budget.percentage >= 80
            else 'on-track'
        )

        total_budget += budget.amount
        total_spent += budget.spent

    total_percentage = (
        round(float((total_spent / total_budget) * 100), 1)
        if total_budget else 0
    )

    return budgets, {
        'total_budget': total_budget,
        'total_spent': total_spent,
        'percentage': total_percentage,
        'bar_percentage': min(100, total_percentage),
        'remaining': max(
            Decimal('0.00'),
            total_budget - total_spent
        ),
        'status': (
            'over' if total_percentage >= 100
            else 'warning' if total_percentage >= 80
            else 'on-track'
        ),
    }


def _budget_warning(request, transaction):
    if transaction.transaction_type != Transaction.TransactionType.EXPENSE:
        return

    month = transaction.date.replace(day=1)

    budget = Budget.objects.filter(
        owner=request.user,
        category=transaction.category,
        month=month
    ).first()

    if not budget:
        return

    start, end = _month_range(month)

    spent = _sum_amount(
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
        messages.error(
            request,
            f'{budget.category.name} budget exceeded: {percentage:.0f}% used.'
        )
    elif percentage >= 80:
        messages.warning(
            request,
            f'{budget.category.name} budget warning: {percentage:.0f}% used.'
        )


def _transaction_filters(request):
    transactions = Transaction.objects.filter(
        owner=request.user
    ).select_related('category', 'account')

    search = request.GET.get('q', '').strip()
    transaction_type = request.GET.get('type', '')
    category_id = request.GET.get('category', '')
    account_id = request.GET.get('account', '')
    payment_method = request.GET.get('payment_method', '')
    start_date = _parse_filter_date(request.GET.get('start_date', ''))
    end_date = _parse_filter_date(request.GET.get('end_date', ''))
    sort = request.GET.get('sort', 'date_desc')

    if search:
        transactions = transactions.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(category__name__icontains=search)
        )

    if transaction_type in Transaction.TransactionType.values:
        transactions = transactions.filter(
            transaction_type=transaction_type
        )

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


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(
                request,
                'Your account is ready. Welcome to Ledgerly!'
            )
            return redirect('dashboard')
    else:
        form = RegistrationForm()

    return render(
        request,
        'registration/register.html',
        {'form': form}
    )


@login_required
def dashboard(request):
    transactions = Transaction.objects.filter(
        owner=request.user
    ).select_related('category')

    today = timezone.localdate()
    this_month = today.replace(day=1)

    month_start, next_month = _month_range(this_month)

    previous_start, previous_end = _month_range(
        _month_start(today.year, today.month, -1)
    )

    # Date range filter handling
    range_param = request.GET.get('range', 'all').strip().lower()
    start_date = None
    end_date = None
    range_label = 'All time'

    if range_param == 'today':
        start_date = today
        end_date = today
        range_label = 'Today'
    elif range_param == 'this_week':
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
        range_label = 'This week'
    elif range_param == 'this_month':
        start_date = month_start
        end_date = next_month - timedelta(days=1)
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
        custom_s = _parse_filter_date(request.GET.get('start_date'))
        custom_e = _parse_filter_date(request.GET.get('end_date'))
        if custom_s or custom_e:
            start_date = custom_s
            end_date = custom_e
            s_str = custom_s.strftime('%d %b %Y') if custom_s else 'Start'
            e_str = custom_e.strftime('%d %b %Y') if custom_e else 'Now'
            range_label = f'{s_str} – {e_str}'
    else:
        range_param = 'all'
        range_label = 'All time'

    # Filtered transactions for active range
    filtered_transactions = transactions
    if start_date:
        filtered_transactions = filtered_transactions.filter(date__gte=start_date)
    if end_date:
        filtered_transactions = filtered_transactions.filter(date__lte=end_date)

    all_time_income = _sum_amount(
        transactions.filter(transaction_type=Transaction.TransactionType.INCOME)
    )
    all_time_expenses = _sum_amount(
        transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE)
    )
    all_time_balance = all_time_income - all_time_expenses

    period_income = _sum_amount(
        filtered_transactions.filter(transaction_type=Transaction.TransactionType.INCOME)
    )
    period_expenses = _sum_amount(
        filtered_transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE)
    )
    period_balance = period_income - period_expenses

    income = period_income if range_param != 'all' else all_time_income
    expenses = period_expenses if range_param != 'all' else all_time_expenses
    balance = period_balance if range_param != 'all' else all_time_balance
    tx_count = filtered_transactions.count() if range_param != 'all' else transactions.count()

    savings_rate = (
        round(float((balance / income) * 100), 1)
        if income > 0 else 0
    )

    month_expenses_qs = transactions.filter(
        transaction_type=Transaction.TransactionType.EXPENSE,
        date__gte=month_start,
        date__lt=next_month
    )

    month_expenses = _sum_amount(month_expenses_qs)

    previous_expenses = _sum_amount(
        transactions.filter(
            transaction_type=Transaction.TransactionType.EXPENSE,
            date__gte=previous_start,
            date__lt=previous_end
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

    budgets, budget_summary = _budget_statuses(
        request.user,
        this_month
    )

    spending_change = (
        round(
            float(
                ((month_expenses - previous_expenses)
                 / previous_expenses) * 100
            ),
            1
        )
        if previous_expenses else 0
    )

    insights = [
        {
            'title': 'Top spending category',
            'value': (
                highest_category['category__name']
                if highest_category else 'No spending yet'
            ),
            'detail': (
                f"₹{highest_category['total']:,.2f} in selected period"
                if highest_category
                else 'Record an expense to unlock this insight.'
            ),
        },
        {
            'title': 'Monthly spending',
            'value': f"₹{month_expenses:,.2f}",
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
            'value': (
                f"₹{(month_expenses / Decimal(max(today.day, 1))):,.2f}"
            ),
            'detail': 'Based on expenses recorded this month.',
        },
    ]

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
            'chart_data': _chart_data(transactions, category_source=filtered_transactions),
            'budget_summary': budget_summary,
            'budget_highlights': budgets[:3],
            'goals': SavingsGoal.objects.filter(
                owner=request.user
            ).order_by('target_date', 'created_at')[:3],
            'insights': insights,
            'current_month_label': today.strftime('%B %Y'),
            'active_range': range_param,
            'range_label': range_label,
            'custom_start': request.GET.get('start_date', ''),
            'custom_end': request.GET.get('end_date', ''),
        },
    )


# ---------------- TRANSACTIONS ----------------

@login_required
def transaction_list(request):
    transactions, filters = _transaction_filters(request)

    paginator = Paginator(transactions, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)

    accounts = Account.objects.filter(owner=request.user)

    return render(
        request,
        'expenses/transaction_list.html',
        {
            'page_obj': page_obj,
            'categories': Category.objects.all(),
            'accounts': accounts,
            'payment_methods': Transaction.PaymentMethod.choices,
            'transaction_types': Transaction.TransactionType.choices,
            'filters': filters,
            'querystring': query_params.urlencode(),
            'total_count': transactions.count(),
        },
    )


# ---------------- CATEGORIES ----------------

@login_required
def category_list(request):
    search = request.GET.get('q', '').strip()
    selected_type = request.GET.get('type', '')

    categories = Category.objects.annotate(
        transaction_count=Count(
            'transactions',
            filter=Q(transactions__owner=request.user)
        )
    )

    if search:
        categories = categories.filter(
            name__icontains=search
        )

    if selected_type in Category.TransactionType.values:
        categories = categories.filter(
            transaction_type=selected_type
        )

    income_categories = categories.filter(
        transaction_type='income'
    )

    expense_categories = categories.filter(
        transaction_type='expense'
    )

    context = {
        'categories': categories,
        'income_categories': income_categories,
        'expense_categories': expense_categories,
        'total_categories': Category.objects.count(),
        'income_count': Category.objects.filter(
            transaction_type='income'
        ).count(),
        'expense_count': Category.objects.filter(
            transaction_type='expense'
        ).count(),
        'total_transactions': Transaction.objects.filter(
            owner=request.user
        ).count(),
        'search': search,
        'selected_type': selected_type,
    }

    return render(
        request,
        'category_list.html',
        context
    )


@login_required
def transaction_create(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST, owner=request.user)

        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.owner = request.user
            transaction.save()

            _budget_warning(request, transaction)

            messages.success(
                request,
                'Transaction added successfully.'
            )

            return redirect('transaction_list')
    else:
        init_date = _parse_filter_date(request.GET.get('date', '')) or timezone.localdate()
        form = TransactionForm(
            initial={
                'date': init_date,
                'transaction_type': Transaction.TransactionType.EXPENSE
            },
            owner=request.user,
        )

    return render(
        request,
        'expenses/transaction_form.html',
        {
            'form': form,
            'page_title': 'Add transaction',
            'submit_label': 'Save transaction'
        }
    )


@login_required
def transaction_detail(request, pk):
    transaction = get_object_or_404(
        Transaction.objects.select_related('category', 'account'),
        pk=pk,
        owner=request.user
    )

    return render(
        request,
        'expenses/transaction_detail.html',
        {'transaction': transaction}
    )


@login_required
def transaction_update(request, pk):
    transaction = get_object_or_404(
        Transaction,
        pk=pk,
        owner=request.user
    )

    if request.method == 'POST':
        form = TransactionForm(
            request.POST,
            instance=transaction,
            owner=request.user,
        )

        if form.is_valid():
            transaction = form.save()
            _budget_warning(request, transaction)

            messages.success(
                request,
                'Transaction updated successfully.'
            )

            return redirect(
                'transaction_detail',
                pk=transaction.pk
            )
    else:
        form = TransactionForm(instance=transaction, owner=request.user)

    return render(
        request,
        'expenses/transaction_form.html',
        {
            'form': form,
            'page_title': 'Edit transaction',
            'submit_label': 'Save changes',
            'transaction': transaction
        }
    )


@login_required
def transaction_duplicate(request, pk):
    source = get_object_or_404(
        Transaction.objects.select_related('category', 'account'),
        pk=pk,
        owner=request.user,
    )
    if request.method == 'POST':
        form = TransactionForm(request.POST, owner=request.user)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.owner = request.user
            tx.save()
            _budget_warning(request, tx)
            messages.success(request, f'Duplicated transaction "{tx.title}" saved successfully.')
            return redirect('transaction_detail', pk=tx.pk)
    else:
        form = TransactionForm(
            initial={
                'title': f'{source.title} (Copy)',
                'transaction_type': source.transaction_type,
                'amount': source.amount,
                'category': source.category_id,
                'account': source.account_id,
                'payment_method': source.payment_method,
                'date': timezone.localdate(),
                'description': source.description,
            },
            owner=request.user,
        )

    return render(
        request,
        'expenses/transaction_form.html',
        {
            'form': form,
            'page_title': f'Duplicate: {source.title}',
            'submit_label': 'Save duplicated transaction',
            'transaction': source,
        },
    )


@login_required
@require_POST
def transaction_delete(request, pk):
    transaction = get_object_or_404(
        Transaction,
        pk=pk,
        owner=request.user
    )

    transaction.delete()

    messages.success(request, 'Transaction deleted.')

    return redirect('transaction_list')


@login_required
def transaction_export_csv(request):
    transactions, _ = _transaction_filters(request)

    response = HttpResponse(
        content_type='text/csv; charset=utf-8'
    )

    response['Content-Disposition'] = (
        'attachment; filename="ledgerly-transactions.csv"'
    )

    writer = csv.writer(response)

    writer.writerow([
        'title',
        'amount',
        'type',
        'category',
        'date',
        'description'
    ])

    for item in transactions:
        writer.writerow([
            item.title,
            item.amount,
            item.transaction_type,
            item.category.name,
            item.date.isoformat(),
            item.description
        ])

    return response


@login_required
def transaction_import_csv(request):
    if request.method == 'POST':
        form = TransactionImportForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():
            try:
                raw_csv = (
                    form.cleaned_data['csv_file']
                    .read()
                    .decode('utf-8-sig')
                )

                reader = csv.DictReader(StringIO(raw_csv))

                required = {
                    'title',
                    'amount',
                    'type',
                    'category',
                    'date'
                }

                field_names = {
                    (name or '').strip().lower()
                    for name in (reader.fieldnames or [])
                }

                if not required.issubset(field_names):
                    raise ValueError(
                        'Use a CSV with title, amount, type, category, and date columns.'
                    )

                errors = []
                pending = []

                for row_number, row in enumerate(reader, start=2):
                    normalized = {
                        (key or '').strip().lower(): (value or '').strip()
                        for key, value in row.items()
                    }

                    try:
                        transaction_type = normalized['type'].lower()

                        if transaction_type not in Transaction.TransactionType.values:
                            raise ValueError(
                                'type must be income or expense'
                            )

                        category = Category.objects.get(
                            name__iexact=normalized['category'],
                            transaction_type=transaction_type
                        )

                        candidate = Transaction(
                            owner=request.user,
                            title=normalized['title'],
                            amount=Decimal(normalized['amount']),
                            transaction_type=transaction_type,
                            category=category,
                            date=date.fromisoformat(normalized['date']),
                            description=normalized.get('description', ''),
                        )

                        candidate.full_clean()
                        pending.append(candidate)

                    except (
                        Category.DoesNotExist,
                        InvalidOperation,
                        KeyError,
                        ValueError
                    ) as exc:
                        errors.append(
                            f'Row {row_number}: {exc}'
                        )

                if errors:
                    for error in errors[:5]:
                        messages.error(request, error)

                    if len(errors) > 5:
                        messages.error(
                            request,
                            f'{len(errors) - 5} additional rows need correction.'
                        )

                else:
                    with db_transaction.atomic():
                        for candidate in pending:
                            candidate.save()

                    messages.success(
                        request,
                        f'Imported {len(pending)} transaction'
                        f'{"s" if len(pending) != 1 else ""}.'
                    )

                    return redirect('transaction_list')

            except UnicodeDecodeError:
                messages.error(
                    request,
                    'The file must use UTF-8 encoding.'
                )

            except (csv.Error, ValueError) as exc:
                messages.error(
                    request,
                    f'Unable to import this CSV: {exc}'
                )

    else:
        form = TransactionImportForm()

    return render(
        request,
        'expenses/transaction_import.html',
        {'form': form}
    )


# ---------------- BUDGETS ----------------

@login_required
def budget_list(request):
    requested_month = request.GET.get('month')

    try:
        selected_month = (
            date.fromisoformat(f'{requested_month}-01')
            if requested_month
            else timezone.localdate().replace(day=1)
        )
    except ValueError:
        selected_month = timezone.localdate().replace(day=1)

    budgets, summary = _budget_statuses(
        request.user,
        selected_month
    )

    today = timezone.localdate()
    days_in_month = py_calendar.monthrange(selected_month.year, selected_month.month)[1]
    is_current_month = (selected_month.year == today.year and selected_month.month == today.month)
    days_remaining = max(1, days_in_month - today.day + 1) if is_current_month else (days_in_month if selected_month > today else 0)

    for b in budgets:
        if days_remaining > 0 and b.remaining > 0:
            b.daily_allowance = round(b.remaining / Decimal(days_remaining), 2)
        else:
            b.daily_allowance = Decimal('0.00')

    return render(
        request,
        'expenses/budget_list.html',
        {
            'budgets': budgets,
            'summary': summary,
            'selected_month': selected_month,
            'days_remaining': days_remaining,
            'is_current_month': is_current_month,
        }
    )


@login_required
def budget_create(request):
    if request.method == 'POST':
        form = BudgetForm(
            request.POST,
            owner=request.user
        )

        form.instance.owner = request.user

        if form.is_valid():
            form.save()

            messages.success(
                request,
                'Budget saved successfully.'
            )

            return redirect('budget_list')
    else:
        form = BudgetForm(
            initial={
                'month': timezone.localdate().replace(day=1)
            }
        )

    return render(
        request,
        'expenses/management_form.html',
        {
            'form': form,
            'page_title': 'Set a budget',
            'submit_label': 'Save budget',
            'back_url': 'budget_list'
        }
    )


@login_required
def budget_update(request, pk):
    budget = get_object_or_404(
        Budget,
        pk=pk,
        owner=request.user
    )

    if request.method == 'POST':
        form = BudgetForm(
            request.POST,
            instance=budget,
            owner=request.user
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                'Budget updated successfully.'
            )

            return redirect('budget_list')
    else:
        form = BudgetForm(instance=budget)

    return render(
        request,
        'expenses/management_form.html',
        {
            'form': form,
            'page_title': 'Edit budget',
            'submit_label': 'Save changes',
            'back_url': 'budget_list'
        }
    )


@login_required
@require_POST
def budget_delete(request, pk):
    get_object_or_404(
        Budget,
        pk=pk,
        owner=request.user
    ).delete()

    messages.success(request, 'Budget deleted.')

    return redirect('budget_list')


# ---------------- SAVINGS GOALS ----------------

@login_required
def goal_list(request):
    goals = list(SavingsGoal.objects.filter(owner=request.user))
    total_target = sum((g.target_amount for g in goals), Decimal('0.00'))
    total_saved = sum((g.current_amount for g in goals), Decimal('0.00'))
    overall_progress = round(float((total_saved / total_target) * 100), 1) if total_target > 0 else 0
    completed_count = sum(1 for g in goals if g.is_complete)

    return render(
        request,
        'expenses/goal_list.html',
        {
            'goals': goals,
            'total_target': total_target,
            'total_saved': total_saved,
            'overall_progress': min(overall_progress, 100.0),
            'completed_count': completed_count,
            'goal_count': len(goals),
        },
    )


@require_POST
@login_required
def goal_deposit(request, pk):
    goal = get_object_or_404(SavingsGoal, pk=pk, owner=request.user)
    try:
        deposit_amount = Decimal(request.POST.get('amount', '0'))
        if deposit_amount <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        messages.error(request, 'Please enter a valid deposit amount greater than zero.')
        return redirect('goal_list')

    goal.current_amount += deposit_amount
    goal.save()
    messages.success(request, f'Added ₹{deposit_amount:,.2f} to savings goal "{goal.name}".')
    return redirect('goal_list')


@login_required
def goal_create(request):
    if request.method == 'POST':
        form = SavingsGoalForm(request.POST)

        if form.is_valid():
            goal = form.save(commit=False)
            goal.owner = request.user
            goal.save()

            messages.success(
                request,
                'Savings goal created.'
            )

            return redirect('goal_list')
    else:
        form = SavingsGoalForm()

    return render(
        request,
        'expenses/management_form.html',
        {
            'form': form,
            'page_title': 'Create a savings goal',
            'submit_label': 'Create goal',
            'back_url': 'goal_list'
        }
    )


@login_required
def goal_update(request, pk):
    goal = get_object_or_404(
        SavingsGoal,
        pk=pk,
        owner=request.user
    )

    if request.method == 'POST':
        form = SavingsGoalForm(
            request.POST,
            instance=goal
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                'Savings goal updated.'
            )

            return redirect('goal_list')
    else:
        form = SavingsGoalForm(instance=goal)

    return render(
        request,
        'expenses/management_form.html',
        {
            'form': form,
            'page_title': 'Update savings goal',
            'submit_label': 'Save changes',
            'back_url': 'goal_list'
        }
    )


@login_required
@require_POST
def goal_delete(request, pk):
    get_object_or_404(
        SavingsGoal,
        pk=pk,
        owner=request.user
    ).delete()

    messages.success(request, 'Savings goal deleted.')

    return redirect('goal_list')


# ---------------- RECURRING TRANSACTIONS ----------------

@login_required
def recurring_list(request):
    recurring_items = list(
        RecurringTransaction.objects
        .filter(owner=request.user)
        .select_related('category')
    )
    active_count = sum(1 for item in recurring_items if item.is_active)
    monthly_commitment = sum(
        (item.amount for item in recurring_items if item.is_active and item.transaction_type == Transaction.TransactionType.EXPENSE),
        Decimal('0.00'),
    )
    monthly_income = sum(
        (item.amount for item in recurring_items if item.is_active and item.transaction_type == Transaction.TransactionType.INCOME),
        Decimal('0.00'),
    )

    return render(
        request,
        'expenses/recurring_list.html',
        {
            'recurring_items': recurring_items,
            'active_count': active_count,
            'monthly_commitment': monthly_commitment,
            'monthly_income': monthly_income,
            'total_count': len(recurring_items),
        },
    )


@require_POST
@login_required
def recurring_toggle(request, pk):
    item = get_object_or_404(RecurringTransaction, pk=pk, owner=request.user)
    item.is_active = not item.is_active
    item.save(update_fields=['is_active', 'updated_at'])
    status_str = 'resumed' if item.is_active else 'paused'
    messages.success(request, f'Recurring schedule "{item.title}" {status_str}.')
    return redirect('recurring_list')


@login_required
def recurring_create(request):
    if request.method == 'POST':
        form = RecurringTransactionForm(request.POST)

        if form.is_valid():
            recurring = form.save(commit=False)
            recurring.owner = request.user
            recurring.next_run = recurring.start_date
            recurring.save()

            messages.success(
                request,
                'Recurring transaction scheduled.'
            )

            return redirect('recurring_list')
    else:
        form = RecurringTransactionForm(
            initial={
                'start_date': timezone.localdate(),
                'transaction_type': Transaction.TransactionType.EXPENSE
            }
        )

    return render(
        request,
        'expenses/management_form.html',
        {
            'form': form,
            'page_title': 'Schedule recurring transaction',
            'submit_label': 'Save schedule',
            'back_url': 'recurring_list'
        }
    )


@login_required
def recurring_update(request, pk):
    recurring = get_object_or_404(
        RecurringTransaction,
        pk=pk,
        owner=request.user
    )

    if request.method == 'POST':
        form = RecurringTransactionForm(
            request.POST,
            instance=recurring
        )

        if form.is_valid():
            recurring = form.save(commit=False)

            if not recurring.last_generated:
                recurring.next_run = recurring.start_date

            recurring.save()

            messages.success(
                request,
                'Recurring schedule updated.'
            )

            return redirect('recurring_list')
    else:
        form = RecurringTransactionForm(
            instance=recurring
        )

    return render(
        request,
        'expenses/management_form.html',
        {
            'form': form,
            'page_title': 'Edit recurring transaction',
            'submit_label': 'Save changes',
            'back_url': 'recurring_list'
        }
    )


@login_required
@require_POST
def recurring_delete(request, pk):
    get_object_or_404(
        RecurringTransaction,
        pk=pk,
        owner=request.user
    ).delete()

    messages.success(
        request,
        'Recurring schedule deleted.'
    )

    return redirect('recurring_list')


@login_required
@require_POST
def recurring_run(request):
    generated = sum(
        item.generate_due_transactions()
        for item in RecurringTransaction.objects.filter(
            owner=request.user,
            is_active=True
        )
    )

    messages.success(
        request,
        f'Generated {generated} due transaction'
        f'{"s" if generated != 1 else ""}.'
    )

    return redirect('recurring_list')


# ---------------- REPORTS ----------------

def _report_metrics(user):
    transactions = Transaction.objects.filter(
        owner=user
    ).select_related('category')

    today = timezone.localdate()
    year_start = date(today.year, 1, 1)

    income = _sum_amount(
        transactions.filter(
            transaction_type=Transaction.TransactionType.INCOME
        )
    )

    expenses = _sum_amount(
        transactions.filter(
            transaction_type=Transaction.TransactionType.EXPENSE
        )
    )

    year_income = _sum_amount(
        transactions.filter(
            transaction_type=Transaction.TransactionType.INCOME,
            date__gte=year_start
        )
    )

    year_expenses = _sum_amount(
        transactions.filter(
            transaction_type=Transaction.TransactionType.EXPENSE,
            date__gte=year_start
        )
    )

    return transactions, {
        'income': income,
        'expenses': expenses,
        'balance': income - expenses,
        'transaction_count': transactions.count(),
        'year_income': year_income,
        'year_expenses': year_expenses,
        'year_balance': year_income - year_expenses,
        'savings_rate': (
            round(float(((income - expenses) / income) * 100), 1)
            if income else 0
        ),
    }


@login_required
def reports(request):
    transactions, metrics = _report_metrics(request.user)

    _, budget_summary = _budget_statuses(
        request.user,
        timezone.localdate().replace(day=1)
    )

    top_categories = list(
        transactions.filter(
            transaction_type=Transaction.TransactionType.EXPENSE
        )
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:7]
    )

    total_exp = metrics['expenses']
    for cat in top_categories:
        cat['percentage'] = round(float((cat['total'] / total_exp) * 100), 1) if total_exp > 0 else 0

    account_breakdown = list(
        transactions.filter(
            transaction_type=Transaction.TransactionType.EXPENSE,
            account__isnull=False,
        )
        .values('account__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    return render(
        request,
        'expenses/reports.html',
        {
            **metrics,
            'chart_data': _chart_data(
                transactions,
                months=12
            ),
            'budget_summary': budget_summary,
            'top_categories': top_categories,
            'account_breakdown': account_breakdown,
            'current_year': timezone.localdate().year,
        },
    )


@login_required
def financial_report_pdf(request):
    """Stream an owner-scoped financial PDF without creating server-side files."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    transactions, metrics = _report_metrics(request.user)

    top_categories = (
        transactions.filter(
            transaction_type=Transaction.TransactionType.EXPENSE
        )
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:7]
    )

    response = HttpResponse(
        content_type='application/pdf'
    )

    response['Content-Disposition'] = (
        'attachment; filename="ledgerly-financial-report.pdf"'
    )

    pdf = canvas.Canvas(response, pagesize=A4)

    width, height = A4

    pdf.setTitle('Ledgerly Financial Report')

    pdf.setFillColor(
        colors.HexColor('#101A33')
    )

    pdf.rect(
        0,
        height - 92,
        width,
        92,
        stroke=0,
        fill=1
    )

    pdf.setFillColor(colors.white)
    pdf.setFont('Helvetica-Bold', 20)

    pdf.drawString(
        42,
        height - 52,
        'Ledgerly Financial Report'
    )

    pdf.setFont('Helvetica', 9)

    pdf.drawString(
        42,
        height - 70,
        f'Prepared for {request.user.get_full_name() or request.user.username} - {timezone.localdate():%d %b %Y}'
    )

    pdf.setFillColor(
        colors.HexColor('#182238')
    )

    pdf.setFont('Helvetica-Bold', 12)

    pdf.drawString(
        42,
        height - 125,
        'Financial overview'
    )

    overview = [
        ('Total income', metrics['income']),
        ('Total expenses', metrics['expenses']),
        ('Net balance', metrics['balance']),
        ('Savings rate', f"{metrics['savings_rate']:.1f}%"),
    ]

    y = height - 153

    for label, value in overview:
        pdf.setFillColor(
            colors.HexColor('#F5F7FC')
        )

        pdf.roundRect(
            42,
            y - 28,
            250,
            38,
            5,
            stroke=0,
            fill=1
        )

        pdf.setFillColor(
            colors.HexColor('#66738A')
        )

        pdf.setFont('Helvetica', 8)

        pdf.drawString(
            54,
            y - 5,
            label.upper()
        )

        pdf.setFillColor(
            colors.HexColor('#182238')
        )

        pdf.setFont('Helvetica-Bold', 12)

        formatted = (
            value
            if isinstance(value, str)
            else f'INR {value:,.2f}'
        )

        pdf.drawRightString(
            280,
            y - 5,
            formatted
        )

        y -= 47

    pdf.setFont('Helvetica-Bold', 12)

    pdf.drawString(
        330,
        height - 125,
        'Top expense categories'
    )

    y = height - 153

    if top_categories:
        for item in top_categories:
            pdf.setStrokeColor(
                colors.HexColor('#E8ECF3')
            )

            pdf.line(
                330,
                y - 14,
                width - 42,
                y - 14
            )

            pdf.setFillColor(
                colors.HexColor('#182238')
            )

            pdf.setFont('Helvetica', 9)

            pdf.drawString(
                330,
                y,
                item['category__name']
            )

            pdf.setFont('Helvetica-Bold', 9)

            pdf.drawRightString(
                width - 42,
                y,
                f"INR {item['total']:,.2f}"
            )

            y -= 28
    else:
        pdf.setFont('Helvetica', 9)

        pdf.setFillColor(
            colors.HexColor('#66738A')
        )

        pdf.drawString(
            330,
            y,
            'No expense data recorded yet.'
        )

    pdf.setFillColor(
        colors.HexColor('#182238')
    )

    pdf.setFont('Helvetica-Bold', 12)

    pdf.drawString(
        42,
        305,
        'Recent transactions'
    )

    y = 280

    for item in transactions[:7]:
        pdf.setStrokeColor(
            colors.HexColor('#E8ECF3')
        )

        pdf.line(
            42,
            y - 14,
            width - 42,
            y - 14
        )

        pdf.setFillColor(
            colors.HexColor('#182238')
        )

        pdf.setFont('Helvetica', 9)

        pdf.drawString(
            42,
            y,
            item.title[:42]
        )

        pdf.setFillColor(
            colors.HexColor('#66738A')
        )

        pdf.drawString(
            245,
            y,
            item.date.strftime('%d %b %Y')
        )

        pdf.setFillColor(
            colors.HexColor(
                '#16A779'
                if item.transaction_type == 'income'
                else '#EF6262'
            )
        )

        pdf.setFont('Helvetica-Bold', 9)

        sign = (
            '+'
            if item.transaction_type == 'income'
            else '-'
        )

        pdf.drawRightString(
            width - 42,
            y,
            f'{sign} INR {item.amount:,.2f}'
        )

        y -= 25

    pdf.setStrokeColor(
        colors.HexColor('#E8ECF3')
    )

    pdf.line(
        42,
        55,
        width - 42,
        55
    )

    pdf.setFillColor(
        colors.HexColor('#66738A')
    )

    pdf.setFont('Helvetica', 8)

    pdf.drawString(
        42,
        38,
        'Generated by Ledgerly - your personal finance workspace'
    )

    pdf.drawRightString(
        width - 42,
        38,
        'Page 1 of 1'
    )

    pdf.showPage()
    pdf.save()

    return response


@login_required
def transaction_calendar(request):
    """Interactive monthly transaction calendar view with daily summaries."""
    today = timezone.localdate()

    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if not (1 <= month <= 12):
            year, month = today.year, today.month
    except (ValueError, TypeError):
        year, month = today.year, today.month

    current_month_date = date(year, month, 1)
    month_start, next_month = _month_range(current_month_date)
    prev_month_date = _month_start(year, month, -1)
    next_month_date = _month_start(year, month, 1)

    # All user transactions for this month
    month_transactions = Transaction.objects.filter(
        owner=request.user,
        date__gte=month_start,
        date__lt=next_month,
    ).select_related('category', 'account')

    # Aggregate by day
    daily_data = {}
    for tx in month_transactions:
        d = tx.date.day
        if d not in daily_data:
            daily_data[d] = {
                'income': Decimal('0.00'),
                'expense': Decimal('0.00'),
                'count': 0,
                'transactions': [],
            }
        if tx.transaction_type == Transaction.TransactionType.INCOME:
            daily_data[d]['income'] += tx.amount
        else:
            daily_data[d]['expense'] += tx.amount
        daily_data[d]['count'] += 1
        daily_data[d]['transactions'].append(tx)

    # Monthly totals
    month_income = sum((item['income'] for item in daily_data.values()), Decimal('0.00'))
    month_expense = sum((item['expense'] for item in daily_data.values()), Decimal('0.00'))
    month_net = month_income - month_expense

    # Generate weeks and days
    cal = py_calendar.Calendar(firstweekday=0)
    month_matrix = []
    for week in cal.monthdatescalendar(year, month):
        week_data = []
        for d in week:
            is_current_month = (d.month == month)
            day_stats = daily_data.get(d.day) if is_current_month else None
            net = (day_stats['income'] - day_stats['expense']) if day_stats else Decimal('0.00')
            week_data.append({
                'date': d,
                'day': d.day,
                'is_current_month': is_current_month,
                'is_today': (d == today),
                'income': day_stats['income'] if day_stats else Decimal('0.00'),
                'expense': day_stats['expense'] if day_stats else Decimal('0.00'),
                'net': net,
                'count': day_stats['count'] if day_stats else 0,
            })
        month_matrix.append(week_data)

    # Selected day details
    selected_date_str = request.GET.get('date', '')
    selected_date = _parse_filter_date(selected_date_str)
    if not selected_date or selected_date.month != month or selected_date.year != year:
        selected_date = today if (today.year == year and today.month == month) else month_start

    selected_day_transactions = month_transactions.filter(date=selected_date)
    selected_day_income = _sum_amount(selected_day_transactions.filter(transaction_type=Transaction.TransactionType.INCOME))
    selected_day_expense = _sum_amount(selected_day_transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE))
    selected_day_net = selected_day_income - selected_day_expense

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
            'month_matrix': month_matrix,
            'month_income': month_income,
            'month_expense': month_expense,
            'month_net': month_net,
            'selected_date': selected_date,
            'selected_day_transactions': selected_day_transactions,
            'selected_day_income': selected_day_income,
            'selected_day_expense': selected_day_expense,
            'selected_day_net': selected_day_net,
        },
    )


@login_required
def account_list(request):
    """Financial accounts and wallets overview."""
    accounts = Account.objects.filter(owner=request.user).annotate(
        tx_count=Count('transactions')
    )
    total_balance = sum((a.balance for a in accounts), Decimal('0.00'))
    return render(
        request,
        'expenses/account_list.html',
        {
            'accounts': accounts,
            'total_balance': total_balance,
            'account_count': accounts.count(),
        },
    )


@login_required
def account_create(request):
    if request.method == 'POST':
        form = AccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.owner = request.user
            account.save()
            messages.success(request, f'Account "{account.name}" created successfully.')
            return redirect('account_list')
    else:
        form = AccountForm()

    return render(
        request,
        'expenses/management_form.html',
        {
            'form': form,
            'page_title': 'Add Account / Wallet',
            'submit_label': 'Save Account',
            'back_url': 'account_list',
        },
    )


@login_required
def account_update(request, pk):
    account = get_object_or_404(Account, pk=pk, owner=request.user)
    if request.method == 'POST':
        form = AccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, f'Account "{account.name}" updated.')
            return redirect('account_list')
    else:
        form = AccountForm(instance=account)

    return render(
        request,
        'expenses/management_form.html',
        {
            'form': form,
            'page_title': f'Edit Account: {account.name}',
            'submit_label': 'Update Account',
            'back_url': 'account_list',
        },
    )


@require_POST
@login_required
def account_delete(request, pk):
    account = get_object_or_404(Account, pk=pk, owner=request.user)
    name = account.name
    account.delete()
    messages.success(request, f'Account "{name}" deleted.')
    return redirect('account_list')


@login_required
def settings_view(request):
    """Multi-tab user, application, and data security settings."""
    user = request.user
    user_settings, _ = UserSettings.objects.get_or_create(user=user)

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
                app_settings_form.save()
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
        },
    )


@login_required
def data_export_json(request):
    """Safely export all of a user's data as a downloadable JSON file."""
    user = request.user
    txs = [
        {
            'title': t.title,
            'amount': str(t.amount),
            'type': t.transaction_type,
            'category': t.category.name,
            'account': t.account.name if t.account else None,
            'payment_method': t.payment_method,
            'date': t.date.isoformat(),
            'description': t.description,
            'created_at': t.created_at.isoformat(),
        }
        for t in Transaction.objects.filter(owner=user).select_related('category', 'account')
    ]
    accounts = [
        {
            'name': a.name,
            'type': a.account_type,
            'balance': str(a.balance),
            'currency': a.currency,
        }
        for a in Account.objects.filter(owner=user)
    ]
    budgets = [
        {
            'category': b.category.name,
            'month': b.month.isoformat(),
            'amount': str(b.amount),
        }
        for b in Budget.objects.filter(owner=user).select_related('category')
    ]
    goals = [
        {
            'name': g.name,
            'target_amount': str(g.target_amount),
            'current_amount': str(g.current_amount),
            'target_date': g.target_date.isoformat() if g.target_date else None,
        }
        for g in SavingsGoal.objects.filter(owner=user)
    ]

    export_payload = {
        'ledgerly_export_version': '1.0',
        'generated_at': timezone.now().isoformat(),
        'user': {
            'username': user.username,
            'email': user.email,
        },
        'accounts': accounts,
        'transactions': txs,
        'budgets': budgets,
        'savings_goals': goals,
    }

    response = HttpResponse(
        json.dumps(export_payload, indent=2),
        content_type='application/json',
    )
    response['Content-Disposition'] = f'attachment; filename="ledgerly-export-{user.username}-{timezone.localdate().isoformat()}.json"'
    return response


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

