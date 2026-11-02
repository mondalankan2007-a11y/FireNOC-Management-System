from django.shortcuts import render


def home(request):
    """
    Landing page for the FireNOC Management System project.
    Provides project overview and entry points to modules.
    """
    return render(request, 'home.html')

