import json

from django.http import StreamingHttpResponse
from django.shortcuts import render
from onlinebanking.models import BankAccount, BankAccountType, AccountTransactionType, AccountTransaction, Customer, \
    CustomerAddress, Retailer
from django.core.management import call_command
from elasticsearch import Elasticsearch
import subprocess
from config import settings

customer_id = getattr(settings, 'DEMO_USER_ID', None)
index_name = getattr(settings, 'TRANSACTION_INDEX_NAME', None)
product_index_name = getattr(settings, 'PRODUCT_INDEX', None)
llm_audit_index_name = getattr(settings, 'LLM_AUDIT_LOG_INDEX', None)
pipeline_name = getattr(settings, 'TRANSACTION_PIPELINE_NAME', None)
elastic_cloud_id = getattr(settings, 'elastic_cloud_id', None)
elastic_user = getattr(settings, 'elastic_user', None)
elastic_password = getattr(settings, 'elastic_password', None)
kibana_url = getattr(settings, 'kibana_url', None)


# Create your views here.
def manager(request):
    return render(request, 'envmanager/index.html')


def cluster(request):
    print(f"elastic cloud id: {elastic_cloud_id}")

    es = Elasticsearch(
        cloud_id=elastic_cloud_id,
        http_auth=(elastic_user, elastic_password)
    )
    context = {
        'cloud_id': elastic_cloud_id,
        'elastic_user': elastic_user,
        'elastic_password': elastic_password,
        'kibana_url': kibana_url,
        'es': es.info,
        'ping': es.ping

    }
    return render(request, 'envmanager/cluster.html', context)


def generate_data(request):
    context = {
        'view_name': 'generate_data'
    }
    return render(request, 'envmanager/index.html', context)


def execute_backend_command(request):
    if request.POST.get('command_name') == 'generate_data':
        message = 'The data generation command has been called and will execute asynchronously in the background.'
        number_of_customers = request.POST.get('number_of_customers')
        number_of_months = request.POST.get('number_of_months')
        transaction_minimum = request.POST.get('transaction_minimum')
        transaction_maximum = request.POST.get('transaction_maximum')
        # Check if arguments are not None or empty before calling call_command
        args = [
            arg for arg in [number_of_customers, number_of_months, transaction_minimum, transaction_maximum]
            if arg is not None and arg != ''
        ]
        call_command('generate_dataset', *args)
        context = {
            'view_name': 'generate_data'
        }
    return render(request, 'envmanager/command_handler.html', context)


def process_data_action(request):
    if request.method == 'POST':
        context = {
            'view_name': 'create',
            'form_data': {
                'number_of_customers': request.POST.get('number_of_customers'),
                'number_of_months': request.POST.get('number_of_months'),
                'transaction_minimum': request.POST.get('transaction_minimum'),
                'transaction_maximum': request.POST.get('transaction_maximum'),
            }
        }
    return render(request, 'envmanager/action.html', context)


def clear_data(request):
    es = Elasticsearch(
        cloud_id=elastic_cloud_id,
        http_auth=(elastic_user, elastic_password))
    query = {
        "match_all": {}
    }
    if request.method == 'POST':
        if request.POST.get('delete'):
            es.delete_by_query(index=index_name, query=query)
            Customer.objects.exclude(id=customer_id).delete()
            CustomerAddress.objects.all().delete()
            BankAccount.objects.all().delete()
            Retailer.objects.all().delete()

    es_record_count = es.count(index=index_name, query=query)
    bank_account_count = BankAccount.objects.count()
    customer_count = Customer.objects.exclude(id=customer_id).count()
    customer_address_count = CustomerAddress.objects.count()
    account_transactions_count = AccountTransaction.objects.count()
    retailer_count = Retailer.objects.count()

    context = {
        'view_name': 'clear_data',
        'bank_account_count': bank_account_count,
        'customer_count': customer_count,
        'customer_address_count': customer_address_count,
        'account_transactions_count': account_transactions_count,
        'retailer_count': retailer_count,
        'es_record_count': es_record_count['count']
    }
    return render(request, 'envmanager/index.html', context)


def run_command():
    # Use subprocess.Popen to run the command and capture output in real-time
    process = subprocess.Popen(
        ['python', 'manage.py', 'elastic_export'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Use line buffering
        universal_newlines=True,
    )

    # Iterate over the command's output in real-time
    for line in iter(process.stdout.readline, ''):
        yield line

    # Ensure the process has completed
    process.stdout.close()
    process.wait()


def read_json_file(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
    return data


def export_data(request):
    if request.POST.get('command_name') == 'elastic_export':
        # Create a StreamingHttpResponse with the generator function
        response = StreamingHttpResponse(run_command(), content_type="text/plain")

    else:
        response = 0

    account_transactions_count = AccountTransaction.objects.filter(exported=0).count()
    context = {
        'record_count': account_transactions_count,
        'view_name': 'export',
        'streaming_content': response
    }
    return render(request, 'envmanager/export.html', context)


def index_setup(request):
    es = Elasticsearch(
        cloud_id=elastic_cloud_id,
        http_auth=(elastic_user, elastic_password))
    if request.method == 'POST':
        transaction_index_mapping = read_json_file(f'files/transaction_index_mapping.json')
        transaction_index_settings = read_json_file(f'files/transaction_index_settings.json')
        product_index_mapping = read_json_file(f'files/product_index_mapping.json')
        llm_audit_index_mapping = read_json_file(f'files/llm_audit_log_mapping.json')
        pipeline_processors = read_json_file(f'files/transaction_index_pipeline.json')

        # transaction index
        index_exists = es.indices.exists(index=index_name)
        if index_exists:
            es.indices.delete(index=index_name)
        es.indices.create(index=index_name, mappings=transaction_index_mapping, settings=transaction_index_settings)

        # product index
        product_index_exists = es.indices.exists(index=product_index_name)
        if product_index_exists:
            es.indices.delete(index=product_index_name)
        es.indices.create(index=product_index_name, mappings=product_index_mapping)

        # llm_audit_log
        llm_index_exists = es.indices.exists(index=llm_audit_index_name)
        if llm_index_exists:
            es.indices.delete(index=llm_audit_index_name)
        es.indices.create(index=llm_audit_index_name, mappings=llm_audit_index_mapping)
        # ingest pipeline
        pipeline_exists = es.ingest.get_pipeline(id=pipeline_name, ignore=[404])
        if pipeline_exists:
            es.ingest.delete_pipeline(id=pipeline_name)
        es.ingest.put_pipeline(id=pipeline_name, processors=pipeline_processors)

        context = {
            'view_name': 'created'
        }
    else:
        # check if the indices exist
        index_exists = es.indices.exists(index=index_name)
        product_index_exists = es.indices.exists(index=product_index_name)
        llm_index_exists = es.indices.exists(index=llm_audit_index_name)
        pipeline_exists = es.ingest.get_pipeline(id=pipeline_name, ignore=[404])
        if index_exists and pipeline_exists and product_index_exists and llm_index_exists:
            transaction_mapping = es.indices.get_mapping(index=index_name)
            product_mapping = es.indices.get_mapping(index=product_index_name)
            ll_audit_mapping = es.indices.get_mapping(index=llm_audit_index_name)
            pipeline = es.ingest.get_pipeline(id=pipeline_name)
            context = {
                'view_name': 'confirmation',
                'transaction_mapping': transaction_mapping,
                'product_mapping': product_mapping,
                'llm_audit_mapping': ll_audit_mapping,
                'pipeline': pipeline
            }
        elif ((product_index_exists and index_exists) and not pipeline_exists) or (
                pipeline_exists and not (index_exists and product_index_exists)):
            context = {
                'view_name': 'incomplete'
            }
        else:
            context = {
                'view_name': 'scratch_build'
            }
    # if the index does not exist, go ahead and build a new one
    return render(request, 'envmanager/indices.html', context)
