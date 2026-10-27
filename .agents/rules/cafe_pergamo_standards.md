# Estándares de Desarrollo y QA para Café Pérgamo

Este archivo define las restricciones, patrones arquitectónicos y guardrails de calidad obligatorios para el proyecto **Café Pérgamo**.

---

## 1. Plantillas HTML y Renderizado de Mensajes Flash

- **Regla de Alertas Únicas:** La plantilla base `templates/base.html` define un bloque global `{% block messages %}`.
  - **Invariante:** Toda plantilla que extienda `base.html` y defina su propio contenedor o tarjeta de alertas dentro de `{% block content %}` **DEBE** anular el bloque superior declarando explícitamente:
    ```html
    {% block messages %}{% endblock %}
    ```
  - **Razón:** Si no se anula, Django renderiza las alertas dos veces (una arriba del contenido y otra dentro de la tarjeta o contenedor de la página).

---

## 2. Estilos Visuales y Contraste (Bootstrap 5 & Café Pérgamo)

- **Colisión de Especificidad en Bootstrap:** La clase utilitaria `.bg-gradient` de Bootstrap 5 tiene una regla con `!important` sobre `background-image` (`background-image: var(--bs-gradient) !important;`).
  - **Prohibición:** NUNCA combinar `.bg-gradient` con degradados personalizados en el atributo `style="background: linear-gradient(...)"`. Bootstrap anulará el fondo y lo dejará transparente/blanco, provocando texto blanco ilegible.
  - **Estilo Institucional:** Usar degradados explícitos con los tokens oficiales:
    ```html
    style="background: linear-gradient(135deg, #2B1810 0%, #4A2C2A 50%, #1B381E 100%) !important; color: #ffffff !important;"
    ```
  - **Accesibilidad:** Garantizar contraste WCAG 2.1 AA (mínimo 4.5:1) en todos los encabezados y textos institucionales.

---

## 3. Reglas de Negocio del Catálogo Comercial (HU-19 / HU-20)

- **Lotes Disponibles (Vitrina Pública):**
  - Toda consulta orientada a compradores o a la API pública comercial DEBE usar como base la función de servicio `lotes_disponibles_en_catalogo()`.
  - Un lote solo es elegible si cumple simultáneamente:
    1. `publicado_en_catalogo = True` y `activo = True`.
    2. `cantidad > Decimal("0.00")` (stock disponible en inventario).
    3. `cosecha.activo = True` y `cosecha.finca.activo = True`.
    4. Cuenta con municipio asignado en la finca, variedad en la cosecha, proceso de beneficio en el lote y evaluación física/sensorial (`CaracteristicasCalidad`).
- **Desplegables de Filtro:**
  - Los desplegables de filtro (Municipio, Variedad, Proceso) deben poblarse exclusivamente con opciones que tengan lotes disponibles en el momento (`obtener_opciones_filtro_catalogo()`), nunca con el catálogo maestro completo.

---

## 4. Convenciones para Suites de Pruebas (fincas/tests.py)

- **Fixtures Precargadas de Municipios:**
  - Las migraciones cargan los 40 municipios de Norte de Santander. En pruebas unitarias, NUNCA usar `Municipio.objects.create(nombre="Toledo")` directamente, ya que provocará un error de validación por nombre duplicado.
  - Usar siempre:
    ```python
    self.municipio = Municipio.objects.filter(nombre="Toledo", departamento="Norte de Santander").first()
    ```
- **Campos Obligatorios de Cosecha:**
  - El modelo `Cosecha` utiliza `fecha_cosecha` y `cantidad_total` (no `cantidad_recolectada`).
