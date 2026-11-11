from django.shortcuts import render


def officer_home(request):
    """
    Fire Officer module landing page view.
    Renders the Officer / Inspection module home page with module overview
    and feature status.
    """
    return render(request, 'officers/officer_home.html')
