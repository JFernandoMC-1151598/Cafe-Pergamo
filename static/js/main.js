/**
 * Café Pérgamo - Scripts Globales (main.js)
 * Manejo de sesión, limpieza de tokens y utilidades comunes.
 */
document.addEventListener('DOMContentLoaded', function () {
    // 1. Manejo del formulario de cierre de sesión (Logout seguro)
    const logoutForm = document.getElementById('logoutForm');
    if (logoutForm) {
        logoutForm.addEventListener('submit', function () {
            // Limpiar tokens JWT del almacenamiento local y de sesión en el cliente
            try {
                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                localStorage.removeItem('accessToken');
                localStorage.removeItem('refreshToken');
                sessionStorage.clear();
            } catch (err) {
                console.warn('Error al limpiar almacenamiento local:', err);
            }
        });
    }
});
