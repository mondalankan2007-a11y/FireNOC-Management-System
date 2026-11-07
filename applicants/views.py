import re
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import render, redirect


def applicant_home(request):
    """
    Applicant home/dashboard placeholder view.
    Renders the Applicant Portal landing page with placeholder actions.
    """
    return render(request, 'applicants/applicant_home.html')


def register(request):
    """
    Applicant registration view.
    Handles GET requests to render the form, and POST requests to validate
    and create an applicant user account using Django's built-in User model.
    """
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
    Applicant login UI view.
    Renders the login page containing email, password, show/hide toggle,
    remember me checkbox, and navigation links.
    Authentication logic will be implemented in a subsequent commit.
    """
    if request.method == 'POST':
        messages.info(
            request,
            "Login UI verified. Authentication logic will be enabled in the upcoming commit."
        )
    return render(request, 'applicants/login.html')
