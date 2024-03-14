import json
import googlemaps
import elasticsearch
from django.shortcuts import render
from .models import BankAccount, AccountTransaction, Customer, Retailer, BankingProducts
from .forms import AccountTransactionForm, AccountTransferForm
from elasticsearch import Elasticsearch
import boto3
from langchain.chat_models import AzureChatOpenAI
from langchain.llms import Bedrock, AzureOpenAI
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta, timezone
import tiktoken
import nltk
from nltk.tokenize import word_tokenize
import re
from config import settings
import pandas as pd
from django.db.models import Q

load_dotenv()

from langchain.schema import (
    SystemMessage,
    HumanMessage,
    AIMessage
)
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
            temperature=1
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
        customer_support_results = es.search(index=customer_support_index, query=query, size=100, fields=customer_support_field_list, min_score=10)
        response_data = [{"_score": hit["_score"], **hit["_source"]} for hit in customer_support_results["hits"]["hits"]]
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
        context_documents = str(documents)
        context_documents = truncate_text(context_documents, 12000)
        augmented_prompt = f"""Please answer the following question using only the documents provided as context: {question}. 
        Context: 
        {context_documents}
        Format your response using Bootstrap
        """
        messages = [
            SystemMessage(
                content="You are a helpful customer support agent."),
            HumanMessage(content=augmented_prompt)
        ]
        chat_model = init_chat_model('azure')
        answer = chat_model(messages).content
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
        # get current banking product offers
        all_offers = BankingProducts.objects.all()
        demo_user = Customer.objects.filter(id=customer_id).first()
        transaction_info_list = []
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
            matching_transactions = es.search(index=index_name, query=offer_query, min_score=10, fields=offer_field_list)
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
        print(offer_summary_dict)

        augmented_prompt = f"""The following special offers are 
        relevant to me based on the these spending patterns:
        {offer_summary}
        Also take into account that I live in the Netherlands, I have 2 children and have a mortgage.
        
        Your job is to use tell me about any offers that would suit me and describe why I should consider them.
        Be as brief as possible and do not refer to the field names with underscores in them and use Bootstrap to format your answer nicely so that they 
        appear in a list and are easy to read.
        """
        messages = [
            SystemMessage(
                content="You are a helpful customer support agent."),
            HumanMessage(content=augmented_prompt)
        ]
        chat_model = init_chat_model('azure')
        answer = chat_model(messages).content
        context = {
            "transaction_list": transaction_info_list,
            'categories': categories,
            'offer_summary': offer_summary_dict,
            'answer': answer
        }

    return render(request, "onlinebanking/financial_analysis.html", context)


def search(request):
    question = ""
    summary = ""
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
                      "transaction_category", "bank_account_number","opening_balance", "closing_balance", "_score"]
        results = es.search(index=index_name, query=query, size=100, min_score=10)
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
            if 'summarise' in request.POST:
                augmented_prompt = f"""Please summarise the following banking transactions into categories, which were returned as part 
                of a search for the following phrase: { question }. 
                {transaction_results}
                Format your response using Bootstrap
                """
                messages = [
                    SystemMessage(
                        content="You are a helpful customer support agent."),
                    HumanMessage(content=augmented_prompt)
                ]
                chat_model = init_chat_model('azure')
                summary = chat_model(messages).content
    else:
        transaction_results = []
    context = {
        'question': question,
        'results': transaction_results,
        'summary': summary
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
