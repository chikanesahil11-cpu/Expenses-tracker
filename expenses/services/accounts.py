from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone

from ..models import Account, Transaction


def _signed_delta(transaction_type, amount, reverse=False):
    delta = Decimal(amount) if transaction_type == Transaction.TransactionType.INCOME else -Decimal(amount)
    return -delta if reverse else delta


def apply_account_delta(account_id, transaction_type, amount, reverse=False):
    """Atomically adjust an Account balance by a transaction's signed effect."""
    if not account_id or amount is None:
        return
    delta = _signed_delta(transaction_type, amount, reverse=reverse)
    Account.objects.filter(pk=account_id).update(
        balance=F('balance') + delta,
        updated_at=timezone.now(),
    )


def sync_transaction_account_create(tx):
    """Apply a newly created transaction's balance effect to its linked account."""
    if tx.account_id:
        with db_transaction.atomic():
            apply_account_delta(tx.account_id, tx.transaction_type, tx.amount)


def sync_transaction_account_update(old_account_id, old_type, old_amount, new_tx):
    """Reverse the previous account effect and apply the updated transaction effect."""
    if (
        old_account_id == new_tx.account_id
        and old_type == new_tx.transaction_type
        and old_amount == new_tx.amount
    ):
        return

    with db_transaction.atomic():
        if old_account_id:
            apply_account_delta(old_account_id, old_type, old_amount, reverse=True)
        if new_tx.account_id:
            apply_account_delta(new_tx.account_id, new_tx.transaction_type, new_tx.amount)


def sync_transaction_account_delete(tx):
    """Reverse a deleted transaction's balance effect from its linked account."""
    if tx.account_id:
        with db_transaction.atomic():
            apply_account_delta(tx.account_id, tx.transaction_type, tx.amount, reverse=True)
