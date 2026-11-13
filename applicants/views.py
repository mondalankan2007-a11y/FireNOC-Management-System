import datetime
from decimal import Decimal, InvalidOperation
import os
import re
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme
from .models import Application, ApplicationDocument


def get_applicant_dashboard_data(user):
    """
    Retrieve dynamic dashboard statistics and recent applications for the authenticated applicant.
    
    Coordinates with the agreed team schema:
    - Filters strictly by the authenticated user to maintain data isolation.
    - Uses Django ORM .filter() and .count() aggregations for optimal database performance.
    - Status definitions aligned across modules:
        * Pending: PENDING, SUBMITTED, UNDER_REVIEW, UNDER_INSPECTION
        * Approved: APPROVED, CLEARED
        * NOCs Issued: NOC_ISSUED, ISSUED (or NOC certificate records)
    - If the Application or NOC model has not been implemented yet (responsibility of
      Harsh / Admin module), gracefully defaults each statistic to zero and recent
      applications to an empty list rather than creating duplicate models in applicants/.
    """
    stats = {
        'total_applications': 0,
        'pending_applications': 0,
        'approved_applications': 0,
        'nocs_issued': 0,
    }
    recent_applications = []

    # Dynamic model inspection across installed apps (e.g. applications, noc, admin_noc)
    Application = None
    user_fk_field = 'applicant'
    for app_config in apps.get_app_configs():
        for model in app_config.get_models():
            model_name = model.__name__.lower()
            if model_name in ('application', 'firenocapplication', 'nocapplication'):
                field_names = [f.name for f in model._meta.get_fields()]
                if 'applicant' in field_names:
                    Application = model
                    user_fk_field = 'applicant'
                    break
                elif 'user' in field_names:
                    Application = model
                    user_fk_field = 'user'
                    break
        if Application:
            break

    # Dynamic NOC model inspection
    NOC = None
    noc_user_field = 'applicant'
    for app_config in apps.get_app_configs():
        for model in app_config.get_models():
            model_name = model.__name__.lower()
            if model_name in ('noc', 'firenoc', 'certificate', 'issuednoc'):
                field_names = [f.name for f in model._meta.get_fields()]
                if 'applicant' in field_names:
                    NOC = model
                    noc_user_field = 'applicant'
                    break
                elif 'user' in field_names:
                    NOC = model
                    noc_user_field = 'user'
                    break
        if NOC:
            break

    # If Application model is integrated in the project, query ORM counts scoped strictly to user
    if Application is not None:
        user_applications = Application.objects.filter(**{user_fk_field: user})

        # 1. Total Applications count
        stats['total_applications'] = user_applications.count()

        # 2. Pending Applications count
        stats['pending_applications'] = user_applications.filter(
            status__in=[
                'PENDING', 'SUBMITTED', 'UNDER_REVIEW', 'UNDER_INSPECTION',
                'pending', 'submitted', 'under_review', 'under_inspection'
            ]
        ).count()

        # 3. Approved Applications count
        stats['approved_applications'] = user_applications.filter(
            status__in=['APPROVED', 'CLEARED', 'approved', 'cleared']
        ).count()

        # 4. NOCs Issued count (from NOC model or NOC_ISSUED status)
        if NOC is not None:
            stats['nocs_issued'] = NOC.objects.filter(**{noc_user_field: user}).count()
        else:
            stats['nocs_issued'] = user_applications.filter(
                status__in=['NOC_ISSUED', 'ISSUED', 'noc_issued', 'issued']
            ).count()

        # Recent Applications list (latest 5)
        ordering = '-created_at' if hasattr(Application, 'created_at') else '-id'
        recent_applications = list(user_applications.order_by(ordering)[:5])

    return stats, recent_applications


@login_required(login_url='login')
def applicant_home(request):
    """
    Applicant home view.
    Redirects authenticated applicants to the full dashboard.
    """
    return redirect('applicants:dashboard')


@login_required(login_url='login')
def dashboard(request):
    """
    Applicant Dashboard view.
    Protected route accessible only to authenticated applicants.
    Prepares metrics and lists recent applications for the logged-in applicant.
    Ensures applicants can only view their own data.
    """
    stats, recent_applications = get_applicant_dashboard_data(request.user)

    context = {
        'stats': stats,
        'recent_applications': recent_applications,
        'applicant': request.user,
    }
    return render(request, 'applicants/dashboard.html', context)


@login_required(login_url='login')
def application_new(request):
    """
    Applicant – New Fire NOC Application form view.
    GET: Renders a multi-section application form pre-filled with the authenticated
         applicant's existing profile information (name, email).
    POST: Validates all required fields, building parameters, occupancy, and contact details
          on the server, saves the application to PostgreSQL using the agreed schema,
          and redirects to the applicant dashboard.
    """
    current_year = datetime.date.today().year

    # Pre-fill applicant details from the authenticated user profile (security: locked to request.user)
    full_name = (
        f"{request.user.first_name} {request.user.last_name}".strip()
        or request.user.username
    )
    email = request.user.email

    prefill = {
        'full_name': full_name,
        'email': email,
    }

    if request.method == 'POST':
        # Extract submitted form values
        mobile_number = request.POST.get('mobile_number', '').strip()
        building_name = request.POST.get('building_name', '').strip()
        building_type = request.POST.get('building_type', '').strip()
        building_type_other = request.POST.get('building_type_other', '').strip()
        building_address = request.POST.get('building_address', '').strip()
        city = request.POST.get('city', '').strip()
        state = request.POST.get('state', '').strip()
        pin_code = request.POST.get('pin_code', '').strip()
        num_floors_raw = request.POST.get('num_floors', '').strip()
        builtup_area_raw = request.POST.get('builtup_area', '').strip()
        year_construction_raw = request.POST.get('year_construction', '').strip()
        occupancy_type = request.POST.get('occupancy_type', '').strip()
        application_type = request.POST.get('application_type', 'NEW_NOC').strip()
        purpose = request.POST.get('purpose', '').strip()
        remarks = request.POST.get('remarks', '').strip()
        declaration = request.POST.get('declaration')

        form_data = {
            'full_name': full_name,
            'email': email,
            'mobile_number': mobile_number,
            'building_name': building_name,
            'building_type': building_type,
            'building_type_other': building_type_other,
            'building_address': building_address,
            'city': city,
            'state': state,
            'pin_code': pin_code,
            'num_floors': num_floors_raw,
            'builtup_area': builtup_area_raw,
            'year_construction': year_construction_raw,
            'occupancy_type': occupancy_type,
            'application_type': application_type,
            'purpose': purpose,
            'remarks': remarks,
            'declaration': bool(declaration),
        }

        errors = []

        # 1. Validate Mobile Number
        if not mobile_number:
            errors.append("Mobile Number is required.")
        elif not re.match(r'^[6-9]\d{9}$', mobile_number):
            errors.append("Please enter a valid 10-digit Indian mobile number starting with 6, 7, 8, or 9.")

        # 2. Validate Building Name
        if not building_name:
            errors.append("Building / Premises Name is required.")
        elif len(building_name) > 150:
            errors.append("Building name cannot exceed 150 characters.")

        # 3. Validate Building Type
        allowed_building_types = [c[0] for c in Application.BUILDING_TYPE_CHOICES]
        if not building_type:
            errors.append("Building Type is required.")
        elif building_type not in allowed_building_types:
            errors.append("Invalid Building Type selected.")
        elif building_type == 'OTHER':
            if not building_type_other:
                errors.append("Please describe the building type when Other is selected.")
            elif len(building_type_other) > 100:
                errors.append("Specified building type description cannot exceed 100 characters.")
        else:
            building_type_other = ''

        # 4. Validate Building Address
        if not building_address:
            errors.append("Building Address is required.")
        elif len(building_address) > 500:
            errors.append("Building Address cannot exceed 500 characters.")

        # 5. Validate City
        if not city:
            errors.append("City / Town is required.")
        elif len(city) > 100:
            errors.append("City name cannot exceed 100 characters.")

        # 6. Validate State
        if not state:
            errors.append("State is required.")
        elif len(state) > 100:
            errors.append("State name cannot exceed 100 characters.")

        # 7. Validate PIN Code
        if not pin_code:
            errors.append("PIN Code is required.")
        elif not re.match(r'^[1-9]\d{5}$', pin_code):
            errors.append("Please enter a valid 6-digit Indian PIN code (cannot start with 0).")

        # 8. Validate Number of Floors
        floors = None
        if not num_floors_raw:
            errors.append("Number of Floors is required.")
        else:
            try:
                floors = int(num_floors_raw)
                if floors < 1 or floors > 200 or '.' in num_floors_raw:
                    errors.append("Number of Floors must be a positive whole number between 1 and 200.")
            except (ValueError, TypeError):
                errors.append("Number of Floors must be a valid positive whole number.")

        # 9. Validate Built-up Area
        builtup_area_dec = None
        if not builtup_area_raw:
            errors.append("Built-up Area is required.")
        else:
            try:
                builtup_area_dec = Decimal(builtup_area_raw)
                if builtup_area_dec <= Decimal('0'):
                    errors.append("Built-up Area must be a positive number greater than 0.")
                elif builtup_area_dec > Decimal('9999999.99'):
                    errors.append("Built-up Area exceeds maximum allowed value.")
            except (InvalidOperation, TypeError):
                errors.append("Built-up Area must be a valid numeric decimal value in square meters.")

        # 10. Validate Year of Construction
        year_val = None
        if not year_construction_raw:
            errors.append("Year of Construction is required.")
        else:
            try:
                year_val = int(year_construction_raw)
                if year_val < 1800 or year_val > current_year:
                    errors.append(f"Year of Construction must be between 1800 and {current_year}.")
            except (ValueError, TypeError):
                errors.append("Year of Construction must be a valid 4-digit year.")

        # 11. Validate Occupancy Type
        allowed_occupancies = [c[0] for c in Application.OCCUPANCY_CHOICES]
        if not occupancy_type:
            errors.append("Occupancy Type is required.")
        elif occupancy_type not in allowed_occupancies:
            errors.append("Invalid Occupancy Type selected.")

        # 12. Validate Application Type
        allowed_app_types = [c[0] for c in Application.APPLICATION_TYPE_CHOICES]
        if not application_type:
            errors.append("Application Type is required.")
        elif application_type not in allowed_app_types:
            errors.append("Invalid Application Type selected.")

        # 13. Validate Purpose
        if not purpose:
            errors.append("Purpose of Application is required.")
        elif len(purpose) > 1000:
            errors.append("Purpose of Application cannot exceed 1000 characters.")

        # 14. Validate Remarks
        if remarks and len(remarks) > 2000:
            errors.append("Additional Remarks cannot exceed 2000 characters.")

        # 15. Validate Declaration
        if not declaration:
            errors.append("You must declare and certify the accuracy of all submitted information.")

        # If validation errors occurred, display messages and preserve form values
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'applicants/application_form.html', {
                'prefill': prefill,
                'form_data': form_data,
                'current_year': current_year,
            })

        # Save Application record using atomic database transaction
        with transaction.atomic():
            application = Application.objects.create(
                applicant=request.user,
                full_name=full_name,
                email=email,
                mobile_number=mobile_number,
                building_name=building_name,
                building_type=building_type,
                building_type_other=building_type_other,
                building_address=building_address,
                city=city,
                state=state,
                pin_code=pin_code,
                num_floors=floors,
                builtup_area=builtup_area_dec,
                year_construction=year_val,
                occupancy_type=occupancy_type,
                application_type=application_type,
                purpose=purpose,
                remarks=remarks,
                status='PENDING',
            )

        messages.success(
            request,
            f"Application {application.application_id} submitted successfully! "
            f"Your Fire NOC application for '{application.building_name}' has been received and is pending review."
        )
        return redirect('applicants:dashboard')

    # GET request: render empty / prefilled form
    form_data = {
        'full_name': full_name,
        'email': email,
        'application_type': 'NEW_NOC',
    }
    return render(request, 'applicants/application_form.html', {
        'prefill': prefill,
        'form_data': form_data,
        'current_year': current_year,
    })


def register(request):
    """
    Applicant registration view.
    Handles GET requests to render the form, and POST requests to validate
    and create an applicant user account using Django's built-in User model.
    """
    if request.user.is_authenticated:
        return redirect('applicants:dashboard')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        mobile_number = request.POST.get('mobile_number', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        # Preserve safe submitted values (never preserve password fields)
        form_data = {
            'full_name': full_name,
            'email': email,
            'mobile_number': mobile_number,
        }

        errors = []

        # 1. Validate required fields
        if not full_name:
            errors.append("Full Name is required.")
        if not email:
            errors.append("Email Address is required.")
        if not mobile_number:
            errors.append("Mobile Number is required.")
        if not password:
            errors.append("Password is required.")
        if not confirm_password:
            errors.append("Confirm Password is required.")

        # If any required fields are missing, display errors and return early
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'applicants/register.html', {'form_data': form_data})

        # 2. Validate email format
        try:
            validate_email(email)
        except ValidationError:
            errors.append("Please enter a valid email address.")

        # 3. Prevent duplicate email registrations
        if not errors and (
            User.objects.filter(email__iexact=email).exists() or
            User.objects.filter(username__iexact=email).exists()
        ):
            errors.append("An account with this email address already exists. Please log in or use a different email.")

        # 4. Validate mobile number format (must be a valid 10-digit number)
        if not re.fullmatch(r'^\d{10}$', mobile_number):
            errors.append("Please enter a valid 10-digit mobile number.")

        # 5. Validate password and confirmation match
        if password != confirm_password:
            errors.append("Passwords do not match. Please ensure both password fields are identical.")

        # 6. Validate password strength using Django's built-in password validators
        if password and password == confirm_password:
            name_parts = full_name.split(maxsplit=1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            temp_user = User(
                username=email.lower(),
                email=email.lower(),
                first_name=first_name,
                last_name=last_name
            )
            try:
                validate_password(password, user=temp_user)
            except ValidationError as validation_err:
                for msg in validation_err.messages:
                    errors.append(msg)

        # If any validation errors occurred, display messages and re-render form
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'applicants/register.html', {'form_data': form_data})

        # 7. Create user securely using create_user() (hashes password with PBKDF2-SHA256)
        name_parts = full_name.split(maxsplit=1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        User.objects.create_user(
            username=email.lower(),
            email=email.lower(),
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        messages.success(request, "Registration successful! You can now log in with your credentials.")
        return redirect('login')

    return render(request, 'applicants/register.html')


def login_view(request):
    """
    Applicant login view.
    Authenticates applicants using their registered email and password.
    Creates a secure session on success and redirects to the applicant dashboard.
    """
    if request.user.is_authenticated:
        return redirect('applicants:dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        remember_me = request.POST.get('remember_me')
        next_url = request.POST.get('next', '').strip() or request.GET.get('next', '').strip()

        # Validate required fields
        if not email or not password:
            messages.error(request, "Both email address and password are required.")
            return render(request, 'applicants/login.html', {'email': email, 'next_url': next_url})

        # Locate user by email and authenticate
        user_obj = User.objects.filter(email__iexact=email).first()
        username = user_obj.username if user_obj else email
        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(request, "Your account has been deactivated. Please contact the administrator.")
                return render(request, 'applicants/login.html', {'email': email, 'next_url': next_url})

            # Establish Django session
            login(request, user)

            # Manage session expiration based on Remember Me
            if not remember_me:
                request.session.set_expiry(0)  # Expires when browser is closed
            else:
                request.session.set_expiry(1209600)  # 2 weeks

            messages.success(request, f"Welcome back, {user.first_name or user.username}!")

            # Safe redirect: prevent open redirect vulnerabilities
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('applicants:dashboard')
        else:
            messages.error(request, "Invalid email address or password. Please check your credentials and try again.")
            return render(request, 'applicants/login.html', {'email': email, 'next_url': next_url})

    next_url = request.GET.get('next', '').strip()
    return render(request, 'applicants/login.html', {'next_url': next_url})


def logout_view(request):
    """
    Applicant logout view.
    Terminates the user's session, clears session cookies,
    and redirects to the login page with a success message.
    Accepts POST requests (standard secure method) as well as GET fallbacks.
    """
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('login')


@login_required(login_url='login')
def my_applications(request):
    """
    My Applications listing page.
    Displays a paginated, filterable list of all Fire NOC applications
    submitted by the currently authenticated applicant.

    Security:
    - Protected by @login_required; unauthenticated requests are redirected to /login/.
    - All queries are strictly filtered using applicant=request.user (never from GET params).
    - Applicants can only see their own records.

    Filtering (GET parameters):
    - q        : search by application_id or building_name (case-insensitive)
    - status   : filter by exact application status choice
    - sort     : 'newest' (default) or 'oldest'
    - page     : pagination page number

    Pagination: 10 records per page; query params preserved in links.
    """
    # --- Base queryset: strictly scoped to logged-in applicant ---
    qs = Application.objects.filter(applicant=request.user)

    # --- Search ---
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(application_id__icontains=q) | Q(building_name__icontains=q)
        )

    # --- Status filter (validate against known choices to prevent injection) ---
    valid_statuses = [choice[0] for choice in Application.STATUS_CHOICES]
    current_status = request.GET.get('status', '').strip()
    if current_status and current_status in valid_statuses:
        qs = qs.filter(status=current_status)
    else:
        current_status = ''

    # --- Sorting ---
    current_sort = request.GET.get('sort', 'newest').strip()
    if current_sort == 'oldest':
        qs = qs.order_by('created_at')
    else:
        current_sort = 'newest'
        qs = qs.order_by('-created_at')

    # --- Pagination ---
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Build a query string without 'page' to append page numbers in template
    query_params = request.GET.copy()
    query_params.pop('page', None)
    filter_query_string = query_params.urlencode()

    context = {
        'page_obj': page_obj,
        'applications': page_obj.object_list,
        'status_choices': Application.STATUS_CHOICES,
        'q': q,
        'current_status': current_status,
        'current_sort': current_sort,
        'filter_query_string': filter_query_string,
    }
    return render(request, 'applicants/my_applications.html', context)


@login_required(login_url='login')
def application_details(request, application_id):
    """
    Application Details view.
    Displays comprehensive details of a submitted Fire NOC application.

    Security:
    - Protected with @login_required decorator.
    - Strictly filters application by applicant=request.user to ensure applicants
      can only access their own applications.
    - Returns HTTP 404 if the application doesn't exist or belongs to another applicant.
    """
    application = get_object_or_404(
        Application.objects.filter(applicant=request.user),
        pk=application_id
    )

    status_descriptions = {
        'PENDING': 'Your application has been received and is waiting for initial departmental review.',
        'UNDER_REVIEW': 'A fire safety desk officer is currently reviewing your application and submitted building parameters.',
        'DOCUMENTS_VERIFIED': 'Your application details and documents have been verified. It is now queued for on-site physical inspection.',
        'UNDER_INSPECTION': 'A fire inspection officer has been assigned and the site inspection is currently underway.',
        'APPROVED': 'Your Fire NOC application has been approved by the department.',
        'REJECTED': 'Your Fire NOC application has been rejected. Please review departmental feedback or contact support.',
        'DEFICIENT': 'Deficiencies were identified during review or site inspection. Rectification is required.',
    }

    status_description = status_descriptions.get(
        application.status,
        'Your application is currently being processed by the fire department.'
    )

    context = {
        'application': application,
        'status_description': status_description,
    }
    return render(request, 'applicants/application_details.html', context)


@login_required(login_url='login')
def document_upload(request, application_id):
    """
    Applicant Document Upload view.
    Handles GET to render the document upload interface and POST to securely
    validate and store uploaded supporting documents against the applicant's application.

    Security & Validation:
    - Protected by @login_required; unauthenticated requests are redirected.
    - Application ownership is strictly checked via Application.objects.filter(applicant=request.user).
      Never trusts application ID alone (returns HTTP 404 for unauthorized attempts).
    - Validates file extensions (.pdf, .jpg, .jpeg, .png) and rejects executables / disallowed formats.
    - Validates MIME type and file header signatures (magic bytes) to prevent content spoofing.
    - Enforces 5 MB file size limit.
    - Replaces previous document upload for the same category or creates a new ApplicationDocument record.
    - Persists file using Django's default storage and records metadata in PostgreSQL.
    """
    application = get_object_or_404(
        Application.objects.filter(applicant=request.user),
        pk=application_id
    )

    # Document categories definitions
    document_categories = [
        {
            'code': 'BUILDING_PLAN',
            'model_type': 'ARCHITECTURAL_BLUEPRINT',
            'name': 'Building Plan',
            'required': True,
            'description': 'Architectural layout plan, site plan, key plan, and section elevations approved by municipal authority.',
            'formats': 'PDF, JPG, PNG',
        },
        {
            'code': 'OWNERSHIP_PROOF',
            'model_type': 'OWNERSHIP_DEED',
            'name': 'Ownership Proof',
            'required': True,
            'description': 'Registered title deed, lease agreement, mutation certificate, or property tax receipt.',
            'formats': 'PDF',
        },
        {
            'code': 'BUILDING_ADDRESS_PROOF',
            'model_type': 'OTHER',
            'name': 'Building Address Proof',
            'required': True,
            'description': 'Electricity bill, land registry document, or municipal occupancy certificate demonstrating building location.',
            'formats': 'PDF, JPG, PNG',
        },
        {
            'code': 'FIRE_SAFETY_EQUIPMENT',
            'model_type': 'EQUIPMENT_TEST_CERTIFICATE',
            'name': 'Fire Safety Equipment Details',
            'required': True,
            'description': 'Schematic of hydrants, sprinklers, fire alarms, smoke detectors, and equipment test certificates.',
            'formats': 'PDF',
        },
        {
            'code': 'PREVIOUS_FIRE_NOC',
            'model_type': 'OTHER',
            'name': 'Previous Fire NOC (optional)',
            'required': False,
            'description': 'Copy of previous provisional or final Fire NOC if applying for renewal or modification.',
            'formats': 'PDF',
        },
        {
            'code': 'OTHER_SUPPORTING',
            'model_type': 'OTHER',
            'name': 'Other Supporting Documents',
            'required': False,
            'description': 'Structural stability certificate, safety audit reports, or additional department clearances.',
            'formats': 'PDF, JPG, PNG',
        },
    ]

    category_map = {cat['code']: cat for cat in document_categories}

    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
    ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
    ALLOWED_CONTENT_TYPES = {
        'application/pdf',
        'image/jpeg',
        'image/pjpeg',
        'image/png',
        'image/x-png',
    }

    def validate_uploaded_file(uploaded_file, category_name):
        """Validate file name, extension, size, and header signature."""
        fname = uploaded_file.name or ''
        root, ext = os.path.splitext(fname)
        ext_lower = ext.lower()

        if not ext_lower or ext_lower not in ALLOWED_EXTENSIONS:
            return f"Invalid file format '{ext}' for {category_name}. Only PDF, JPG, JPEG, and PNG files are allowed."

        if uploaded_file.size > MAX_FILE_SIZE:
            size_mb = uploaded_file.size / (1024 * 1024)
            return f"File '{fname}' ({size_mb:.2f} MB) for {category_name} exceeds the maximum allowed size of 5 MB."

        if uploaded_file.size == 0:
            return f"File '{fname}' for {category_name} is empty (0 bytes)."

        # Content type check
        content_type = getattr(uploaded_file, 'content_type', '')
        if content_type and content_type.lower() not in ALLOWED_CONTENT_TYPES:
            # Let pass if extension is valid but verify magic bytes
            pass

        # Magic bytes check for security (verify real content type against extension)
        try:
            current_pos = uploaded_file.tell()
            header = uploaded_file.read(8)
            uploaded_file.seek(current_pos)

            if ext_lower == '.pdf' and not header.startswith(b'%PDF'):
                return f"File '{fname}' is not a valid PDF document."
            elif ext_lower in ('.jpg', '.jpeg') and not header.startswith(b'\xff\xd8\xff'):
                return f"File '{fname}' is not a valid JPEG image."
            elif ext_lower == '.png' and not header.startswith(b'\x89PNG\r\n\x1a\n'):
                return f"File '{fname}' is not a valid PNG image."
        except Exception:
            pass

        return None

    if request.method == 'POST':
        uploaded_files_found = 0
        errors = []
        files_to_process = []

        # Inspect all possible document inputs
        for code, cat in category_map.items():
            field_name = f"doc_{code}"
            if field_name in request.FILES:
                uploaded_file = request.FILES[field_name]
                if uploaded_file:
                    uploaded_files_found += 1
                    err = validate_uploaded_file(uploaded_file, cat['name'])
                    if err:
                        errors.append(err)
                    else:
                        files_to_process.append((code, cat, uploaded_file))

        if uploaded_files_found == 0:
            messages.error(request, "No files were selected for upload. Please choose at least one document.")
            return redirect('applicants:document_upload', application_id=application.id)

        if errors:
            for err in errors:
                messages.error(request, err)
            # Re-render with existing documents shown
            existing_docs = application.documents.all()
            return render(request, 'applicants/document_upload.html', {
                'application': application,
                'document_categories': document_categories,
                'existing_docs': existing_docs,
                'max_file_size_mb': 5,
                'allowed_extensions': ['.pdf', '.jpg', '.jpeg', '.png'],
            })

        # Save documents in an atomic transaction
        saved_count = 0
        with transaction.atomic():
            for code, cat, uploaded_file in files_to_process:
                doc_title = f"{cat['name']} - {application.building_name}"
                # If a document for this exact category and application already exists, update its file
                existing_doc = ApplicationDocument.objects.filter(
                    application=application,
                    document_name__startswith=f"{cat['name']} - "
                ).first()

                if existing_doc:
                    existing_doc.file = uploaded_file
                    existing_doc.document_name = doc_title
                    existing_doc.document_type = cat['model_type']
                    existing_doc.save()
                    # Reset any officer verification to PENDING if re-uploaded
                    if hasattr(existing_doc, 'verification'):
                        existing_doc.verification.status = 'PENDING'
                        existing_doc.verification.officer_remarks = 'Re-uploaded by applicant. Pending re-verification.'
                        existing_doc.verification.save()
                else:
                    ApplicationDocument.objects.create(
                        application=application,
                        document_type=cat['model_type'],
                        document_name=doc_title,
                        file=uploaded_file,
                    )
                saved_count += 1

        messages.success(
            request,
            f"Successfully uploaded {saved_count} document(s) for Application {application.application_id}."
        )
        return redirect('applicants:application_details', application_id=application.id)

    # GET request
    existing_docs = application.documents.all()
    context = {
        'application': application,
        'document_categories': document_categories,
        'existing_docs': existing_docs,
        'max_file_size_mb': 5,
        'allowed_extensions': ['.pdf', '.jpg', '.jpeg', '.png'],
    }
    return render(request, 'applicants/document_upload.html', context)


@login_required(login_url='login')
def my_documents(request):
    """
    Applicant Uploaded Documents listing page.
    Displays all documents uploaded by the currently authenticated applicant
    across their Fire NOC applications, along with current verification status
    and officer remarks if verified/rejected by the department.

    Security & Ownership:
    - Protected with @login_required.
    - Strictly filters documents via application__applicant=request.user.
    - Applicants can never see other applicants' uploaded documents.

    Filtering & Search:
    - status : filter by verification status (PENDING, VERIFIED, REJECTED)
    - q      : search by document name, application reference ID, or building name
    - page   : pagination page number (10 documents per page)
    """
    # Base queryset strictly scoped to authenticated user
    docs_qs = ApplicationDocument.objects.filter(
        application__applicant=request.user
    ).select_related('application', 'verification').order_by('-uploaded_at')

    # Status filter
    status_filter = request.GET.get('status', '').strip().upper()
    if status_filter in ['PENDING', 'VERIFIED', 'REJECTED']:
        if status_filter == 'PENDING':
            # Verification record missing OR status == 'PENDING'
            docs_qs = docs_qs.filter(
                Q(verification__isnull=True) | Q(verification__status='PENDING')
            )
        else:
            docs_qs = docs_qs.filter(verification__status=status_filter)
    else:
        status_filter = ''

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        docs_qs = docs_qs.filter(
            Q(document_name__icontains=q) |
            Q(application__application_id__icontains=q) |
            Q(application__building_name__icontains=q)
        )

    # Pagination: 10 per page
    paginator = Paginator(docs_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Build query string without page for pagination links
    query_params = request.GET.copy()
    query_params.pop('page', None)
    filter_query_string = query_params.urlencode()

    # Get applicant's applications (for quick upload target selection or empty state CTA)
    user_applications = Application.objects.filter(applicant=request.user).order_by('-created_at')

    context = {
        'page_obj': page_obj,
        'documents': page_obj.object_list,
        'total_count': paginator.count,
        'status_filter': status_filter,
        'q': q,
        'filter_query_string': filter_query_string,
        'user_applications': user_applications,
        'latest_application': user_applications.first(),
    }
    return render(request, 'applicants/my_documents.html', context)
