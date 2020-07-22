from django.shortcuts import render

from nameserver.forms import NameServerInfoForm

from subprocess import Popen, PIPE


# View method to check domain info
def index(request):
    output = None
    # Checking request method
    if request.method == 'POST':
        # Initialising form with POST request
        form = NameServerInfoForm(request.POST)
        # Validating form inputs
        if form.is_valid():
            process_output = Popen(['nslookup', form.cleaned_data['domain_url']], stdout=PIPE)
            output = process_output.communicate()[0]
            if process_output.returncode:
                output = 'Please enter valid domain.'

    else:
        # Initialising empty form
        form = NameServerInfoForm()

    return render(request, 'nameserver/index.html', {'form': form, 'output': output})
