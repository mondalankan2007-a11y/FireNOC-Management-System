from django.shortcuts import render


def applicant_home(request):
    """
    Applicant home/dashboard placeholder view.
    Renders the Applicant Portal landing page with placeholder actions.
    """
    return render(request, 'applicants/applicant_home.html')
