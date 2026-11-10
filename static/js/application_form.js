/**
 * FireNOC Management System - Application Form Interactive Validation
 * Handles Building Details validation, conditional "Other" building type field,
 * live character counters, real-time input sanitization, and form submission feedback.
 */

document.addEventListener('DOMContentLoaded', () => {
    'use strict';

    const form = document.getElementById('nocApplicationForm');
    if (!form) return;

    const currentYear = new Date().getFullYear();

    // Elements
    const buildingTypeSelect = document.getElementById('id_building_type');
    const otherWrapper = document.getElementById('other_building_type_wrapper');
    const otherInput = document.getElementById('id_building_type_other');
    const buildingNameInput = document.getElementById('id_building_name');
    const buildingAddressInput = document.getElementById('id_building_address');
    const cityInput = document.getElementById('id_city');
    const stateSelect = document.getElementById('id_state');
    const pinInput = document.getElementById('id_pin_code');
    const floorsInput = document.getElementById('id_num_floors');
    const areaInput = document.getElementById('id_builtup_area');
    const yearInput = document.getElementById('id_year_construction');
    const occupancySelect = document.getElementById('id_occupancy_type');
    const mobileInput = document.getElementById('id_mobile');
    const purposeTextarea = document.getElementById('id_purpose');
    const remarksTextarea = document.getElementById('id_remarks');
    const declarationCheckbox = document.getElementById('id_declaration');
    const validationStatusAlert = document.getElementById('formValidationStatus');

    // 1. Ensure Year input max attribute matches current year
    if (yearInput) {
        yearInput.max = currentYear;
        const yearFeedback = document.getElementById('year_construction_feedback');
        if (yearFeedback) {
            yearFeedback.textContent = `Enter a 4-digit year between 1900 and ${currentYear}.`;
        }
    }

    // 2. Interactive "Other" Building Type behaviour
    function toggleOtherBuildingType(focus) {
        if (!buildingTypeSelect || !otherWrapper || !otherInput) return;
        const isOther = (buildingTypeSelect.value === 'OTHER');
        if (isOther) {
            otherWrapper.style.display = 'block';
            otherInput.required = true;
            otherInput.setAttribute('aria-required', 'true');
            if (focus) {
                setTimeout(() => otherInput.focus(), 100);
            }
        } else {
            otherWrapper.style.display = 'none';
            otherInput.required = false;
            otherInput.removeAttribute('aria-required');
            otherInput.value = '';
            otherInput.classList.remove('is-invalid', 'is-valid');
        }
    }

    if (buildingTypeSelect) {
        buildingTypeSelect.addEventListener('change', () => toggleOtherBuildingType(true));
        // Initialize state on page load (e.g. if reloaded with values)
        toggleOtherBuildingType(false);
    }

    // 3. Live Input Sanitization & Format Constraints
    // PIN code: strictly 6 digits
    if (pinInput) {
        pinInput.addEventListener('input', function () {
            this.value = this.value.replace(/\D/g, '').slice(0, 6);
            validatePinCode(this);
        });
        pinInput.addEventListener('blur', function () {
            validatePinCode(this);
        });
    }

    function validatePinCode(input) {
        const val = input.value.trim();
        // Indian PIN code: 6 digits, first digit 1-9
        const pinPattern = /^[1-9][0-9]{5}$/;
        if (!pinPattern.test(val)) {
            setFieldInvalid(input, 'Enter a valid 6-digit Indian PIN code (cannot start with 0).');
            return false;
        } else {
            setFieldValid(input);
            return true;
        }
    }

    // Number of floors: positive integer
    if (floorsInput) {
        floorsInput.addEventListener('input', function () {
            // Remove negative signs or decimal dots
            if (this.value.includes('-')) this.value = this.value.replace(/-/g, '');
            validateFloors(this);
        });
        floorsInput.addEventListener('blur', function () {
            validateFloors(this);
        });
    }

    function validateFloors(input) {
        const val = parseInt(input.value, 10);
        if (isNaN(val) || val < 1 || val > 200 || input.value.includes('.')) {
            setFieldInvalid(input, 'Enter a positive whole number between 1 and 200.');
            return false;
        } else {
            setFieldValid(input);
            return true;
        }
    }

    // Built-up area: positive decimal value
    if (areaInput) {
        areaInput.addEventListener('input', function () {
            validateBuiltupArea(this);
        });
        areaInput.addEventListener('blur', function () {
            validateBuiltupArea(this);
        });
    }

    function validateBuiltupArea(input) {
        const val = parseFloat(input.value);
        if (isNaN(val) || val <= 0 || val > 9999999) {
            setFieldInvalid(input, 'Enter a positive built-up area in square metres (greater than 0).');
            return false;
        } else {
            setFieldValid(input);
            return true;
        }
    }

    // Year of construction: 1900 to currentYear
    if (yearInput) {
        yearInput.addEventListener('input', function () {
            if (this.value.length > 4) {
                this.value = this.value.slice(0, 4);
            }
            validateYear(this);
        });
        yearInput.addEventListener('blur', function () {
            validateYear(this);
        });
    }

    function validateYear(input) {
        const val = parseInt(input.value, 10);
        if (isNaN(val) || val < 1900 || val > currentYear || input.value.length !== 4) {
            setFieldInvalid(input, `Enter a valid 4-digit construction year between 1900 and ${currentYear}.`);
            return false;
        } else {
            setFieldValid(input);
            return true;
        }
    }

    // Building Name: required, max 150
    if (buildingNameInput) {
        buildingNameInput.addEventListener('input', function () {
            validateBuildingName(this);
        });
        buildingNameInput.addEventListener('blur', function () {
            validateBuildingName(this);
        });
    }

    function validateBuildingName(input) {
        const val = input.value.trim();
        if (!val || val.length > 150) {
            setFieldInvalid(input, 'Building name is required (maximum 150 characters).');
            return false;
        } else {
            setFieldValid(input);
            return true;
        }
    }

    // Building Address: required
    if (buildingAddressInput) {
        buildingAddressInput.addEventListener('blur', function () {
            if (!this.value.trim()) {
                setFieldInvalid(this, 'Building address is required.');
            } else {
                setFieldValid(this);
            }
        });
    }

    // City: required
    if (cityInput) {
        cityInput.addEventListener('blur', function () {
            if (!this.value.trim()) {
                setFieldInvalid(this, 'City / Town name is required.');
            } else {
                setFieldValid(this);
            }
        });
    }

    // Mobile Number: digits only, 10 digits
    if (mobileInput) {
        mobileInput.addEventListener('input', function () {
            this.value = this.value.replace(/\D/g, '').slice(0, 10);
            if (this.value.length === 10) {
                setFieldValid(this);
            }
        });
        mobileInput.addEventListener('blur', function () {
            if (!/^[6-9][0-9]{9}$/.test(this.value.trim())) {
                setFieldInvalid(this, 'Enter a valid 10-digit mobile number starting with 6, 7, 8, or 9.');
            } else {
                setFieldValid(this);
            }
        });
    }

    // Helper functions for valid/invalid state toggling
    function setFieldInvalid(el, message) {
        el.classList.add('is-invalid');
        el.classList.remove('is-valid');
        const feedback = document.getElementById(el.getAttribute('aria-describedby')) ||
                         (el.closest('.has-validation') ? el.closest('.has-validation').querySelector('.invalid-feedback') : null) ||
                         el.parentElement.querySelector('.invalid-feedback');
        if (feedback && message) {
            feedback.textContent = message;
        }
    }

    function setFieldValid(el) {
        el.classList.remove('is-invalid');
        el.classList.add('is-valid');
    }

    // 4. Character Counters for Textareas
    function setupCharCounter(textareaId, counterId, max) {
        const ta = document.getElementById(textareaId);
        const counter = document.getElementById(counterId);
        if (!ta || !counter) return;
        const update = () => {
            const len = ta.value.length;
            counter.textContent = `${len} / ${max}`;
            counter.classList.toggle('text-danger', len >= max);
        };
        ta.addEventListener('input', update);
        update();
    }
    setupCharCounter('id_purpose', 'purpose_char_count', 1000);
    setupCharCounter('id_remarks', 'remarks_char_count', 2000);

    // 5. Radio card selection visual highlight
    document.querySelectorAll('.app-form-radio-card input[type="radio"]').forEach(radio => {
        radio.addEventListener('change', function () {
            document.querySelectorAll('.app-form-radio-card').forEach(card => {
                card.classList.remove('selected');
            });
            this.closest('.app-form-radio-card').classList.add('selected');
            const appTypeFeedback = document.getElementById('app_type_feedback');
            if (appTypeFeedback) appTypeFeedback.style.display = 'none';
        });
    });

    // 6. Form Submission Validation Handler
    window.handleFormSubmit = function (e) {
        if (e) e.preventDefault();

        let isFormValid = true;
        let firstInvalidElement = null;

        // Trigger native check
        form.classList.add('was-validated');

        // Check Building Name
        if (buildingNameInput && !validateBuildingName(buildingNameInput)) {
            isFormValid = false;
            if (!firstInvalidElement) firstInvalidElement = buildingNameInput;
        }

        // Check Building Type
        if (buildingTypeSelect) {
            if (!buildingTypeSelect.value) {
                setFieldInvalid(buildingTypeSelect, 'Please select a building type.');
                isFormValid = false;
                if (!firstInvalidElement) firstInvalidElement = buildingTypeSelect;
            } else {
                setFieldValid(buildingTypeSelect);
            }
        }

        // Check Other Building Type (if visible)
        if (buildingTypeSelect && buildingTypeSelect.value === 'OTHER' && otherInput) {
            if (!otherInput.value.trim()) {
                setFieldInvalid(otherInput, 'Please specify the building type.');
                isFormValid = false;
                if (!firstInvalidElement) firstInvalidElement = otherInput;
            } else {
                setFieldValid(otherInput);
            }
        }

        // Check Building Address
        if (buildingAddressInput) {
            if (!buildingAddressInput.value.trim()) {
                setFieldInvalid(buildingAddressInput, 'Building address is required.');
                isFormValid = false;
                if (!firstInvalidElement) firstInvalidElement = buildingAddressInput;
            } else {
                setFieldValid(buildingAddressInput);
            }
        }

        // Check City
        if (cityInput) {
            if (!cityInput.value.trim()) {
                setFieldInvalid(cityInput, 'City / Town name is required.');
                isFormValid = false;
                if (!firstInvalidElement) firstInvalidElement = cityInput;
            } else {
                setFieldValid(cityInput);
            }
        }

        // Check State
        if (stateSelect) {
            if (!stateSelect.value) {
                setFieldInvalid(stateSelect, 'Please select a state or union territory.');
                isFormValid = false;
                if (!firstInvalidElement) firstInvalidElement = stateSelect;
            } else {
                setFieldValid(stateSelect);
            }
        }

        // Check PIN Code
        if (pinInput && !validatePinCode(pinInput)) {
            isFormValid = false;
            if (!firstInvalidElement) firstInvalidElement = pinInput;
        }

        // Check Number of Floors
        if (floorsInput && !validateFloors(floorsInput)) {
            isFormValid = false;
            if (!firstInvalidElement) firstInvalidElement = floorsInput;
        }

        // Check Built-up Area
        if (areaInput && !validateBuiltupArea(areaInput)) {
            isFormValid = false;
            if (!firstInvalidElement) firstInvalidElement = areaInput;
        }

        // Check Year of Construction
        if (yearInput && !validateYear(yearInput)) {
            isFormValid = false;
            if (!firstInvalidElement) firstInvalidElement = yearInput;
        }

        // Check Occupancy Type
        if (occupancySelect) {
            if (!occupancySelect.value) {
                setFieldInvalid(occupancySelect, 'Please select an occupancy type.');
                isFormValid = false;
                if (!firstInvalidElement) firstInvalidElement = occupancySelect;
            } else {
                setFieldValid(occupancySelect);
            }
        }

        // Check Mobile Number
        if (mobileInput) {
            const mobVal = mobileInput.value.trim();
            if (!/^[6-9][0-9]{9}$/.test(mobVal)) {
                setFieldInvalid(mobileInput, 'Enter a valid 10-digit mobile number starting with 6, 7, 8, or 9.');
                isFormValid = false;
                if (!firstInvalidElement) firstInvalidElement = mobileInput;
            } else {
                setFieldValid(mobileInput);
            }
        }

        // Check Application Type radio
        const appTypeChecked = form.querySelector('input[name="application_type"]:checked');
        const appTypeFeedback = document.getElementById('app_type_feedback');
        if (!appTypeChecked) {
            if (appTypeFeedback) appTypeFeedback.style.display = 'block';
            isFormValid = false;
            if (!firstInvalidElement) firstInvalidElement = document.getElementById('app_type_new');
        } else {
            if (appTypeFeedback) appTypeFeedback.style.display = 'none';
        }

        // Check Purpose
        if (purposeTextarea) {
            if (!purposeTextarea.value.trim()) {
                setFieldInvalid(purposeTextarea, 'Please specify the purpose of this application.');
                isFormValid = false;
                if (!firstInvalidElement) firstInvalidElement = purposeTextarea;
            } else {
                setFieldValid(purposeTextarea);
            }
        }

        // Check Declaration
        if (declarationCheckbox && !declarationCheckbox.checked) {
            declarationCheckbox.classList.add('is-invalid');
            isFormValid = false;
            if (!firstInvalidElement) firstInvalidElement = declarationCheckbox;
        } else if (declarationCheckbox) {
            declarationCheckbox.classList.remove('is-invalid');
        }

        // Status Feedback Banner
        if (validationStatusAlert) {
            if (!isFormValid) {
                validationStatusAlert.className = 'alert alert-danger d-flex align-items-center shadow-sm mb-4';
                validationStatusAlert.innerHTML = `
                    <i class="bi bi-exclamation-triangle-fill fs-3 text-danger me-3 flex-shrink-0"></i>
                    <div>
                        <h6 class="alert-heading fw-bold mb-1">Please Correct the Highlighted Form Errors</h6>
                        <p class="mb-0 small text-danger-emphasis">
                            One or more required fields in Building Information or Application Details are missing or invalid.
                            Please review the highlighted fields above and correct them.
                        </p>
                    </div>
                `;
                validationStatusAlert.classList.remove('d-none');
            } else {
                validationStatusAlert.className = 'alert alert-success d-flex align-items-center shadow-sm mb-4';
                validationStatusAlert.innerHTML = `
                    <i class="bi bi-check-circle-fill fs-3 text-success me-3 flex-shrink-0"></i>
                    <div>
                        <h6 class="alert-heading fw-bold mb-1">Form Validated Successfully!</h6>
                        <p class="mb-0 small text-success-emphasis">
                            All applicant details, building parameters, and application information meet fire safety requirements.
                            <strong>Ready for submission!</strong> (Note: Database submission and document uploads will be enabled in the upcoming commit).
                        </p>
                    </div>
                `;
                validationStatusAlert.classList.remove('d-none');
            }
        }

        if (!isFormValid) {
            if (firstInvalidElement) {
                firstInvalidElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                firstInvalidElement.focus();
            }
        } else {
            // Scroll to the success banner so the user sees the confirmation
            if (validationStatusAlert) {
                validationStatusAlert.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
    };

    // 7. Sticky section navigator scroll spy
    const sections = [
        { id: 'section-a', nav: 'nav-a' },
        { id: 'section-b', nav: 'nav-b' },
        { id: 'section-c', nav: 'nav-c' },
    ];
    const colorMap = { 'nav-a': 'bg-danger', 'nav-b': 'bg-primary', 'nav-c': 'bg-success' };

    function onScroll() {
        let current = sections[0].nav;
        sections.forEach(({ id, nav }) => {
            const el = document.getElementById(id);
            if (el && window.scrollY >= el.offsetTop - 160) current = nav;
        });
        sections.forEach(({ nav }) => {
            const link = document.getElementById(nav);
            if (!link) return;
            const badge = link.querySelector('.app-form-step-badge');
            if (nav === current) {
                link.classList.add('active');
                if (badge) {
                    badge.className = 'app-form-step-badge text-white ' + (colorMap[nav] || 'bg-secondary');
                }
            } else {
                link.classList.remove('active');
                if (badge) badge.className = 'app-form-step-badge bg-secondary text-white';
            }
        });
    }
    document.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    // 8. Bootstrap tooltips initialization
    if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
        document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            new bootstrap.Tooltip(el);
        });
    }
});

