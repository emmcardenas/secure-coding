from django.shortcuts import render

from nameserver.forms import NameServerInfoForm

from os import popen3


# View method to check domain info
def index(request):
    output = None
    # Checking request method
    if request.method == 'POST':
        # Initialising form with POST request
        form = NameServerInfoForm(request.POST)
        # Validating form inputs
        if form.is_valid():
            process_output = popen3('nslookup ' + form.cleaned_data['domain_url'], 'r')
            output = process_output[1].read()
    else:
        # Initialising empty form
        form = NameServerInfoForm()

    return render(request, 'nameserver/index.html', {'form': form, 'output': output})