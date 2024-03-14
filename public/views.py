from django.shortcuts import render
from config import settings

# from envmanager.models import ClusterDetail
# Create your views here.
kibana_url = getattr(settings, 'kibana_url', None)
def home(request):
    context = {
        'kibana_url': kibana_url
    }
    return render(request, 'index.html', context)
