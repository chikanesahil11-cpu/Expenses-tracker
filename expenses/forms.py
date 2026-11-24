from django import forms
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django.contrib.auth.models import User

from .models import (
    Account,
    Budget,
    Category,
    RecurringTransaction,
    SavingsGoal,
    Transaction,
    UserSettings,
)


class CategorySelect(forms.Select):
    """Expose a category's type to the progressive client-side filter."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        category = getattr(value, 'instance', None)
        if category is not None:
            option['attrs']['data-type'] = category.transaction_type
        return option


class StyledFormMixin:
    """Apply consistent Bootstrap classes without duplicating widgets."""

    def apply_bootstrap_classes(self):
        for field in self.fields.values():
            existing = field.widget.attrs.get('class', '')
            css_class = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
            field.widget.attrs['class'] = f'{existing} {css_class}'.strip()


class RegistrationForm(StyledFormMixin, UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=False, label='First name')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap_classes()
        self.fields['username'].help_text = 'Up to 150 characters. Letters, digits and @/./+/-/_ only.'

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        if commit:
            user.save()
        return user


class AccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Account
        fields = ('name', 'account_type', 'balance', 'currency', 'color')
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Main Bank, Cash Wallet'}),
            'balance': forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0.00'}),
            'color': forms.TextInput(attrs={'type': 'color'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap_classes()


class TransactionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Transaction
        fields = (
            'transaction_type', 'title', 'amount', 'category',
            'account', 'payment_method', 'date', 'description'
        )
        widgets = {
            'category': CategorySelect(),
            'date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional note'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
            'title': forms.TextInput(attrs={'placeholder': 'e.g. November salary'}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()
        self.fields['category'].empty_label = 'Choose a category'
        if owner:
            self.fields['account'].queryset = Account.objects.filter(owner=owner)
        else:
            self.fields['account'].queryset = Account.objects.none()
        self.fields['account'].empty_label = 'Choose an account (optional)'
        self.fields['account'].required = False
        self.fields['payment_method'].required = False
        self.apply_bootstrap_classes()

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Enter an amount greater than zero.')
        return amount

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        transaction_type = cleaned_data.get('transaction_type')
        if category and transaction_type and category.transaction_type != transaction_type:
            self.add_error('category', 'Choose a category that matches the transaction type.')
        return cleaned_data


class BudgetForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Budget
        fields = ('category', 'month', 'amount')
        widgets = {
            'month': forms.DateInput(attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(
            transaction_type=Category.TransactionType.EXPENSE
        )
        self.apply_bootstrap_classes()

    def clean_month(self):
        month = self.cleaned_data['month']
        return month.replace(day=1)

    def clean(self):
        cleaned_data = super().clean()
        owner = self.owner or getattr(self.instance, 'owner', None)
        category = cleaned_data.get('category')
        month = cleaned_data.get('month')
        if owner and category and month:
            duplicate = Budget.objects.filter(owner=owner, category=category, month=month)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error(None, 'A budget for this category and month already exists.')
        return cleaned_data


class SavingsGoalForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = ('name', 'target_amount', 'current_amount', 'target_date')
        widgets = {
            'target_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
            'current_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': '0.00'}),
            'target_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap_classes()


class RecurringTransactionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = RecurringTransaction
        fields = (
            'transaction_type', 'title', 'amount', 'category', 'frequency',
            'start_date', 'end_date', 'description', 'is_active',
        )
        widgets = {
            'category': CategorySelect(),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional note'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()
        self.apply_bootstrap_classes()

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        transaction_type = cleaned_data.get('transaction_type')
        if category and transaction_type and category.transaction_type != transaction_type:
            self.add_error('category', 'Choose a category that matches the transaction type.')
        return cleaned_data


class TransactionImportForm(StyledFormMixin, forms.Form):
    csv_file = forms.FileField(
        label='CSV file',
        help_text='Columns: title, amount, type, category, date, description (description is optional).',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['csv_file'].widget.attrs['accept'] = '.csv,text/csv'
        self.apply_bootstrap_classes()

    def clean_csv_file(self):
        csv_file = self.cleaned_data['csv_file']
        if csv_file.size > 2 * 1024 * 1024:
            raise forms.ValidationError('Choose a CSV file smaller than 2 MB.')
        if not csv_file.name.lower().endswith('.csv'):
            raise forms.ValidationError('Choose a .csv file.')
        return csv_file


class UserProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'username')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap_classes()
        self.fields['email'].required = True

    def clean_email(self):
        email = self.cleaned_data['email']
        duplicate = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError('A user with this email address already exists.')
        return email


class ApplicationSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = UserSettings
        fields = ('currency', 'date_format', 'first_day_of_week', 'theme_preference')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap_classes()


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap_classes()
