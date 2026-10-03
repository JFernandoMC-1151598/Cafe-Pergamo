/**
 * Café Pérgamo - Solicitud de Recuperación de Contraseña (recuperar_contrasena.js)
 * Separación de responsabilidades: Lógica de cliente desacoplada de la plantilla HTML.
 */
document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('recoveryForm');
    if (!form) return;

    const apiUrl = form.dataset.apiUrl || '/api/auth/password-reset/request/';
    const email = document.getElementById('email');
    const emailFeedback = document.getElementById('email-feedback');
    const generalAlert = document.getElementById('general-alert');
    const submitButton = document.getElementById('submitRecoveryBtn');
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    function setInvalid(message) {
        if (!email) return;
        email.classList.remove('is-valid');
        email.classList.add('is-invalid');
        if (emailFeedback) {
            emailFeedback.innerHTML = message;
        }
    }

    function setValid() {
        if (!email) return;
        email.classList.remove('is-invalid');
        email.classList.add('is-valid');
    }

    function clearAlert() {
        if (!generalAlert) return;
        generalAlert.className = 'alert d-none';
        generalAlert.textContent = '';
    }

    if (email) {
        email.addEventListener('input', function () {
            clearAlert();
            const value = email.value.trim();
            if (value === '') {
                email.classList.remove('is-valid', 'is-invalid');
            } else if (!emailRegex.test(value)) {
                setInvalid('Ingresa un correo electrónico válido.');
            } else {
                setValid();
            }
        });
    }

    form.addEventListener('submit', function (event) {
        event.preventDefault();
        const value = email ? email.value.trim() : '';

        if (value === '') {
            setInvalid('El correo electrónico es obligatorio.');
            if (email) email.focus();
            return;
        }

        if (!emailRegex.test(value)) {
            setInvalid('Ingresa un correo electrónico válido.');
            if (email) email.focus();
            return;
        }

        if (email) email.value = value;
        setValid();

        if (submitButton) {
            submitButton.disabled = true;
            submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Enviando...';
        }

        const csrfTokenEl = document.querySelector('[name=csrfmiddlewaretoken]');
        const csrfToken = csrfTokenEl ? csrfTokenEl.value : '';

        fetch(apiUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ email: value })
        })
            .then(function (response) {
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (result) {
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.innerHTML = '<i class="bi bi-envelope-arrow-up me-1"></i> Solicitar recuperación';
                }

                if (!result.ok) {
                    if (generalAlert) {
                        generalAlert.className = 'alert alert-danger';
                        generalAlert.textContent = result.data.error || 'No se pudo procesar la solicitud.';
                    }
                    return;
                }

                if (generalAlert) {
                    generalAlert.className = 'alert alert-success';
                    generalAlert.textContent = result.data.message;
                }
            })
            .catch(function () {
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.innerHTML = '<i class="bi bi-envelope-arrow-up me-1"></i> Solicitar recuperación';
                }
                if (generalAlert) {
                    generalAlert.className = 'alert alert-danger';
                    generalAlert.textContent = 'Ocurrió un error al contactar el servidor. Intenta de nuevo.';
                }
            });
    });
});
