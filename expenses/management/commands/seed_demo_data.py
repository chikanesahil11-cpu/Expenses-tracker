from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from expenses.models import Category, Transaction


def _month_date(months_ago, day):
    today = timezone.localdate()
    month_index = today.month - 1 - months_ago
    year = today.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day, 28))


class Command(BaseCommand):
    help = 'Add idempotent, fictional INR transactions to one explicitly selected user.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True, help='Existing user who will receive demo records.')

    def handle(self, *args, **options):
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=options['username'])
        except user_model.DoesNotExist as exc:
            raise CommandError('No user exists with that username.') from exc

        categories = {}
        for name, transaction_type in (
            ('Salary', 'income'), ('Freelance', 'income'), ('Rent', 'expense'),
            ('Groceries', 'expense'), ('Dining', 'expense'), ('Transport', 'expense'),
            ('Utilities', 'expense'), ('Healthcare', 'expense'), ('Entertainment', 'expense'),
        ):
            categories[name], _ = Category.objects.get_or_create(name=name, transaction_type=transaction_type)

        templates = (
            ('Monthly salary', '52000.00', 'income', 'Salary', 2),
            ('Freelance design project', '8500.00', 'income', 'Freelance', 18),
            ('Apartment rent', '16500.00', 'expense', 'Rent', 5),
            ('BigBasket groceries', '3650.00', 'expense', 'Groceries', 9),
            ('Metro and cab rides', '1450.00', 'expense', 'Transport', 13),
            ('Electricity and internet', '2200.00', 'expense', 'Utilities', 16),
            ('Weekend dining', '1850.00', 'expense', 'Dining', 21),
            ('OTT and entertainment', '799.00', 'expense', 'Entertainment', 24),
            ('Pharmacy essentials', '620.00', 'expense', 'Healthcare', 26),
        )
        created = 0
        for months_ago in range(6):
            for title, amount, transaction_type, category_name, day in templates:
                transaction_date = _month_date(months_ago, day)
                _, was_created = Transaction.objects.get_or_create(
                    owner=user,
                    title=title,
                    date=transaction_date,
                    defaults={
                        'amount': Decimal(amount),
                        'transaction_type': transaction_type,
                        'category': categories[category_name],
                        'description': 'Fictional Ledgerly demo record.',
                    },
                )
                created += int(was_created)

        self.stdout.write(self.style.SUCCESS(
            f'Added {created} fictional INR transaction(s) for {user.username}. Existing records were not changed.'
        ))
