import random_address
import uuid
from datetime import datetime, timedelta, timezone
from mimesis import Person, Finance
from mimesis.locales import Locale
from django.core.management.base import BaseCommand
from onlinebanking.models import BankingProducts, BankAccountType, BankAccount, \
    TransactionCategory, AccountTransaction, AccountTransactionType, Retailer, Customer
import random
from config import settings

customer_id = getattr(settings, 'DEMO_USER_ID', None)

person = Person(locale=Locale.EN)
finance = Finance(locale=Locale.EN_GB)


def generate_address():
    address = random_address.real_random_address()
    key = 'city'
    if key not in address:
        address[key] = 'San Francisco'
    return address


def get_date_x_months_ago(x):
    current_date = datetime.now(tz=timezone.utc)
    months_ago_date = current_date - timedelta(days=30 * x)
    return months_ago_date


def generate_inbound_payment(bank_account, transaction_date, transaction_value, keywords):
    random_keyword = random.choice(keywords)
    description = f"Inbound payment made from {bank_account} for {random_keyword}, " \
                  f"{finance.company()}: {uuid.uuid4()}"
    transaction_type = AccountTransactionType.objects.filter(transaction_type='Credit').first()
    transaction_category = TransactionCategory.objects.filter(category_name='EFT').first()
    latest_transaction = AccountTransaction.objects.filter(
        bank_account=bank_account).order_by('-timestamp').first()
    if latest_transaction:
        closing_balance = latest_transaction.closing_balance
    else:
        closing_balance = 0
    transaction_value = transaction_value
    if transaction_type.transaction_operator == '-':
        new_closing_balance = closing_balance - transaction_value
    elif transaction_type.transaction_operator == '+':
        new_closing_balance = closing_balance + transaction_value

    new_transaction = AccountTransaction.objects.create(
        bank_account=bank_account,
        transaction_type=transaction_type,
        transaction_category=transaction_category,
        opening_balance=closing_balance,
        transaction_value=transaction_value,
        closing_balance=new_closing_balance,
        description=description,
        transaction_date=transaction_date
    )
    return new_transaction


def generate_outbound_payment(bank_account, transaction_date, transaction_value, keywords):
    keyword = random.choice(keywords)
    description = f"Payment made from {bank_account} to {person.first_name()} {person.last_name()} for { keyword }, " \
                  f"{finance.company()}: {uuid.uuid4()}"
    transaction_type = AccountTransactionType.objects.filter(transaction_type='Debit').first()
    transaction_category = TransactionCategory.objects.filter(category_name='EFT').first()
    latest_transaction = AccountTransaction.objects.filter(
        bank_account=bank_account).order_by('-timestamp').first()
    if latest_transaction:
        closing_balance = latest_transaction.closing_balance
    else:
        closing_balance = 0
    transaction_value = transaction_value
    if transaction_type.transaction_operator == '-':
        new_closing_balance = closing_balance - transaction_value
    elif transaction_type.transaction_operator == '+':
        new_closing_balance = closing_balance + transaction_value

    AccountTransaction.objects.create(
        bank_account=bank_account,
        transaction_type=transaction_type,
        transaction_category=transaction_category,
        opening_balance=closing_balance,
        transaction_value=transaction_value,
        closing_balance=new_closing_balance,
        description=description,
        transaction_date=transaction_date
    )
    return


def generate_purchase(bank_account, transaction_date, transaction_value, keywords):
    keyword = random.choice(keywords)
    transaction_type = AccountTransactionType.objects.filter(transaction_type='Debit').first()
    transaction_category = TransactionCategory.objects.filter(category_name='Purchase').first()
    latest_transaction = AccountTransaction.objects.filter(
        bank_account=bank_account).order_by('-timestamp').first()
    if latest_transaction:
        opening_balance = latest_transaction.closing_balance
    else:
        opening_balance = random.randint(100, 5000)
    transaction_value = transaction_value
    if transaction_type.transaction_operator == '-':
        closing_balance = opening_balance - transaction_value
    elif transaction_type.transaction_operator == '+':
        closing_balance = opening_balance + transaction_value
    retailers = Retailer.objects.all()
    retailer = random.choice(retailers)
    address = generate_address()
    city = address['city']
    state = address['state']
    description = f"Purchase at merchant: {retailer.name}, location: {city},{state}, meta: {keyword}"

    AccountTransaction.objects.create(
        bank_account=bank_account,
        transaction_type=transaction_type,
        transaction_category=transaction_category,
        opening_balance=opening_balance,
        transaction_value=transaction_value,
        closing_balance=closing_balance,
        description=description,
        transaction_date=transaction_date
    )
    return

def generate_bank_account_number():
    number = random.randint(100000, 999999)
    prefix = random.randint(1, 9)
    acc_number = f"EL0{prefix}-{number}"
    return acc_number


def random_description():
    payment_topics = ['gifts', 'mobile phone', 'school fees', 'cleaner', 'babysitting', 'contractors', 'gym', 'repairs']
    word = random.choice(payment_topics)
    return word


class Command(BaseCommand):
    help = 'Generate a random dataset based on a specific scenario'

    def add_arguments(self, parser):
        parser.add_argument('arg1', type=int, help='Indicates the id of the product offer used.')

    def handle(self, *args, **kwargs):
        banking_product_id = kwargs['arg1']
        banking_product = BankingProducts.objects.get(id=banking_product_id)
        print(banking_product.generator_keywords)
        customer = Customer.objects.get(id=customer_id)
        bank_account = BankAccount.objects.filter(customer_id=customer_id,
                                                  account_type=banking_product.account_type).first()
        if not bank_account:
            new_account_number = generate_bank_account_number()
            new_bank_account = BankAccount.objects.create(account_type=banking_product.account_type,
                                                          account_number=new_account_number,
                                                          customer=customer)
            bank_account = new_bank_account

        oldest_record = AccountTransaction.objects.order_by('transaction_date').first().transaction_date
        newest_record = AccountTransaction.objects.order_by('-transaction_date').first().transaction_date
        delta = newest_record - oldest_record
        number_of_transactions = random.randint(0, delta.days)
        counter = 0

        while counter <= number_of_transactions:
            random_day = random.randint(0, number_of_transactions)
            random_transaction_date = datetime.now().date() - timedelta(days=random_day)
            if str(banking_product.account_type) == 'Savings':
                min_transaction_value = 100
                max_transaction_value = 500
                transaction_value = random.randint(min_transaction_value, max_transaction_value)
                keyword_list = banking_product.generator_keywords.split(',')
                generate_inbound_payment(bank_account, random_transaction_date, transaction_value, keyword_list)
            elif str(banking_product.account_type) == 'Transmission':
                min_transaction_value = 100
                max_transaction_value = 500
                transaction_value = random.randint(min_transaction_value, max_transaction_value)
                keyword_list = banking_product.generator_keywords.split(',')
                transaction_type = random.choice('EFT', 'Purchase')
                if transaction_type == 'EFT':
                    generate_outbound_payment(bank_account, random_transaction_date, transaction_value, keyword_list)
                elif transaction_type == 'Purchase':
                    generate_purchase(bank_account, random_transaction_date, transaction_value,
                                      keyword_list)
            elif str(banking_product.account_type) == 'Credit':
                min_transaction_value = 10
                max_transaction_value = 180
                transaction_value = random.randint(min_transaction_value, max_transaction_value)
                keyword_list = banking_product.generator_keywords.split(',')
                generate_purchase(bank_account, random_transaction_date, transaction_value, keyword_list)
            counter = counter + 1
