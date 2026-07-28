document.addEventListener('DOMContentLoaded', function() {
    // ---------------------------------------------------------
    // 1. CONFIGURACIÓN Y UTILIDADES
    // ---------------------------------------------------------
    
    // Mapeo exacto de operadores según informe_inteligente/metadata.py
    const OPERADORES_POR_TIPO = {
        "texto":   [["igual", "Es igual a"], ["diferente", "Es diferente de"], ["contiene", "Contiene"], ["es_nulo", "Está vacío"], ["no_es_nulo", "No está vacío"]],
        "numero":  [["igual", "Es igual a"], ["diferente", "Es diferente de"], ["mayor", "Es mayor que"], ["menor", "Es menor que"], ["es_nulo", "Está vacío"], ["no_es_nulo", "No está vacío"]],
        "fecha":   [["entre_fechas", "Entre fechas"], ["mayor", "Después de"], ["menor", "Antes de"], ["es_nulo", "Está vacío"], ["no_es_nulo", "No está vacío"]],
        "opcion":  [["igual", "Es igual a"], ["diferente", "Es diferente de"], ["es_nulo", "Está vacío"], ["no_es_nulo", "No está vacío"]],
        "booleano": [["igual", "Es igual a (Sí/No)"]]
    };

    // Función para obtener el CSRF Token de Django
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    const csrftoken = getCookie('csrftoken');

    // ---------------------------------------------------------
    // 2. MANEJO DEL PANEL DE CAMPOS (HTMX y Eventos)
    // ---------------------------------------------------------
    
    // Cuando el usuario cambia el Modelo Raíz, recargamos los campos vía HTMX
    const selectModelo = document.getElementById('selectModeloRaiz');
    if (selectModelo) {
        selectModelo.addEventListener('change', function(e) {
            const modelo = e.target.value;
            htmx.ajax('GET', `/informe-inteligente/campos/${modelo}/`, {
                target: '#panelCamposContainer', 
                swap: 'innerHTML'
            });
            
            // Limpiar el estado anterior
            document.getElementById('listaFiltros').innerHTML = '';
            document.getElementById('resultadosContainer').innerHTML = '';
            document.getElementById('contadorRegistros').textContent = '—';
            document.getElementById('btnGuardarFavorito').disabled = true;
        });
    }

    // HTMX inyecta el HTML dinámicamente, por lo que inicializamos 
    // los eventos de los checkboxes cada vez que se actualiza el panel.
    document.body.addEventListener('htmx:afterSwap', function(evt) {
        if(evt.target.id === 'panelCamposContainer') {
            initCamposBehavior();
        }
    });

    function initCamposBehavior() {
        const checkboxes = document.querySelectorAll('.campo-checkbox');
        const buscador = document.getElementById('buscadorCampos');
        const contador = document.getElementById('contadorCampos');
        const selectOrden = document.getElementById('selectOrdenarPor');

        // Búsqueda en vivo de campos
        if(buscador) {
            buscador.addEventListener('input', function(e) {
                const term = e.target.value.toLowerCase();
                document.querySelectorAll('.ii-fld-check').forEach(div => {
                    const label = div.getAttribute('data-label');
                    div.style.display = label.includes(term) ? 'flex' : 'none';
                });
            });
        }

        // Sincronizar checkboxes con el select de ordenación
        checkboxes.forEach(cb => {
            cb.addEventListener('change', function() {
                const seleccionados = document.querySelectorAll('.campo-checkbox:checked');
                contador.textContent = `${seleccionados.length} seleccionados`;

                const valorActual = selectOrden.value;
                selectOrden.innerHTML = '<option value="">— Sin ordenar —</option>';
                
                seleccionados.forEach(sel => {
                    if (sel.dataset.ordenable === '1') {
                        const opt = document.createElement('option');
                        opt.value = sel.value;
                        opt.textContent = sel.dataset.label;
                        selectOrden.appendChild(opt);
                    }
                });
                
                // Mantener la selección de orden si el campo sigue marcado
                if (Array.from(selectOrden.options).some(o => o.value === valorActual)) {
                    selectOrden.value = valorActual;
                }
            });
        });
    }
    
    // Llamada inicial por si el HTML ya viene renderizado
    initCamposBehavior();

    // ---------------------------------------------------------
    // 3. LÓGICA DE FILTROS DINÁMICOS
    // ---------------------------------------------------------
    
    const btnAgregarFiltro = document.getElementById('btnAgregarFiltro');
    const listaFiltros = document.getElementById('listaFiltros');

    if (btnAgregarFiltro) {
        btnAgregarFiltro.addEventListener('click', () => {
            const row = document.createElement('div');
            row.className = 'ii-filter-row row g-2 align-items-center mb-2';

            // Extraer solo campos que permiten filtrado
            const camposDisponibles = Array.from(document.querySelectorAll('.campo-checkbox'))
                .filter(cb => cb.dataset.filtrable === '1')
                .map(cb => ({ key: cb.value, label: cb.dataset.label, tipo: cb.dataset.tipo }));

            let optionsCampos = '<option value="">— Seleccionar campo —</option>';
            camposDisponibles.forEach(c => {
                optionsCampos += `<option value="${c.key}" data-tipo="${c.tipo}">${c.label}</option>`;
            });

            row.innerHTML = `
                <div class="col-md-4">
                    <select class="form-select form-select-sm select-filtro-campo">${optionsCampos}</select>
                </div>
                <div class="col-md-3">
                    <select class="form-select form-select-sm select-filtro-operador" disabled>
                        <option value="">— Operador —</option>
                    </select>
                </div>
                <div class="col-md-4 container-filtro-valor">
                    <input type="text" class="form-control form-control-sm input-filtro-valor" placeholder="Valor" disabled>
                </div>
                <div class="col-md-1 text-end">
                    <button type="button" class="btn btn-outline-danger btn-sm btn-eliminar-filtro">
                        <i class="bx bx-trash"></i>
                    </button>
                </div>
            `;

            listaFiltros.appendChild(row);

            const selCampo = row.querySelector('.select-filtro-campo');
            const selOp = row.querySelector('.select-filtro-operador');
            const contValor = row.querySelector('.container-filtro-valor');
            
            row.querySelector('.btn-eliminar-filtro').addEventListener('click', () => row.remove());

            // Al cambiar el campo, cargar los operadores válidos para su tipo
            selCampo.addEventListener('change', function() {
                const tipo = this.options[this.selectedIndex]?.dataset.tipo;
                if(!tipo) {
                    selOp.innerHTML = '<option value="">— Operador —</option>';
                    selOp.disabled = true;
                    contValor.innerHTML = '<input type="text" class="form-control form-control-sm" disabled>';
                    return;
                }

                selOp.innerHTML = '';
                OPERADORES_POR_TIPO[tipo].forEach(op => {
                    selOp.innerHTML += `<option value="${op[0]}">${op[1]}</option>`;
                });
                selOp.disabled = false;
                selOp.dispatchEvent(new Event('change'));
            });

            // Al cambiar el operador, adaptar el input de valor
            selOp.addEventListener('change', function() {
                const operador = this.value;
                const tipo = selCampo.options[selCampo.selectedIndex].dataset.tipo;

                if (operador === 'es_nulo' || operador === 'no_es_nulo') {
                    contValor.innerHTML = '<input type="text" class="form-control form-control-sm" disabled placeholder="No aplica">';
                } else if (operador === 'entre_fechas') {
                    contValor.innerHTML = `
                        <div class="input-group input-group-sm">
                            <input type="date" class="form-control input-desde" placeholder="Desde">
                            <input type="date" class="form-control input-hasta" placeholder="Hasta">
                        </div>
                    `;
                } else if (tipo === 'fecha') {
                    contValor.innerHTML = '<input type="date" class="form-control form-control-sm input-filtro-valor">';
                } else if (tipo === 'numero') {
                    contValor.innerHTML = '<input type="number" step="any" class="form-control form-control-sm input-filtro-valor">';
                } else if (tipo === 'booleano') {
                     contValor.innerHTML = `
                        <select class="form-select form-select-sm input-filtro-valor">
                            <option value="true">Sí</option>
                            <option value="false">No</option>
                        </select>
                     `;
                } else {
                    contValor.innerHTML = '<input type="text" class="form-control form-control-sm input-filtro-valor">';
                }
            });
        });
    }

    // ---------------------------------------------------------
    // 4. CONSTRUCCIÓN DE JSON Y LLAMADAS AL BACKEND
    // ---------------------------------------------------------
    
    function obtenerConfiguracion() {
        const config = {
            campos: [],
            filtros: [],
            ordenar_por: document.getElementById('selectOrdenarPor')?.value || "",
            orden_direccion: document.getElementById('selectOrdenDireccion')?.value || "asc"
        };

        // Recolectar campos seleccionados
        document.querySelectorAll('.campo-checkbox:checked').forEach(cb => {
            config.campos.push(cb.value);
        });

        // Recolectar filtros válidos
        document.querySelectorAll('.ii-filter-row').forEach(row => {
            const campo = row.querySelector('.select-filtro-campo').value;
            const operador = row.querySelector('.select-filtro-operador').value;
            if(!campo || !operador) return;

            let valor = null;
            if(operador === 'entre_fechas') {
                const desde = row.querySelector('.input-desde')?.value;
                const hasta = row.querySelector('.input-hasta')?.value;
                if(desde && hasta) valor = { desde, hasta };
            } else if (operador !== 'es_nulo' && operador !== 'no_es_nulo') {
                valor = row.querySelector('.input-filtro-valor')?.value;
            }

            if((operador !== 'es_nulo' && operador !== 'no_es_nulo') && !valor) return;

            config.filtros.push({ campo, operador, valor });
        });

        return config;
    }

    function generarVistaPrevia(pagina = 1) {
        const config = obtenerConfiguracion();
        if (config.campos.length === 0) {
            alert('Debes seleccionar al menos un campo para mostrar en el informe.');
            return;
        }

        const modeloRaiz = document.getElementById('selectModeloRaiz').value;
        const formData = new FormData();
        formData.append('modelo_raiz', modeloRaiz);
        formData.append('configuracion', JSON.stringify(config));
        formData.append('pagina', pagina);

        const container = document.getElementById('resultadosContainer');
        container.innerHTML = `
            <div class="ii-panel p-5 text-center text-muted">
                <div class="spinner-border text-primary" style="color: var(--ii-navy) !important;"></div>
                <div class="mt-2 fw-semibold">Procesando registros...</div>
            </div>`;

        fetch('/informe-inteligente/vista-previa/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrftoken },
            body: formData
        })
        .then(res => {
            if(!res.ok) throw new Error('Error al generar la vista previa. Revisa los filtros.');
            return res.text();
        })
        .then(html => {
            container.innerHTML = html;
            document.getElementById('btnGuardarFavorito').disabled = false;
            
            // Extraer el conteo total renderizado por Django y actualizar la barra superior
            const countMatch = html.match(/de (\d+) registros/);
            if (countMatch) {
                document.getElementById('contadorRegistros').textContent = countMatch[1];
            }
        })
        .catch(err => {
            container.innerHTML = `<div class="alert alert-danger m-3"><i class="bi bi-exclamation-triangle"></i> ${err.message}</div>`;
        });
    }

    // Disparador principal
    const btnGenerar = document.getElementById('btnGenerarVistaPrevia');
    if(btnGenerar) {
        btnGenerar.addEventListener('click', () => generarVistaPrevia(1));
    }

    // Delegación de eventos para los clics en la paginación (ya que se inyecta dinámicamente)
    document.getElementById('resultadosContainer').addEventListener('click', function(e) {
        if (e.target.classList.contains('page-link') && e.target.dataset.pagina) {
            e.preventDefault();
            generarVistaPrevia(e.target.dataset.pagina);
        }
    });

    // ---------------------------------------------------------
    // 5. GUARDAR FAVORITOS
    // ---------------------------------------------------------
    
    document.getElementById('btnGuardarFavorito')?.addEventListener('click', () => {
        const modal = new bootstrap.Modal(document.getElementById('modalGuardarFavorito'));
        modal.show();
    });

    document.getElementById('btnConfirmarGuardarFavorito')?.addEventListener('click', () => {
        const nombre = document.getElementById('inputNombreFavorito').value.trim();
        if (!nombre) {
            alert('Por favor, ingresa un nombre para guardar el informe.');
            return;
        }

        const formData = new FormData();
        formData.append('nombre', nombre);
        formData.append('modelo_raiz', document.getElementById('selectModeloRaiz').value);
        formData.append('configuracion', JSON.stringify(obtenerConfiguracion()));

        fetch('/informe-inteligente/guardar-favorito/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrftoken },
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (data.ok) {
                bootstrap.Modal.getInstance(document.getElementById('modalGuardarFavorito')).hide();
                window.location.reload(); // Recargamos para que el backend renderice el nuevo favorito en la barra
            } else {
                alert(data.error || 'Ocurrió un error al guardar el favorito.');
            }
        })
        .catch(() => alert('Error de red al intentar guardar.'));
    });
});