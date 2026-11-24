/**
 * Dashboard de Indicadores de Trazabilidad y Comercialización (HU-26 / SCRUM-285)
 * CAFÉ PÉRGAMO - Universidad Francisco de Paula Santander (UFPS)
 *
 * Lee los datos iniciales inyectados en #datos-dashboard-inicial, inicializa los
 * gráficos interactivos con Chart.js y gestiona la reactividad asíncrona de filtros
 * multicriterio consumiendo la API REST /api/v1/indicadores/dashboard/.
 */

(function () {
    'use strict';

    // Paleta de colores institucional oficial de Café Pérgamo
    const PALETA_COLORES = {
        cafeOscuro: '#2B1810',
        cafeTostado: '#4A2C2A',
        verdePergamo: '#1B381E',
        rojoUFPS: '#990000',
        doradoPergamo: '#B8860B',
        verdeEsmeralda: '#2E7D32',
        azulCielo: '#0288D1',
        ambar: '#FFA000',
        purpura: '#7B1FA2',
        grisNeutro: '#6C757D',
        etapas: ['#4A2C2A', '#1B381E', '#B8860B', '#2E7D32', '#990000'],
        estados: ['#1B381E', '#FFA000', '#0288D1', '#990000', '#6C757D']
    };

    // Referencias a instancias globales de gráficos Chart.js
    let chartEtapasInstance = null;
    let chartVariedadesInstance = null;
    let chartEstadosInstance = null;
    let chartRegionalInstance = null;

    // Formateadores numéricos y de moneda para Colombia
    const formateadorMoneda = new Intl.NumberFormat('es-CO', {
        style: 'currency',
        currency: 'COP',
        maximumFractionDigits: 0
    });

    const formateadorNumero = new Intl.NumberFormat('es-CO', {
        maximumFractionDigits: 1,
        minimumFractionDigits: 0
    });

    /**
     * Extrae el contexto inicial serializado por Django
     */
    function obtenerDatosIniciales() {
        const nodo = document.getElementById('datos-dashboard-inicial');
        if (!nodo) return null;
        try {
            return JSON.parse(nodo.textContent);
        } catch (e) {
            console.error('Error al parsear datos iniciales del dashboard:', e);
            return null;
        }
    }

    /**
     * Inicializa los 4 gráficos interactivos con Chart.js
     */
    function inicializarGraficos(datos) {
        if (typeof Chart === 'undefined') {
            console.warn('Chart.js no está cargado en la página.');
            return;
        }

        const trazabilidad = datos.indicadores_trazabilidad || {};
        const comercializacion = datos.indicadores_comercializacion || {};
        const regional = datos.distribucion_regional || [];
        const topFincas = comercializacion.top_fincas || [];

        // 1. Gráfico de Etapas de Beneficio (Doughnut)
        const canvasEtapas = document.getElementById('graficoEtapasBeneficio');
        if (canvasEtapas) {
            const etapas = trazabilidad.etapas_beneficio || {};
            const labelsEtapas = ['Cosecha', 'Despulpado', 'Fermentación', 'Lavado', 'Secado'];
            const dataEtapas = [
                etapas.cosecha || 0,
                etapas.despulpado || 0,
                etapas.fermentacion || 0,
                etapas.lavado || 0,
                etapas.secado || 0
            ];

            chartEtapasInstance = new Chart(canvasEtapas.getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: labelsEtapas,
                    datasets: [{
                        data: dataEtapas,
                        backgroundColor: PALETA_COLORES.etapas,
                        borderWidth: 2,
                        borderColor: '#ffffff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    const val = ctx.raw || 0;
                                    return ` ${ctx.label}: ${val} lote(s)`;
                                }
                            }
                        }
                    },
                    cutout: '65%'
                }
            });
        }

        // 2. Gráfico de Variedades Botánicas (Barras)
        const canvasVariedades = document.getElementById('graficoVariedades');
        if (canvasVariedades) {
            const variedades = comercializacion.volumen_por_variedad || [];
            const labelsVariedades = variedades.map(v => v.variedad);
            const dataVendidos = variedades.map(v => v.volumen_vendido_kg);
            const dataDisponibles = variedades.map(v => v.volumen_disponible_kg);

            chartVariedadesInstance = new Chart(canvasVariedades.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: labelsVariedades.length ? labelsVariedades : ['Sin datos'],
                    datasets: [
                        {
                            label: 'Vendido (kg)',
                            data: dataVendidos.length ? dataVendidos : [0],
                            backgroundColor: PALETA_COLORES.rojoUFPS,
                            borderRadius: 6
                        },
                        {
                            label: 'Disponible (kg)',
                            data: dataDisponibles.length ? dataDisponibles : [0],
                            backgroundColor: PALETA_COLORES.verdePergamo,
                            borderRadius: 6
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    return ` ${ctx.dataset.label}: ${formateadorNumero.format(ctx.raw)} kg`;
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: 'Kilogramos (kg)' }
                        }
                    }
                }
            });
        }

        // 3. Gráfico de Estado Comercial de Lotes (Doughnut / Pie)
        const canvasEstados = document.getElementById('graficoEstadosComerciales');
        if (canvasEstados) {
            const estados = trazabilidad.estados_lotes || {};
            const labelsEstados = ['Disponible', 'Reservado', 'Negociado', 'Vendido'];
            const dataEstados = [
                estados.disponible || 0,
                estados.reservado || 0,
                estados.negociado || 0,
                estados.vendido || 0
            ];

            chartEstadosInstance = new Chart(canvasEstados.getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: labelsEstados,
                    datasets: [{
                        data: dataEstados,
                        backgroundColor: PALETA_COLORES.estados,
                        borderWidth: 2,
                        borderColor: '#ffffff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    return ` ${ctx.label}: ${ctx.raw} lote(s)`;
                                }
                            }
                        }
                    },
                    cutout: '60%'
                }
            });
        }

        // 4. Gráfico Regional o Fincas Propias (Barras Horizontales)
        const canvasRegional = document.getElementById('graficoRegional');
        if (canvasRegional) {
            let labelsRegional = [];
            let dataRegional = [];

            if (datos.es_asociacion_o_admin) {
                labelsRegional = regional.map(r => r.municipio);
                dataRegional = regional.map(r => r.volumen_total_kg);
            } else {
                labelsRegional = topFincas.map(f => f.finca);
                dataRegional = topFincas.map(f => f.volumen_kg);
            }

            chartRegionalInstance = new Chart(canvasRegional.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: labelsRegional.length ? labelsRegional : ['Sin registros'],
                    datasets: [{
                        label: 'Volumen Total (kg)',
                        data: dataRegional.length ? dataRegional : [0],
                        backgroundColor: PALETA_COLORES.doradoPergamo,
                        borderRadius: 6
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    return ` Volumen: ${formateadorNumero.format(ctx.raw)} kg`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            title: { display: true, text: 'kg' }
                        }
                    }
                }
            });
        }
    }

    /**
     * Actualiza el contenido visual del Dashboard (KPIs, Gráficos y Tablas)
     */
    function actualizarVisualizacionDashboard(datos) {
        if (!datos) return;

        const resumen = datos.resumen_general || {};
        const trazabilidad = datos.indicadores_trazabilidad || {};
        const comercializacion = datos.indicadores_comercializacion || {};
        const embudo = comercializacion.embudo_negociaciones || {};

        // 1. Actualizar Tarjetas KPI
        const elTotalLotes = document.getElementById('kpiTotalLotes');
        if (elTotalLotes) elTotalLotes.textContent = resumen.total_lotes ?? 0;

        const elLotesConQR = document.getElementById('kpiLotesConQR');
        if (elLotesConQR) elLotesConQR.textContent = trazabilidad.lotes_con_qr ?? 0;

        const elVolumenProducido = document.getElementById('kpiVolumenProducido');
        if (elVolumenProducido) elVolumenProducido.textContent = `${formateadorNumero.format(comercializacion.volumen_total_producido_kg ?? 0)} kg`;

        const elVolumenDisponible = document.getElementById('kpiVolumenDisponible');
        if (elVolumenDisponible) elVolumenDisponible.textContent = formateadorNumero.format(comercializacion.volumen_disponible_catalogo_kg ?? 0);

        const elVolumenVendido = document.getElementById('kpiVolumenVendido');
        if (elVolumenVendido) elVolumenVendido.textContent = `${formateadorNumero.format(comercializacion.volumen_vendido_kg ?? 0)} kg`;

        const elTotalVentas = document.getElementById('kpiTotalVentas');
        if (elTotalVentas) elTotalVentas.textContent = comercializacion.total_ventas_concretadas ?? 0;

        const elIngresosTotales = document.getElementById('kpiIngresosTotales');
        if (elIngresosTotales) elIngresosTotales.textContent = formateadorMoneda.format(comercializacion.ingresos_totales_cop ?? 0);

        const elPrecioPromedio = document.getElementById('kpiPrecioPromedio');
        if (elPrecioPromedio) elPrecioPromedio.textContent = formateadorNumero.format(comercializacion.precio_promedio_kg_cop ?? 0);

        const elCompletitud = document.getElementById('kpiCompletitud');
        if (elCompletitud) elCompletitud.textContent = `${trazabilidad.completitud_promedio_porcentaje ?? 0}%`;

        const elBarraCompletitud = document.getElementById('kpiBarraCompletitud');
        if (elBarraCompletitud) {
            const comp = trazabilidad.completitud_promedio_porcentaje ?? 0;
            elBarraCompletitud.style.width = `${comp}%`;
            elBarraCompletitud.setAttribute('aria-valuenow', comp);
        }

        const elPuntajeSca = document.getElementById('kpiPuntajeSca');
        if (elPuntajeSca) {
            elPuntajeSca.innerHTML = `${trazabilidad.puntaje_sca_promedio ?? 0} <span class="fs-6 fw-normal text-muted">pts</span>`;
        }

        const elLotesEvaluados = document.getElementById('kpiLotesEvaluados');
        if (elLotesEvaluados) elLotesEvaluados.textContent = trazabilidad.lotes_con_evaluacion_calidad ?? 0;

        const elTasaConversion = document.getElementById('kpiTasaConversion');
        if (elTasaConversion) elTasaConversion.textContent = `${comercializacion.tasa_conversion_porcentaje ?? 0}%`;

        const elTotalNegociaciones = document.getElementById('kpiTotalNegociaciones');
        if (elTotalNegociaciones) elTotalNegociaciones.textContent = embudo.total ?? 0;

        const elTotalFincas = document.getElementById('kpiTotalFincas');
        if (elTotalFincas) elTotalFincas.textContent = resumen.total_fincas ?? 0;

        const elTotalCosechas = document.getElementById('kpiTotalCosechas');
        if (elTotalCosechas) elTotalCosechas.textContent = resumen.total_cosechas ?? 0;

        // Actualizar Embudo si existe en la vista
        const elEmbudoSol = document.getElementById('embudoSolicitadas');
        if (elEmbudoSol) elEmbudoSol.textContent = embudo.solicitada ?? 0;
        const elEmbudoNeg = document.getElementById('embudoEnNegociacion');
        if (elEmbudoNeg) elEmbudoNeg.textContent = embudo.en_negociacion ?? 0;
        const elEmbudoAce = document.getElementById('embudoAceptadas');
        if (elEmbudoAce) elEmbudoAce.textContent = embudo.aceptada ?? 0;
        const elEmbudoRec = document.getElementById('embudoRechazadas');
        if (elEmbudoRec) elEmbudoRec.textContent = embudo.rechazada ?? 0;

        // 2. Actualizar Datasets de Chart.js
        if (chartEtapasInstance) {
            const etapas = trazabilidad.etapas_beneficio || {};
            chartEtapasInstance.data.datasets[0].data = [
                etapas.cosecha || 0,
                etapas.despulpado || 0,
                etapas.fermentacion || 0,
                etapas.lavado || 0,
                etapas.secado || 0
            ];
            chartEtapasInstance.update();
        }

        if (chartVariedadesInstance) {
            const variedades = comercializacion.volumen_por_variedad || [];
            chartVariedadesInstance.data.labels = variedades.length ? variedades.map(v => v.variedad) : ['Sin datos'];
            chartVariedadesInstance.data.datasets[0].data = variedades.length ? variedades.map(v => v.volumen_vendido_kg) : [0];
            chartVariedadesInstance.data.datasets[1].data = variedades.length ? variedades.map(v => v.volumen_disponible_kg) : [0];
            chartVariedadesInstance.update();
        }

        if (chartEstadosInstance) {
            const estados = trazabilidad.estados_lotes || {};
            chartEstadosInstance.data.datasets[0].data = [
                estados.disponible || 0,
                estados.reservado || 0,
                estados.negociado || 0,
                estados.vendido || 0
            ];
            chartEstadosInstance.update();
        }

        if (chartRegionalInstance) {
            const regional = datos.distribucion_regional || [];
            const topFincas = comercializacion.top_fincas || [];
            if (datos.es_asociacion_o_admin) {
                chartRegionalInstance.data.labels = regional.length ? regional.map(r => r.municipio) : ['Sin datos'];
                chartRegionalInstance.data.datasets[0].data = regional.length ? regional.map(r => r.volumen_total_kg) : [0];
            } else {
                chartRegionalInstance.data.labels = topFincas.length ? topFincas.map(f => f.finca) : ['Sin datos'];
                chartRegionalInstance.data.datasets[0].data = topFincas.length ? topFincas.map(f => f.volumen_kg) : [0];
            }
            chartRegionalInstance.update();
        }

        // 3. Actualizar Tablas Dinámicamente
        actualizarTablasHTML(datos);

        // Actualizar etiqueta de sincronización
        const lblHora = document.getElementById('lblUltimaSincronizacion');
        if (lblHora) {
            const ahora = new Date();
            lblHora.textContent = ahora.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }
    }

    /**
     * Renderiza o actualiza las filas de las tablas de desglose regional y top fincas
     */
    function actualizarTablasHTML(datos) {
        // Tabla Regional
        const tablaRegional = document.getElementById('tablaDesgloseRegional');
        if (tablaRegional) {
            const tbody = tablaRegional.querySelector('tbody');
            if (tbody) {
                const regional = datos.distribucion_regional || [];
                if (regional.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="6" class="text-center py-4 text-muted">
                                <i class="bi bi-inbox fs-4 d-block mb-1"></i> No hay lotes registrados para los filtros seleccionados.
                            </td>
                        </tr>
                    `;
                } else {
                    let html = '';
                    regional.forEach(r => {
                        const puntajeHtml = r.puntaje_sca_promedio > 0
                            ? `<span class="badge bg-warning text-dark">${r.puntaje_sca_promedio} pts</span>`
                            : `<span class="text-muted small">—</span>`;

                        html += `
                            <tr>
                                <td class="fw-semibold">
                                    <i class="bi bi-geo-alt-fill text-danger me-1"></i>${r.municipio}
                                </td>
                                <td class="text-center">
                                    <span class="badge bg-secondary rounded-pill">${r.lotes}</span>
                                </td>
                                <td class="text-end fw-semibold">${formateadorNumero.format(r.volumen_total_kg)} kg</td>
                                <td class="text-end text-success fw-semibold">${formateadorNumero.format(r.volumen_vendido_kg)} kg</td>
                                <td class="text-end fw-bold">${formateadorMoneda.format(r.ingresos_totales_cop)}</td>
                                <td class="text-center">${puntajeHtml}</td>
                            </tr>
                        `;
                    });
                    tbody.innerHTML = html;
                }
            }
        }

        // Tabla Top Fincas
        const tablaTopFincas = document.getElementById('tablaTopFincas');
        if (tablaTopFincas) {
            const tbody = tablaTopFincas.querySelector('tbody');
            if (tbody) {
                const topFincas = (datos.indicadores_comercializacion && datos.indicadores_comercializacion.top_fincas) || [];
                if (topFincas.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="3" class="text-center py-3 text-muted small">Sin registros activos</td></tr>`;
                } else {
                    let html = '';
                    topFincas.forEach(f => {
                        html += `
                            <tr>
                                <td>
                                    <div class="fw-bold text-truncate" style="max-width: 140px;">${f.finca}</div>
                                    <small class="text-muted">${f.municipio}</small>
                                </td>
                                <td class="text-center">
                                    <span class="badge bg-light text-dark border">${f.lotes}</span>
                                </td>
                                <td class="text-end fw-semibold">${formateadorNumero.format(f.volumen_kg)} kg</td>
                            </tr>
                        `;
                    });
                    tbody.innerHTML = html;
                }
            }
        }
    }

    /**
     * Ejecuta una consulta asíncrona a la API REST de Indicadores
     */
    function consultarApiDashboard(queryParams) {
        const overlay = document.getElementById('loadingOverlayDashboard');
        const iconoRefrescar = document.getElementById('iconoRefrescar');

        if (overlay) overlay.style.display = 'flex';
        if (iconoRefrescar) iconoRefrescar.classList.add('spin-animation');

        const url = `/api/v1/indicadores/dashboard/?${queryParams}`;

        fetch(url, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`Error HTTP ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(datos => {
            actualizarVisualizacionDashboard(datos);
            // Sincronizar URL del navegador sin recarga para permitir compartir filtros
            const nuevaUrl = `${window.location.pathname}${queryParams ? '?' + queryParams : ''}`;
            window.history.replaceState(null, '', nuevaUrl);
        })
        .catch(err => {
            console.error('Error al actualizar el dashboard de indicadores:', err);
        })
        .finally(() => {
            if (overlay) overlay.style.display = 'none';
            if (iconoRefrescar) iconoRefrescar.classList.remove('spin-animation');
        });
    }

    /**
     * Vinculación de eventos interactivos
     */
    document.addEventListener('DOMContentLoaded', function () {
        const datosIniciales = obtenerDatosIniciales();
        if (datosIniciales) {
            inicializarGraficos(datosIniciales);
        }

        const formFiltros = document.getElementById('formFiltrosDashboard');
        if (formFiltros) {
            formFiltros.addEventListener('submit', function (e) {
                e.preventDefault();
                const formData = new FormData(formFiltros);
                const params = new URLSearchParams();
                for (const [key, value] of formData.entries()) {
                    if (value && value.trim() !== '') {
                        params.append(key, value.trim());
                    }
                }
                consultarApiDashboard(params.toString());
            });
        }

        const btnLimpiar = document.getElementById('btnLimpiarFiltros');
        if (btnLimpiar && formFiltros) {
            btnLimpiar.addEventListener('click', function () {
                formFiltros.reset();
                consultarApiDashboard('');
            });
        }

        const btnRefrescar = document.getElementById('btnRefrescarDashboard');
        if (btnRefrescar && formFiltros) {
            btnRefrescar.addEventListener('click', function () {
                const formData = new FormData(formFiltros);
                const params = new URLSearchParams();
                for (const [key, value] of formData.entries()) {
                    if (value && value.trim() !== '') {
                        params.append(key, value.trim());
                    }
                }
                consultarApiDashboard(params.toString());
            });
        }
    });

})();
