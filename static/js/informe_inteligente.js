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
    const DIAS_DEL_MES = Array.from({ length: 31 }, function (_, i) { return String(i + 1); });
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
        if (typeof window.mostrarToast !== 'function') return;
        window.mostrarToast(mensaje, icono);
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

    // Las columnas del informe (tabla y documentos exportables) se ordenan
    // de izquierda a derecha según el orden en que el usuario marcó cada
    // checkbox, no según el orden en que aparecen en el panel. Cada
    // checkbox marcado guarda en qué "turno" se marcó; si se desmarca y se
    // vuelve a marcar, pasa a ocupar el último lugar.
    let turnoSeleccionCampos = 0;

    function marcarOrdenSeleccion(cb) {
        cb.dataset.ordenSeleccion = String(++turnoSeleccionCampos);
    }

    function camposSeleccionados() {
        return checkboxesCampos()
            .filter(cb => cb.checked)
            .sort((a, b) => Number(a.dataset.ordenSeleccion || 0) - Number(b.dataset.ordenSeleccion || 0));
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

        // Desgloses especiales (suman un campo agrupado, ej. "Plazas Aprob.
        // por Unid. Org.") — no son columnas, así que no tienen checkbox.
        (leerJsonEmbebido('datosDesglosesEspeciales') || []).forEach(spec => {
            const opcion = document.createElement('option');
            opcion.value = spec.key;
            opcion.textContent = spec.label;
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
            if (e.target.checked) marcarOrdenSeleccion(e.target);
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
            if (cb.checked) marcarOrdenSeleccion(cb);
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

        if (window.jQuery) {
            $('#listaFiltros .select-filtro-campo').each(function () {
                if ($(this).data('select2')) $(this).select2('destroy');
            });
        }
        elem('listaFiltros').innerHTML = '';
        elem('resultadosContainer').innerHTML = '';
        elem('contadorRegistros').textContent = '—';
        elem('btnGuardarFavorito').disabled = true;
        document.querySelectorAll('.btn-plantilla').forEach(c => c.classList.remove('active'));
        actualizarAvisoFiltros();
        refrescarSelectOrden();
        refrescarSelectDesglose();
        // Ya mismo, sin esperar a que HTMX traiga los campos: si la fuente nueva
        // no se fotografía, el selector de fecha no puede quedar ni un instante
        // habilitado con el mes anterior todavía puesto.
        aplicarEstadoDePeriodo();
        actualizarPanelEvolucion();
    });

    document.body.addEventListener('htmx:afterSwap', function (evt) {
        if (evt.target.id !== 'panelCamposContainer') return;

        actualizarContadorCampos();
        refrescarSelectOrden();
        refrescarSelectDesglose();
        // El panel recién inyectado trae su propio icono de ayuda sin activar.
        activarAyudaContextual(evt.target);
        // Los checkboxes acaban de llegar: hay que volver a aplicarles el estado
        // del período (puede haber campos que este cierre no guardó).
        aplicarEstadoDePeriodo();

        // Este es el primer momento en que los checkboxes de campos existen, así
        // que es aquí donde se puede restaurar la sesión anterior y no antes.
        if (!sesionPorRestaurar) return;

        const sesion = sesionPorRestaurar;
        const select = elem('selectModeloRaiz');
        const modeloGuardado = sesion.modelo_raiz;
        const existeElModelo = select && Array.from(select.options)
            .some(function (o) { return o.value === modeloGuardado; });

        // La sesión puede ser de un tipo de datos distinto del que carga la
        // página por defecto. En ese caso hay que traer primero SUS campos: se
        // cambia el selector y su propio 'change' recarga el panel, que vuelve a
        // pasar por aquí ya con los campos correctos.
        if (existeElModelo && select.value !== modeloGuardado) {
            select.value = modeloGuardado;
            select.dispatchEvent(new Event('change'));
            return;
        }

        sesionPorRestaurar = null;

        // Si el tipo de datos guardado ya no existe en el sistema, la sesión no
        // se puede reconstruir: se descarta en silencio y la pantalla queda
        // limpia, en vez de dejarla a medias.
        if (!existeElModelo) {
            sessionStorage.removeItem(CLAVE_SESION);
            return;
        }

        restaurarSesionDeTrabajo(sesion);
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
    /** Destruye cualquier instancia Select2 que quede dentro del contenedor antes de repintarlo. */
    function limpiarSelect2(contenedor) {
        if (!window.jQuery) return;
        contenedor.querySelectorAll('select').forEach(function (sel) {
            if ($(sel).data('select2')) $(sel).select2('destroy');
        });
    }

    /** Select2 en modo "tags": permite elegir de la lista o escribir un valor libre. */
    function inicializarSelectInteligente(select, multiple) {
        if (!window.jQuery) return;
        $(select).select2({
            theme: 'bootstrap-5',
            width: '100%',
            tags: true,
            multiple: !!multiple,
            placeholder: multiple ? 'Escriba o elija una o varias opciones…' : 'Escriba o elija una opción…',
            language: {
                noResults: function () { return 'Sin coincidencias — puede escribir un valor manual.'; },
            },
        });
    }

    function pintarControlValor(fila, valorInicial) {
        const contenedor = fila.querySelector('.ii-filtro-valor');
        const selectCampo = fila.querySelector('.select-filtro-campo');
        const operador = fila.querySelector('.select-filtro-operador').value;
        const opcionCampo = selectCampo.options[selectCampo.selectedIndex];
        const tipo = opcionCampo ? opcionCampo.dataset.tipo : '';
        const esRecurrenteAnual = opcionCampo ? opcionCampo.dataset.recurrente === '1' : false;

        limpiarSelect2(contenedor);

        if (OPERADORES_SIN_VALOR.includes(operador)) {
            contenedor.innerHTML = '<input type="text" class="form-control form-control-sm" disabled placeholder="No aplica">';
            return;
        }

        if (operador === 'entre_fechas' && esRecurrenteAnual) {
            // Cumpleaños y campos similares: se compara solo día+mes, el año
            // no importa. Mismos <select> de meses que ya usa "Mes de", más
            // un <select> de día, para no depender de parsear texto libre.
            const desde = (valorInicial && valorInicial.desde) ? valorInicial.desde.split('-') : ['1', '1'];
            const hasta = (valorInicial && valorInicial.hasta) ? valorInicial.hasta.split('-') : ['12', '31'];
            function opcionesDia(seleccionado) {
                return DIAS_DEL_MES.map(function (d) {
                    return '<option value="' + d + '"' + (d === seleccionado ? ' selected' : '') + '>' + d + '</option>';
                }).join('');
            }
            function opcionesMes(seleccionado) {
                return MESES.map(function (par) {
                    return '<option value="' + par[0] + '"' + (par[0] === seleccionado ? ' selected' : '') + '>' + par[1] + '</option>';
                }).join('');
            }
            contenedor.innerHTML =
                '<div class="d-flex align-items-center gap-1 flex-wrap ii-rango-diames">' +
                '  <select class="form-select form-select-sm input-dia-desde" style="width:auto;">' + opcionesDia(desde[1]) + '</select>' +
                '  <select class="form-select form-select-sm input-mes-desde" style="width:auto;">' + opcionesMes(desde[0]) + '</select>' +
                '  <span class="text-muted small px-1">a</span>' +
                '  <select class="form-select form-select-sm input-dia-hasta" style="width:auto;">' + opcionesDia(hasta[1]) + '</select>' +
                '  <select class="form-select form-select-sm input-mes-hasta" style="width:auto;">' + opcionesMes(hasta[0]) + '</select>' +
                '</div>';
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

        if (OPERADORES_MULTIVALOR.includes(operador) && choices.length) {
            // Selección múltiple: permite expresar "es CDI o CEJ" en un solo filtro.
            // Select2 con tags:true, igual que "Desglosar por Resumen": se puede
            // buscar escribiendo, elegir de la lista o teclear un valor manual.
            const yaElegidos = Array.isArray(valorInicial) ? valorInicial.map(String) : [];
            let html = '<select class="form-select form-select-sm input-filtro-valor" multiple>';
            choices.forEach(function (par) {
                const seleccionado = yaElegidos.includes(String(par[0])) ? ' selected' : '';
                html += '<option value="' + par[0] + '"' + seleccionado + '>' + par[1] + '</option>';
            });
            // Valores ya elegidos que no están en el catálogo (se escribieron a mano
            // la vez anterior): se agregan como <option> aparte para que no se pierdan.
            yaElegidos.filter(function (v) { return !choices.some(function (par) { return String(par[0]) === v; }); })
                .forEach(function (v) { html += '<option value="' + v + '" selected>' + v + '</option>'; });
            html += '</select>';
            contenedor.innerHTML = html;
            inicializarSelectInteligente(contenedor.querySelector('.input-filtro-valor'), true);
            return;
        }

        if (OPERADORES_MULTIVALOR.includes(operador)) {
            // Campo multivalor sin catálogo conocido (choices vacío): escritura libre,
            // Select2 en modo tags puro (cada Enter agrega un valor a la lista).
            contenedor.innerHTML = '<select class="form-select form-select-sm input-filtro-valor" multiple></select>';
            const select = contenedor.querySelector('.input-filtro-valor');
            (Array.isArray(valorInicial) ? valorInicial : []).forEach(function (v) {
                const opcion = document.createElement('option');
                opcion.value = v; opcion.textContent = v; opcion.selected = true;
                select.appendChild(opcion);
            });
            inicializarSelectInteligente(select, true);
            return;
        }

        if (tipo === 'opcion' && choices.length) {
            let html = '<select class="form-select form-select-sm input-filtro-valor">';
            html += '<option value=""></option>';
            choices.forEach(function (par) {
                const seleccionado = String(par[0]) === valor ? ' selected' : '';
                html += '<option value="' + par[0] + '"' + seleccionado + '>' + par[1] + '</option>';
            });
            // Igual que arriba: si el valor guardado no está en el catálogo actual
            // (se escribió a mano), se preserva como opción propia.
            if (valor && !choices.some(function (par) { return String(par[0]) === valor; })) {
                html += '<option value="' + valor + '" selected>' + valor + '</option>';
            }
            contenedor.innerHTML = html + '</select>';
            inicializarSelectInteligente(contenedor.querySelector('.input-filtro-valor'), false);
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
        //
        // Menos la Unidad Organizativa, que tiene su propio control en la fila de
        // arriba. Si siguiera aquí habría dos sitios para lo mismo, y usarlos a la
        // vez los combinaría con Y — pedir «Oficina Central» arriba y «Florida»
        // abajo daría cero, sin que nada explicara por qué.
        const filtrables = checkboxesCampos().filter(function (cb) {
            return cb.dataset.filtrable === '1' && cb.value !== CAMPO_UNIDAD;
        });

        if (!filtrables.length) {
            notificar('Los campos aún se están cargando. Inténtelo de nuevo en un momento.', 'info');
            return null;
        }

        let opcionesHtml = '<option value="">— Seleccionar campo —</option>';
        filtrables.forEach(function (cb) {
            const seleccionado = cb.value === campoInicial ? ' selected' : '';
            opcionesHtml += '<option value="' + cb.value + '"' +
                ' data-tipo="' + cb.dataset.tipo + '"' +
                ' data-recurrente="' + (cb.dataset.recurrente || '0') + '"' +
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

        // Select2 sobre el desplegable de campo: con decenas de campos
        // repartidos en varias categorías, poder escribir para filtrar la
        // lista es mucho más rápido que desplazarse por un <select> nativo.
        if (window.jQuery) {
            const $selectCampo = $(fila.querySelector('.select-filtro-campo'));
            $selectCampo.select2({
                theme: 'bootstrap-5',
                width: '100%',
                dropdownAutoWidth: true,
            });
            // Select2 dispara 'change' por el sistema de eventos de jQuery,
            // no como evento nativo del DOM: el listener delegado más abajo
            // (addEventListener sobre #listaFiltros) nunca lo recibiría, así
            // que aquí se engancha directo con jQuery sobre este elemento.
            $selectCampo.on('change', function () {
                pintarOperadores(fila, null);
                pintarControlValor(fila, null);
            });
        }

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
            const filaEliminar = e.target.closest('.ii-filter-row');
            if (window.jQuery) {
                $(filaEliminar.querySelector('.select-filtro-campo')).select2('destroy');
            }
            filaEliminar.remove();
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

    /* ---------------------------------------------------------------
       SELECTOR DE UNIDAD ORGANIZATIVA (fila superior)
       ---------------------------------------------------------------
       El control es el mismo que usan el Dashboard e Informes RRHH
       (`base/partials/selector_unidades.html`). Aquí solo se lee y se escribe:
       el filtro por texto de la unidad lo resuelve el servidor, que además es
       quien expande una principal a sus subunidades. */

    //: Campo que dejó de ser un filtro de la lista para tener su propio control.
    var CAMPO_UNIDAD = 'unidad_organizativa';

    function selectUnidades() {
        var caja = elem('filtro_unidades_ii');
        return caja ? caja.querySelector('.chip-multiselect-native') : null;
    }

    /** Descripciones de las unidades marcadas. */
    function unidadesElegidas() {
        var select = selectUnidades();
        if (!select) return [];
        return Array.prototype.filter.call(select.options, function (o) { return o.selected; })
                                     .map(function (o) { return o.text; });
    }

    /** Marca en el selector las unidades que traiga una configuración guardada. */
    function aplicarUnidades(descripciones) {
        var caja = elem('filtro_unidades_ii');
        var select = selectUnidades();
        if (!select) return;
        var buscadas = descripciones || [];
        Array.prototype.forEach.call(select.options, function (o) {
            o.selected = buscadas.indexOf(o.text) !== -1;
        });
        // Solo se repinta: fichas y contador tienen que reflejar lo que se acaba
        // de marcar por código. NO se reinicia el control —eso ataba un segundo
        // manejador de clic a la misma caja y el panel se abría y se cerraba en
        // el mismo clic, con lo que el selector dejaba de responder.
        if (caja && window.OrbithSelectorUnidades) {
            window.OrbithSelectorUnidades.sincronizar(caja);
        }
    }

    function obtenerConfiguracion() {
        const configuracion = {
            campos: camposSeleccionados().map(cb => cb.value),
            filtros: [],
            desglosar_por: window.jQuery ? ($(elem('selectDesglosarPor')).val() || []) : [],
            ordenar_por: elem('selectOrdenarPor')?.value || '',
            orden_direccion: elem('selectOrdenDireccion')?.value || 'asc'
        };

        /* La Unidad Organizativa viaja como un filtro más, pero se lee del
           selector de arriba y no de la lista de filtros. Así el informe que se
           envía al servidor no cambia de forma —el motor lo sigue tratando como
           un filtro `en_lista`— y los favoritos guardados siguen valiendo. */
        var unidades = unidadesElegidas();
        if (unidades.length) {
            configuracion.filtros.push({
                campo: 'unidad_organizativa', operador: 'en_lista', valor: unidades
            });
        }

        document.querySelectorAll('.ii-filter-row').forEach(function (fila) {
            const campo = fila.querySelector('.select-filtro-campo').value;
            const operador = fila.querySelector('.select-filtro-operador').value;
            if (!campo || !operador) return;

            if (OPERADORES_SIN_VALOR.includes(operador)) {
                configuracion.filtros.push({ campo: campo, operador: operador, valor: null });
                return;
            }

            if (operador === 'entre_fechas' && fila.querySelector('.ii-rango-diames')) {
                // Cumpleaños y campos recurrentes anuales: valor como "MM-DD",
                // sin año (ver informe_inteligente/motor.py::_q_rango_dia_mes).
                const diaDesde = fila.querySelector('.input-dia-desde')?.value;
                const mesDesde = fila.querySelector('.input-mes-desde')?.value;
                const diaHasta = fila.querySelector('.input-dia-hasta')?.value;
                const mesHasta = fila.querySelector('.input-mes-hasta')?.value;
                if (!diaDesde || !mesDesde || !diaHasta || !mesHasta) return;
                configuracion.filtros.push({
                    campo: campo, operador: operador,
                    valor: { desde: mesDesde + '-' + diaDesde, hasta: mesHasta + '-' + diaHasta }
                });
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
        const todos = checkboxesCampos();
        turnoSeleccionCampos = 0;
        todos.forEach(function (cb) {
            cb.checked = false;
            delete cb.dataset.ordenSeleccion;
        });
        // Se marcan en el mismo orden en que vienen en `campos`, así la
        // tabla/documentos exportables respetan el orden guardado.
        campos.forEach(function (valor) {
            const cb = todos.find(function (c) { return c.value === valor; });
            if (!cb) return;  // el campo se eliminó del registro desde que se guardó
            cb.checked = true;
            marcarOrdenSeleccion(cb);
        });

        /* Los favoritos guardados antes de este cambio llevan la unidad como un
           filtro más de la lista. Se traslada al selector de arriba en vez de
           descartarlo: el informe se sigue viendo igual que cuando se guardó, y
           el usuario lo encuentra ya en el control nuevo. */
        var filtros = configuracion.filtros || [];
        var deUnidad = filtros.filter(function (f) { return f.campo === CAMPO_UNIDAD; });
        var resto = filtros.filter(function (f) { return f.campo !== CAMPO_UNIDAD; });

        var unidadesGuardadas = [];
        deUnidad.forEach(function (filtro) {
            var valor = filtro.valor;
            if (Array.isArray(valor)) unidadesGuardadas = unidadesGuardadas.concat(valor);
            else if (valor) unidadesGuardadas.push(valor);
        });
        aplicarUnidades(unidadesGuardadas);

        elem('listaFiltros').innerHTML = '';
        resto.forEach(function (filtro) {
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
    // 4.a FECHA DEL INFORME (tiempo real o cierre mensual)
    // =====================================================================
    /* El selector superior no filtra: cambia la FUENTE del informe entero.
     * Vacío = los datos vivos de ahora mismo (comportamiento por defecto del
     * módulo). Con un mes, todo se lee de la fotografía que el módulo de
     * Cierres congeló ese mes.
     *
     * Solo hay fotografía de Contratos y de Plantilla. En Bajas, Aspirantes y
     * Movimientos el selector se apaga en vez de prometer un mes pasado que
     * nadie guardó. */
    const SOPORTE_HISTORICO = leerJsonEmbebido('datosSoporteHistorico') || {};

    // Derivados de `MESES`, que ya existe arriba: una sola fuente para los
    // nombres de mes en todo el módulo.
    const MESES_NOMBRE = MESES.map(function (par) { return par[1]; });
    const MESES_CORTOS = MESES_NOMBRE.map(function (n) { return n.slice(0, 3); });

    /* Los períodos llegan como [['2026-09', 'Septiembre 2026'], ...] y se
     * reagrupan por año: {2026: Set(9, 8), 2025: Set(12)}. La rejilla pinta
     * SIEMPRE los 12 meses del año que se está viendo y apaga los que no están
     * en ese conjunto, para que se vea de un golpe qué se cerró y qué no. */
    const MESES_POR_ANNO = (function () {
        const mapa = {};
        (leerJsonEmbebido('datosPeriodosCerrados') || []).forEach(function (par) {
            const partes = String(par[0]).split('-');
            const anno = parseInt(partes[0], 10);
            const mes = parseInt(partes[1], 10);
            if (!mapa[anno]) mapa[anno] = new Set();
            mapa[anno].add(mes);
        });
        return mapa;
    })();

    const ANNOS_CON_CIERRE = Object.keys(MESES_POR_ANNO).map(Number).sort();
    let annoVisible = ANNOS_CON_CIERRE.length
        ? ANNOS_CON_CIERRE[ANNOS_CON_CIERRE.length - 1]
        : new Date().getFullYear();

    function periodoActual() {
        const campo = elem('periodoSeleccionado');
        return campo ? campo.value : '';
    }

    function etiquetaDePeriodo(clave) {
        if (!clave) return 'Datos actuales';
        const partes = String(clave).split('-');
        return 'Cierre de ' + MESES_NOMBRE[parseInt(partes[1], 10) - 1] + ' ' + partes[0];
    }

    function pintarRejillaDeMeses() {
        const rejilla = elem('rejillaMeses');
        if (!rejilla) return;

        elem('periodoAnnoActual').textContent = annoVisible;

        // Las flechas solo se mueven entre años que tienen algún cierre: no
        // tiene sentido navegar a un año vacío.
        const indice = ANNOS_CON_CIERRE.indexOf(annoVisible);
        elem('periodoAnnoAnterior').disabled = indice <= 0;
        elem('periodoAnnoSiguiente').disabled =
            indice === -1 || indice >= ANNOS_CON_CIERRE.length - 1;

        const disponibles = MESES_POR_ANNO[annoVisible] || new Set();
        const seleccionado = periodoActual();

        rejilla.innerHTML = '';
        for (let mes = 1; mes <= 12; mes++) {
            const clave = annoVisible + '-' + String(mes).padStart(2, '0');
            const hayCierre = disponibles.has(mes);
            const esActual = seleccionado === clave;

            const boton = document.createElement('button');
            boton.type = 'button';
            boton.textContent = MESES_CORTOS[mes - 1];
            boton.className = 'btn btn-sm ' + (esActual
                ? 'btn-primary'
                : (hayCierre ? 'btn-outline-primary' : 'btn-light text-muted'));
            boton.disabled = !hayCierre;
            boton.title = hayCierre
                ? 'Ver el informe tal como estaba en el cierre de ' + MESES_NOMBRE[mes - 1]
                : 'Sin cierre declarado en ' + MESES_NOMBRE[mes - 1] + ' ' + annoVisible;
            if (hayCierre) {
                boton.addEventListener('click', function () {
                    fijarPeriodo(clave);
                    bootstrap.Dropdown.getOrCreateInstance(elem('btnPeriodo')).hide();
                });
            }
            rejilla.appendChild(boton);
        }
    }

    function fijarPeriodo(clave) {
        elem('periodoSeleccionado').value = clave || '';
        elem('etiquetaPeriodo').textContent = etiquetaDePeriodo(clave);
        pintarRejillaDeMeses();
        aplicarEstadoDePeriodo();
        // Cambiar de fecha cambia el informe entero: lo ya pintado corresponde
        // a la fecha anterior y dejarlo en pantalla induciría a error.
        elem('resultadosContainer').innerHTML = '';
        elem('contadorRegistros').textContent = '—';
        elem('btnGuardarFavorito').disabled = true;
    }

    elem('periodoAnnoAnterior')?.addEventListener('click', function () {
        const i = ANNOS_CON_CIERRE.indexOf(annoVisible);
        if (i > 0) { annoVisible = ANNOS_CON_CIERRE[i - 1]; pintarRejillaDeMeses(); }
    });
    elem('periodoAnnoSiguiente')?.addEventListener('click', function () {
        const i = ANNOS_CON_CIERRE.indexOf(annoVisible);
        if (i !== -1 && i < ANNOS_CON_CIERRE.length - 1) {
            annoVisible = ANNOS_CON_CIERRE[i + 1];
            pintarRejillaDeMeses();
        }
    });
    elem('btnVolverTiempoReal')?.addEventListener('click', function () {
        fijarPeriodo('');
        bootstrap.Dropdown.getOrCreateInstance(elem('btnPeriodo')).hide();
    });

    function fuenteAdmiteHistorico() {
        return Object.prototype.hasOwnProperty.call(SOPORTE_HISTORICO, modeloRaizActual());
    }

    /* Campos que la fotografía de esta fuente no guardó. Se deshabilitan al
     * elegir un mes: es preferible que el usuario vea POR QUÉ no puede pedirlos
     * a que reciba una columna llena de guiones sin explicación. */
    function camposSinHistorico() {
        return SOPORTE_HISTORICO[modeloRaizActual()] || [];
    }

    function pintarAvisoPeriodo(texto, clase) {
        const aviso = elem('avisoPeriodo');
        if (!aviso) return;
        aviso.className = 'alert py-2 px-3 small ' + (clase || 'alert-info');
        aviso.innerHTML = texto;
        aviso.classList.toggle('d-none', !texto);
    }

    function aplicarEstadoDePeriodo() {
        const boton = elem('btnPeriodo');
        if (!boton) return;

        const admite = fuenteAdmiteHistorico();
        const hayCierres = ANNOS_CON_CIERRE.length > 0;
        boton.disabled = !admite || !hayCierres;

        /* Un botón apagado y sin más se lee como «esto está roto». Se explica
         * el motivo en el propio botón (title) además del aviso de debajo, que
         * es lo primero que mira quien no entiende por qué no puede pulsarlo. */
        boton.title = boton.disabled
            ? (!admite
                ? 'Este informe solo existe en tiempo real: no se guarda una fotografía mensual de estos datos.'
                : 'Todavía no hay ningún cierre mensual declarado que consultar.')
            : 'Elegir si el informe muestra los datos actuales o los de un cierre mensual';

        if (!admite) {
            // La fuente no se fotografía: se fuerza a tiempo real.
            if (periodoActual()) fijarPeriodo('');
            pintarAvisoPeriodo(
                '<i class="bi bi-info-circle me-1"></i>Este informe solo existe en ' +
                '<strong>tiempo real</strong>: de estos datos no se guarda una fotografía mensual, ' +
                'así que no se puede consultar un mes cerrado.', 'alert-secondary');
            marcarCamposNoDisponibles([]);
            return;
        }

        if (!hayCierres) {
            pintarAvisoPeriodo(
                '<i class="bi bi-info-circle me-1"></i>El selector de fecha está apagado porque ' +
                '<strong>todavía no hay ningún cierre mensual declarado</strong>. Se activará solo ' +
                'en cuanto se declare el primero, en Plantilla → Gestor de Plantilla.',
                'alert-secondary');
            marcarCamposNoDisponibles([]);
            return;
        }

        const periodo = periodoActual();
        if (!periodo) {
            pintarAvisoPeriodo('', null);
            marcarCamposNoDisponibles([]);
            return;
        }

        const sinFoto = camposSinHistorico();
        let texto = '<i class="bi bi-calendar-check-fill me-1"></i>Está viendo la ' +
            '<strong>fotografía del ' + etiquetaDePeriodo(periodo).toLowerCase() +
            '</strong>, no los datos actuales.';
        if (sinFoto.length) {
            texto += ' Hay ' + sinFoto.length + ' campo(s) que ese cierre no guardó y quedan ' +
                'deshabilitados.';
        }
        pintarAvisoPeriodo(texto, 'alert-primary');
        marcarCamposNoDisponibles(sinFoto);
    }

    function marcarCamposNoDisponibles(claves) {
        const sinFoto = new Set(claves);
        checkboxesCampos().forEach(function (cb) {
            const bloqueado = sinFoto.has(cb.value);
            cb.disabled = bloqueado;
            if (bloqueado && cb.checked) {
                cb.checked = false;
                delete cb.dataset.ordenSeleccion;
            }
            const etiqueta = cb.closest('label') || cb.parentElement;
            if (etiqueta) {
                etiqueta.classList.toggle('text-muted', bloqueado);
                etiqueta.title = bloqueado
                    ? 'Este dato no se guarda en el cierre mensual, solo existe en tiempo real.'
                    : '';
            }
        });
        actualizarContadorCampos();
        refrescarSelectOrden();
        refrescarSelectDesglose();
    }

    // =====================================================================
    // 4.a.2 EVOLUCIÓN MENSUAL
    // =====================================================================
    /* Responde a una pregunta distinta de la del resumen: no «cómo está esto»
     * sino «cómo ha ido cambiando». Solo puede existir donde hay fotografías
     * mensuales que recorrer, así que el panel se oculta en las fuentes sin
     * histórico.
     *
     * Se consulta al desplegarlo, no al generar el informe: recorrer todos los
     * cierres cuesta una agregación por mes y no tiene por qué pagarla quien
     * nunca abre el panel. */
    const MEDIDAS_EVOLUCION = leerJsonEmbebido('datosMedidasEvolucion') || {};
    let graficoEvolucion = null;
    /* Contador de peticiones para descartar respuestas obsoletas. Cambiar de
     * medida dos veces seguidas lanza dos consultas, y no hay ninguna garantía
     * de que lleguen en orden: sin esto, la respuesta de la medida ANTERIOR
     * puede pisar a la de la actual y el gráfico acaba mostrando una cosa
     * distinta de la que dice el desplegable (visto al probarlo). */
    let peticionEvolucion = 0;
    let annoEvolucion = ANNOS_CON_CIERRE.length
        ? ANNOS_CON_CIERRE[ANNOS_CON_CIERRE.length - 1]
        : new Date().getFullYear();

    function actualizarFlechasDeAnno() {
        const i = ANNOS_CON_CIERRE.indexOf(annoEvolucion);
        elem('evolucionAnnoActual').textContent = annoEvolucion;
        elem('evolucionAnnoAnterior').disabled = i <= 0;
        elem('evolucionAnnoSiguiente').disabled =
            i === -1 || i >= ANNOS_CON_CIERRE.length - 1;
    }

    elem('evolucionAnnoAnterior')?.addEventListener('click', function () {
        const i = ANNOS_CON_CIERRE.indexOf(annoEvolucion);
        if (i > 0) { annoEvolucion = ANNOS_CON_CIERRE[i - 1]; dibujarEvolucion(); }
    });
    elem('evolucionAnnoSiguiente')?.addEventListener('click', function () {
        const i = ANNOS_CON_CIERRE.indexOf(annoEvolucion);
        if (i !== -1 && i < ANNOS_CON_CIERRE.length - 1) {
            annoEvolucion = ANNOS_CON_CIERRE[i + 1];
            dibujarEvolucion();
        }
    });

    function actualizarPanelEvolucion() {
        const panel = elem('panelEvolucion');
        if (!panel) return;

        const medidas = MEDIDAS_EVOLUCION[modeloRaizActual()] || [];
        const hayCierres = ANNOS_CON_CIERRE.length > 0;
        panel.classList.toggle('d-none', !medidas.length || !hayCierres);
        if (!medidas.length || !hayCierres) return;

        const select = elem('selectMedidaEvolucion');
        const elegido = select.value;

        // Select2 se monta sobre el <select>; hay que desmontarlo antes de
        // reescribir las opciones o se queda mostrando las de la fuente vieja.
        if (window.jQuery && $(select).data('select2')) $(select).select2('destroy');

        select.innerHTML = '';
        medidas.forEach(function (par) {
            const opcion = document.createElement('option');
            opcion.value = par[0];
            opcion.textContent = par[1];
            select.appendChild(opcion);
        });
        // Si la medida anterior sigue existiendo en la fuente nueva, se respeta.
        if (medidas.some(function (p) { return p[0] === elegido; })) select.value = elegido;

        /* Se delega en el inicializador global (`select_unificado.js`), que es
           el que da el aspecto y el comportamiento de TODOS los desplegables de
           Orbith: mismo tema, mismo alto y buscador incluido. Montarlo aquí por
           separado —y sin buscador— dejaba este control distinto del de al lado
           y del formulario de contrato. */
        if (window.jQuery) {
            // Se pasa el CONTENEDOR y no el <select>: asi el inicializador puede
            // barrer de paso cualquier caja de Select2 que quedara huerfana.
            if (window.orbithInitSelects) {
                window.orbithInitSelects(select.parentElement || select);
            }
            // Select2 confirma con un 'change' de jQuery, que el listener nativo
            // de más abajo no ve. Se reenvía como evento real del DOM.
            $(select).off('select2:select.evolucion')
                     .on('select2:select.evolucion', function () {
                         this.dispatchEvent(new Event('change', { bubbles: true }));
                     });
        }
    }

    function mensajeEvolucion(texto) {
        const caja = elem('mensajeEvolucion');
        caja.textContent = texto || '';
        caja.classList.toggle('d-none', !texto);
        elem('graficoEvolucion').classList.toggle('d-none', !!texto);
    }

    function dibujarEvolucion() {
        const configuracion = obtenerConfiguracion();
        if (!configuracion.campos.length) {
            mensajeEvolucion('Elija al menos un campo del informe para poder calcular la evolución.');
            return;
        }

        const datos = new FormData();
        datos.append('modelo_raiz', modeloRaizActual());
        datos.append('configuracion', JSON.stringify(configuracion));
        datos.append('indicador', elem('selectMedidaEvolucion').value);
        datos.append('anno', annoEvolucion);

        actualizarFlechasDeAnno();
        mensajeEvolucion('Calculando la evolución…');
        const miPeticion = ++peticionEvolucion;

        fetch(URLS.evolucion, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrftoken },
            body: datos
        })
            .then(r => r.json())
            .then(function (respuesta) {
                // Llegó tarde: ya se pidió otra medida después de esta.
                if (miPeticion !== peticionEvolucion) return;

                if (!respuesta.ok) {
                    mensajeEvolucion(respuesta.error || 'No se pudo calcular la evolución.');
                    return;
                }
                // Los doce meses vienen siempre; lo que puede faltar son los
                // valores. Si NINGUNO tiene dato, no hay nada que dibujar.
                if (!respuesta.puntos.some(function (p) { return p.valor !== null; })) {
                    mensajeEvolucion('No hay ningún cierre declarado en ' + annoEvolucion + '.');
                    return;
                }
                mensajeEvolucion('');
                pintarGraficoEvolucion(respuesta);
            })
            .catch(function () {
                if (miPeticion !== peticionEvolucion) return;
                mensajeEvolucion('No se pudo contactar con el servidor.');
            });
    }

    function pintarGraficoEvolucion(respuesta) {
        const contenedor = elem('graficoEvolucion');
        if (typeof ApexCharts === 'undefined') {
            mensajeEvolucion('No se pudo cargar el componente de gráficos.');
            return;
        }

        /* Mismo lenguaje visual que el gráfico de Altas/Bajas del Dashboard
         * (área con degradado y trazo suave), con dos diferencias a propósito:
         * aquí SÍ se muestra el eje Y —allí es un widget de vistazo y aquí un
         * panel de análisis, donde el valor concreto importa— y los meses sin
         * cierre van como `null` para que la línea se corte en vez de caer a
         * cero, que sería un dato falso. */
        /* Un solo formateador para el eje y para el globo de ayuda: antes el eje
           redondeaba y el globo no, asi que la misma cifra se leia distinta
           segun donde se mirara. Los porcentajes llevan su signo, que es lo que
           distingue un 40 % de cobertura de 40 plazas. */
        function formatearMedida(valor) {
            if (valor === null || valor === undefined) return '';
            if (respuesta.formato === 'entero') {
                return Math.round(valor).toLocaleString('es-ES');
            }
            if (respuesta.formato === 'porcentaje') {
                return Number(valor).toLocaleString(
                    'es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' %';
            }
            return Number(valor).toLocaleString('es-ES', { minimumFractionDigits: 2 });
        }

        const opciones = {
            chart: { type: 'area', height: 320, toolbar: { show: false },
                     fontFamily: 'inherit', parentHeightOffset: 0 },
            series: [{
                name: respuesta.etiqueta,
                data: respuesta.puntos.map(function (p) { return p.valor; })
            }],
            colors: ['#6366f1'],
            fill: {
                type: 'gradient',
                gradient: { shadeIntensity: 0.7, opacityFrom: 0.7, opacityTo: 0.2 }
            },
            stroke: { curve: 'smooth', width: 2 },
            xaxis: {
                categories: respuesta.puntos.map(function (p) { return p.etiqueta; }),
                labels: { style: { fontSize: '11px', colors: '#94a3b8', fontWeight: 600 } },
                axisBorder: { show: false }, axisTicks: { show: false },
                tooltip: { enabled: false },
            },
            markers: { size: 4 },
            grid: { borderColor: '#eef0f3' },
            dataLabels: { enabled: false },
            legend: { show: false },
            yaxis: {
                labels: { formatter: function (v) { return formatearMedida(v); } }
            },
            tooltip: {
                y: {
                    formatter: function (v) {
                        return v === null ? 'Sin cierre declarado' : formatearMedida(v);
                    }
                }
            },
            noData: { text: 'Sin datos que mostrar' },
        };

        if (graficoEvolucion) graficoEvolucion.destroy();
        graficoEvolucion = new ApexCharts(contenedor, opciones);
        graficoEvolucion.render();
    }

    // Se calcula al ABRIR el panel, no antes.
    elem('cuerpoEvolucion')?.addEventListener('shown.bs.collapse', function () {
        // Select2 mide mal dentro de un contenedor oculto: se remonta ahora que
        // el panel ya tiene ancho real.
        actualizarPanelEvolucion();
        dibujarEvolucion();
    });
    elem('selectMedidaEvolucion')?.addEventListener('change', function () {
        if (elem('cuerpoEvolucion').classList.contains('show')) dibujarEvolucion();
    });

    // =====================================================================
    // 4.b SESIÓN DE TRABAJO (volver donde se dejó)
    // =====================================================================
    /* Al salir del módulo y volver, la pantalla se recupera tal como estaba.
     *
     * Vive en `sessionStorage`, no en la base de datos ni en `localStorage`, por
     * dos razones: se limpia solo al cerrar la pestaña —que es exactamente el
     * alcance de "me fui a otra parte de la app y volví"— y la configuración
     * puede contener valores de filtro personales (un carnet de identidad, por
     * ejemplo) que no deben quedar guardados en una PC compartida.
     *
     * Es distinto de `UltimoInformeEjecutado` (servidor): aquel sobrevive al
     * cierre del navegador pero exige pulsar "Recargar este informe"; este es
     * automático y solo dura la sesión.
     */
    const CLAVE_SESION = 'orbith:informe-inteligente:sesion';

    function guardarSesionDeTrabajo(configuracion, pagina) {
        try {
            sessionStorage.setItem(CLAVE_SESION, JSON.stringify({
                modelo_raiz: modeloRaizActual(),
                configuracion: configuracion,
                pagina: pagina
            }));
        } catch (e) {
            // Modo privado o cuota llena: no poder recordar la sesión no puede
            // impedir que el informe se siga usando con normalidad.
        }
    }

    function leerSesionDeTrabajo() {
        try {
            const crudo = sessionStorage.getItem(CLAVE_SESION);
            if (!crudo) return null;
            const sesion = JSON.parse(crudo);
            // Una sesión sin campos no restaura nada útil y haría saltar el
            // aviso de "seleccione al menos un campo" nada más entrar.
            if (!sesion || !sesion.configuracion || !(sesion.configuracion.campos || []).length) {
                return null;
            }
            return sesion;
        } catch (e) {
            sessionStorage.removeItem(CLAVE_SESION);  // quedó dañada
            return null;
        }
    }

    /* Un informe que otro usuario compartió llega incrustado por el servidor
     * (`ver_informe_compartido`). Se trata como una "sesión a restaurar" más,
     * para reutilizar tal cual el mecanismo de abajo — incluido el caso de que
     * sea de un tipo de datos distinto del que carga la página por defecto.
     * Tiene prioridad sobre la sesión guardada: si el usuario llega pulsando
     * «Ver informe» desde una notificación, eso es lo que quiere ver. */
    function leerInformeCompartido() {
        const configuracion = leerJsonEmbebido('datosInformeCompartido');
        const marca = elem('modeloInformeCompartido');
        if (!configuracion || !marca) return null;
        return { modelo_raiz: marca.dataset.modelo, configuracion: configuracion, pagina: 1,
                 esCompartido: true };
    }

    /* Se lee UNA vez al arrancar y se consume en el primer swap del panel de
     * campos. A partir de ahí queda en null, para que cambiar de modelo raíz a
     * mano no vuelva a disparar la restauración. */
    let sesionPorRestaurar = leerInformeCompartido() || leerSesionDeTrabajo();

    function restaurarSesionDeTrabajo(sesion) {
        if (!aplicarConfiguracion(sesion.configuracion)) return;
        // Sin desplazar: se recupera el informe, pero la pantalla se queda arriba,
        // que es donde el usuario acaba de llegar.
        generarVistaPrevia(sesion.pagina || 1, false);
        // Con un informe compartido el aviso ya lo da el propio banner de la
        // pantalla, así que aquí sobra.
        if (!sesion.esCompartido) {
            notificar('Se recuperó el informe que tenía abierto.', 'info');
        }
    }

    // =====================================================================
    // 5. VISTA PREVIA Y PAGINACIÓN
    // =====================================================================

    /* `desplazar`: si al terminar hay que llevar la vista hasta los resultados.
     *
     * Es `true` cuando el usuario ha PEDIDO el informe (pulsar «Generar», cambiar
     * de página, aplicar una plantilla): ahí desplazarse es justo lo que espera.
     *
     * Es `false` al restaurar la sesión anterior nada más abrir la pantalla. Ese
     * caso también renderiza el informe, y arrastraba al usuario hasta el final
     * de la página cada vez que entraba en Informe Inteligente. El estado se
     * recupera igual; lo que no se toca es dónde está mirando. */
    function generarVistaPrevia(pagina, desplazar) {
        if (desplazar === undefined) desplazar = true;
        const configuracion = obtenerConfiguracion();

        if (!configuracion.campos.length) {
            notificar('Seleccione al menos un campo para mostrar en el detalle del informe.', 'warning');
            return;
        }

        const datos = new FormData();
        datos.append('modelo_raiz', modeloRaizActual());
        datos.append('configuracion', JSON.stringify(configuracion));
        datos.append('pagina', pagina || 1);
        datos.append('periodo', periodoActual());

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

                // Se guarda solo cuando el informe salió bien: si falló, lo que
                // hay en pantalla es un error, y restaurarlo al volver no le
                // sirve de nada al usuario.
                guardarSesionDeTrabajo(configuracion, pagina || 1);

                if (desplazar) {
                    contenedor.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
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

    /* Cambiar de unidad vuelve a generar el informe, igual que en el Dashboard y
       en Informes RRHH: los tres aplican al CERRAR el panel. Solo si ya había un
       informe en pantalla — si el usuario aún no ha elegido campos, generar aquí
       le soltaría un aviso de «seleccione al menos un campo» que no ha pedido. */
    elem('filtro_unidades_ii')?.addEventListener('orbith:unidades', function () {
        if (elem('resultadosContainer')?.innerHTML.trim()) {
            generarVistaPrevia(1);
        }
    });

    elem('resultadosContainer')?.addEventListener('click', function (e) {
        const enlace = e.target.closest('a.page-link[data-pagina]');
        if (!enlace) return;
        e.preventDefault();
        if (enlace.closest('.page-item').classList.contains('disabled')) return;
        generarVistaPrevia(enlace.dataset.pagina);
    });

    /**
     * Exporta el informe con la configuración actual (mismos filtros,
     * columnas y orden que se ven en pantalla) a PDF, Word o Excel. Usa un
     * formulario oculto con submit() real en vez de fetch: así el
     * navegador dispara la descarga a partir del Content-Disposition
     * que devuelve el servidor.
     */
    function ejecutarExportacionInformeInteligente(tipo) {
        const configuracion = obtenerConfiguracion();
        if (!configuracion.campos.length) {
            notificar('Seleccione al menos un campo para exportar el informe.', 'warning');
            return;
        }

        const URLS_EXPORTACION = { word: URLS.exportarWord, excel: URLS.exportarExcel, pdf: URLS.exportarPDF };
        const url = URLS_EXPORTACION[tipo] || URLS.exportarPDF;
        if (!url) return;

        const form = document.createElement('form');
        form.method = 'POST';
        form.action = url;
        form.style.display = 'none';

        const campos = {
            csrfmiddlewaretoken: csrftoken,
            modelo_raiz: modeloRaizActual(),
            configuracion: JSON.stringify(configuracion),
            // El documento exportado tiene que ser de la MISMA fecha que lo que
            // se ve en pantalla; si no, el PDF diría otra cosa que la tabla.
            periodo: periodoActual()
        };
        Object.keys(campos).forEach(function (nombre) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = nombre;
            input.value = campos[nombre];
            form.appendChild(input);
        });

        // Es un submit de formulario normal (no AJAX): no hay forma de confirmar
        // desde aquí que la descarga terminó ni que el documento se generó bien.
        const NOMBRES_TIPO = { word: 'documento Word', excel: 'archivo Excel', pdf: 'documento PDF' };
        notificar('Preparando el ' + (NOMBRES_TIPO[tipo] || NOMBRES_TIPO.pdf) + '…', 'info');

        document.body.appendChild(form);
        form.submit();
        form.remove();
    }
    window.ejecutarExportacionInformeInteligente = ejecutarExportacionInformeInteligente;

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

    // --- Guardar y editar favoritos ---

    /* El mismo modal sirve para las dos cosas. `favoritoEnEdicion` es lo que las
     * distingue: null = guardar uno nuevo, un objeto = actualizar ese informe.
     * Antes solo existía el primer caso, así que renombrar un favorito obligaba a
     * volver a guardarlo y quedaban dos copias del mismo informe. */
    let favoritoEnEdicion = null;

    function abrirModalFavorito(favorito) {
        favoritoEnEdicion = favorito || null;
        const esEdicion = favoritoEnEdicion !== null;

        elem('inputNombreFavorito').value = esEdicion ? favoritoEnEdicion.nombre : '';
        elem('inputDescripcionFavorito').value = esEdicion ? favoritoEnEdicion.descripcion : '';
        elem('tituloModalFavorito').textContent = esEdicion
            ? 'Editar informe guardado'
            : 'Guardar informe en favoritos';
        elem('btnConfirmarGuardarFavorito').textContent = esEdicion
            ? 'Guardar cambios'
            : 'Guardar informe';

        elem('cajaReemplazarConfig').classList.toggle('d-none', !esEdicion);
        elem('switchReemplazarConfig').checked = false;

        new bootstrap.Modal(elem('modalGuardarFavorito')).show();
    }

    elem('btnGuardarFavorito')?.addEventListener('click', function () {
        abrirModalFavorito(null);
    });

    elem('btnConfirmarGuardarFavorito')?.addEventListener('click', function () {
        const nombre = elem('inputNombreFavorito').value.trim();
        if (!nombre) {
            notificar('Escriba un nombre para el informe.', 'warning');
            return;
        }

        const esEdicion = favoritoEnEdicion !== null;
        const reemplazar = esEdicion && elem('switchReemplazarConfig').checked;

        const datos = new FormData();
        datos.append('nombre', nombre);
        datos.append('descripcion', elem('inputDescripcionFavorito').value.trim());

        // Al crear, la configuración viaja siempre. Al editar solo si se pidió
        // reemplazarla: renombrar no debe arrastrar lo que haya en pantalla,
        // que puede pertenecer a un informe distinto del que se está editando.
        if (!esEdicion || reemplazar) {
            datos.append('modelo_raiz', modeloRaizActual());
            datos.append('configuracion', JSON.stringify(obtenerConfiguracion()));
        }
        if (reemplazar) {
            datos.append('reemplazar_configuracion', 'true');
        }

        const url = esEdicion
            ? URLS.editarFavorito.replace('/0/', '/' + favoritoEnEdicion.id + '/')
            : URLS.guardarFavorito;

        const boton = this;
        boton.disabled = true;

        fetch(url, {
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
                notificar(esEdicion
                    ? 'Informe «' + respuesta.nombre + '» actualizado.'
                    : 'Informe «' + respuesta.nombre + '» guardado en sus favoritos.');
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

    // --- Compartir un informe con otros usuarios ---

    /* No crea una copia en los favoritos del receptor: le llega una notificación
     * con un botón «Ver informe» y decide él si lo guarda. Así nadie recibe en su
     * lista algo que no pidió. */
    let informeACompartir = null;

    function abrirModalCompartir(informeId, nombre) {
        informeACompartir = informeId;
        elem('nombreInformeCompartir').textContent = '«' + nombre + '»';

        const select = elem('selectDestinatarios');
        if (select && window.jQuery) {
            $(select).val(null);
            // Select2 se monta la primera vez; después basta con limpiar.
            if (!$(select).data('select2')) {
                $(select).select2({
                    theme: 'bootstrap-5',
                    width: '100%',
                    multiple: true,
                    placeholder: 'Escriba para buscar usuarios…',
                    dropdownParent: $('#modalCompartirInforme'),
                });
            }
            $(select).trigger('change');
        }

        new bootstrap.Modal(elem('modalCompartirInforme')).show();
    }

    elem('btnConfirmarCompartir')?.addEventListener('click', function () {
        if (!informeACompartir) return;

        const select = elem('selectDestinatarios');
        const seleccionados = window.jQuery
            ? ($(select).val() || [])
            : Array.from(select.selectedOptions).map(function (o) { return o.value; });

        if (!seleccionados.length) {
            notificar('Elija al menos un usuario.', 'warning');
            return;
        }

        const datos = new FormData();
        seleccionados.forEach(function (id) { datos.append('destinatarios', id); });

        const boton = this;
        boton.disabled = true;

        fetch(URLS.compartirFavorito.replace('/0/', '/' + informeACompartir + '/'), {
            method: 'POST',
            headers: { 'X-CSRFToken': csrftoken },
            body: datos
        })
            .then(r => r.json())
            .then(function (respuesta) {
                if (!respuesta.ok) {
                    notificar(respuesta.error || 'No se pudo compartir el informe.', 'error');
                    return;
                }
                bootstrap.Modal.getInstance(elem('modalCompartirInforme')).hide();
                notificar(respuesta.enviados === 1
                    ? 'Informe enviado a 1 usuario.'
                    : 'Informe enviado a ' + respuesta.enviados + ' usuarios.');
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

        if (e.target.closest('.btn-editar-favorito')) {
            abrirModalFavorito({
                id: informeId,
                nombre: item.dataset.nombre || '',
                descripcion: item.dataset.descripcion || ''
            });
            return;
        }

        if (e.target.closest('.btn-compartir-favorito')) {
            abrirModalCompartir(informeId, item.dataset.nombre || '');
            return;
        }

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

    /* Ayuda contextual: los popovers de Bootstrap no se activan solos, hay que
     * instanciarlos. Se llama también tras cada swap de HTMX porque el panel de
     * campos se reinyecta al cambiar de fuente y trae su propio icono. */
    function activarAyudaContextual(raiz) {
        (raiz || document).querySelectorAll('[data-bs-toggle="popover"]').forEach(function (el) {
            if (!bootstrap.Popover.getInstance(el)) new bootstrap.Popover(el);
        });
    }
    activarAyudaContextual();

    // Estado inicial de los indicadores
    pintarRejillaDeMeses();
    aplicarEstadoDePeriodo();
    actualizarPanelEvolucion();
    actualizarAvisoFiltros();
    actualizarContadorCampos();
});
