from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Category(models.Model):
    class TransactionType(models.TextChoices):
        INCOME = 'income', 'Income'
        EXPENSE = 'expense', 'Expense'

    name = models.CharField(max_length=50)
    transaction_type = models.CharField(max_length=7, choices=TransactionType.choices)

    class Meta:
        ordering = ['transaction_type', 'name']
        verbose_name_plural = 'categories'
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'transaction_type'], name='unique_category_per_type'
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.get_transaction_type_display()})'


class Account(models.Model):
    class AccountType(models.TextChoices):
        BANK = 'bank', 'Bank Account'
        CASH = 'cash', 'Cash Wallet'
        CREDIT = 'credit', 'Credit Card'
        SAVINGS = 'savings', 'Savings'
        INVESTMENT = 'investment', 'Investment'
        OTHER = 'other', 'Other'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='accounts'
    )
    name = models.CharField(max_length=60)
    account_type = models.CharField(max_length=20, choices=AccountType.choices, default=AccountType.BANK)
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    currency = models.CharField(max_length=10, default='INR')
    color = models.CharField(max_length=20, default='#10b981')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'name'], name='unique_account_per_owner'
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.get_account_type_display()})'


class Transaction(models.Model):
    class TransactionType(models.TextChoices):
        INCOME = 'income', 'Income'
        EXPENSE = 'expense', 'Expense'

    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        BANK_TRANSFER = 'bank_transfer', 'Bank Transfer'
        CREDIT_CARD = 'credit_card', 'Credit Card'
        DEBIT_CARD = 'debit_card', 'Debit Card'
        UPI = 'upi', 'UPI / Online'
        OTHER = 'other', 'Other'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transactions'
    )
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    transaction_type = models.CharField(max_length=7, choices=TransactionType.choices)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='transactions')
    account = models.ForeignKey(
        Account, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions'
    )
    payment_method = models.CharField(
        max_length=30, blank=True, choices=PaymentMethod.choices
    )
    recurring_source = models.ForeignKey(
        'RecurringTransaction',
        on_delete=models.SET_NULL,
        related_name='generated_transactions',
        null=True,
        blank=True,
        editable=False,
    )
    date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['owner', '-date']),
            models.Index(fields=['owner', 'transaction_type']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'recurring_source', 'date'],
                condition=models.Q(recurring_source__isnull=False),
                name='unique_recurring_transaction_per_day',
            )
        ]

    def clean(self):
        super().clean()
        if self.category_id and self.transaction_type:
            if self.category.transaction_type != self.transaction_type:
                raise ValidationError({'category': 'Choose a category that matches the transaction type.'})

    def __str__(self):
        return f'{self.title} — {self.amount}'


class Budget(models.Model):
    """A category-level spending limit for a specific calendar month."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='budgets'
    )
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='budgets')
    month = models.DateField(help_text='Use any day in the month; it will be saved as the first day.')
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-month', 'category__name']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'category', 'month'], name='unique_budget_per_category_month'
            )
        ]
        indexes = [models.Index(fields=['owner', 'month'])]

    def clean(self):
        super().clean()
        if self.category_id and self.category.transaction_type != Category.TransactionType.EXPENSE:
            raise ValidationError({'category': 'Budgets can only be set for expense categories.'})
        if self.month:
            self.month = self.month.replace(day=1)

    def __str__(self):
        return f'{self.category.name} budget - {self.month:%b %Y}'


class SavingsGoal(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='savings_goals'
    )
    name = models.CharField(max_length=100)
    target_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    current_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))]
    )
    target_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['target_date', 'created_at']

    @property
    def progress_percentage(self):
        if not self.target_amount:
            return 0
        return min(100, round(float((self.current_amount / self.target_amount) * 100), 1))

    @property
    def is_complete(self):
        return self.current_amount >= self.target_amount

    @property
    def remaining_amount(self):
        return max(Decimal('0.00'), self.target_amount - self.current_amount)

    def __str__(self):
        return self.name


class RecurringTransaction(models.Model):
    class Frequency(models.TextChoices):
        WEEKLY = 'weekly', 'Weekly'
        MONTHLY = 'monthly', 'Monthly'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='recurring_transactions'
    )
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    transaction_type = models.CharField(max_length=7, choices=Transaction.TransactionType.choices)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='recurring_transactions')
    frequency = models.CharField(max_length=7, choices=Frequency.choices, default=Frequency.MONTHLY)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(blank=True, null=True)
    next_run = models.DateField(default=timezone.localdate)
    last_generated = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['is_active', 'next_run', 'title']
        indexes = [models.Index(fields=['owner', 'is_active', 'next_run'])]

    def clean(self):
        super().clean()
        if self.category_id and self.category.transaction_type != self.transaction_type:
            raise ValidationError({'category': 'Choose a category that matches the transaction type.'})
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date cannot be before the start date.'})

    def next_occurrence(self, value=None):
        value = value or self.next_run
        if self.frequency == self.Frequency.WEEKLY:
            return value.fromordinal(value.toordinal() + 7)
        year, month = value.year, value.month + 1
        if month == 13:
            year, month = year + 1, 1
        return date(year, month, min(value.day, monthrange(year, month)[1]))

    def generate_due_transactions(self, today=None):
        """Create each due record once, protected by a database uniqueness constraint."""
        today = today or timezone.localdate()
        generated = 0
        while self.is_active and self.next_run <= today:
            if self.end_date and self.next_run > self.end_date:
                self.is_active = False
                break
            _, created = Transaction.objects.get_or_create(
                owner=self.owner,
                recurring_source=self,
                date=self.next_run,
                defaults={
                    'title': self.title,
                    'description': self.description,
                    'amount': self.amount,
                    'transaction_type': self.transaction_type,
                    'category': self.category,
                },
            )
            generated += int(created)
            self.last_generated = self.next_run
            self.next_run = self.next_occurrence(self.next_run)
        self.save(update_fields=['next_run', 'last_generated', 'is_active', 'updated_at'])
        return generated

    def __str__(self):
        return f'{self.title} ({self.get_frequency_display()})'


CURRENCY_METADATA = {
    'INR': ('₹', 'en-IN'),
    'USD': ('$', 'en-US'),
    'EUR': ('€', 'en-IE'),
    'GBP': ('£', 'en-GB'),
    'CAD': ('CA$', 'en-CA'),
    'AUD': ('A$', 'en-AU'),
    'JPY': ('¥', 'ja-JP'),
}


def get_currency_meta(code):
    """Return (symbol, locale) for a supported ISO currency code."""
    return CURRENCY_METADATA.get(code, ('₹', 'en-IN'))


class UserSettings(models.Model):
    class CurrencyChoice(models.TextChoices):
        INR = 'INR', 'INR (₹) - Indian Rupee'
        USD = 'USD', 'USD ($) - US Dollar'
        EUR = 'EUR', 'EUR (€) - Euro'
        GBP = 'GBP', 'GBP (£) - British Pound'
        CAD = 'CAD', 'CAD ($) - Canadian Dollar'
        AUD = 'AUD', 'AUD ($) - Australian Dollar'
        JPY = 'JPY', 'JPY (¥) - Japanese Yen'

    class DateFormatChoice(models.TextChoices):
        ISO = 'YYYY-MM-DD', 'YYYY-MM-DD'
        DMY = 'DD/MM/YYYY', 'DD/MM/YYYY'
        MDY = 'MM/DD/YYYY', 'MM/DD/YYYY'
        VERBOSE = 'DD Mon YYYY', 'DD Mon YYYY'

    class DayOfWeek(models.TextChoices):
        MONDAY = 'monday', 'Monday'
        SUNDAY = 'sunday', 'Sunday'

    class ThemeChoice(models.TextChoices):
        DARK = 'dark', 'Dark (Midnight Emerald)'
        LIGHT = 'light', 'Light'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='settings'
    )
    currency = models.CharField(max_length=10, choices=CurrencyChoice.choices, default=CurrencyChoice.INR)
    date_format = models.CharField(max_length=20, choices=DateFormatChoice.choices, default=DateFormatChoice.ISO)
    first_day_of_week = models.CharField(max_length=10, choices=DayOfWeek.choices, default=DayOfWeek.MONDAY)
    theme_preference = models.CharField(max_length=10, choices=ThemeChoice.choices, default=ThemeChoice.DARK)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def currency_symbol(self):
        return get_currency_meta(self.currency)[0]

    @property
    def currency_locale(self):
        return get_currency_meta(self.currency)[1]

    def __str__(self):
        return f'{self.user.username} Settings'

