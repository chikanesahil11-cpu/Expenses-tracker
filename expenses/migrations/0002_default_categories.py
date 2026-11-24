from django.db import migrations


INCOME_CATEGORIES = ['Salary', 'Freelance', 'Business', 'Investment', 'Other income']
EXPENSE_CATEGORIES = ['Food', 'Shopping', 'Transport', 'Education', 'Bills', 'Entertainment', 'Healthcare', 'Other expenses']


def create_default_categories(apps, schema_editor):
    Category = apps.get_model('expenses', 'Category')
    for name in INCOME_CATEGORIES:
        Category.objects.get_or_create(name=name, transaction_type='income')
    for name in EXPENSE_CATEGORIES:
        Category.objects.get_or_create(name=name, transaction_type='expense')


def remove_default_categories(apps, schema_editor):
    Category = apps.get_model('expenses', 'Category')
    Category.objects.filter(name__in=INCOME_CATEGORIES, transaction_type='income').delete()
    Category.objects.filter(name__in=EXPENSE_CATEGORIES, transaction_type='expense').delete()


class Migration(migrations.Migration):
    dependencies = [('expenses', '0001_initial')]

    operations = [migrations.RunPython(create_default_categories, remove_default_categories)]
