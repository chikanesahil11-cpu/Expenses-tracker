from django.contrib import admin

from .models import Budget, Category, RecurringTransaction, SavingsGoal, Transaction


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'transaction_type')
    list_filter = ('transaction_type',)
    search_fields = ('name',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'transaction_type', 'category', 'amount', 'date', 'recurring_source')
    list_filter = ('transaction_type', 'category', 'date')
    search_fields = ('title', 'description', 'owner__username')
    list_select_related = ('owner', 'category')


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('owner', 'category', 'month', 'amount')
    list_filter = ('month', 'category')
    list_select_related = ('owner', 'category')


@admin.register(SavingsGoal)
class SavingsGoalAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'current_amount', 'target_amount', 'target_date')
    list_filter = ('target_date',)
    search_fields = ('name', 'owner__username')


@admin.register(RecurringTransaction)
class RecurringTransactionAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'transaction_type', 'amount', 'frequency', 'next_run', 'is_active')
    list_filter = ('transaction_type', 'frequency', 'is_active')
    search_fields = ('title', 'owner__username')
    list_select_related = ('owner', 'category')
