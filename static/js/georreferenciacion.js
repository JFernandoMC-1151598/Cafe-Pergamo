/**
 * Café Pérgamo - Módulo de Georreferenciación (HU-07 / SCRUM-95)
 * Subtarea: HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
 * 
 * Funcionalidades:
 * 1. Comportamiento cuando el campo no es informado (sin bloquear el formulario).
 * 2. Asistente interactivo de captura GPS mediante Geolocation API.
 * 3. Validación y feedback visual en tiempo real de rangos decimales WGS84.
 * 4. Botón de limpieza para restablecer al estado opcional vacío.
 */

document.addEventListener('DOMContentLoaded', () => {
    const inputLat = document.getElementById('id_latitud');
    const inputLng = document.getElementById('id_longitud');
    const btnGps = document.getElementById('btn-detectar-gps');
    const btnMapa = document.getElementById('btn-ubicar-mapa');
    const mapaWrapper = document.getElementById('mapa-georreferenciacion-wrapper');
    const mapaContenedor = document.getElementById('mapa-georreferenciacion');
    const btnLimpiar = document.getElementById('btn-limpiar-geo');
    const statusAlert = document.getElementById('geo-status-alert');
    const statusText = document.getElementById('geo-status-text');
    const statusIcon = document.getElementById('geo-status-icon');
    const resumenIcon = document.getElementById('geo-resumen-icon');
    const resumenTexto = document.getElementById('geo-resumen-texto');
    const latFeedback = document.getElementById('latitud-feedback');
    const lngFeedback = document.getElementById('longitud-feedback');

    if (!inputLat || !inputLng) {
        return; // No se encuentra el componente en el DOM
    }

    /**
     * Muestra una notificación temporal de estado (éxito, error o advertencia).
     */
    function mostrarMensajeStatus(tipo, mensaje, iconoClase) {
        if (!statusAlert) return;
        statusAlert.className = `alert alert-${tipo} py-2 px-3 mb-3 small d-flex align-items-center gap-2`;
        if (statusIcon) statusIcon.className = `bi ${iconoClase}`;
        if (statusText) statusText.textContent = mensaje;
        statusAlert.classList.remove('d-none');
    }

    function ocultarMensajeStatus() {
        if (statusAlert) statusAlert.classList.add('d-none');
    }

    /**
     * Valida y actualiza el estado visual de los campos de coordenadas.
     */
    function actualizarEstadoGeorreferenciacion() {
        const valLat = inputLat.value.trim();
        const valLng = inputLng.value.trim();

        // Control de visibilidad del botón Limpiar
        if (valLat !== '' || valLng !== '') {
            btnLimpiar?.classList.remove('d-none');
            btnLimpiar?.classList.add('d-inline-flex');
        } else {
            btnLimpiar?.classList.add('d-none');
            btnLimpiar?.classList.remove('d-inline-flex');
        }

        // Caso 1: Ambos vacíos (Comportamiento cuando el campo NO es informado)
        if (valLat === '' && valLng === '') {
            inputLat.classList.remove('is-invalid', 'is-valid');
            inputLng.classList.remove('is-invalid', 'is-valid');
            latFeedback?.classList.add('d-none');
            lngFeedback?.classList.add('d-none');

            if (resumenIcon) resumenIcon.className = 'bi bi-dash-circle text-secondary';
            if (resumenTexto) resumenTexto.textContent = 'Sin georreferenciación asignada (el predio se guardará sin coordenadas satelitales).';
            return { valido: true, informado: false };
        }

        let latValida = false;
        let lngValida = false;

        // Validar Latitud [-90, 90]
        if (valLat === '') {
            inputLat.classList.remove('is-invalid', 'is-valid');
            latFeedback?.classList.add('d-none');
        } else {
            const numLat = parseFloat(valLat);
            if (!isNaN(numLat) && numLat >= -90.0 && numLat <= 90.0) {
                inputLat.classList.remove('is-invalid');
                inputLat.classList.add('is-valid');
                latFeedback?.classList.add('d-none');
                latValida = true;
            } else {
                inputLat.classList.remove('is-valid');
                inputLat.classList.add('is-invalid');
                latFeedback?.classList.remove('d-none');
            }
        }

        // Validar Longitud [-180, 180]
        if (valLng === '') {
            inputLng.classList.remove('is-invalid', 'is-valid');
            lngFeedback?.classList.add('d-none');
        } else {
            const numLng = parseFloat(valLng);
            if (!isNaN(numLng) && numLng >= -180.0 && numLng <= 180.0) {
                inputLng.classList.remove('is-invalid');
                inputLng.classList.add('is-valid');
                lngFeedback?.classList.add('d-none');
                lngValida = true;
            } else {
                inputLng.classList.remove('is-valid');
                inputLng.classList.add('is-invalid');
                lngFeedback?.classList.remove('d-none');
            }
        }

        // Resumen y retroalimentación cuando al menos uno está informado
        if (latValida && lngValida) {
            if (resumenIcon) resumenIcon.className = 'bi bi-check-circle-fill text-success';
            if (resumenTexto) {
                resumenTexto.innerHTML = `<strong>Coordenadas válidas:</strong> Lat: ${parseFloat(valLat).toFixed(6)}, Lng: ${parseFloat(valLng).toFixed(6)} (WGS84)`;
            }
            return { valido: true, informado: true };
        } else if (valLat !== '' && valLng === '') {
            if (resumenIcon) resumenIcon.className = 'bi bi-exclamation-triangle-fill text-warning';
            if (resumenTexto) resumenTexto.textContent = 'Ingrese también la longitud para completar el punto cartográfico.';
            return { valido: false, informado: true };
        } else if (valLat === '' && valLng !== '') {
            if (resumenIcon) resumenIcon.className = 'bi bi-exclamation-triangle-fill text-warning';
            if (resumenTexto) resumenTexto.textContent = 'Ingrese también la latitud para completar el punto cartográfico.';
            return { valido: false, informado: true };
        } else {
            if (resumenIcon) resumenIcon.className = 'bi bi-x-circle-fill text-danger';
            if (resumenTexto) resumenTexto.textContent = 'Corrija los valores fuera de rango indicados en los campos.';
            return { valido: false, informado: true };
        }
    }

    // Eventos de entrada en tiempo real
    inputLat.addEventListener('input', actualizarEstadoGeorreferenciacion);
    inputLng.addEventListener('input', actualizarEstadoGeorreferenciacion);

    // Captura asistida por GPS (HTML5 Geolocation API)
    if (btnGps) {
        btnGps.addEventListener('click', () => {
            if (!navigator.geolocation) {
                mostrarMensajeStatus(
                    'warning',
                    'Tu navegador no soporta geolocalización satelital.',
                    'bi-exclamation-triangle'
                );
                return;
            }

            const textoOriginal = btnGps.innerHTML;
            btnGps.disabled = true;
            btnGps.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Obteniendo GPS...';
            mostrarMensajeStatus('info', 'Obteniendo coordenadas satelitales de alta precisión...', 'bi-hourglass-split');

            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude.toFixed(6);
                    const lng = position.coords.longitude.toFixed(6);
                    const precision = Math.round(position.coords.accuracy || 0);

                    inputLat.value = lat;
                    inputLng.value = lng;

                    btnGps.disabled = false;
                    btnGps.innerHTML = textoOriginal;

                    mostrarMensajeStatus(
                        'success',
                        `Ubicación GPS capturada con precisión de ~${precision} metros.`,
                        'bi-check-circle-fill'
                    );

                    actualizarEstadoGeorreferenciacion();
                },
                (error) => {
                    btnGps.disabled = false;
                    btnGps.innerHTML = textoOriginal;

                    let detalleError = 'No se pudo obtener la ubicación GPS.';
                    if (error.code === error.PERMISSION_DENIED) {
                        detalleError = 'Permiso de ubicación denegado por el usuario o navegador.';
                    } else if (error.code === error.POSITION_UNAVAILABLE) {
                        detalleError = 'Información de ubicación GPS no disponible en este momento.';
                    } else if (error.code === error.TIMEOUT) {
                        detalleError = 'Tiempo de espera agotado al consultar el sensor GPS.';
                    }

                    mostrarMensajeStatus('danger', detalleError, 'bi-exclamation-octagon-fill');
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 0
                }
            );
        });
    }

    // Mapa interactivo de respaldo (HU07): alternativa a la captura GPS para
    // cuando el dispositivo no tiene GPS o la señal es imprecisa. Usa
    // Leaflet + OpenStreetMap (gratis, sin API Key ni registro). Centrado
    // por defecto en Norte de Santander; se carga perezosamente (solo si el
    // usuario pulsa el botón) para no cargar la librería en cada visita.
    const LEAFLET_VERSION = '1.9.4';
    const CENTRO_NORTE_DE_SANTANDER = { lat: 7.8891, lng: -72.4967 };
    let mapaInstancia = null;
    let marcadorMapa = null;
    let estadoScriptMaps = 'ninguno'; // 'ninguno' | 'cargando' | 'listo' | 'error'

    function mostrarAvisoMapaNoDisponible(mensaje) {
        if (!mapaContenedor) return;
        mapaContenedor.innerHTML = `
            <div class="d-flex flex-column align-items-center justify-content-center text-center h-100 p-3 text-muted small">
                <i class="bi bi-map fs-3 mb-2"></i>
                <span>${mensaje}</span>
            </div>
        `;
    }

    function posicionInicialMapa() {
        const lat = parseFloat(inputLat.value);
        const lng = parseFloat(inputLng.value);
        if (!isNaN(lat) && !isNaN(lng)) {
            return { lat, lng };
        }
        return CENTRO_NORTE_DE_SANTANDER;
    }

    function colocarCoordenadasDesdeMapa(lat, lng) {
        inputLat.value = lat.toFixed(6);
        inputLng.value = lng.toFixed(6);
        actualizarEstadoGeorreferenciacion();
        mostrarMensajeStatus(
            'success',
            `Ubicación tomada del mapa: ${lat.toFixed(6)}, ${lng.toFixed(6)}.`,
            'bi-check-circle-fill'
        );
    }

    function inicializarMapaLeaflet() {
        estadoScriptMaps = 'listo';
        if (!mapaContenedor || typeof L === 'undefined') return;

        mapaContenedor.innerHTML = ''; // limpia el aviso de "Cargando mapa..."

        const centro = posicionInicialMapa();
        const esCentroPorDefecto = (centro === CENTRO_NORTE_DE_SANTANDER);

        mapaInstancia = L.map(mapaContenedor).setView([centro.lat, centro.lng], esCentroPorDefecto ? 9 : 15);

        // tile.openstreetmap.org (OSMF) bloquea cada vez más el acceso
        // directo embebido ("osm.wiki/Blocked"), y CARTO ya exige API Key
        // para sus basemaps públicos. Se usan en su lugar los tiles de Esri
        // World Street Map (ArcGIS Online), que sí son de uso público
        // gratuito sin necesidad de registrarse ni de una clave.
        // Nota: a diferencia de los servicios XYZ estándar, ArcGIS ordena
        // la ruta como {z}/{y}/{x} (no {z}/{x}/{y}).
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 19,
            attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom',
        }).addTo(mapaInstancia);

        marcadorMapa = L.marker([centro.lat, centro.lng], { draggable: true }).addTo(mapaInstancia);

        marcadorMapa.on('dragend', () => {
            const pos = marcadorMapa.getLatLng();
            colocarCoordenadasDesdeMapa(pos.lat, pos.lng);
        });

        mapaInstancia.on('click', (evento) => {
            marcadorMapa.setLatLng(evento.latlng);
            colocarCoordenadasDesdeMapa(evento.latlng.lat, evento.latlng.lng);
        });

        // El contenedor estaba oculto (d-none) justo antes de crear el mapa;
        // Leaflet necesita recalcular el tamaño una vez que es visible.
        setTimeout(() => mapaInstancia.invalidateSize(), 100);
    }

    function cargarLeaflet() {
        estadoScriptMaps = 'cargando';
        mostrarAvisoMapaNoDisponible('Cargando mapa...');

        const script = document.createElement('script');
        script.src = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.js`;
        script.integrity = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';
        script.crossOrigin = '';
        script.onload = inicializarMapaLeaflet;
        script.onerror = () => {
            estadoScriptMaps = 'error';
            mostrarAvisoMapaNoDisponible(
                'No se pudo cargar el mapa (sin conexión o el servicio no respondió). Usa "Capturar mi ubicación GPS" o ingresa las coordenadas manualmente.'
            );
        };
        document.head.appendChild(script);
    }

    // Botón "Ubicar en el mapa": muestra/oculta el mapa, cargándolo solo la primera vez
    if (btnMapa && mapaWrapper) {
        btnMapa.addEventListener('click', () => {
            const estaOculto = mapaWrapper.classList.contains('d-none');

            if (estaOculto) {
                mapaWrapper.classList.remove('d-none');
                if (estadoScriptMaps === 'ninguno') {
                    cargarLeaflet();
                } else if (estadoScriptMaps === 'listo' && mapaInstancia) {
                    // Ya estaba cargado: solo recentrar por si el usuario ya tenía coordenadas
                    const centro = posicionInicialMapa();
                    mapaInstancia.setView([centro.lat, centro.lng], mapaInstancia.getZoom());
                    marcadorMapa?.setLatLng([centro.lat, centro.lng]);
                    setTimeout(() => mapaInstancia.invalidateSize(), 50);
                }
            } else {
                mapaWrapper.classList.add('d-none');
            }
        });
    }

    // Acción de Limpiar / Omitir (restablece al estado opcional desatendido)
    if (btnLimpiar) {
        btnLimpiar.addEventListener('click', () => {
            inputLat.value = '';
            inputLng.value = '';
            ocultarMensajeStatus();
            actualizarEstadoGeorreferenciacion();
        });
    }

    // Inicializar estado al cargar la página
    actualizarEstadoGeorreferenciacion();
});
