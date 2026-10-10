/**
 * Validación visual del formulario de actores de la cadena (HU08-ST4).
 *
 * La persistencia se realiza en el endpoint Django protegido por RBAC.
 */
document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('actorCadenaForm');
    if (!form) return;

    const fields = Array.from(form.querySelectorAll('input, select'));
    const correo = document.getElementById('correo');
    const correoFeedback = document.getElementById('correo-feedback');
    const telefono = document.getElementById('telefono');
    const generalAlert = document.getElementById('general-alert');
    const generalAlertMessage = document.getElementById('general-alert-message');

    function setValid(field) {
        field.classList.remove('is-invalid');
        field.classList.add('is-valid');
    }

    function setInvalid(field, message) {
        field.classList.remove('is-valid');
        field.classList.add('is-invalid');
        if (message) {
            const feedback = field.parentElement.querySelector('.invalid-feedback');
            if (feedback) feedback.textContent = message;
        }
    }

    function clearValidation(field) {
        field.classList.remove('is-valid', 'is-invalid');
    }

    function validarCorreo() {
        if (!correo.value.trim()) {
            clearValidation(correo);
            return false;
        }

        if (!correo.checkValidity()) {
            setInvalid(correo, 'Ingrese un correo electrónico válido.');
            if (correoFeedback) correoFeedback.textContent = 'Ingrese un correo electrónico válido.';
            return false;
        }

        setValid(correo);
        return true;
    }

    function validarTelefono() {
        if (!telefono.value.trim()) {
            clearValidation(telefono);
            return true;
        }

        const telefonoValido = /^[+0-9 ()-]{7,30}$/.test(telefono.value.trim());
        if (!telefonoValido) {
            setInvalid(telefono, 'Ingrese un teléfono válido.');
            return false;
        }

        setValid(telefono);
        return true;
    }

    fields.forEach(function (field) {
        field.addEventListener('blur', function () {
            if (field === correo) {
                validarCorreo();
            } else if (field === telefono) {
                validarTelefono();
            } else if (field.value.trim()) {
                setValid(field);
            } else {
                setInvalid(field);
            }
        });

        field.addEventListener('input', function () {
            if (!field.value.trim()) {
                clearValidation(field);
            } else if (field === correo) {
                validarCorreo();
            } else if (field === telefono) {
                validarTelefono();
            } else {
                setValid(field);
            }
        });
    });

    form.addEventListener('submit', function (event) {
        const camposInvalidos = fields.filter(function (field) {
            if (field === telefono) return !validarTelefono();
            if (field === correo) return !validarCorreo();
            if (!field.value.trim()) {
                setInvalid(field);
                return true;
            }
            setValid(field);
            return false;
        });

        if (camposInvalidos.length > 0) {
            event.preventDefault();
            generalAlert.classList.remove('d-none', 'alert-success');
            generalAlert.classList.add('alert-danger');
            generalAlertMessage.textContent = 'Revise los campos marcados antes de continuar.';
            camposInvalidos[0].focus();
            return;
        }
    });
});
