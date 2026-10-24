/* Filtros de las listas de Contratos y Bajas (24-10-2026).
 *
 * Dos ayudas para quien no está acostumbrado a usar filtros:
 *
 * 1. ETIQUETAS sobre la tabla con cada filtro en uso («Sexo: Mujeres ✕»). La ✕
 *    quita ese filtro sin abrir el panel. Así, quien llega desde el «Ver más» de
 *    la Dashboard ve enseguida por qué la lista sale acotada.
 * 2. «FILTROS AVANZADOS» plegados: el botón dice cuántos hay en uso y la sección
 *    se abre sola si alguno lo está.
 *
 * No cambia ningún campo: lee los mismos <select>/<input> del panel. La fuente de
 * verdad sigue siendo el panel, y quitar una etiqueta es limpiar su campo y
 * volver a buscar (`triggerSearch()` de cada lista).
 *
 * Marcado que espera:
 *   - el panel:             .orb-panel-filtros
 *   - la sección plegada:   [data-filtros-avanzados] (un .collapse de Bootstrap)
 *   - el contador:          [data-contador-avanzados] dentro del botón
 *   - la fila de etiquetas: [data-filtros-activos]
 */
(function () {
    'use strict';

    function etiquetaDe(control) {
        if (control.dataset.etiqueta) return control.dataset.etiqueta;
        var label = control.id ? document.querySelector('label[for="' + control.id + '"]') : null;
        if (!label) {
            var caja = control.closest('.mb-2, .col-5, .col-6, .col-7, .col-12');
            label = caja ? caja.querySelector('label') : null;
        }
        return label ? label.textContent.replace(/\s+/g, ' ').trim() : control.name;
    }

    function fecha(valor) {
        var p = valor.split('-');
        return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : valor;
    }

    /* Los filtros en uso de una zona del panel: [{etiqueta, texto, quitar}]. */
    function enUso(zona) {
        var lista = [];
        zona.querySelectorAll('select[name], input[name]').forEach(function (control) {
            if (control.disabled || ['hidden', 'search', 'text'].indexOf(control.type) !== -1) return;
            var etiqueta = etiquetaDe(control);
            if (control.multiple) {
                // Selector de fichas (unidad, departamento, cargo): una etiqueta por ficha.
                Array.prototype.forEach.call(control.options, function (opcion) {
                    if (!opcion.selected) return;
                    lista.push({
                        etiqueta: etiqueta, texto: opcion.text.trim(),
                        quitar: function () {
                            opcion.selected = false;
                            var raiz = control.closest('.chip-multiselect');
                            if (raiz && window.OrbithSelectorUnidades) window.OrbithSelectorUnidades.sincronizar(raiz);
                            buscar();
                        }
                    });
                });
                return;
            }
            if (!control.value) return;
            var texto = control.tagName === 'SELECT'
                ? (control.selectedOptions[0] ? control.selectedOptions[0].text.trim() : control.value)
                : (control.type === 'date' ? fecha(control.value) : control.value);
            lista.push({
                etiqueta: etiqueta, texto: texto,
                quitar: function () {
                    control.value = '';
                    // El `onchange` del campo ya busca (y la provincia recarga sus municipios).
                    control.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });
        });
        return lista;
    }

    function buscar() {
        if (typeof window.triggerSearch === 'function') window.triggerSearch();
    }

    function pintar() {
        var panel = document.querySelector('.orb-panel-filtros');
        if (!panel) return;

        // Contador de los avanzados.
        var avanzados = panel.querySelector('[data-filtros-avanzados]');
        var contador = panel.querySelector('[data-contador-avanzados]');
        if (avanzados && contador) {
            var n = enUso(avanzados).length;
            contador.textContent = n ? n + (n === 1 ? ' activo' : ' activos') : '';
            contador.classList.toggle('d-none', !n);
        }

        // Etiquetas sobre la tabla.
        var fila = document.querySelector('[data-filtros-activos]');
        if (!fila) return;
        var activos = enUso(panel);
        fila.innerHTML = '';
        fila.classList.toggle('d-none', !activos.length);
        if (!activos.length) return;
        var rotulo = document.createElement('span');
        rotulo.className = 'small text-muted me-1';
        rotulo.textContent = 'Filtrando por:';
        fila.appendChild(rotulo);
        activos.forEach(function (filtro) {
            var etiqueta = document.createElement('span');
            etiqueta.className = 'badge bg-label-primary d-inline-flex align-items-center gap-1 fw-semibold';
            etiqueta.style.fontSize = '.75rem';
            var texto = document.createElement('span');
            texto.textContent = filtro.etiqueta + ': ' + filtro.texto;
            var quitar = document.createElement('button');
            quitar.type = 'button';
            quitar.className = 'btn-close btn-close-sm ms-1';
            quitar.style.fontSize = '.55rem';
            quitar.setAttribute('aria-label', 'Quitar el filtro ' + filtro.etiqueta);
            quitar.addEventListener('click', function () { filtro.quitar(); setTimeout(pintar, 0); });
            etiqueta.appendChild(texto);
            etiqueta.appendChild(quitar);
            fila.appendChild(etiqueta);
        });
        if (activos.length > 1 && typeof window.resetFiltros === 'function') {
            var todos = document.createElement('button');
            todos.type = 'button';
            todos.className = 'btn btn-link btn-sm p-0 ms-1 small';
            todos.textContent = 'Quitar todos';
            todos.addEventListener('click', function () { window.resetFiltros(); setTimeout(pintar, 0); });
            fila.appendChild(todos);
        }
    }

    function iniciar() {
        var panel = document.querySelector('.orb-panel-filtros');
        if (!panel) return;
        // Con algún avanzado en uso, la sección se abre sola.
        var avanzados = panel.querySelector('[data-filtros-avanzados]');
        if (avanzados && enUso(avanzados).length && window.bootstrap) {
            window.bootstrap.Collapse.getOrCreateInstance(avanzados, { toggle: false }).show();
        }
        pintar();
        panel.addEventListener('change', function () { setTimeout(pintar, 0); });
        document.addEventListener('orbith:unidades', function () { setTimeout(pintar, 0); }, true);
        // La búsqueda (también «Reset») y la recarga de municipios o especialidades.
        document.addEventListener('htmx:afterSettle', function () { setTimeout(pintar, 0); });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
    else iniciar();
})();
