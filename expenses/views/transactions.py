import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import TransactionForm, TransactionImportForm
from ..models import Account, Category, Transaction
from ..services import (
    budget_warning,
    export_transactions_csv,
    import_transactions_csv,
    parse_filter_date,
    sync_transaction_account_create,
    sync_transaction_account_delete,
    sync_transaction_account_update,
    transaction_filters,
)


@login_required
def transaction_list(request):
    transactions, filters = transaction_filters(request)

    paginator = Paginator(transactions, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)

    return render(
        request,
        'expenses/transaction_list.html',
        {
            'page_obj': page_obj,
            'categories': Category.objects.all(),
            'accounts': Account.objects.filter(owner=request.user),
            'payment_methods': Transaction.PaymentMethod.choices,
            'transaction_types': Transaction.TransactionType.choices,
            'filters': filters,
            'querystring': query_params.urlencode(),
            'total_count': paginator.count,
        },
    )


@login_required
def category_list(request):
    search = request.GET.get('q', '').strip()
    selected_type = request.GET.get('type', '')

    categories = Category.objects.annotate(
        transaction_count=Count('transactions', filter=Q(transactions__owner=request.user))
    )
    if search:
        categories = categories.filter(name__icontains=search)
    if selected_type in Category.TransactionType.values:
        categories = categories.filter(transaction_type=selected_type)

    return render(
        request,
        'expenses/category_list.html',
        {
            'categories': categories,
            'income_categories': categories.filter(transaction_type='income'),
            'expense_categories': categories.filter(transaction_type='expense'),
            'total_categories': Category.objects.count(),
            'income_count': Category.objects.filter(transaction_type='income').count(),
            'expense_count': Category.objects.filter(transaction_type='expense').count(),
            'total_transactions': Transaction.objects.filter(owner=request.user).count(),
            'search': search,
            'selected_type': selected_type,
        },
    )


def _save_new_transaction(request, form):
    """Persist a new transaction, sync its linked account balance, and check budget thresholds."""
    with db_transaction.atomic():
        tx = form.save(commit=False)
        tx.owner = request.user
        tx.save()
        sync_transaction_account_create(tx)
    budget_warning(request, tx)
    return tx


@login_required
def transaction_create(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST, owner=request.user)
        if form.is_valid():
            _save_new_transaction(request, form)
            messages.success(request, 'Transaction added successfully.')
            return redirect('transaction_list')
    else:
        init_date = parse_filter_date(request.GET.get('date', '')) or timezone.localdate()
        form = TransactionForm(
            initial={'date': init_date, 'transaction_type': Transaction.TransactionType.EXPENSE},
            owner=request.user,
        )

    return render(
        request,
        'expenses/transaction_form.html',
        {'form': form, 'page_title': 'Add transaction', 'submit_label': 'Save transaction'},
    )


@login_required
def transaction_detail(request, pk):
    transaction = get_object_or_404(
        Transaction.objects.select_related('category', 'account'),
        pk=pk,
        owner=request.user,
    )
    return render(request, 'expenses/transaction_detail.html', {'transaction': transaction})


@login_required
def transaction_update(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, owner=request.user)

    if request.method == 'POST':
        old_account_id = transaction.account_id
        old_type = transaction.transaction_type
        old_amount = transaction.amount

        form = TransactionForm(request.POST, instance=transaction, owner=request.user)
        if form.is_valid():
            with db_transaction.atomic():
                transaction = form.save()
                sync_transaction_account_update(old_account_id, old_type, old_amount, transaction)
            budget_warning(request, transaction)
            messages.success(request, 'Transaction updated successfully.')
            return redirect('transaction_detail', pk=transaction.pk)
    else:
        form = TransactionForm(instance=transaction, owner=request.user)

    return render(
        request,
        'expenses/transaction_form.html',
        {
            'form': form,
            'page_title': 'Edit transaction',
            'submit_label': 'Save changes',
            'transaction': transaction,
        },
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
            tx = _save_new_transaction(request, form)
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
    transaction = get_object_or_404(Transaction, pk=pk, owner=request.user)
    with db_transaction.atomic():
        sync_transaction_account_delete(transaction)
        transaction.delete()
    messages.success(request, 'Transaction deleted.')
    return redirect('transaction_list')


@login_required
def transaction_export_csv(request):
    transactions, _ = transaction_filters(request)
    return export_transactions_csv(transactions)


@login_required
def transaction_import_csv(request):
    if request.method == 'POST':
        form = TransactionImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                count, errors = import_transactions_csv(request.user, form.cleaned_data['csv_file'])
                if errors:
                    for error in errors[:5]:
                        messages.error(request, error)
                    if len(errors) > 5:
                        messages.error(request, f'{len(errors) - 5} additional rows need correction.')
                else:
                    messages.success(request, f'Imported {count} transaction{"s" if count != 1 else ""}.')
                    return redirect('transaction_list')
            except UnicodeDecodeError:
                messages.error(request, 'The file must use UTF-8 encoding.')
            except (csv.Error, ValueError) as exc:
                messages.error(request, f'Unable to import this CSV: {exc}')
    else:
        form = TransactionImportForm()

    return render(request, 'expenses/transaction_import.html', {'form': form})
