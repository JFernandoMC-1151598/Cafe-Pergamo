/**
 * Café Pérgamo - Validación e Interacción de Inicio de Sesión (login.js)
 * Separación de responsabilidades: Lógica de cliente desacoplada de login.html.
 */
document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('loginForm');
    if (!form) return;

    const email = document.getElementById('email');
    const password = document.getElementById('password');
    const generalAlert = document.getElementById('general-alert');
    const emailFeedback = document.getElementById('email-feedback');
    const passwordFeedback = document.getElementById('password-feedback');
    const togglePasswordBtn = document.getElementById('togglePasswordBtn');
    const togglePasswordIcon = document.getElementById('togglePasswordIcon');

    // Expresión regular para validar formato de correo electrónico
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    /**
     * Alternar visibilidad de contraseña (mostrar/ocultar)
     */
    if (togglePasswordBtn && password && togglePasswordIcon) {
        togglePasswordBtn.addEventListener('click', function () {
            const currentType = password.getAttribute('type');
            if (currentType === 'password') {
                password.setAttribute('type', 'text');
                togglePasswordIcon.classList.replace('bi-eye', 'bi-eye-slash');
            } else {
                password.setAttribute('type', 'password');
                togglePasswordIcon.classList.replace('bi-eye-slash', 'bi-eye');
            }
        });
    }

    /**
     * Funciones de utilidad para validación visual Bootstrap 5
     */
    function setInvalid(input, feedbackElement = null, message = null) {
        if (!input) return;
        input.classList.remove('is-valid');
        input.classList.add('is-invalid');
        if (feedbackElement && message) {
            feedbackElement.textContent = message;
        }
    }

    function setValid(input) {
        if (!input) return;
        input.classList.remove('is-invalid');
        input.classList.add('is-valid');
    }

    function clearValidation(input) {
        if (!input) return;
        input.classList.remove('is-valid', 'is-invalid');
    }

    // Escuchar cambios en vivo
    if (email) {
        email.addEventListener('input', function () {
            const val = this.value.trim();
            if (val === '') {
                clearValidation(this);
            } else if (!emailRegex.test(val)) {
                setInvalid(this, emailFeedback, 'Ingrese un formato de correo electrónico válido.');
            } else {
                setValid(this);
            }
        });
    }

    if (password) {
        password.addEventListener('input', function () {
            if (this.value.trim() !== '') {
                setValid(this);
            } else {
                clearValidation(this);
            }
        });
    }

    // Validación al enviar el formulario
    form.addEventListener('submit', function (event) {
        let isValid = true;
        let firstInvalidElement = null;

        // Validar email
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

        // Validar password
        const passVal = password ? password.value.trim() : '';
        if (passVal === '') {
            setInvalid(password, passwordFeedback, 'La contraseña es obligatoria.');
            isValid = false;
            if (!firstInvalidElement) firstInvalidElement = password;
        } else {
            setValid(password);
        }

        // Interceptar si hay errores en el cliente
        if (!isValid) {
            event.preventDefault();
            event.stopPropagation();
            if (generalAlert) {
                generalAlert.classList.remove('d-none');
            }
            if (firstInvalidElement) {
                firstInvalidElement.focus();
            }
        } else {
            if (generalAlert) {
                generalAlert.classList.add('d-none');
            }
        }
    });
});
