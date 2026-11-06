from django.shortcuts import render


def applicant_home(request):
    """
    Applicant home/dashboard placeholder view.
    Renders the Applicant Portal landing page with placeholder actions.
    """
    return render(request, 'applicants/applicant_home.html')


def register(request):
    """
    Applicant registration UI view.
    Renders the registration form for Fire NOC applicants.
    """
    return render(request, 'applicants/register.html')
