from django.shortcuts import render


def applicant_home(request):
    """
    Initial placeholder view for the Applicant Module.
    Full functionality will be added in subsequent commits.
    """
    return render(request, 'applicants/home.html')
