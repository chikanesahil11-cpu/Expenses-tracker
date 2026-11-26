import calendar as py_calendar
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..context_processors import get_user_settings
from ..forms import (
    AccountForm,
    BudgetForm,
    RecurringTransactionForm,
    SavingsGoalForm,
)
from ..models import (
    Account,
    Budget,
    RecurringTransaction,
    SavingsGoal,
    Transaction,
)
from ..services import budget_statuses, build_user_json_export


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

    budgets, summary = budget_statuses(request.user, selected_month)

    today = timezone.localdate()
    days_in_month = py_calendar.monthrange(selected_month.year, selected_month.month)[1]
    is_current_month = selected_month.year == today.year and selected_month.month == today.month
    days_remaining = (
        max(1, days_in_month - today.day + 1)
        if is_current_month
        else (days_in_month if selected_month > today else 0)
    )

    for b in budgets:
        b.daily_allowance = (
            round(b.remaining / Decimal(days_remaining), 2)
            if days_remaining > 0 and b.remaining > 0
            else Decimal('0.00')
        )

    return render(
        request,
        'expenses/budget_list.html',
        {
            'budgets': budgets,
            'summary': summary,
            'selected_month': selected_month,
            'days_remaining': days_remaining,
            'is_current_month': is_current_month,
        },
    )


@login_required
def budget_create(request):
    if request.method == 'POST':
        form = BudgetForm(request.POST, owner=request.user)
        form.instance.owner = request.user
        if form.is_valid():
            form.save()
            messages.success(request, 'Budget saved successfully.')
            return redirect('budget_list')
    else:
        form = BudgetForm(initial={'month': timezone.localdate().replace(day=1)}, owner=request.user)

    return render(
        request,
        'expenses/management_form.html',
        {'form': form, 'page_title': 'Set a budget', 'submit_label': 'Save budget', 'back_url': 'budget_list'},
    )


@login_required
def budget_update(request, pk):
    budget = get_object_or_404(Budget, pk=pk, owner=request.user)
    if request.method == 'POST':
        form = BudgetForm(request.POST, instance=budget, owner=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Budget updated successfully.')
            return redirect('budget_list')
    else:
        form = BudgetForm(instance=budget, owner=request.user)

    return render(
        request,
        'expenses/management_form.html',
        {'form': form, 'page_title': 'Edit budget', 'submit_label': 'Save changes', 'back_url': 'budget_list'},
    )


@login_required
@require_POST
def budget_delete(request, pk):
    get_object_or_404(Budget, pk=pk, owner=request.user).delete()
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

    symbol = get_user_settings(request).currency_symbol
    goal.current_amount += deposit_amount
    goal.save()
    messages.success(request, f'Added {symbol}{deposit_amount:,.2f} to savings goal "{goal.name}".')
    return redirect('goal_list')


@login_required
def goal_create(request):
    if request.method == 'POST':
        form = SavingsGoalForm(request.POST)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.owner = request.user
            goal.save()
            messages.success(request, 'Savings goal created.')
            return redirect('goal_list')
    else:
        form = SavingsGoalForm()

    return render(
        request,
        'expenses/management_form.html',
        {'form': form, 'page_title': 'Create a savings goal', 'submit_label': 'Create goal', 'back_url': 'goal_list'},
    )


@login_required
def goal_update(request, pk):
    goal = get_object_or_404(SavingsGoal, pk=pk, owner=request.user)
    if request.method == 'POST':
        form = SavingsGoalForm(request.POST, instance=goal)
        if form.is_valid():
            form.save()
            messages.success(request, 'Savings goal updated.')
            return redirect('goal_list')
    else:
        form = SavingsGoalForm(instance=goal)

    return render(
        request,
        'expenses/management_form.html',
        {'form': form, 'page_title': 'Update savings goal', 'submit_label': 'Save changes', 'back_url': 'goal_list'},
    )


@login_required
@require_POST
def goal_delete(request, pk):
    get_object_or_404(SavingsGoal, pk=pk, owner=request.user).delete()
    messages.success(request, 'Savings goal deleted.')
    return redirect('goal_list')


# ---------------- RECURRING TRANSACTIONS ----------------

@login_required
def recurring_list(request):
    recurring_items = list(
        RecurringTransaction.objects.filter(owner=request.user).select_related('category')
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
            messages.success(request, 'Recurring transaction scheduled.')
            return redirect('recurring_list')
    else:
        form = RecurringTransactionForm(
            initial={'start_date': timezone.localdate(), 'transaction_type': Transaction.TransactionType.EXPENSE}
        )

    return render(
        request,
        'expenses/management_form.html',
        {'form': form, 'page_title': 'Schedule recurring transaction', 'submit_label': 'Save schedule', 'back_url': 'recurring_list'},
    )


@login_required
def recurring_update(request, pk):
    recurring = get_object_or_404(RecurringTransaction, pk=pk, owner=request.user)
    if request.method == 'POST':
        form = RecurringTransactionForm(request.POST, instance=recurring)
        if form.is_valid():
            recurring = form.save(commit=False)
            if not recurring.last_generated:
                recurring.next_run = recurring.start_date
            recurring.save()
            messages.success(request, 'Recurring schedule updated.')
            return redirect('recurring_list')
    else:
        form = RecurringTransactionForm(instance=recurring)

    return render(
        request,
        'expenses/management_form.html',
        {'form': form, 'page_title': 'Edit recurring transaction', 'submit_label': 'Save changes', 'back_url': 'recurring_list'},
    )


@login_required
@require_POST
def recurring_delete(request, pk):
    get_object_or_404(RecurringTransaction, pk=pk, owner=request.user).delete()
    messages.success(request, 'Recurring schedule deleted.')
    return redirect('recurring_list')


@login_required
@require_POST
def recurring_run(request):
    generated = sum(
        item.generate_due_transactions()
        for item in RecurringTransaction.objects.filter(owner=request.user, is_active=True)
    )
    messages.success(request, f'Generated {generated} due transaction{"s" if generated != 1 else ""}.')
    return redirect('recurring_list')


# ---------------- ACCOUNTS ----------------

@login_required
def account_list(request):
    """Financial accounts and wallets overview."""
    accounts = Account.objects.filter(owner=request.user).annotate(tx_count=Count('transactions'))
    total_balance = sum((a.balance for a in accounts), Decimal('0.00'))
    return render(
        request,
        'expenses/account_list.html',
        {'accounts': accounts, 'total_balance': total_balance, 'account_count': accounts.count()},
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
        {'form': form, 'page_title': 'Add Account / Wallet', 'submit_label': 'Save Account', 'back_url': 'account_list'},
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
        {'form': form, 'page_title': f'Edit Account: {account.name}', 'submit_label': 'Update Account', 'back_url': 'account_list'},
    )


@require_POST
@login_required
def account_delete(request, pk):
    account = get_object_or_404(Account, pk=pk, owner=request.user)
    name = account.name
    account.delete()
    messages.success(request, f'Account "{name}" deleted.')
    return redirect('account_list')


# ---------------- DATA EXPORT ----------------

@login_required
def data_export_json(request):
    """Safely export all of a user's data as a downloadable JSON file."""
    return build_user_json_export(request.user)
