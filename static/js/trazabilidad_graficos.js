/**
 * Gráficos de trazabilidad de "Mis Fincas".
 * Lee el resumen que la vista entrega con json_script (#datos-trazabilidad)
 * y dibuja cuatro gráficos con Chart.js: kg por cosecha, lotes por cosecha,
 * lotes por estado del lote y lotes por proceso de beneficio.
 */
(function () {
    'use strict';

    var nodo = document.getElementById('datos-trazabilidad');
    if (!nodo || typeof Chart === 'undefined') { return; }

    var datos;
    try { datos = JSON.parse(nodo.textContent); } catch (e) { return; }

    var PALETA = ['#4A2C2A', '#1B381E', '#B8860B', '#6B8E23', '#8B5A2B',
                  '#2F5D62', '#A0522D', '#556B2F', '#7B3F00', '#3E6B48'];
    var COLOR_TOTAL = '#4A2C2A';
    var COLOR_EN_LOTES = '#1B381E';
    var COLOR_DISPONIBLE = '#B8860B';

    function lienzo(id) {
        var el = document.getElementById(id);
        return el ? el.getContext('2d') : null;
    }

    var cosechas = datos.cosechas || [];
    var etiquetas = cosechas.map(function (c) { return c.etiqueta; });

    // 1) Kg por cosecha: total, ya repartido en lotes y disponible.
    var ctx1 = lienzo('grafico-kg-cosecha');
    if (ctx1) {
        new Chart(ctx1, {
            type: 'bar',
            data: {
                labels: etiquetas,
                datasets: [
                    { label: 'Total cosechado (kg)', data: cosechas.map(function (c) { return c.total_kg; }), backgroundColor: COLOR_TOTAL },
                    { label: 'En lotes (kg)', data: cosechas.map(function (c) { return c.en_lotes_kg; }), backgroundColor: COLOR_EN_LOTES },
                    { label: 'Disponible (kg)', data: cosechas.map(function (c) { return c.disponible_kg; }), backgroundColor: COLOR_DISPONIBLE }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } },
                scales: { y: { beginAtZero: true, title: { display: true, text: 'kg' } } }
            }
        });
    }

    // 2) Lotes por cosecha, un dataset por finca para colorearlas distinto.
    var ctx2 = lienzo('grafico-lotes-cosecha');
    if (ctx2) {
        var fincas = [];
        cosechas.forEach(function (c) { if (fincas.indexOf(c.finca) === -1) { fincas.push(c.finca); } });
        new Chart(ctx2, {
            type: 'bar',
            data: {
                labels: etiquetas,
                datasets: fincas.map(function (finca, i) {
                    return {
                        label: finca,
                        data: cosechas.map(function (c) { return c.finca === finca ? c.lotes : null; }),
                        backgroundColor: PALETA[i % PALETA.length]
                    };
                })
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    x: { stacked: true },
                    y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: 'Lotes' } }
                }
            }
        });
    }

    // 3 y 4) Donas de distribución de lotes.
    function dona(idLienzo, filas) {
        var ctx = lienzo(idLienzo);
        if (!ctx) { return; }
        filas = filas || [];
        if (!filas.length) { return; }
        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: filas.map(function (f) { return f.nombre; }),
                datasets: [{
                    data: filas.map(function (f) { return f.total; }),
                    backgroundColor: filas.map(function (f, i) { return PALETA[i % PALETA.length]; })
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } }
            }
        });
    }
    dona('grafico-lotes-estado', datos.por_estado);
    dona('grafico-lotes-proceso', datos.por_proceso);
})();
