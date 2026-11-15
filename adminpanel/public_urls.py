"""
The routes in this module are the only ones in the admin app that do not
require an account.

Certificate verification is useless behind a sign-in. The people who need to
check a Fire NOC — a landlord's bank, an insurer, a venue's licensing officer,
a tenant — have no business having accounts in the fire department's system,
and asking them to register in order to read a certificate they are already
holding would mean nobody ever checks one.

Mounted at /verify/ rather than under /admin-panel/ for the same reason: the
address is printed on a public document, so it should not look like part of a
restricted area.
"""

from django.urls import path

from . import views

app_name = 'verify'

urlpatterns = [
    # Where the QR code on a printed certificate leads.
    path('<str:number>/<str:code>/', views.verify_certificate, name='certificate'),

    # The same check, for someone typing the details from the paper by hand.
    path('', views.verify_certificate, name='form'),
]
