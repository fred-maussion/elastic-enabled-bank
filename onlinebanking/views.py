import json
import googlemaps
from django.shortcuts import render
from .models import BankAccount, AccountTransaction, Customer, Retailer, BankingProducts, DemoScenarios
from .forms import AccountTransactionForm, AccountTransferForm
from elasticsearch import Elasticsearch
from langchain.chat_models import AzureChatOpenAI
from dotenv import load_dotenv
import os
from datetime import datetime, timezone
import tiktoken
import nltk
from nltk.tokenize import word_tokenize
import re
from config import settings
import pandas as pd
from django.db.models import Q
import math
import uuid

load_dotenv()

from langchain.schema import (
    SystemMessage,
    HumanMessage)
from config.settings import GOOGLE_MAPS_API_KEY

customer_id = getattr(settings, 'DEMO_USER_ID', None)
index_name = getattr(settings, 'TRANSACTION_INDEX_NAME', None)
elastic_cloud_id = getattr(settings, 'elastic_cloud_id', None)
elastic_user = getattr(settings, 'elastic_user', None)
elastic_password = getattr(settings, 'elastic_password', None)
openai_api_key = os.environ['openai_api_key']
openai_api_type = os.environ['openai_api_type']
openai_api_base = os.environ['openai_api_base']
openai_api_version = os.environ['openai_api_version']
model_id = getattr(settings, 'MODEL_ID', None)
pipeline_name = getattr(settings, 'TRANSACTION_PIPELINE_NAME', None)
product_index_name = getattr(settings, 'PRODUCT_INDEX', None)
customer_support_index = getattr(settings, 'CUSTOMER_SUPPORT_INDEX', None)
logging_index = getattr(settings, 'LLM_AUDIT_LOG_INDEX', None)
logging_pipeline = getattr(settings, 'LLM_AUDIT_LOG_INDEX_PIPELINE_NAME', None)
llm_provider = getattr(settings, 'LLM_PROVIDER', None)
llm_temperature = 1

# calculate the cost of an LLM interaction
def calculate_cost(message, type):
    provider = llm_provider
    rate_card = {
        'azure': {
            'prompt': 0.003,
            'response': 0.004
        },
        'aws': {
            'prompt': 0.008,
            'response': 0.024
        }
    }
    cost_per_1k = rate_card[provider][type]
    message_token_count = num_tokens_from_string(message, "cl100k_base")
    billable_message_tokens = message_token_count / 1000
    rounded_up_message_tokens = math.ceil(billable_message_tokens)
    message_cost = rounded_up_message_tokens * cost_per_1k
    return message_cost


def log_llm_interaction(prompt, response, sent_time, received_time, answer_type, provider, model, business_process):
    es = Elasticsearch(
        cloud_id=elastic_cloud_id,
        http_auth=(elastic_user, elastic_password)
    )
    log_id = uuid.uuid4()
    dt_latency = received_time - sent_time
    actual_latency = dt_latency.total_seconds()
    body = {
        "@timestamp": datetime.now(tz=timezone.utc),
        "prompt": prompt,
        "response": response,
        "business_process": business_process,
        "provider": provider,
        "model": model,
        "timestamp_sent": sent_time,
        "timestamp_received": received_time,
        "prompt_cost": calculate_cost(prompt, 'prompt'),
        "response_cost": calculate_cost(response, 'response'),
        "answer_type": answer_type,
        "llm_latency": actual_latency,
        "llm_temperature": llm_temperature

    }
    response = es.index(index=logging_index, id=log_id, document=body, pipeline=logging_pipeline)
    return


def init_chat_model(provider):
    provider = 'azure'
    if provider == 'azure':
        BASE_URL = os.environ['openai_api_base']
        API_KEY = os.environ['openai_api_key']
        DEPLOYMENT_NAME = os.environ['openai_deployment_name']
        chat_model = AzureChatOpenAI(
            openai_api_base=BASE_URL,
            openai_api_version=os.environ['openai_api_version'],
            deployment_name=DEPLOYMENT_NAME,
            openai_api_key=API_KEY,
            openai_api_type="azure",
            temperature=llm_temperature
        )
    return chat_model


def chat_model_message(query, context):
    # interact with the LLM
    augmented_prompt = f"""Using only the contexts below, answer the query.
    Contexts: {context}
    Query: {query}"""
    messages = [
        SystemMessage(
            content="You are a helpful financial analyst using transaction search results to answer questions. If "
                    "you do not know the answer, simply say that the data available cannot answer the question."),
        HumanMessage(content=augmented_prompt)
    ]
    return messages


def num_tokens_from_string(string: str, encoding_name: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def truncate_text(text, max_tokens):
    nltk.download('punkt')
    tokens = word_tokenize(text)
    trimmed_text = ' '.join(tokens[:max_tokens])
    return trimmed_text


def build_record(transaction_id):
    payload = {}
    transaction_details = AccountTransaction.objects.filter(id=transaction_id).first()
    bank_account_details = BankAccount.objects.filter(id=transaction_details.bank_account_id).first()
    customer_details = Customer.objects.filter(id=bank_account_details.customer_id).first()

    payload = {
        "transaction_date": transaction_details.transaction_date.strftime("%Y-%m-%d"),
        "bank_account_number": str(transaction_details.bank_account),
        "bank_account_type": str(bank_account_details.account_type),
        "transaction_category": transaction_details.transaction_category.category_name,
        "transaction_type": transaction_details.transaction_type.transaction_type,
        "opening_balance": transaction_details.opening_balance,
        "transaction_value": transaction_details.transaction_value,
        "closing_balance": transaction_details.closing_balance,
        "description": transaction_details.description,
        "customer_name": f'{customer_details.first_name} {customer_details.last_name}',
        "customer_email": customer_details.email
    }
    pattern = r"merchant: (.+?), location: (.+)$"
    match = re.search(pattern, transaction_details.description)
    if match:
        merchant = match.group(1)
        retailer_format = Retailer.objects.filter(name=merchant).first()
        payload[
            'description'] = f"{transaction_details.description} - category: {retailer_format.dominant_operational_format}"
        payload['merchant_name'] = match.group(1)
        payload['location'] = match.group(2)

        gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
        geocode_result = gmaps.geocode(payload['location'])
        location = geocode_result[0]['geometry']['location']
        latitude = location['lat']
        longitude = location['lng']
        payload['geometry'] = {
            "lat": latitude,
            "lon": longitude
        }
    payload = json.dumps(payload)
    print(payload)
    return payload


def trim_tokens(text_to_trim):
    llm_token_limit = 10000
    tokens = text_to_trim.split()
    if len(tokens) > llm_token_limit:
        trimmed_text = ' '.join(tokens[:llm_token_limit])
    else:
        trimmed_text = text_to_trim
    return trimmed_text


# Create your views here.

def customer_support(request):
    question = ""
    answer = ""
    documents = ""
    if request.method == 'POST':
        question = request.POST.get('question')
        es = Elasticsearch(
            cloud_id=elastic_cloud_id,
            http_auth=(elastic_user, elastic_password)
        )
        query = {
            "bool": {
                "should": [
                    {
                        "text_expansion": {
                            "ml.inference.title_expanded.predicted_value": {
                                "model_id": model_id,
                                "model_text": question,
                                "boost": 5
                            }
                        }
                    },
                    {
                        "text_expansion": {
                            "ml.inference.body_content_expanded.predicted_value": {
                                "model_id": model_id,
                                "model_text": question
                            }
                        }
                    },
                    {
                        "match": {
                            "body_content": question
                        }
                    },
                    {
                        "match": {
                            "title": question
                        }
                    }
                ]
            }
        }
        customer_support_field_list = ['title', 'body_content', '_score']
        customer_support_results = es.search(index=customer_support_index, query=query, size=50,
                                             fields=customer_support_field_list, min_score=10)
        # response_data = [{"_score": hit["_score"], **hit["_source"]} for hit in
        #                  customer_support_results["hits"]["hits"]]
        documents = []
        # Check if there are hits
        if customer_support_results['hits']['total']['value'] > 1:
            for hit in customer_support_results['hits']['hits']:
                doc_info = {
                    "score": hit["_score"],
                    "title": hit["_source"]["title"],
                    "body_content": hit["_source"]["body_content"]
                }
                documents.append(doc_info)

        context_documents = str(documents[:3])
        context_documents = truncate_text(context_documents, 12000)
        prompt_file = 'files/customer_support_prompt.txt'
        with open(prompt_file, "r") as file:
            prompt_contents_template = file.read()
            prompt = prompt_contents_template.format(question=question, context_documents=context_documents)
            augmented_prompt = prompt

        messages = [
            SystemMessage(
                content="You are a helpful customer support agent."),
            HumanMessage(content=augmented_prompt)
        ]
        sent_time = datetime.now(tz=timezone.utc)
        chat_model = init_chat_model('azure')
        answer = chat_model(messages).content
        received_time = datetime.now(tz=timezone.utc)
        log_llm_interaction(augmented_prompt, answer, sent_time, received_time, 'original', 'azure', model_id, 'customer support')
    context = {
        "question": question,
        "answer": answer,
        "supporting_results": documents
    }
    return render(request, "onlinebanking/customer_support.html", context)


def financial_analysis(request):
    # search elastic for user transactions and aggregate them by category
    es = Elasticsearch(
        cloud_id=elastic_cloud_id,
        http_auth=(elastic_user, elastic_password)
    )
    query = {
        "size": 0,
        "query": {
            "term": {
                "customer_name.keyword": {
                    "value": "Moe Money"
                }
            }
        },
        "aggs": {
            "retail_categories": {
                "terms": {
                    "field": "retail_category.keyword"
                },
                "aggs": {
                    "total_transaction_value": {
                        "sum": {
                            "field": "transaction_value"
                        }
                    }
                }
            }
        }
    }
    field_list = ["transaction_date", "description", "transaction_value", "transaction_category", "retailer_category"]
    results = es.search(index=index_name, body=query, fields=field_list)

    categories = []
    for bucket in results['aggregations']['retail_categories']['buckets']:
        category = {
            'name': bucket['key'],
            'total_value': bucket['total_transaction_value']['value']
        }
        categories.append(category)

    context = {
        'categories': categories
    }

    if request.method == 'POST':
        transaction_info_list = []
        if request.POST.get('interested'):
            # get current banking product offers
            all_offers = BankingProducts.objects.all()
            demo_user = Customer.objects.filter(id=customer_id).first()
            for offer in all_offers:
                offer_query = {
                    "bool": {
                        "should": [
                            {
                                "text_expansion": {
                                    "ml.inference.description_expanded.predicted_value": {
                                        "model_id": model_id,
                                        "model_text": offer.description,
                                        "boost": 1
                                    }
                                }
                            },
                            {
                                "match": {
                                    "description": {
                                        "query": offer.description,
                                        "boost": 1
                                    }

                                }
                            }
                        ],
                        "filter": {
                            "term": {
                                "customer_email.keyword": demo_user.email
                            }
                        }
                    }
                }
                offer_field_list = ["transaction_date", "description", "transaction_value", "transaction_category",
                                    "retail_category"]
                matching_transactions = es.search(index=index_name, query=offer_query, min_score=10,
                                                  fields=offer_field_list)
                if matching_transactions['hits']['total']['value'] > 1:
                    for hit in matching_transactions['hits']['hits']:
                        transaction_info = {
                            "score": hit["_score"],
                            "offer_name": offer.product_name,
                            "offer_description": offer.description,
                            "transaction_description": hit["_source"]["description"],
                            "purchase_value": hit["_source"]["transaction_value"]
                        }
                        transaction_info_list.append(transaction_info)
                    transaction_df = pd.DataFrame(transaction_info_list)
                    offer_summary = transaction_df.groupby('offer_name').agg(
                        {'purchase_value': 'sum', 'score': 'sum', 'offer_description': 'first'}).reset_index()
                    offer_summary_dict = offer_summary.to_dict(orient='records')
                    demo_scenario_details = DemoScenarios.objects.get(active=True)
                    demo_scenario_dict = {
                        "My region": demo_scenario_details.user_geography,
                        "Facts about me": demo_scenario_details.custom_attributes
                    }
                    prompt_file = 'files/product_offer_prompt.txt'
                    with open(prompt_file, "r") as file:
                        prompt_contents_template = file.read()
                        prompt = prompt_contents_template.format(offer_summary=offer_summary, demo_scenario=demo_scenario_dict)
                        augmented_prompt = prompt
                    messages = [
                        SystemMessage(
                            content="You are a helpful customer support agent."),
                        HumanMessage(content=augmented_prompt)
                    ]
                    sent_time = datetime.now(tz=timezone.utc)
                    chat_model = init_chat_model('azure')
                    answer = chat_model(messages).content
                    received_time = datetime.now(tz=timezone.utc)
                    log_llm_interaction(augmented_prompt, answer, sent_time, received_time, 'original', 'azure', model_id,
                                        'product offer')
                else:
                    offer_summary_dict = []
                    answer = "Your financial needs are currently perfectly met by your existing suite of products. Well done!"
        else:
            offer_summary_dict = []
            answer = "You have chosen not to review your financial products."

        context = {
            "transaction_list": transaction_info_list,
            'categories': categories,
            'offer_summary': offer_summary_dict,
            'answer': answer
        }

    return render(request, "onlinebanking/financial_analysis.html", context)


def search(request):
    question = ""
    if request.method == 'POST':
        question = request.POST.get('question')
        demo_user = Customer.objects.filter(id=customer_id).first()
        # handle the es connection for the map and conversational search components
        es = Elasticsearch(
            cloud_id=elastic_cloud_id,
            http_auth=(elastic_user, elastic_password)
        )

        query = {
            "bool": {
                "should": [
                    {
                        "text_expansion": {
                            "ml.inference.description_expanded.predicted_value": {
                                "model_id": model_id,
                                "model_text": question,
                                "boost": 10
                            }
                        }
                    },
                    {
                        "match": {
                            "description": question
                        }
                    }
                ],
                "filter": {
                    "term": {
                        "customer_email.keyword": demo_user.email
                    }
                }
            }
        }

        field_list = ["transaction_date", "description", "transaction_value",
                      "transaction_category", "bank_account_number", "opening_balance", "closing_balance", "_score"]
        results = es.search(index=index_name, query=query, size=100, min_score=1)
        print(results)
        response_data = [{"_score": hit["_score"], **hit["_source"]} for hit in results["hits"]["hits"]]
        transaction_results = []
        # Check if there are hits
        if "hits" in results and "total" in results["hits"]:
            total_hits = results["hits"]["total"]
            # Check if there are any hits with a value greater than 0
            if isinstance(total_hits, dict) and "value" in total_hits and total_hits["value"] > 0:
                for hit in response_data:
                    doc_data = {field: hit[field] for field in field_list if field in hit}
                    transaction_results.append(doc_data)
    else:
        transaction_results = []
    context = {
        'question': question,
        'results': transaction_results,
    }
    return render(request, "onlinebanking/search.html", context)


def transactions(request, bank_account_id):
    if request.method == 'POST':
        keyword = request.POST.get('keyword', '')
        transaction_list = AccountTransaction.objects.filter(
            Q(bank_account=bank_account_id) &
            (Q(description__icontains=keyword) | Q(transaction_date__icontains=keyword))
        ).order_by('-transaction_date')
    else:
        transaction_list = AccountTransaction.objects.filter(bank_account=bank_account_id).order_by(
            '-transaction_date')
    context = {
        'transaction_list': transaction_list,
        'bank_account_id': bank_account_id
    }
    return render(request, "onlinebanking/transactions.html", context)


def landing(request):
    demo_user = Customer.objects.filter(id=customer_id).first()
    # handle the es connection for the map and conversational search components
    es = Elasticsearch(
        cloud_id=elastic_cloud_id,
        http_auth=(elastic_user, elastic_password)
    )

    # handle any form posting
    if request.method == 'POST':
        payment_form = AccountTransactionForm(request.POST)
        transfer_form = AccountTransferForm(request.POST)

        if payment_form.is_valid():
            # get latest balance
            latest_transaction = AccountTransaction.objects.filter(
                bank_account=payment_form.cleaned_data['bank_account']).order_by('-timestamp').first()

            new_transaction = payment_form.save(commit=False)
            new_transaction.opening_balance = latest_transaction.closing_balance
            new_transaction.transaction_value = payment_form.cleaned_data['transaction_value']
            new_transaction.closing_balance = new_transaction.opening_balance - new_transaction.transaction_value
            new_description = f"Payment to {payment_form.cleaned_data['target_bank']} | {payment_form.cleaned_data['target_account']}. {new_transaction.description}"
            new_transaction.description = new_description
            new_transaction.transaction_date = datetime.now(tz=timezone.utc)
            new_transaction.save()

        if transfer_form.is_valid():
            # work out the closing balance for the source account and save the record
            latest_transaction_source_account = AccountTransaction.objects.filter(
                bank_account=payment_form.cleaned_data['bank_account']).order_by('-timestamp').first()

            new_outbound_transfer = transfer_form.save(commit=False)
            new_outbound_transfer.opening_balance = latest_transaction_source_account.closing_balance
            new_outbound_transfer.closing_balance = new_outbound_transfer.opening_balance - new_outbound_transfer.transaction_value
            new_outbound_description = f"Outbound transfer to {transfer_form.cleaned_data['target_account']}. {transfer_form.cleaned_data['description']}"
            new_outbound_transfer.description = new_outbound_description
            new_outbound_transfer.transaction_date = datetime.now(tz=timezone.utc)

            new_outbound_transfer.save()

            # work out the closing balance for the target account and save the record
            new_inbound_transfer = AccountTransaction()
            latest_transaction_target_account = AccountTransaction.objects.filter(
                bank_account=transfer_form.cleaned_data['target_account']).order_by('-timestamp').first()
            new_inbound_transfer.transaction_value = transfer_form.cleaned_data['transaction_value']
            new_inbound_transfer.opening_balance = latest_transaction_target_account.closing_balance
            new_inbound_transfer.closing_balance = new_inbound_transfer.opening_balance + new_inbound_transfer.transaction_value
            new_inbound_description = f"Inbound transfer from {new_outbound_transfer.bank_account}. {transfer_form.cleaned_data['description']} "
            new_inbound_transfer.description = new_inbound_description
            new_inbound_transfer.bank_account = transfer_form.cleaned_data['target_account']
            new_inbound_transfer.transaction_type = transfer_form.cleaned_data['transaction_type']
            new_inbound_transfer.transaction_category = transfer_form.cleaned_data['transaction_category']
            new_inbound_transfer.transaction_date = datetime.now(tz=timezone.utc)
            new_inbound_transfer.save()

        records_to_import = AccountTransaction.objects.filter(exported=0)
        for r in records_to_import:
            payload = build_record(r.id)
            index_response = es.index(index=index_name, id=r.id, document=payload, pipeline=pipeline_name)
            r.exported = 1
            r.save()
    payment_form = AccountTransactionForm()
    transfer_form = AccountTransferForm()
    account_list = BankAccount.objects.filter(customer=customer_id)
    account_dict_list = []
    for a in account_list:
        latest_transaction = AccountTransaction.objects.filter(bank_account=a).order_by(
            '-transaction_date').first()
        if latest_transaction:
            account_dict = {
                'id': a.id,
                'account_number': a.account_number,
                'latest_balance': latest_transaction.closing_balance
            }
            account_dict_list.append(account_dict)
    context = {
        'account_dict_list': account_dict_list,
        'payment_form': payment_form,
        'transfer_form': transfer_form,
    }
    return render(request, "onlinebanking/index.html", context)
