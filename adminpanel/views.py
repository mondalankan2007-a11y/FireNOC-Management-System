from django.shortcuts import render


def admin_home(request):
    """
    Admin Module landing page.

    Entry point for the Admin + Database + NOC module. Later commits attach
    the department dashboard, applicant/officer management, application
    monitoring, NOC issuance and reporting views beneath this namespace.
    """
    return render(request, 'adminpanel/admin_home.html')
