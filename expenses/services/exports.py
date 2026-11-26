import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.db import transaction as db_transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone

from ..models import Account, Budget, Category, SavingsGoal, Transaction
from .accounts import apply_account_delta
from .analytics import report_metrics

FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def sanitize_csv_cell(value):
    """Neutralize spreadsheet formula injection in exported CSV text cells."""
    text = '' if value is None else str(value)
    if text and text[0] in FORMULA_PREFIXES:
        return f"'{text}"
    return text


def export_transactions_csv(transactions):
    """Build a downloadable CSV HttpResponse for a filtered transaction queryset."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="ledgerly-transactions.csv"'

    writer = csv.writer(response)
    writer.writerow(['title', 'amount', 'type', 'category', 'account', 'payment_method', 'date', 'description'])

    for item in transactions:
        writer.writerow([
            sanitize_csv_cell(item.title),
            item.amount,
            item.transaction_type,
            sanitize_csv_cell(item.category.name),
            sanitize_csv_cell(item.account.name if item.account else ''),
            item.payment_method or '',
            item.date.isoformat(),
            sanitize_csv_cell(item.description),
        ])
    return response


def import_transactions_csv(user, uploaded_file):
    """Validate and atomically import transactions from a UTF-8 CSV file.

    Returns (imported_count, error_messages).
    """
    raw_csv = uploaded_file.read().decode('utf-8-sig')
    reader = csv.DictReader(StringIO(raw_csv))

    required = {'title', 'amount', 'type', 'category', 'date'}
    field_names = {(name or '').strip().lower() for name in (reader.fieldnames or [])}
    if not required.issubset(field_names):
        raise ValueError('Use a CSV with title, amount, type, category, and date columns.')

    user_accounts = {acc.name.lower(): acc for acc in Account.objects.filter(owner=user)}
    errors = []
    pending = []

    for row_number, row in enumerate(reader, start=2):
        normalized = {(key or '').strip().lower(): (value or '').strip() for key, value in row.items()}
        try:
            transaction_type = normalized['type'].lower()
            if transaction_type not in Transaction.TransactionType.values:
                raise ValueError('type must be income or expense')

            category = Category.objects.get(
                name__iexact=normalized['category'],
                transaction_type=transaction_type,
            )

            account_name = normalized.get('account', '')
            account = None
            if account_name:
                account = user_accounts.get(account_name.lower())
                if account is None:
                    raise ValueError(f'Unknown account "{account_name}"')

            payment_method = normalized.get('payment_method', '').lower()
            if payment_method and payment_method not in Transaction.PaymentMethod.values:
                raise ValueError(f'Invalid payment_method "{payment_method}"')

            candidate = Transaction(
                owner=user,
                title=normalized['title'],
                amount=Decimal(normalized['amount']),
                transaction_type=transaction_type,
                category=category,
                account=account,
                payment_method=payment_method,
                date=date.fromisoformat(normalized['date']),
                description=normalized.get('description', ''),
            )
            candidate.full_clean()
            pending.append(candidate)
        except (Category.DoesNotExist, InvalidOperation, KeyError, ValueError) as exc:
            errors.append(f'Row {row_number}: {exc}')

    if errors:
        return 0, errors

    with db_transaction.atomic():
        for candidate in pending:
            candidate.save()
            if candidate.account_id:
                apply_account_delta(candidate.account_id, candidate.transaction_type, candidate.amount)

    return len(pending), []


def build_financial_report_pdf(user, currency_code='INR'):
    """Stream an owner-scoped financial PDF without creating server-side files."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    transactions, metrics = report_metrics(user)
    top_categories = list(
        transactions.filter(transaction_type=Transaction.TransactionType.EXPENSE)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:7]
    )

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="ledgerly-financial-report.pdf"'

    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    pdf.setTitle('Ledgerly Financial Report')

    def draw_header():
        pdf.setFillColor(colors.HexColor('#101A33'))
        pdf.rect(0, height - 92, width, 92, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont('Helvetica-Bold', 20)
        pdf.drawString(42, height - 52, 'Ledgerly Financial Report')
        pdf.setFont('Helvetica', 9)
        pdf.drawString(
            42,
            height - 70,
            f'Prepared for {user.get_full_name() or user.username} - {timezone.localdate():%d %b %Y}',
        )

    def draw_footer(page_num):
        pdf.setStrokeColor(colors.HexColor('#E8ECF3'))
        pdf.line(42, 55, width - 42, 55)
        pdf.setFillColor(colors.HexColor('#66738A'))
        pdf.setFont('Helvetica', 8)
        pdf.drawString(42, 38, 'Generated by Ledgerly - your personal finance workspace')
        pdf.drawRightString(width - 42, 38, f'Page {page_num}')

    draw_header()
    page_num = 1

    pdf.setFillColor(colors.HexColor('#182238'))
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(42, height - 125, 'Financial overview')

    overview = [
        ('Total income', metrics['income']),
        ('Total expenses', metrics['expenses']),
        ('Net balance', metrics['balance']),
        ('Savings rate', f"{metrics['savings_rate']:.1f}%"),
    ]

    left_y = height - 153
    for label, value in overview:
        pdf.setFillColor(colors.HexColor('#F5F7FC'))
        pdf.roundRect(42, left_y - 28, 250, 38, 5, stroke=0, fill=1)
        pdf.setFillColor(colors.HexColor('#66738A'))
        pdf.setFont('Helvetica', 8)
        pdf.drawString(54, left_y - 5, label.upper())
        pdf.setFillColor(colors.HexColor('#182238'))
        pdf.setFont('Helvetica-Bold', 12)
        formatted = value if isinstance(value, str) else f'{currency_code} {value:,.2f}'
        pdf.drawRightString(280, left_y - 5, formatted)
        left_y -= 47

    pdf.setFillColor(colors.HexColor('#182238'))
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(330, height - 125, 'Top expense categories')

    right_y = height - 153
    if top_categories:
        for item in top_categories:
            pdf.setStrokeColor(colors.HexColor('#E8ECF3'))
            pdf.line(330, right_y - 14, width - 42, right_y - 14)
            pdf.setFillColor(colors.HexColor('#182238'))
            pdf.setFont('Helvetica', 9)
            pdf.drawString(330, right_y, item['category__name'])
            pdf.setFont('Helvetica-Bold', 9)
            pdf.drawRightString(width - 42, right_y, f"{currency_code} {item['total']:,.2f}")
            right_y -= 28
    else:
        pdf.setFont('Helvetica', 9)
        pdf.setFillColor(colors.HexColor('#66738A'))
        pdf.drawString(330, right_y, 'No expense data recorded yet.')
        right_y -= 28

    section_y = min(left_y, right_y) - 24
    if section_y < 140:
        draw_footer(page_num)
        pdf.showPage()
        page_num += 1
        draw_header()
        section_y = height - 130

    pdf.setFillColor(colors.HexColor('#182238'))
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(42, section_y, 'Recent transactions')

    y = section_y - 25
    for item in transactions[:10]:
        if y < 80:
            draw_footer(page_num)
            pdf.showPage()
            page_num += 1
            draw_header()
            y = height - 130

        pdf.setStrokeColor(colors.HexColor('#E8ECF3'))
        pdf.line(42, y - 14, width - 42, y - 14)
        pdf.setFillColor(colors.HexColor('#182238'))
        pdf.setFont('Helvetica', 9)
        pdf.drawString(42, y, item.title[:42])
        pdf.setFillColor(colors.HexColor('#66738A'))
        pdf.drawString(245, y, item.date.strftime('%d %b %Y'))
        pdf.setFillColor(colors.HexColor('#16A779' if item.transaction_type == 'income' else '#EF6262'))
        pdf.setFont('Helvetica-Bold', 9)
        sign = '+' if item.transaction_type == 'income' else '-'
        pdf.drawRightString(width - 42, y, f'{sign} {currency_code} {item.amount:,.2f}')
        y -= 25

    draw_footer(page_num)
    pdf.showPage()
    pdf.save()
    return response


def build_user_json_export(user):
    """Build a downloadable JSON full-data export HttpResponse for the user."""
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

    response = HttpResponse(json.dumps(export_payload, indent=2), content_type='application/json')
    response['Content-Disposition'] = (
        f'attachment; filename="ledgerly-export-{user.username}-{timezone.localdate().isoformat()}.json"'
    )
    return response
