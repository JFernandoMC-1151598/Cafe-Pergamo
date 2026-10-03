/**
 * Café Pérgamo - Validación y Envío de Registro de Usuarios (registro.js)
 * Separación de responsabilidades: Lógica del lado del cliente desacoplada de la plantilla HTML.
 */
document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('registroForm');
    if (!form) return;

    // Endpoints inyectados limpiamente desde data-attributes en el HTML
    const apiUrl = form.dataset.apiUrl || '/api/auth/register';
    const loginUrl = form.dataset.loginUrl || '/login/';

    // Elementos del formulario
    const firstName = document.getElementById('first_name');
    const lastName = document.getElementById('last_name');
    const email = document.getElementById('email');
    const phone = document.getElementById('phone');
    const tipoDocumento = document.getElementById('tipo_documento');
    const numeroDocumento = document.getElementById('numero_documento');
    const role = document.getElementById('role');
    const password = document.getElementById('password');
    const confirmPassword = document.getElementById('confirm_password');
    const generalAlert = document.getElementById('general-alert');
    const generalAlertMessage = document.getElementById('general-alert-message');
    const emailFeedback = document.getElementById('email-feedback');
    const confirmFeedback = document.getElementById('confirm-password-feedback');
    const numeroDocumentoFeedback = document.getElementById('numero-documento-feedback');
    const submitButton = form.querySelector('button[type="submit"]');
    const submitButtonHtmlOriginal = submitButton ? submitButton.innerHTML : 'Registrarse';

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    /**
     * Marca un campo como inválido con mensaje de error visual Bootstrap
     */
    function setInvalid(input, feedbackElement = null, customMessage = null) {
        if (!input) return;
        input.classList.remove('is-valid');
        input.classList.add('is-invalid');
        if (feedbackElement && customMessage) {
            feedbackElement.textContent = customMessage;
        }
    }

    /**
     * Marca un campo como válido
     */
    function setValid(input) {
        if (!input) return;
        input.classList.remove('is-invalid');
        input.classList.add('is-valid');
    }

    /**
     * Limpia los estados de validación
     */
    function clearValidation(input) {
        if (!input) return;
        input.classList.remove('is-valid', 'is-invalid');
    }

    /**
     * Despliega mensajes generales informativos o de alerta
     */
    function mostrarAlertaGeneral(mensaje, tipo = 'danger') {
        if (!generalAlert || !generalAlertMessage) return;
        generalAlert.classList.remove('d-none', 'alert-danger', 'alert-success', 'alert-warning');
        generalAlert.classList.add('alert-' + tipo);
        generalAlertMessage.textContent = mensaje;
    }

    // Mapeo de campos retornados por la API del backend
    const CAMPO_A_INPUT = {
        correo: { input: email, feedback: emailFeedback },
        email: { input: email, feedback: emailFeedback },
        'contraseña': { input: password, feedback: null },
        password: { input: password, feedback: null },
        telefono: { input: phone, feedback: null },
        phone: { input: phone, feedback: null },
        tipo_documento: { input: tipoDocumento, feedback: null },
        numero_documento: { input: numeroDocumento, feedback: numeroDocumentoFeedback },
        rol: { input: role, feedback: null },
        role: { input: role, feedback: null },
    };

    // Escucha de eventos en tiempo real
    [firstName, lastName, phone, numeroDocumento, password].forEach(field => {
        if (field) {
            field.addEventListener('input', function () {
                if (this.value.trim() !== '') {
                    setValid(this);
                } else {
                    clearValidation(this);
                }
            });
        }
    });

    [role, tipoDocumento].forEach(select => {
        if (select) {
            select.addEventListener('change', function () {
                if (this.value !== '') {
                    setValid(this);
                } else {
                    clearValidation(this);
                }
            });
        }
    });

    if (email) {
        email.addEventListener('input', function () {
            const val = this.value.trim();
            if (val === '') {
                clearValidation(this);
            } else if (!emailRegex.test(val)) {
                setInvalid(this, emailFeedback, 'Ingrese un formato de correo válido (ej. usuario@dominio.com).');
            } else {
                setValid(this);
            }
        });
    }

    if (confirmPassword) {
        confirmPassword.addEventListener('input', function () {
            const passVal = password ? password.value : '';
            const confirmVal = this.value;
            if (confirmVal === '') {
                clearValidation(this);
            } else if (confirmVal !== passVal) {
                setInvalid(this, confirmFeedback, 'Las contraseñas no coinciden.');
            } else {
                setValid(this);
            }
        });
    }

    /**
     * Envío asíncrono con Fetch API
     */
    async function enviarRegistro() {
        const payload = {
            email: email ? email.value.trim() : '',
            password: password ? password.value : '',
            first_name: firstName ? firstName.value.trim() : '',
            last_name: lastName ? lastName.value.trim() : '',
            phone: phone ? phone.value.trim() : '',
            role: role ? role.value : '',
            tipo_documento: tipoDocumento ? tipoDocumento.value : '',
            numero_documento: numeroDocumento ? numeroDocumento.value.trim() : '',
        };

        if (submitButton) {
            submitButton.disabled = true;
            submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Registrando...';
        }

        try {
            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json' 
                },
                body: JSON.stringify(payload),
            });

            let data = {};
            try {
                data = await response.json();
            } catch (parseError) {
                data = {};
            }

            if (response.ok) {
                mostrarAlertaGeneral('¡Registro exitoso! Redirigiendo al inicio de sesión...', 'success');
                setTimeout(function () {
                    window.location.href = loginUrl;
                }, 1800);
                return;
            }

            if (data.campos) {
                Object.keys(data.campos).forEach(function (campo) {
                    const mapeo = CAMPO_A_INPUT[campo];
                    if (mapeo && mapeo.input) {
                        setInvalid(mapeo.input, mapeo.feedback, data.campos[campo]);
                    }
                });
            }

            mostrarAlertaGeneral(data.error || 'No se pudo completar el registro. Intente de nuevo.', 'danger');
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = submitButtonHtmlOriginal;
            }
        } catch (networkError) {
            mostrarAlertaGeneral('No se pudo conectar con el servidor. Verifique su conexión e intente de nuevo.', 'danger');
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = submitButtonHtmlOriginal;
            }
        }
    }

    /**
     * Intercepción del evento submit
     */
    form.addEventListener('submit', function (event) {
        event.preventDefault();
        event.stopPropagation();

        let isValid = true;
        let firstInvalidElement = null;

        if (!firstName || firstName.value.trim() === '') {
            setInvalid(firstName);
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = firstName;
        } else {
            setValid(firstName);
        }

        if (!lastName || lastName.value.trim() === '') {
            setInvalid(lastName);
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = lastName;
        } else {
            setValid(lastName);
        }

        const emailVal = email ? email.value.trim() : '';
        if (emailVal === '') {
            setInvalid(email, emailFeedback, 'El correo electrónico es obligatorio.');
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = email;
        } else if (!emailRegex.test(emailVal)) {
            setInvalid(email, emailFeedback, 'Ingrese una dirección de correo electrónico válida.');
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = email;
        } else {
            setValid(email);
        }

        if (!phone || phone.value.trim() === '') {
            setInvalid(phone);
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = phone;
        } else {
            setValid(phone);
        }

        if (!tipoDocumento || !tipoDocumento.value || tipoDocumento.value.trim() === '') {
            setInvalid(tipoDocumento);
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = tipoDocumento;
        } else {
            setValid(tipoDocumento);
        }

        if (!numeroDocumento || numeroDocumento.value.trim() === '') {
            setInvalid(numeroDocumento, numeroDocumentoFeedback, 'El número de documento es obligatorio.');
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = numeroDocumento;
        } else {
            setValid(numeroDocumento);
        }

        if (!role || !role.value || role.value.trim() === '') {
            setInvalid(role);
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = role;
        } else {
            setValid(role);
        }

        const passVal = password ? password.value : '';
        if (passVal.trim() === '') {
            setInvalid(password);
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = password;
        } else {
            setValid(password);
        }

        const confirmVal = confirmPassword ? confirmPassword.value : '';
        if (confirmVal.trim() === '') {
            setInvalid(confirmPassword, confirmFeedback, 'Debe confirmar su contraseña.');
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = confirmPassword;
        } else if (confirmVal !== passVal) {
            setInvalid(confirmPassword, confirmFeedback, 'La confirmación de contraseña debe coincidir exactamente con la contraseña.');
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = confirmPassword;
        } else {
            setValid(confirmPassword);
        }

        if (!isValid) {
            mostrarAlertaGeneral('Por favor, revise los errores en el formulario antes de continuar.', 'danger');
            if (firstInvalidElement) {
                firstInvalidElement.focus();
            }
            return;
        }

        if (generalAlert) {
            generalAlert.classList.add('d-none');
        }
        enviarRegistro();
    });
});
