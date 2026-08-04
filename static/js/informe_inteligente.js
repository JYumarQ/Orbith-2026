/**
 * Informe Inteligente — lógica de la interfaz.
 *
 * Estructura del archivo:
 *   1. Constantes y utilidades
 *   2. Panel de campos (selección, búsqueda, contador)
 *   3. Panel de filtros dinámicos
 *   4. Configuración: leerla del formulario y volcarla en él
 *   5. Vista previa y paginación
 *   6. Plantillas rápidas, favoritos e historial
 */
document.addEventListener('DOMContentLoaded', function () {

    // =====================================================================
    // 1. CONSTANTES Y UTILIDADES
    // =====================================================================

    // Debe reflejar OPERADORES_POR_TIPO de informe_inteligente/metadata.py.
    const OPERADORES_POR_TIPO = {
        texto:    [['igual', 'Es igual a'], ['diferente', 'Es diferente de'], ['contiene', 'Contiene'], ['es_nulo', 'Está vacío'], ['no_es_nulo', 'No está vacío']],
        numero:   [['igual', 'Es igual a'], ['diferente', 'Es diferente de'], ['mayor', 'Es mayor que'], ['menor', 'Es menor que'], ['es_nulo', 'Está vacío'], ['no_es_nulo', 'No está vacío']],
        fecha:    [['entre_fechas', 'Entre fechas'], ['mes', 'Mes de'], ['semana', 'Semana de'], ['mayor', 'Después de'], ['menor', 'Antes de'], ['es_nulo', 'Está vacío'], ['no_es_nulo', 'No está vacío']],
        opcion:   [['igual', 'Es igual a'], ['diferente', 'Es diferente de'], ['en_lista', 'Es alguno de'], ['no_en_lista', 'No es ninguno de'], ['es_nulo', 'Está vacío'], ['no_es_nulo', 'No está vacío']],
        booleano: [['igual', 'Es igual a']]
    };

    // Operadores que no necesitan que el usuario escriba un valor.
    const OPERADORES_SIN_VALOR = ['es_nulo', 'no_es_nulo'];

    // Operadores cuyo valor es una lista de opciones, no un dato suelto.
    const OPERADORES_MULTIVALOR = ['en_lista', 'no_en_lista'];

    const MESES = [
        ['1', 'Enero'], ['2', 'Febrero'], ['3', 'Marzo'], ['4', 'Abril'],
        ['5', 'Mayo'], ['6', 'Junio'], ['7', 'Julio'], ['8', 'Agosto'],
        ['9', 'Septiembre'], ['10', 'Octubre'], ['11', 'Noviembre'], ['12', 'Diciembre'],
    ];
    const MESES_LARGOS = MESES.map(par => par[1].toLowerCase());

    /** Lunes de la semana actual desplazada `offsetSemanas` semanas. */
    function lunesDeLaSemana(offsetSemanas) {
        const hoy = new Date();
        const diaSemana = (hoy.getDay() + 6) % 7; // lunes=0 ... domingo=6
        const lunes = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - diaSemana);
        lunes.setDate(lunes.getDate() + offsetSemanas * 7);
        return lunes;
    }

    /** Repinta la etiqueta "Semana del 10 al 16 de agosto" y guarda el offset. */
    function actualizarEtiquetaSemana(contenedor, offsetSemanas) {
        const lunes = lunesDeLaSemana(offsetSemanas);
        const domingo = new Date(lunes);
        domingo.setDate(lunes.getDate() + 6);

        const inputOffset = contenedor.querySelector('.ii-semana-offset');
        if (inputOffset) inputOffset.value = offsetSemanas;

        let texto;
        if (lunes.getMonth() === domingo.getMonth()) {
            texto = 'Semana del ' + lunes.getDate() + ' al ' + domingo.getDate() + ' de ' + MESES_LARGOS[lunes.getMonth()];
        } else {
            texto = 'Semana del ' + lunes.getDate() + ' de ' + MESES_LARGOS[lunes.getMonth()] +
                ' al ' + domingo.getDate() + ' de ' + MESES_LARGOS[domingo.getMonth()];
        }
        if (offsetSemanas === 0) texto += ' (actual)';

        const etiqueta = contenedor.querySelector('.ii-semana-etiqueta');
        if (etiqueta) etiqueta.textContent = texto;
    }

    const URLS = window.II_URLS || {};

    function obtenerCookie(nombre) {
        const coincidencia = document.cookie.match('(^|;)\\s*' + nombre + '\\s*=\\s*([^;]+)');
        return coincidencia ? decodeURIComponent(coincidencia.pop()) : null;
    }
    const csrftoken = obtenerCookie('csrftoken');

    /** Aviso breve, con el mismo estilo que usa el resto de Orbith. */
    function notificar(mensaje, icono = 'success') {
        if (!window.Swal) return;
        Swal.fire({
            toast: true,
            position: 'top-end',
            icon: icono,
            title: mensaje,
            showConfirmButton: false,
            timer: 3000,
            timerProgressBar: true,
            background: '#fff',
            color: '#697a8d',
            customClass: { popup: 'border shadow-lg' }
        });
    }

    function confirmar(titulo, texto) {
        if (!window.Swal) return Promise.resolve(window.confirm(texto));
        return Swal.fire({
            title: titulo,
            text: texto,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Sí, continuar',
            cancelButtonText: 'Cancelar',
            customClass: {
                confirmButton: 'btn btn-danger px-4 me-2',
                cancelButton: 'btn btn-secondary px-4'
            },
            buttonsStyling: false
        }).then(r => r.isConfirmed);
    }

    function leerJsonEmbebido(id) {
        const nodo = document.getElementById(id);
        if (!nodo) return null;
        try {
            return JSON.parse(nodo.textContent);
        } catch (e) {
            return null;
        }
    }

    const PLANTILLAS = leerJsonEmbebido('datosPlantillas') || {};

    function elem(id) { return document.getElementById(id); }

    function modeloRaizActual() {
        const select = elem('selectModeloRaiz');
        return select ? select.value : 'CAlta';
    }

    // =====================================================================
    // 2. PANEL DE CAMPOS
    // =====================================================================
    // El panel se inyecta por HTMX, así que todos los manejadores usan
    // delegación de eventos sobre document: siguen funcionando aunque el
    // HTML se reemplace al cambiar de modelo raíz.

    function checkboxesCampos() {
        return Array.from(document.querySelectorAll('.campo-checkbox'));
    }

    function camposSeleccionados() {
        return checkboxesCampos().filter(cb => cb.checked);
    }

    function actualizarContadorCampos() {
        const contador = elem('contadorCampos');
        if (!contador) return;
        const total = camposSeleccionados().length;
        contador.textContent = total === 1 ? '1 campo seleccionado' : total + ' campos seleccionados';
    }

    /**
     * Rellena el desplegable de ordenación con los campos marcados que
     * admiten orden, conservando la elección previa si sigue disponible.
     */
    function refrescarSelectOrden() {
        const select = elem('selectOrdenarPor');
        if (!select) return;

        const valorPrevio = select.value;
        select.innerHTML = '<option value="">— Sin ordenar —</option>';

        camposSeleccionados()
            .filter(cb => cb.dataset.ordenable === '1')
            .forEach(cb => {
                const opcion = document.createElement('option');
                opcion.value = cb.value;
                opcion.textContent = cb.dataset.label;
                select.appendChild(opcion);
            });

        select.value = Array.from(select.options).some(o => o.value === valorPrevio) ? valorPrevio : '';
        actualizarResumenOrden();
    }

    /**
     * 'desglosar_por' admite varios campos a la vez. Esta función acepta
     * tanto el string único que usaban los favoritos/plantillas guardados
     * antes de esta versión como la lista nueva, para no romper nada viejo.
     */
    function normalizarDesglose(valor) {
        if (!valor) return [];
        return Array.isArray(valor) ? valor : [valor];
    }

    /**
     * Rellena el desplegable de desglose (Select2 de selección múltiple) con
     * TODOS los campos agrupables del modelo, estén o no marcados para
     * mostrar: el resumen es independiente de las columnas del detalle.
     */
    function refrescarSelectDesglose() {
        const select = elem('selectDesglosarPor');
        if (!select) return;

        const valoresPrevios = window.jQuery ? ($(select).val() || []) : [];

        if (window.jQuery && $(select).data('select2')) {
            $(select).select2('destroy');
        }
        select.innerHTML = '';

        checkboxesCampos()
            .filter(cb => cb.dataset.agrupable === '1')
            .forEach(cb => {
                const opcion = document.createElement('option');
                opcion.value = cb.value;
                opcion.textContent = cb.dataset.label;
                select.appendChild(opcion);
            });

        const disponibles = Array.from(select.options).map(o => o.value);
        const aRestaurar = valoresPrevios.filter(v => disponibles.includes(v));

        if (window.jQuery) {
            $(select).val(aRestaurar);
            $(select).select2({
                theme: 'bootstrap-5',
                width: '100%',
                placeholder: '— Sin desglose —',
                allowClear: true,
            });
        }
    }

    function actualizarResumenOrden() {
        const resumen = elem('resumenOrden');
        const select = elem('selectOrdenarPor');
        if (!resumen || !select) return;

        if (!select.value) {
            resumen.textContent = 'Sin ordenar';
            return;
        }
        const direccion = elem('selectOrdenDireccion').value === 'desc' ? 'descendente' : 'ascendente';
        const etiqueta = select.options[select.selectedIndex].textContent;
        resumen.textContent = etiqueta + ' · ' + direccion;
    }

    document.addEventListener('change', function (e) {
        if (e.target.classList.contains('campo-checkbox')) {
            actualizarContadorCampos();
            refrescarSelectOrden();
        }
        if (e.target.id === 'selectOrdenarPor' || e.target.id === 'selectOrdenDireccion') {
            actualizarResumenOrden();
        }
    });

    // Búsqueda en vivo de campos por nombre
    document.addEventListener('input', function (e) {
        if (e.target.id !== 'buscadorCampos') return;

        const termino = e.target.value.trim().toLowerCase();
        let visibles = 0;

        document.querySelectorAll('.ii-fld-check').forEach(fila => {
            const coincide = fila.dataset.label.includes(termino);
            fila.style.display = coincide ? 'flex' : 'none';
            if (coincide) visibles++;
        });

        // Ocultar la columna de una categoría si ninguno de sus campos coincide
        document.querySelectorAll('.ii-categoria-col').forEach(columna => {
            const alguno = Array.from(columna.querySelectorAll('.ii-fld-check'))
                .some(f => f.style.display !== 'none');
            columna.style.display = alguno ? '' : 'none';
        });

        const aviso = elem('mensajeSinCoincidencias');
        if (aviso) aviso.style.display = visibles === 0 ? 'block' : 'none';
    });

    // Marcar / desmarcar todos (solo los campos visibles tras una búsqueda)
    document.addEventListener('click', function (e) {
        const marcar = e.target.closest('#btnMarcarTodos');
        const desmarcar = e.target.closest('#btnDesmarcarTodos');
        if (!marcar && !desmarcar) return;

        checkboxesCampos().forEach(cb => {
            const fila = cb.closest('.ii-fld-check');
            if (fila && fila.style.display === 'none') return;
            cb.checked = Boolean(marcar);
        });
        actualizarContadorCampos();
        refrescarSelectOrden();
    });

    // Al cambiar de modelo raíz se recargan los campos y se limpia todo lo demás
    elem('selectModeloRaiz')?.addEventListener('change', function () {
        const modelo = this.value;
        htmx.ajax('GET', URLS.campos.replace('MODELO', encodeURIComponent(modelo)), {
            target: '#panelCamposContainer',
            swap: 'innerHTML'
        });

        elem('listaFiltros').innerHTML = '';
        elem('resultadosContainer').innerHTML = '';
        elem('contadorRegistros').textContent = '—';
        elem('btnGuardarFavorito').disabled = true;
        document.querySelectorAll('.btn-plantilla').forEach(c => c.classList.remove('active'));
        actualizarAvisoFiltros();
        refrescarSelectOrden();
        refrescarSelectDesglose();
    });

    document.body.addEventListener('htmx:afterSwap', function (evt) {
        if (evt.target.id === 'panelCamposContainer') {
            actualizarContadorCampos();
            refrescarSelectOrden();
            refrescarSelectDesglose();
        }
    });

    // =====================================================================
    // 3. FILTROS DINÁMICOS
    // =====================================================================

    function actualizarAvisoFiltros() {
        const total = document.querySelectorAll('.ii-filter-row').length;
        const contador = elem('contadorFiltros');
        const aviso = elem('avisoSinFiltros');

        if (contador) {
            contador.textContent = total === 0
                ? 'Sin filtros'
                : (total === 1 ? '1 filtro activo' : total + ' filtros activos');
        }
        if (aviso) aviso.style.display = total === 0 ? 'block' : 'none';
    }

    /**
     * Dibuja el control de valor apropiado según el tipo de campo y el
     * operador elegido: fecha, número, desplegable de opciones o texto.
     */
    function pintarControlValor(fila, valorInicial) {
        const contenedor = fila.querySelector('.ii-filtro-valor');
        const selectCampo = fila.querySelector('.select-filtro-campo');
        const operador = fila.querySelector('.select-filtro-operador').value;
        const opcionCampo = selectCampo.options[selectCampo.selectedIndex];
        const tipo = opcionCampo ? opcionCampo.dataset.tipo : '';

        if (OPERADORES_SIN_VALOR.includes(operador)) {
            contenedor.innerHTML = '<input type="text" class="form-control form-control-sm" disabled placeholder="No aplica">';
            return;
        }

        if (operador === 'entre_fechas') {
            const desde = (valorInicial && valorInicial.desde) || '';
            const hasta = (valorInicial && valorInicial.hasta) || '';
            contenedor.innerHTML =
                '<div class="input-group input-group-sm">' +
                '  <input type="date" class="form-control input-filtro-desde" value="' + desde + '">' +
                '  <span class="input-group-text">a</span>' +
                '  <input type="date" class="form-control input-filtro-hasta" value="' + hasta + '">' +
                '</div>';
            return;
        }

        if (operador === 'mes') {
            const mesInicial = valorInicial ? String(valorInicial) : String(new Date().getMonth() + 1);
            let html = '<select class="form-select form-select-sm input-filtro-valor">';
            MESES.forEach(function (par) {
                html += '<option value="' + par[0] + '"' + (par[0] === mesInicial ? ' selected' : '') + '>' + par[1] + '</option>';
            });
            contenedor.innerHTML = html + '</select>';
            return;
        }

        if (operador === 'semana') {
            const offsetInicial = (valorInicial && typeof valorInicial === 'object' && valorInicial.offset_semanas !== undefined)
                ? (parseInt(valorInicial.offset_semanas, 10) || 0) : 0;
            contenedor.innerHTML =
                '<div class="ii-semana-navegador d-flex align-items-center gap-1">' +
                '  <button type="button" class="btn btn-outline-secondary btn-sm btn-semana-prev" title="Semana anterior"><i class="bi bi-chevron-left"></i></button>' +
                '  <div class="flex-grow-1 text-center small fw-semibold ii-semana-etiqueta"></div>' +
                '  <button type="button" class="btn btn-outline-secondary btn-sm btn-semana-next" title="Semana siguiente"><i class="bi bi-chevron-right"></i></button>' +
                '  <button type="button" class="btn btn-outline-primary btn-sm btn-semana-hoy" title="Ir a la semana actual"><i class="bi bi-calendar-check"></i></button>' +
                '  <input type="hidden" class="ii-semana-offset" value="' + offsetInicial + '">' +
                '</div>';
            actualizarEtiquetaSemana(contenedor, offsetInicial);
            return;
        }

        const valor = (valorInicial === null || valorInicial === undefined) ? '' : String(valorInicial);
        let choices = [];
        try {
            choices = JSON.parse(opcionCampo?.dataset.choices || '[]');
        } catch (e) {
            choices = [];
        }

        if (OPERADORES_MULTIVALOR.includes(operador)) {
            // Selección múltiple: permite expresar "es CDI o CEJ" en un solo filtro.
            const yaElegidos = Array.isArray(valorInicial) ? valorInicial.map(String) : [];
            let html = '<select class="form-select form-select-sm input-filtro-valor" multiple size="' +
                Math.min(choices.length || 3, 6) + '">';
            choices.forEach(function (par) {
                const seleccionado = yaElegidos.includes(String(par[0])) ? ' selected' : '';
                html += '<option value="' + par[0] + '"' + seleccionado + '>' + par[1] + '</option>';
            });
            html += '</select><div class="form-text" style="font-size:10px;">Mantenga Ctrl para elegir varios.</div>';
            contenedor.innerHTML = html;
            return;
        }

        if (tipo === 'opcion' && choices.length) {
            let html = '<select class="form-select form-select-sm input-filtro-valor">';
            choices.forEach(function (par) {
                const seleccionado = String(par[0]) === valor ? ' selected' : '';
                html += '<option value="' + par[0] + '"' + seleccionado + '>' + par[1] + '</option>';
            });
            contenedor.innerHTML = html + '</select>';
        } else if (tipo === 'fecha') {
            contenedor.innerHTML = '<input type="date" class="form-control form-control-sm input-filtro-valor" value="' + valor + '">';
        } else if (tipo === 'numero') {
            contenedor.innerHTML = '<input type="number" step="any" class="form-control form-control-sm input-filtro-valor" value="' + valor + '" placeholder="Valor">';
        } else if (tipo === 'booleano') {
            contenedor.innerHTML =
                '<select class="form-select form-select-sm input-filtro-valor">' +
                '  <option value="true"' + (valor === 'true' ? ' selected' : '') + '>Sí</option>' +
                '  <option value="false"' + (valor === 'false' ? ' selected' : '') + '>No</option>' +
                '</select>';
        } else {
            contenedor.innerHTML = '<input type="text" class="form-control form-control-sm input-filtro-valor" value="' + valor + '" placeholder="Valor a comparar">';
        }
    }

    function pintarOperadores(fila, operadorInicial) {
        const selectCampo = fila.querySelector('.select-filtro-campo');
        const selectOperador = fila.querySelector('.select-filtro-operador');
        const opcionCampo = selectCampo.options[selectCampo.selectedIndex];
        const tipo = opcionCampo ? opcionCampo.dataset.tipo : '';

        if (!tipo || !OPERADORES_POR_TIPO[tipo]) {
            selectOperador.innerHTML = '<option value="">— Operador —</option>';
            selectOperador.disabled = true;
            return;
        }

        selectOperador.innerHTML = '';
        OPERADORES_POR_TIPO[tipo].forEach(function (op) {
            const opcion = document.createElement('option');
            opcion.value = op[0];
            opcion.textContent = op[1];
            selectOperador.appendChild(opcion);
        });
        selectOperador.disabled = false;

        if (operadorInicial && OPERADORES_POR_TIPO[tipo].some(op => op[0] === operadorInicial)) {
            selectOperador.value = operadorInicial;
        }
    }

    /**
     * Añade una fila de filtro. Los tres parámetros permiten reconstruir un
     * filtro guardado (plantilla, favorito o último informe ejecutado).
     */
    function crearFilaFiltro(campoInicial, operadorInicial, valorInicial) {
        const lista = elem('listaFiltros');
        if (!lista) return null;

        // El desplegable ofrece TODOS los campos filtrables del modelo, estén
        // o no marcados para mostrar: se puede filtrar por algo sin mostrarlo.
        const filtrables = checkboxesCampos().filter(cb => cb.dataset.filtrable === '1');

        if (!filtrables.length) {
            notificar('Los campos aún se están cargando. Inténtelo de nuevo en un momento.', 'info');
            return null;
        }

        let opcionesHtml = '<option value="">— Seleccionar campo —</option>';
        filtrables.forEach(function (cb) {
            const seleccionado = cb.value === campoInicial ? ' selected' : '';
            opcionesHtml += '<option value="' + cb.value + '"' +
                ' data-tipo="' + cb.dataset.tipo + '"' +
                " data-choices='" + (cb.dataset.choices || '[]') + "'" +
                seleccionado + '>' + cb.dataset.label + '</option>';
        });

        const fila = document.createElement('div');
        fila.className = 'ii-filter-row row g-2 align-items-center';
        fila.innerHTML =
            '<div class="col-md-4">' +
            '  <select class="form-select form-select-sm select-filtro-campo">' + opcionesHtml + '</select>' +
            '</div>' +
            '<div class="col-md-3">' +
            '  <select class="form-select form-select-sm select-filtro-operador" disabled><option value="">— Operador —</option></select>' +
            '</div>' +
            '<div class="col-md-4 ii-filtro-valor">' +
            '  <input type="text" class="form-control form-control-sm" disabled placeholder="Valor">' +
            '</div>' +
            '<div class="col-md-1 text-end">' +
            '  <button type="button" class="btn btn-sm btn-link text-danger p-0 btn-eliminar-filtro" title="Eliminar este filtro">' +
            '    <i class="bi bi-trash3"></i>' +
            '  </button>' +
            '</div>';

        lista.appendChild(fila);

        if (campoInicial) {
            pintarOperadores(fila, operadorInicial);
            pintarControlValor(fila, valorInicial);
        }

        actualizarAvisoFiltros();
        return fila;
    }

    elem('btnAgregarFiltro')?.addEventListener('click', function () {
        crearFilaFiltro(null, null, null);
    });

    // Delegación para las filas de filtro, que se crean y destruyen sin parar
    elem('listaFiltros')?.addEventListener('change', function (e) {
        const fila = e.target.closest('.ii-filter-row');
        if (!fila) return;

        if (e.target.classList.contains('select-filtro-campo')) {
            pintarOperadores(fila, null);
            pintarControlValor(fila, null);
        } else if (e.target.classList.contains('select-filtro-operador')) {
            pintarControlValor(fila, null);
        }
    });

    elem('listaFiltros')?.addEventListener('click', function (e) {
        if (e.target.closest('.btn-eliminar-filtro')) {
            e.target.closest('.ii-filter-row').remove();
            actualizarAvisoFiltros();
            return;
        }

        const prev = e.target.closest('.btn-semana-prev');
        const next = e.target.closest('.btn-semana-next');
        const hoy = e.target.closest('.btn-semana-hoy');
        if (!prev && !next && !hoy) return;

        const contenedorValor = e.target.closest('.ii-filtro-valor');
        const inputOffset = contenedorValor?.querySelector('.ii-semana-offset');
        if (!inputOffset) return;

        let offset = parseInt(inputOffset.value, 10) || 0;
        if (prev) offset -= 1;
        else if (next) offset += 1;
        else offset = 0;

        actualizarEtiquetaSemana(contenedorValor, offset);
    });

    // =====================================================================
    // 4. CONFIGURACIÓN: LEERLA Y VOLCARLA
    // =====================================================================

    function obtenerConfiguracion() {
        const configuracion = {
            campos: camposSeleccionados().map(cb => cb.value),
            filtros: [],
            desglosar_por: window.jQuery ? ($(elem('selectDesglosarPor')).val() || []) : [],
            ordenar_por: elem('selectOrdenarPor')?.value || '',
            orden_direccion: elem('selectOrdenDireccion')?.value || 'asc'
        };

        document.querySelectorAll('.ii-filter-row').forEach(function (fila) {
            const campo = fila.querySelector('.select-filtro-campo').value;
            const operador = fila.querySelector('.select-filtro-operador').value;
            if (!campo || !operador) return;

            if (OPERADORES_SIN_VALOR.includes(operador)) {
                configuracion.filtros.push({ campo: campo, operador: operador, valor: null });
                return;
            }

            if (operador === 'entre_fechas') {
                const desde = fila.querySelector('.input-filtro-desde')?.value;
                const hasta = fila.querySelector('.input-filtro-hasta')?.value;
                if (!desde || !hasta) return;  // rango incompleto: se ignora
                configuracion.filtros.push({ campo: campo, operador: operador, valor: { desde: desde, hasta: hasta } });
                return;
            }

            if (OPERADORES_MULTIVALOR.includes(operador)) {
                const elegidos = Array.from(fila.querySelectorAll('.input-filtro-valor option:checked')).map(o => o.value);
                if (!elegidos.length) return;  // sin opciones marcadas: se ignora
                configuracion.filtros.push({ campo: campo, operador: operador, valor: elegidos });
                return;
            }

            if (operador === 'semana') {
                const offset = parseInt(fila.querySelector('.ii-semana-offset')?.value, 10) || 0;
                configuracion.filtros.push({ campo: campo, operador: operador, valor: { offset_semanas: offset } });
                return;
            }

            const valor = fila.querySelector('.input-filtro-valor')?.value;
            if (valor === undefined || valor === null || valor === '') return;  // filtro vacío: se ignora
            configuracion.filtros.push({ campo: campo, operador: operador, valor: valor });
        });

        return configuracion;
    }

    /** Vuelca una configuración guardada sobre los paneles de la pantalla. */
    function aplicarConfiguracion(configuracion) {
        if (!configuracion) return false;

        if (!checkboxesCampos().length) {
            notificar('Los campos aún se están cargando. Inténtelo de nuevo en un momento.', 'info');
            return false;
        }

        refrescarSelectDesglose();
        const selectDesglose = elem('selectDesglosarPor');
        if (selectDesglose && window.jQuery) {
            $(selectDesglose).val(normalizarDesglose(configuracion.desglosar_por)).trigger('change');
        }

        const campos = configuracion.campos || [];
        checkboxesCampos().forEach(function (cb) {
            cb.checked = campos.includes(cb.value);
        });

        elem('listaFiltros').innerHTML = '';
        (configuracion.filtros || []).forEach(function (filtro) {
            crearFilaFiltro(filtro.campo, filtro.operador, filtro.valor);
        });

        actualizarContadorCampos();
        actualizarAvisoFiltros();
        refrescarSelectOrden();

        const selectOrden = elem('selectOrdenarPor');
        if (selectOrden) {
            selectOrden.value = configuracion.ordenar_por || '';
            elem('selectOrdenDireccion').value = configuracion.orden_direccion || 'asc';
            actualizarResumenOrden();
        }
        return true;
    }

    // =====================================================================
    // 5. VISTA PREVIA Y PAGINACIÓN
    // =====================================================================

    function generarVistaPrevia(pagina) {
        const configuracion = obtenerConfiguracion();

        if (!configuracion.campos.length) {
            notificar('Seleccione al menos un campo para mostrar en el detalle del informe.', 'warning');
            return;
        }

        const datos = new FormData();
        datos.append('modelo_raiz', modeloRaizActual());
        datos.append('configuracion', JSON.stringify(configuracion));
        datos.append('pagina', pagina || 1);

        const contenedor = elem('resultadosContainer');
        contenedor.innerHTML =
            '<div class="ii-panel p-5 text-center text-muted">' +
            '  <div class="spinner-border" style="color: var(--ii-blue);"></div>' +
            '  <div class="mt-2 fw-semibold">Procesando registros...</div>' +
            '</div>';

        fetch(URLS.vistaPrevia, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrftoken },
            body: datos
        })
            .then(function (respuesta) {
                return respuesta.text().then(function (html) {
                    return { ok: respuesta.ok, html: html };
                });
            })
            .then(function (resultado) {
                contenedor.innerHTML = resultado.html;

                if (!resultado.ok) {
                    elem('contadorRegistros').textContent = '—';
                    elem('btnGuardarFavorito').disabled = true;
                    return;
                }

                elem('btnGuardarFavorito').disabled = false;

                // El total lo publica el propio fragmento renderizado por Django,
                // así no hay que adivinarlo leyendo el texto de la tabla.
                const panel = contenedor.querySelector('[data-total-registros]');
                elem('contadorRegistros').textContent = panel
                    ? Number(panel.dataset.totalRegistros).toLocaleString('es-ES')
                    : '—';

                contenedor.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            })
            .catch(function () {
                contenedor.innerHTML =
                    '<div class="alert alert-danger m-0">' +
                    '  <i class="bi bi-exclamation-triangle me-1"></i>' +
                    '  No se pudo contactar con el servidor. Compruebe su conexión e inténtelo de nuevo.' +
                    '</div>';
                elem('contadorRegistros').textContent = '—';
                elem('btnGuardarFavorito').disabled = true;
            });
    }

    elem('btnGenerarVistaPrevia')?.addEventListener('click', function () {
        generarVistaPrevia(1);
    });

    elem('resultadosContainer')?.addEventListener('click', function (e) {
        const enlace = e.target.closest('a.page-link[data-pagina]');
        if (!enlace) return;
        e.preventDefault();
        if (enlace.closest('.page-item').classList.contains('disabled')) return;
        generarVistaPrevia(enlace.dataset.pagina);
    });

    // =====================================================================
    // 6. PLANTILLAS RÁPIDAS, FAVORITOS E HISTORIAL
    // =====================================================================

    elem('contenedorPlantillas')?.addEventListener('click', function (e) {
        const chip = e.target.closest('.btn-plantilla');
        if (!chip) return;

        const plantillasDelModelo = PLANTILLAS[modeloRaizActual()] || [];
        const plantilla = plantillasDelModelo.find(p => p.key === chip.dataset.plantilla);
        if (!plantilla) return;

        if (!aplicarConfiguracion(plantilla.configuracion)) return;

        document.querySelectorAll('.btn-plantilla').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');

        notificar('Plantilla «' + plantilla.nombre + '» aplicada.');
        generarVistaPrevia(1);
    });

    // --- Guardar como favorito ---
    elem('btnGuardarFavorito')?.addEventListener('click', function () {
        elem('inputNombreFavorito').value = '';
        elem('inputDescripcionFavorito').value = '';
        new bootstrap.Modal(elem('modalGuardarFavorito')).show();
    });

    elem('btnConfirmarGuardarFavorito')?.addEventListener('click', function () {
        const nombre = elem('inputNombreFavorito').value.trim();
        if (!nombre) {
            notificar('Escriba un nombre para el informe.', 'warning');
            return;
        }

        const datos = new FormData();
        datos.append('nombre', nombre);
        datos.append('descripcion', elem('inputDescripcionFavorito').value.trim());
        datos.append('modelo_raiz', modeloRaizActual());
        datos.append('configuracion', JSON.stringify(obtenerConfiguracion()));

        const boton = this;
        boton.disabled = true;

        fetch(URLS.guardarFavorito, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrftoken },
            body: datos
        })
            .then(r => r.json())
            .then(function (respuesta) {
                if (!respuesta.ok) {
                    notificar(respuesta.error || 'No se pudo guardar el informe.', 'error');
                    return;
                }
                bootstrap.Modal.getInstance(elem('modalGuardarFavorito')).hide();
                notificar('Informe «' + respuesta.nombre + '» guardado en sus favoritos.');
                // Se recarga para que el servidor vuelva a pintar la lista de
                // favoritos, evitando duplicar aquí la lógica de la plantilla.
                setTimeout(() => window.location.reload(), 900);
            })
            .catch(function () {
                notificar('No se pudo contactar con el servidor.', 'error');
            })
            .finally(function () {
                boton.disabled = false;
            });
    });

    // --- Cargar y eliminar favoritos ---
    elem('listaFavoritos')?.addEventListener('click', function (e) {
        const item = e.target.closest('[data-informe-id]');
        if (!item) return;
        const informeId = item.dataset.informeId;

        if (e.target.closest('.btn-eliminar-favorito')) {
            confirmar('¿Eliminar este informe?', 'Se borrará de sus favoritos de forma permanente.')
                .then(function (confirmado) {
                    if (!confirmado) return;
                    fetch(URLS.eliminarFavorito.replace('/0/', '/' + informeId + '/'), {
                        method: 'POST',
                        headers: { 'X-CSRFToken': csrftoken }
                    })
                        .then(r => r.json())
                        .then(function (respuesta) {
                            if (!respuesta.ok) throw new Error();
                            item.remove();
                            notificar('Informe eliminado.');
                        })
                        .catch(() => notificar('No se pudo eliminar el informe.', 'error'));
                });
            return;
        }

        if (!e.target.closest('.btn-cargar-favorito')) return;

        fetch(URLS.cargarFavorito.replace('/0/', '/' + informeId + '/'))
            .then(function (respuesta) {
                if (!respuesta.ok) throw new Error();
                return respuesta.json();
            })
            .then(function (datos) {
                const select = elem('selectModeloRaiz');
                if (select && select.value !== datos.modelo_raiz) {
                    notificar('Este informe pertenece a otro tipo de datos. Cambie el tipo y vuelva a cargarlo.', 'warning');
                    return;
                }
                if (!aplicarConfiguracion(datos.configuracion)) return;

                document.querySelectorAll('.btn-plantilla').forEach(c => c.classList.remove('active'));
                bootstrap.Offcanvas.getInstance(elem('panelFavoritos'))?.hide();
                notificar('Informe «' + datos.nombre + '» cargado.');
                generarVistaPrevia(1);
            })
            .catch(() => notificar('No se pudo cargar el informe guardado.', 'error'));
    });

    // --- Recargar el último informe ejecutado ---
    elem('btnRecargarUltimo')?.addEventListener('click', function () {
        const configuracion = leerJsonEmbebido('datosUltimoInforme');
        if (!configuracion) {
            notificar('No hay ningún informe anterior que recargar.', 'info');
            return;
        }
        if (!aplicarConfiguracion(configuracion)) return;

        document.querySelectorAll('.btn-plantilla').forEach(c => c.classList.remove('active'));
        bootstrap.Offcanvas.getInstance(elem('panelFavoritos'))?.hide();
        generarVistaPrevia(1);
    });

    // Estado inicial de los indicadores
    actualizarAvisoFiltros();
    actualizarContadorCampos();
});
