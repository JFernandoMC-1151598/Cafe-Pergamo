/**
 * Café Pérgamo - Mapa de "Mis Fincas" (SCRUM-92 / HU06-ST6)
 *
 * Pinta en un mapa Leaflet (tiles de Esri World Street Map, gratis y sin
 * API Key -- ver static/js/georreferenciacion.js para el mismo criterio)
 * un marcador por cada finca del productor autenticado que SÍ tiene
 * coordenadas cargadas. Los datos vienen embebidos de forma segura desde
 * fincas/views.py:mis_fincas_view mediante el filtro `json_script` de
 * Django (templates/fincas/mis_fincas.html), nunca por una llamada AJAX
 * aparte.
 *
 * Las fincas SIN georreferenciación no aparecen aquí (no hay coordenada
 * que pintar), pero sí siguen listadas como tarjetas en la misma página.
 */

document.addEventListener('DOMContentLoaded', () => {
    const mapaContenedor = document.getElementById('mapa-mis-fincas');
    const datosEl = document.getElementById('fincas-geo-data');

    if (!mapaContenedor || !datosEl) {
        return; // Esta página no tiene mapa (p. ej. estado vacío sin fincas)
    }

    let fincas = [];
    try {
        fincas = JSON.parse(datosEl.textContent);
    } catch (error) {
        fincas = [];
    }

    function mostrarAvisoMapa(mensaje, iconoClase) {
        mapaContenedor.innerHTML = `
            <div class="d-flex flex-column align-items-center justify-content-center text-center h-100 p-3 text-muted small">
                <i class="bi ${iconoClase} fs-3 mb-2"></i>
                <span>${mensaje}</span>
            </div>
        `;
    }

    if (fincas.length === 0) {
        mostrarAvisoMapa(
            'Ninguna de tus fincas tiene coordenadas satelitales todavía. Edítalas para ubicarlas aquí.',
            'bi-map'
        );
        return;
    }

    cargarLeafletYDibujarMapa(fincas);

    function cargarLeafletYDibujarMapa(listaFincas) {
        const script = document.createElement('script');
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        script.integrity = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';
        script.crossOrigin = '';
        script.onload = () => dibujarMapa(listaFincas);
        script.onerror = () => {
            mostrarAvisoMapa(
                'No se pudo cargar el mapa (sin conexión o el servicio no respondió). Tus fincas siguen disponibles en la lista de abajo.',
                'bi-exclamation-triangle'
            );
        };
        document.head.appendChild(script);
    }

    function dibujarMapa(listaFincas) {
        if (typeof L === 'undefined') return;

        const mapa = L.map(mapaContenedor);

        // Mismos tiles gratuitos sin API Key que el formulario de registro
        // (ver static/js/georreferenciacion.js para el detalle de por qué
        // no se usan los de OpenStreetMap/CARTO directamente).
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 19,
            attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom',
        }).addTo(mapa);

        const marcadores = listaFincas.map((finca) => {
            const marcador = L.marker([finca.lat, finca.lng]).addTo(mapa);
            const vereda = finca.vereda ? ` (${finca.vereda})` : '';
            marcador.bindPopup(`<strong>${finca.nombre}</strong><br>${finca.municipio}${vereda}`);
            return marcador;
        });

        if (marcadores.length === 1) {
            mapa.setView(marcadores[0].getLatLng(), 14);
        } else {
            const grupo = L.featureGroup(marcadores);
            mapa.fitBounds(grupo.getBounds().pad(0.2));
        }

        // El contenedor pudo medir 0 al crear el mapa según el orden de
        // renderizado del navegador; recalcular tamaño por seguridad.
        setTimeout(() => mapa.invalidateSize(), 100);
    }
});
