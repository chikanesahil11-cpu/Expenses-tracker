from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import (
    Account,
    Budget,
    Category,
    RecurringTransaction,
    SavingsGoal,
    Transaction,
    UserSettings,
)


class ExpenseTrackerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='owner', password='safe-password-2026')
        cls.other_user = User.objects.create_user(username='other', password='safe-password-2026')
        cls.income_category = Category.objects.create(name='Test Salary', transaction_type='income')
        cls.expense_category = Category.objects.create(name='Test Food', transaction_type='expense')

    def test_dashboard_totals_are_calculated_from_user_records(self):
        Transaction.objects.create(owner=self.user, title='Payday', amount=Decimal('2500.00'), transaction_type='income', category=self.income_category, date=date.today())
        Transaction.objects.create(owner=self.user, title='Lunch', amount=Decimal('25.50'), transaction_type='expense', category=self.expense_category, date=date.today())
        Transaction.objects.create(owner=self.other_user, title='Private', amount=Decimal('999.00'), transaction_type='expense', category=self.expense_category, date=date.today())
        self.client.login(username='owner', password='safe-password-2026')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, '2,474.50')
        self.assertEqual(response.context['transaction_count'], 2)

    def test_user_cannot_view_or_modify_another_users_transaction(self):
        transaction = Transaction.objects.create(owner=self.other_user, title='Private', amount=Decimal('10.00'), transaction_type='expense', category=self.expense_category, date=date.today())
        self.client.login(username='owner', password='safe-password-2026')
        self.assertEqual(self.client.get(reverse('transaction_detail', args=[transaction.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('transaction_delete', args=[transaction.pk])).status_code, 404)
        self.assertTrue(Transaction.objects.filter(pk=transaction.pk).exists())

    def test_transaction_form_rejects_wrong_category_type_and_negative_amount(self):
        self.client.login(username='owner', password='safe-password-2026')
        response = self.client.post(reverse('transaction_create'), {'title': 'Bad record', 'amount': '-10', 'transaction_type': 'income', 'category': self.expense_category.pk, 'date': '2026-11-23'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter an amount greater than zero.')
        self.assertFalse(Transaction.objects.filter(owner=self.user).exists())

    def test_registration_login_and_transaction_crud_workflow(self):
        registration = self.client.post(
            reverse('register'),
            {
                'username': 'newmember',
                'first_name': 'New Member',
                'email': 'member@example.com',
                'password1': 'Safe-and-unique-password-2026',
                'password2': 'Safe-and-unique-password-2026',
            },
        )
        self.assertRedirects(registration, reverse('dashboard'))
        new_user = User.objects.get(username='newmember')

        create = self.client.post(
            reverse('transaction_create'),
            {
                'title': 'Project payment',
                'amount': '125.00',
                'transaction_type': 'income',
                'category': self.income_category.pk,
                'date': '2026-11-23',
                'description': 'First client payment',
            },
        )
        self.assertRedirects(create, reverse('transaction_list'))
        transaction = Transaction.objects.get(owner=new_user, title='Project payment')

        edit = self.client.post(
            reverse('transaction_update', args=[transaction.pk]),
            {
                'title': 'Updated project payment',
                'amount': '175.00',
                'transaction_type': 'income',
                'category': self.income_category.pk,
                'date': '2026-11-23',
                'description': 'Updated payment',
            },
        )
        self.assertRedirects(edit, reverse('transaction_detail', args=[transaction.pk]))
        transaction.refresh_from_db()
        self.assertEqual(transaction.amount, Decimal('175.00'))
        self.assertEqual(transaction.title, 'Updated project payment')

        delete = self.client.post(reverse('transaction_delete', args=[transaction.pk]))
        self.assertRedirects(delete, reverse('transaction_list'))
        self.assertFalse(Transaction.objects.filter(pk=transaction.pk).exists())

        logout = self.client.post(reverse('logout'))
        self.assertRedirects(logout, reverse('login'))
        login_response = self.client.post(reverse('login'), {'username': 'newmember', 'password': 'Safe-and-unique-password-2026'})
        self.assertRedirects(login_response, reverse('dashboard'))

    def test_authenticated_pages_and_filters_render(self):
        transaction = Transaction.objects.create(
            owner=self.user,
            title='Filtered salary',
            amount=Decimal('300.00'),
            transaction_type='income',
            category=self.income_category,
            date=date.today(),
        )
        self.client.login(username='owner', password='safe-password-2026')
        self.assertEqual(self.client.get(reverse('transaction_create')).status_code, 200)
        list_response = self.client.get(reverse('transaction_list'), {'q': 'salary', 'type': 'income', 'category': self.income_category.pk})
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, 'Filtered salary')
        invalid_dates = self.client.get(
            reverse('transaction_list'),
            {'start_date': 'not-a-date', 'end_date': '2026-99-99'},
        )
        self.assertEqual(invalid_dates.status_code, 200)
        self.assertContains(invalid_dates, 'Filtered salary')

        transaction_form = self.client.get(reverse('transaction_create'))
        self.assertContains(transaction_form, 'data-type="income"')
        self.assertContains(transaction_form, 'data-type="expense"')
        self.assertEqual(self.client.get(reverse('transaction_detail', args=[transaction.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 200)

    def test_budget_goal_and_recurring_workflows(self):
        self.client.login(username='owner', password='safe-password-2026')
        today = date.today()

        recurring_form = self.client.get(reverse('recurring_create'))
        self.assertContains(recurring_form, 'data-type="expense"')

        create_budget = self.client.post(
            reverse('budget_create'),
            {'category': self.expense_category.pk, 'month': today.isoformat(), 'amount': '250.00'},
        )
        self.assertRedirects(create_budget, reverse('budget_list'))
        budget = Budget.objects.get(owner=self.user)
        self.assertEqual(budget.month.day, 1)
        duplicate_budget = self.client.post(
            reverse('budget_create'),
            {'category': self.expense_category.pk, 'month': today.isoformat(), 'amount': '300.00'},
        )
        self.assertEqual(duplicate_budget.status_code, 200)
        self.assertEqual(Budget.objects.filter(owner=self.user).count(), 1)

        create_goal = self.client.post(
            reverse('goal_create'),
            {'name': 'Emergency fund', 'target_amount': '1000.00', 'current_amount': '100.00', 'target_date': ''},
        )
        self.assertRedirects(create_goal, reverse('goal_list'))
        self.assertEqual(SavingsGoal.objects.get(owner=self.user).progress_percentage, 10.0)

        schedule = self.client.post(
            reverse('recurring_create'),
            {
                'transaction_type': 'expense', 'title': 'Weekly lunch', 'amount': '50.00',
                'category': self.expense_category.pk, 'frequency': 'weekly',
                'start_date': today.isoformat(), 'end_date': '', 'description': '', 'is_active': 'on',
            },
        )
        self.assertRedirects(schedule, reverse('recurring_list'))
        recurring = RecurringTransaction.objects.get(owner=self.user)
        self.client.post(reverse('recurring_run'))
        self.client.post(reverse('recurring_run'))
        self.assertEqual(Transaction.objects.filter(recurring_source=recurring).count(), 1)

    def test_csv_import_export_and_pdf_report(self):
        self.client.login(username='owner', password='safe-password-2026')
        csv_file = SimpleUploadedFile(
            'transactions.csv',
            b'title,amount,type,category,date,description\nLunch,18.50,expense,Test Food,2026-11-23,Team meal\n',
            content_type='text/csv',
        )
        imported = self.client.post(reverse('transaction_import_csv'), {'csv_file': csv_file})
        self.assertRedirects(imported, reverse('transaction_list'))
        self.assertTrue(Transaction.objects.filter(owner=self.user, title='Lunch').exists())

        export = self.client.get(reverse('transaction_export_csv'))
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn(b'Lunch', b''.join(export.streaming_content) if hasattr(export, 'streaming_content') else export.content)

        report = self.client.get(reverse('financial_report_pdf'))
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report['Content-Type'], 'application/pdf')
        self.assertTrue(report.content.startswith(b'%PDF'))

    def test_demo_data_command_is_opt_in_and_idempotent(self):
        self.assertFalse(Transaction.objects.filter(owner=self.user).exists())
        call_command('seed_demo_data', username=self.user.username)
        created_count = Transaction.objects.filter(owner=self.user).count()
        self.assertGreater(created_count, 1)
        self.assertTrue(
            Transaction.objects.filter(
                owner=self.user, description='Fictional Ledgerly demo record.'
            ).exists()
        )
        call_command('seed_demo_data', username=self.user.username)
        self.assertEqual(Transaction.objects.filter(owner=self.user).count(), created_count)

    def test_account_crud_and_isolation(self):
        self.client.login(username='owner', password='safe-password-2026')

        create = self.client.post(reverse('account_create'), {
            'name': 'HDFC Salary Account',
            'account_type': 'bank',
            'balance': '50000.00',
            'currency': 'INR',
            'color': '#10b981',
        })
        self.assertRedirects(create, reverse('account_list'))
        account = Account.objects.get(owner=self.user, name='HDFC Salary Account')
        self.assertEqual(account.balance, Decimal('50000.00'))

        other_account = Account.objects.create(
            owner=self.other_user,
            name='Secret Vault',
            account_type='savings',
            balance=Decimal('10000.00'),
        )

        list_res = self.client.get(reverse('account_list'))
        self.assertContains(list_res, 'HDFC Salary Account')
        self.assertNotContains(list_res, 'Secret Vault')

        self.assertEqual(self.client.get(reverse('account_update', args=[other_account.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('account_delete', args=[other_account.pk])).status_code, 404)

        update = self.client.post(reverse('account_update', args=[account.pk]), {
            'name': 'HDFC Main Account',
            'account_type': 'bank',
            'balance': '55000.00',
            'currency': 'INR',
            'color': '#10b981',
        })
        self.assertRedirects(update, reverse('account_list'))
        account.refresh_from_db()
        self.assertEqual(account.name, 'HDFC Main Account')
        self.assertEqual(account.balance, Decimal('55000.00'))

        delete = self.client.post(reverse('account_delete', args=[account.pk]))
        self.assertRedirects(delete, reverse('account_list'))
        self.assertFalse(Account.objects.filter(pk=account.pk).exists())

    def test_transaction_duplicate_and_account_association(self):
        account = Account.objects.create(
            owner=self.user,
            name='Cash Wallet',
            account_type='cash',
            balance=Decimal('2000.00'),
        )
        tx = Transaction.objects.create(
            owner=self.user,
            title='Groceries at Supermarket',
            amount=Decimal('850.00'),
            transaction_type='expense',
            category=self.expense_category,
            account=account,
            payment_method='cash',
            date=date.today(),
            description='Weekly vegetables and fruits',
        )
        self.client.login(username='owner', password='safe-password-2026')

        dup_get = self.client.get(reverse('transaction_duplicate', args=[tx.pk]))
        self.assertEqual(dup_get.status_code, 200)
        self.assertContains(dup_get, 'Groceries at Supermarket (Copy)')

        dup_post = self.client.post(reverse('transaction_duplicate', args=[tx.pk]), {
            'title': 'Groceries at Supermarket (Copy)',
            'amount': '850.00',
            'transaction_type': 'expense',
            'category': self.expense_category.pk,
            'account': account.pk,
            'payment_method': 'cash',
            'date': date.today().isoformat(),
            'description': 'Weekly vegetables and fruits',
        })
        dup_tx = Transaction.objects.get(owner=self.user, title='Groceries at Supermarket (Copy)')
        self.assertRedirects(dup_post, reverse('transaction_detail', args=[dup_tx.pk]))
        self.assertEqual(dup_tx.account, account)
        self.assertEqual(dup_tx.payment_method, 'cash')

    def test_calendar_view(self):
        self.client.login(username='owner', password='safe-password-2026')
        Transaction.objects.create(
            owner=self.user,
            title='Coffee',
            amount=Decimal('150.00'),
            transaction_type='expense',
            category=self.expense_category,
            date=date.today(),
        )
        response = self.client.get(reverse('transaction_calendar'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TRANSACTION MATRIX')
        self.assertContains(response, 'SELECTED TIMELINE')
        self.assertIn('month_matrix', response.context)
        self.assertIn('month_expense', response.context)

    def test_settings_and_preferences(self):
        self.client.login(username='owner', password='safe-password-2026')
        response = self.client.get(reverse('settings_view'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h1>Settings</h1>')
        self.assertContains(response, 'PREFERENCES & SECURITY')

        profile_res = self.client.post(reverse('settings_view'), {
            'action': 'update_profile',
            'username': 'owner',
            'first_name': 'Chief Executive',
            'last_name': 'Admin',
            'email': 'ceo@ledgerly.finance',
        })
        self.assertRedirects(profile_res, f"{reverse('settings_view')}?tab=profile")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Chief Executive')
        self.assertEqual(self.user.email, 'ceo@ledgerly.finance')

        pref_res = self.client.post(reverse('settings_view'), {
            'action': 'update_preferences',
            'currency': 'USD',
            'date_format': 'YYYY-MM-DD',
            'first_day_of_week': 'monday',
            'theme_preference': 'dark',
        })
        self.assertRedirects(pref_res, f"{reverse('settings_view')}?tab=preferences")
        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.currency, 'USD')

    def test_data_export_json(self):
        self.client.login(username='owner', password='safe-password-2026')
        Transaction.objects.create(
            owner=self.user,
            title='JSON Export Test',
            amount=Decimal('420.00'),
            transaction_type='expense',
            category=self.expense_category,
            date=date.today(),
        )
        response = self.client.get(reverse('data_export_json'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('attachment', response['Content-Disposition'])
        import json
        data = json.loads(response.content.decode('utf-8'))
        self.assertEqual(data['user']['username'], 'owner')
        self.assertTrue(any(t['title'] == 'JSON Export Test' for t in data['transactions']))

    def test_goal_deposit_and_recurring_toggle(self):
        self.client.login(username='owner', password='safe-password-2026')

        goal = SavingsGoal.objects.create(
            owner=self.user,
            name='Retirement Starter',
            target_amount=Decimal('10000.00'),
            current_amount=Decimal('2000.00'),
        )
        dep_res = self.client.post(reverse('goal_deposit', args=[goal.pk]), {'amount': '1500.00'})
        self.assertRedirects(dep_res, reverse('goal_list'))
        goal.refresh_from_db()
        self.assertEqual(goal.current_amount, Decimal('3500.00'))

        recurring = RecurringTransaction.objects.create(
            owner=self.user,
            title='Streaming Subscription',
            amount=Decimal('699.00'),
            transaction_type='expense',
            category=self.expense_category,
            frequency='monthly',
            start_date=date.today(),
            is_active=True,
        )
        toggle_res = self.client.post(reverse('recurring_toggle', args=[recurring.pk]))
        self.assertRedirects(toggle_res, reverse('recurring_list'))
        recurring.refresh_from_db()
        self.assertFalse(recurring.is_active)

        toggle_res2 = self.client.post(reverse('recurring_toggle', args=[recurring.pk]))
        self.assertRedirects(toggle_res2, reverse('recurring_list'))
        recurring.refresh_from_db()
        self.assertTrue(recurring.is_active)

    def test_account_balance_syncs_with_transaction_crud_and_csv_import(self):
        self.client.login(username='owner', password='safe-password-2026')
        checking = Account.objects.create(
            owner=self.user, name='Main Bank', account_type='bank', balance=Decimal('1000.00')
        )
        cash = Account.objects.create(
            owner=self.user, name='Cash Pouch', account_type='cash', balance=Decimal('500.00')
        )

        # Create expense -> decreases checking
        self.client.post(reverse('transaction_create'), {
            'title': 'Dinner',
            'amount': '200.00',
            'transaction_type': 'expense',
            'category': self.expense_category.pk,
            'account': checking.pk,
            'date': '2026-11-23',
        })
        checking.refresh_from_db()
        self.assertEqual(checking.balance, Decimal('800.00'))

        tx = Transaction.objects.get(owner=self.user, title='Dinner')

        # Update: switch account to cash and change to income 150 -> checking restored (1000), cash +150 (650)
        self.client.post(reverse('transaction_update', args=[tx.pk]), {
            'title': 'Refund',
            'amount': '150.00',
            'transaction_type': 'income',
            'category': self.income_category.pk,
            'account': cash.pk,
            'date': '2026-11-23',
        })
        checking.refresh_from_db()
        cash.refresh_from_db()
        self.assertEqual(checking.balance, Decimal('1000.00'))
        self.assertEqual(cash.balance, Decimal('650.00'))

        # Delete -> cash restored to 500
        self.client.post(reverse('transaction_delete', args=[tx.pk]))
        cash.refresh_from_db()
        self.assertEqual(cash.balance, Decimal('500.00'))

        # CSV import with account column
        csv_file = SimpleUploadedFile(
            'acct.csv',
            b'title,amount,type,category,account,date\nBonus,300.00,income,Test Salary,Main Bank,2026-11-23\n',
            content_type='text/csv',
        )
        self.client.post(reverse('transaction_import_csv'), {'csv_file': csv_file})
        checking.refresh_from_db()
        self.assertEqual(checking.balance, Decimal('1300.00'))

    def test_user_settings_currency_date_format_and_calendar_week_start_are_applied(self):
        self.client.login(username='owner', password='safe-password-2026')
        UserSettings.objects.create(
            user=self.user,
            currency='USD',
            date_format='DD/MM/YYYY',
            first_day_of_week='sunday',
            theme_preference='light',
        )
        Transaction.objects.create(
            owner=self.user,
            title='Client Retainer',
            amount=Decimal('1200.00'),
            transaction_type='income',
            category=self.income_category,
            date=date(2026, 11, 5),
        )

        dash = self.client.get(reverse('dashboard'))
        self.assertContains(dash, '$1,200.00')
        self.assertContains(dash, '05/11/2026')
        self.assertContains(dash, 'data-theme="light"')

        cal = self.client.get(reverse('transaction_calendar'))
        self.assertEqual(cal.context['weekday_headers'][0], 'Sun')
        self.assertContains(cal, '$1,200.00')

    def test_goal_remaining_amount_and_budget_over_display(self):
        self.client.login(username='owner', password='safe-password-2026')
        today = date.today()
        SavingsGoal.objects.create(
            owner=self.user,
            name='Laptop',
            target_amount=Decimal('1000.00'),
            current_amount=Decimal('250.00'),
        )
        goal_res = self.client.get(reverse('goal_list'))
        self.assertContains(goal_res, 'Remaining: ₹750.00')
        self.assertNotContains(goal_res, 'Remaining: ₹1,250.00')

        Budget.objects.create(
            owner=self.user,
            category=self.expense_category,
            month=today.replace(day=1),
            amount=Decimal('200.00'),
        )
        Transaction.objects.create(
            owner=self.user,
            title='Big Meal',
            amount=Decimal('350.00'),
            transaction_type='expense',
            category=self.expense_category,
            date=today,
        )
        budget_res = self.client.get(reverse('budget_list'))
        self.assertContains(budget_res, 'Over by ₹150.00')

    def test_csv_export_neutralizes_formula_injection(self):
        self.client.login(username='owner', password='safe-password-2026')
        Transaction.objects.create(
            owner=self.user,
            title='=CMD("calc")',
            amount=Decimal('10.00'),
            transaction_type='expense',
            category=self.expense_category,
            date=date(2026, 11, 20),
            description='+SUM(A1:A2)',
        )
        export = self.client.get(reverse('transaction_export_csv'))
        content = export.content.decode('utf-8')
        self.assertIn("'=CMD(", content)
        self.assertIn("'+SUM(A1:A2)", content)

    def test_logout_buttons_present_and_logout_works(self):
        self.client.login(username='owner', password='safe-password-2026')
        dash = self.client.get(reverse('dashboard'))
        self.assertContains(dash, reverse('logout'))
        self.assertContains(dash, 'Log out')

        sec = self.client.get(f"{reverse('settings_view')}?tab=security")
        self.assertContains(sec, 'Active Session')
        self.assertContains(sec, 'Log out')

        res = self.client.post(reverse('logout'))
        self.assertRedirects(res, reverse('login'))

    def test_categories_page_and_clean_transaction_form(self):
        self.client.login(username='owner', password='safe-password-2026')
        cat_res = self.client.get(reverse('category_list'))
        self.assertEqual(cat_res.status_code, 200)
        self.assertContains(cat_res, 'Income categories')
        self.assertContains(cat_res, 'Expense categories')

        cat_expense = self.client.get(reverse('category_list'), {'type': 'expense'})
        self.assertEqual(cat_expense.status_code, 200)
        self.assertNotContains(cat_expense, '<h2>Income categories</h2>')
        self.assertContains(cat_expense, '<h2>Expense categories</h2>')

        form_res = self.client.get(reverse('transaction_create'))
        self.assertEqual(form_res.status_code, 200)
        self.assertNotContains(form_res, 'class="field-hint"')
