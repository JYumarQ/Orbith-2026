/*
 * Formulario de contrato: el código común de «Registrar contrato» (add_contrato.html)
 * y «Editar contrato» (updt_contrato.html). Antes cada pantalla tenía su copia (85 %
 * igual, unas 700 líneas cada una) y cada arreglo había que hacerlo dos veces
 * (unificado el 18-11-2026).
 *
 * Cada pantalla llama a `OrbithFormularioContrato.iniciar(opciones)` con lo suyo:
 *
 *   modo               'alta' | 'edicion'
 *   urls               { tipoInfo (con 0 en lugar del id), validarExpediente, lista,
 *                        datosPrevios (solo alta) }
 *   aspiranteId        (alta) para recuperar expediente y registro militar anteriores
 *   motivoInicial      motivo que debe quedar elegido al repintar los motivos del tipo
 *   expedienteOriginal el del contrato (en edición no se comprueba si ya existe)
 *   cargoOriginal, ocupabaPlaza
 *                      (edición) la plaza que el contrato YA ocupaba no se comprueba:
 *                      antes, en un cargo lleno, vaciaba el Cargo de su propio ocupante
 *   alGuardarSinNavegar
 *                      (edición) si existe `window.OrbithGestorSinNavegar` (abierto desde
 *                      el Gestor de Plantilla), no se navega al guardar
 *   reiniciar          función que vuelve a montar la pantalla tras repintarla con errores
 *
 * Diferencias de la EDICIÓN que viven aquí, no en la plantilla:
 *   - La F. de Contratación no se cambia (va oculta; se ve en un input suelto).
 *   - Las copias ocultas `data-solo-para-calculo` (cargo, tridente, tipo de salario
 *     bloqueados) no se validan: no se pueden rellenar.
 */
(function () {
    if (window.OrbithFormularioContrato) return;

    function iniciar(o) {
        var $form = $('#contratoForm');
        var formulario = $form[0];
        if (!formulario) return;
        var esEdicion = o.modo === 'edicion';

        const $btnSubmit = $form.find('button[type="submit"]');

        // 1. ALTA: recuperar expediente y registro militar de un contrato anterior.
        if (!esEdicion && o.aspiranteId && !window.datosRecuperados) {
            fetch(o.urls.datosPrevios + '?aspirante_id=' + o.aspiranteId)
                .then(res => res.json())
                .then(data => {
                    if (data.existe) {
                        var $campoExp = $('#id_no_expediente');
                        if ($campoExp.length && !$campoExp.val()) {
                            $campoExp.val(data.no_expediente)
                                    .css('backgroundColor', '#e8f0fe')
                                    .attr('title', 'Recuperado del historial');
                            $('#id_reg_militar').val(data.reg_militar);
                            if (typeof Swal !== 'undefined') Swal.fire({toast: true, position: 'top-end', icon: 'info', title: 'Datos recuperados', showConfirmButton: false, timer: 3000});
                        }
                    }
                    window.datosRecuperados = true;
                }).catch(err => console.error(err));
        }

        // 1. EDICIÓN: la F. de Contratación va inhabilitada pero se ENVÍA (gris nativo).
        if (esEdicion) {
            $('#id_fecha_alta').removeAttr('disabled')
                .attr('readonly', 'readonly')
                .css({'pointer-events': 'none', 'background-color': '#e9ecef', 'opacity': '1'});
        }

        // 2. SWITCHES Y DEPENDENCIAS
        function toggleCampo($check, $res) {
            if (!$check.length || !$res.length) return;
            $check.is(':checked') ? $res.removeAttr('disabled') : $res.attr('disabled', 'disabled').val('');
            $res.trigger('change');
        }

        $form.off('change.switches').on('change.switches', '#id_c_formal, #id_mision', function() {
            if (this.id === 'id_c_formal') toggleCampo($(this), $('#id_c_formal_res'));
            if (this.id === 'id_mision') toggleCampo($(this), $('#id_pais, #id_mision_dias, #id_mision_importe'));
        });

        // 3. TIPO DE CONTRATO
        $form.off('change.tipo').on('change.tipo', '#id_tipo', function() {
            var tipoId = $(this).val();
            var $duracion = $('#id_duracion'), $motivo = $('#id_motivo');

            if (!tipoId) {
                $duracion.attr('disabled', 'disabled').val('');
                $motivo.attr('disabled', 'disabled').empty().append('<option value="">---------</option>');
                $duracion.trigger('change'); $motivo.trigger('change');
                return;
            }

            fetch(o.urls.tipoInfo.replace('0', tipoId))
            .then(res => res.json())
            .then(data => {
                var desc = data.descripcion ? data.descripcion.toUpperCase() : '';
                desc.includes('INDETERMINADO') ? $duracion.attr('disabled', 'disabled').val('') : $duracion.removeAttr('disabled');

                // Conservamos la selección actual al repintar: si el modal se repinta
                // tras un error de validación, el motivo elegido debe sobrevivir.
                var valorPrevio = $motivo.val() || o.motivoInicial || '';
                $motivo.empty().append('<option value="">---------</option>');
                if (data.motivos_asociados) {
                    data.motivos_asociados.forEach(m => {
                        var seleccionado = (String(m.id) === String(valorPrevio));
                        $motivo.append(new Option(m.descripcion, m.id, false, seleccionado));
                    });
                }

                data.requiere_motivo ? $motivo.removeAttr('disabled') : $motivo.attr('disabled', 'disabled').val('');
                if ($motivo.hasClass('select2-hidden-accessible')) $motivo.trigger('change.select2');
                setTimeout(() => { $motivo.trigger('change'); $duracion.trigger('input'); }, 50);
            }).catch(() => {
                $motivo.removeAttr('disabled');
                $duracion.removeAttr('disabled');
            });
        });

        // =======================================================
        // MOTOR DE DEPENDENCIA: CARGOS (FUNC/DESIG) Y CHOFER MANUAL
        // =======================================================
        const $checkFunc = $('#id_funcionario');
        const $checkDesig = $('#id_designado');
        const $codFunc = $('#id_funcionario_res');
        const $codDesig = $('#id_designado_res');
        // De Confianza (24-10-2026): mismo trato que Funcionario y Designado.
        const $checkConf = $('#id_de_confianza');
        const $codConf = $('#id_confianza_res');

        // Referencias exactas a los campos del Chofer
        const $licencia = $('#id_fv_lic');
        const $recal = $('#id_fv_rec');
        const $seguro = $('#id_fv_seg');
        // BLOQUEO VISUAL Y FÍSICO (Funcionario, Designado y De Confianza: los decide el cargo)
        [$checkFunc, $checkDesig, $checkConf].forEach(function ($check) {
            if (!$check.length) return;
            $check.prop('disabled', true).prop('readonly', true);
            $check.closest('.form-check').addClass('switch-del-cargo').attr('title', 'Lo decide el cargo (Gestor de Plantilla)');
        });
        // Nota: El switch del Chofer queda libre y clicleable para el usuario

        function evaluarColorCodigo($input) {
            if ($input.prop('disabled')) return;
            if ($input.val().trim() === '') {
                $input.addClass('input-pendiente').removeClass('border-success border-danger is-invalid');
            } else {
                $input.addClass('border-success').removeClass('input-pendiente border-danger is-invalid');
            }
        }

        function manejarInputCodigo($input, habilitado, esCambioManual, msgTipo) {
            if (!$input.length) return;
            if (!habilitado) {
                if (esCambioManual && $input.val().trim() !== '') {
                    $input.val('');
                    // Solo lanza SweetAlert si enviamos un msgTipo (ej: al cambiar el cargo automático)
                    if (typeof Swal !== 'undefined' && msgTipo) {
                        Swal.fire({ toast: true, position: 'top-end', icon: 'info', title: 'Limpieza automática', text: `El nuevo cargo no exige ${msgTipo}.`, showConfirmButton: false, timer: 4500 });
                    }
                }
                $input.prop('disabled', true).removeClass('input-pendiente border-success border-danger is-invalid').css('background-color', '#e9ecef');
            } else {
                $input.prop('disabled', false).css('background-color', '#fff');
                evaluarColorCodigo($input);
            }
        }

        // SINCRONIZACIÓN AUTOMÁTICA (Funcionario, Designado y De Confianza)
        function sincronizarEstadosEspeciales(esCambioManual = true) {
            const $option = $('#id_cargo').find('option:selected');
            const hay = $option.length && $option.val();
            const isFunc = !!hay && $option.attr('data-funcionario') === 'true';
            const isDesig = !!hay && $option.attr('data-designado') === 'true';
            const isConf = !!hay && $option.attr('data-de-confianza') === 'true';

            if ($checkFunc.length) $checkFunc.prop('checked', isFunc).trigger('change');
            if ($checkDesig.length) $checkDesig.prop('checked', isDesig).trigger('change');
            if ($checkConf.length) $checkConf.prop('checked', isConf).trigger('change');

            manejarInputCodigo($codFunc, isFunc, esCambioManual, 'Funcionario');
            manejarInputCodigo($codDesig, isDesig, esCambioManual, 'Designado');
            manejarInputCodigo($codConf, isConf, esCambioManual, 'De Confianza');
        }

        $('#id_cargo').on('change.sincro', function() { sincronizarEstadosEspeciales(true); });

        // CONTROL MANUAL DEL CHOFER PROFESIONAL
        // Usamos .switches para que se dispare en el arranque inicial unificado
        $form.off('change.switches_chofer').on('change.switches change', '#id_profesional', function() {
            let enable = $(this).is(':checked');
            // Enviamos 'null' como mensaje para que NO salte un SweetAlert molesto cuando el usuario apague el switch a mano
            manejarInputCodigo($licencia, enable, true, null);
            manejarInputCodigo($recal, enable, true, null);
            manejarInputCodigo($seguro, enable, true, null);
        });

        // Reactividad en vivo para los colores al escribir
        $codFunc.add($codDesig).add($codConf).add($licencia).add($recal).add($seguro).on('input change', function() {
            evaluarColorCodigo($(this));
        });

        // =======================================================
        // MOTOR DE EXCLUSIVIDAD PARA NOCTURNIDAD (Nativo)
        // =======================================================
        function aplicarExclusividadNocturnidad() {
            const $n1 = $('#id_nocturnidad_1');
            const $n2 = $('#id_nocturnidad_2');
            const val1 = $n1.val();
            const val2 = $n2.val();

            // 1. Restaurar todas las opciones a su estado normal
            $n1.find('option').prop('disabled', false).css({'color': '', 'background-color': ''});
            $n2.find('option').prop('disabled', false).css({'color': '', 'background-color': ''});

            // 2. Bloquear y aplicar gris tenue a la opción cruzada
            if (val2) {
                $n1.find(`option[value="${val2}"]`).prop('disabled', true).css({'color': '#adb5bd', 'background-color': '#f8f9fa'});
            }
            if (val1) {
                $n2.find(`option[value="${val1}"]`).prop('disabled', true).css({'color': '#adb5bd', 'background-color': '#f8f9fa'});
            }
        }

        $('#id_nocturnidad_1, #id_nocturnidad_2').on('change.exclusividad', aplicarExclusividadNocturnidad);

        // 4. MOTOR DE PLAZAS (SELECT2 ESTABLE) Y VALIDACIÓN CRUZADA
        let ocupaPlazaOficial = false;
        const $cargoSelect = $('#id_cargo');

        function formatCargoOption(state) {
            if (!state.id) return state.text;
            const $el = $(state.element);

            const grupo = $el.data('grupo') || '';
            const aprobadas = parseInt($el.data('aprobadas')) || 0, ocupadas = parseInt($el.data('ocupadas')) || 0;
            const estaLleno = (aprobadas - ocupadas) <= 0;

            let color = 'bg-secondary', tachado = '';

            if (ocupaPlazaOficial) {
                if (estaLleno) { color = 'bg-danger'; tachado = 'text-decoration-line-through text-muted'; }
                else { color = 'bg-success'; }
            }

            const textoCargo = grupo
                ? `<span title="Grupo Escala: ${grupo}" style="cursor: help;">${state.text}</span>`
                : state.text;

            return $(`<div class="d-flex justify-content-between align-items-center w-100 ${tachado}"><span>${textoCargo}</span><span class="badge ${color} rounded-pill">${ocupadas} / ${aprobadas}</span></div>`);
        }

        function initSelect2Cargo() {
            if ($cargoSelect.hasClass("select2-hidden-accessible")) $cargoSelect.select2('destroy');
            // theme 'bootstrap-5' es obligatorio: sin él el contenedor se pinta como
            // select2-container--default y ni el tema ni select2-sneat-fix.css aplican,
            // por lo que el control encoge ~11px al inicializarse (parpadeo visible).
            $cargoSelect.select2({ dropdownParent: $cargoSelect.parent(), width: '100%', theme: 'bootstrap-5', templateResult: formatCargoOption, templateSelection: s => s.text });
        }
        initSelect2Cargo();

        // Unidad Organizativa y Departamento: mismo patrón que el cargo (búsqueda por
        // escritura, single-select), sin badge de plazas porque no aplica aquí.
        function initSelect2Cascada(selector) {
            const $select = $(selector);
            if (!$select.length) return;
            if ($select.hasClass('select2-hidden-accessible')) $select.select2('destroy');
            $select.select2({ dropdownParent: $select.parent(), width: '100%', theme: 'bootstrap-5', templateSelection: s => s.text });

            // PUENTE HTMX <-> SELECT2: Select2 dispara 'change' con el trigger()
            // sintético de jQuery, que HTMX (basado en addEventListener nativo) no
            // detecta, así que el hx-get de este campo nunca se disparaba. Se
            // escucha el evento propio de Select2 (no 'change', para no crear un
            // bucle infinito al despachar el 'change' nativo) y se despacha un
            // 'change' real del DOM, que sí dispara el hx-trigger="change".
            $select.off('select2:select.htmxBridge select2:unselect.htmxBridge select2:clear.htmxBridge')
                   .on('select2:select.htmxBridge select2:unselect.htmxBridge select2:clear.htmxBridge', function () {
                       this.dispatchEvent(new Event('change', { bubbles: true }));
                   });
        }
        initSelect2Cascada('#id_unidad');
        initSelect2Cascada('#id_departamento');
        initSelect2Cascada('#id_motivo');

        function validarCargoCruado() {
            const valCargo = $cargoSelect.val();
            let $errPlaza = $('#error_plaza_agotada');

            if ($errPlaza.length === 0) {
                $errPlaza = $('<small id="error_plaza_agotada" class="text-danger fw-bold d-none mt-1"></small>');
                $cargoSelect.next('.select2-container').after($errPlaza);
            }

            $errPlaza.addClass('d-none');
            $cargoSelect.next('.select2-container').find('.select2-selection').removeClass('border-danger');

            if (!valCargo) return;

            const $optionSeleccionada = $cargoSelect.find('option:selected');
            const aprobadas = parseInt($optionSeleccionada.data('aprobadas')) || 0;
            const ocupadas = parseInt($optionSeleccionada.data('ocupadas')) || 0;
            // EDICIÓN: la plaza que este contrato YA ocupaba no se comprueba (25-10-2026):
            // antes, en un cargo lleno, vaciaba el Cargo de su propio ocupante. Si el cargo
            // está sobregirado lo explica el aviso de arriba (`aviso_plaza_sobregirada`).
            if (o.ocupabaPlaza && String(valCargo) === String(o.cargoOriginal || '')) return;

            if (ocupaPlazaOficial && (aprobadas - ocupadas <= 0)) {
                $cargoSelect.val(null).trigger('change.select2');
                $errPlaza.html('<i class="fas fa-exclamation-triangle me-1"></i> El tipo de contrato exige vacante. El cargo seleccionado estaba lleno.').removeClass('d-none');
                $cargoSelect.next('.select2-container').find('.select2-selection').addClass('border-danger');
                $('#help-cargo-grupo').slideUp(200, function() { $(this).addClass('d-none').html(''); });
            }
        }

        $form.off('change.plaza').on('change.plaza', '#id_tipo', function() {
            const radar = $(this).attr('data-ocupa-plaza');
            ocupaPlazaOficial = $(this).val() ? (radar ? JSON.parse(radar).includes(parseInt($(this).val())) : false) : false;
            initSelect2Cargo();
            validarCargoCruado();
        });

        $cargoSelect.on('select2:selecting', function(e) {
            const $el = $(e.params.args.data.element);
            const aprobadas = parseInt($el.data('aprobadas')) || 0, ocupadas = parseInt($el.data('ocupadas')) || 0;
            if (ocupaPlazaOficial && (aprobadas - ocupadas <= 0)) {
                e.preventDefault(); Swal.fire({toast: true, position: 'top-end', icon: 'error', title: 'Cargo sin vacantes', showConfirmButton: false, timer: 3000});
            }
        });

        $cargoSelect.on('change', validarCargoCruado);

        // --- CARGO FUERA DE LA PLANTILLA APROBADA ---
        // Una plaza que no está en la plantilla aprobada no puede sostener un
        // contrato que ocupe plaza. En cuanto se elige el cargo se apagan esos
        // tipos; el servidor lo vuelve a validar en CAltaForm.clean().
        const $tipoContrato = $('#id_tipo');

        function tiposQueOcupanPlaza() {
            const radar = $tipoContrato.attr('data-ocupa-plaza');
            try { return radar ? JSON.parse(radar) : []; } catch (e) { return []; }
        }

        function avisoFueraDePlantilla(mostrar) {
            let $aviso = $('#aviso_fuera_plantilla');
            if ($aviso.length === 0) {
                $aviso = $('<small id="aviso_fuera_plantilla" class="fw-bold d-none mt-1 d-block" style="color: #ffab00;"></small>');
                $cargoSelect.next('.select2-container').after($aviso);
            }
            if (mostrar) {
                $aviso.html('<i class="fas fa-exclamation-triangle me-1"></i> Este cargo está fuera de la plantilla aprobada, por lo que no admite contratos que ocupen plaza.')
                      .removeClass('d-none');
            } else {
                $aviso.addClass('d-none');
            }
        }

        function aplicarReglaFueraDePlantilla() {
            const $opcion = $cargoSelect.find('option:selected');
            const fuera = !!$cargoSelect.val() && $opcion.attr('data-en-plantilla') === 'false';
            const ocupan = tiposQueOcupanPlaza();
            // El valor se lee ANTES del bucle: al marcar `disabled` sobre la
            // opción que está seleccionada, el navegador puede dejar de
            // devolverla en `.val()`, y entonces la comparación fallaba y el
            // tipo bloqueado se quedaba puesto en pantalla.
            const tipoElegido = $tipoContrato.val();
            let anulado = false;

            $tipoContrato.find('option').each(function() {
                if (!this.value) return;
                const bloquear = fuera && ocupan.includes(parseInt(this.value));
                this.disabled = bloquear;
                if (bloquear && tipoElegido === this.value) anulado = true;
            });

            if (anulado) $tipoContrato.val('');

            avisoFueraDePlantilla(fuera);

            if (anulado) {
                $tipoContrato.trigger('change.tipo').trigger('change.plaza');
                if (window.mostrarToast) {
                    window.mostrarToast(
                        'Este cargo está fuera de la plantilla aprobada: se ha quitado el tipo de contrato que ocupa plaza.',
                        'warning'
                    );
                }
            }
        }

        $cargoSelect.on('change', aplicarReglaFueraDePlantilla);

        /* Y también cuando HTMX acaba de traer las opciones de cargo.
           Sin esto la regla solo funcionaba al EDITAR: ahí el formulario ya
           llega con los cargos cargados. Al CREAR, las opciones entran por la
           cascada (unidad -> departamento -> cargo) sin disparar ningún
           `change`, así que el desplegable de Tipo se quedaba sin filtrar. */
        document.body.addEventListener('htmx:afterSwap', function (evento) {
            const destino = evento.detail.target ? evento.detail.target.id : '';
            if (destino === 'id_cargo') aplicarReglaFueraDePlantilla();
        });

        aplicarReglaFueraDePlantilla();

        $form.off('change.cascada').on('change.cascada', '#id_unidad, #id_departamento', function() {
            if ($(this).is('#id_unidad')) {
                $('#id_departamento').empty().trigger('change.select2');
            }
            $('#id_cargo').empty().trigger('change.select2');
            if (window.htmx) htmx.trigger('#disparador-salarios', 'actualizarSalarios');
        });

        $cargoSelect.off('change.grupoEscala').on('change.grupoEscala', function() {
            let $option = $(this).find('option:selected');
            let grupo = $option.data('grupo');
            let $helpText = $('#help-cargo-grupo');

            if (grupo) {
                $helpText.html(`<i class="fas fa-info-circle me-1"></i> Este cargo pertenece al Grupo Escala ${grupo}`)
                        .removeClass('d-none').hide().slideDown(200);
            } else {
                $helpText.slideUp(200, function() { $(this).addClass('d-none').html(''); });
            }
        });

        if ($cargoSelect.val()) {
            $cargoSelect.trigger('change.grupoEscala');
        }

        $form.off('change.htmx').on('change.htmx', '#id_cargo, #id_tridente, #id_tipo_salario', function(e, extraParams) {
            if (extraParams && extraParams.omitirHtmx) {
                return;
            }
            if (window.htmx) htmx.trigger('#disparador-salarios', 'actualizarSalarios');
        });

        // 5. EVALUACIÓN DE TRIDENTE Y SALARIOS
        function evaluarTridente() {
            const rol = $('#id_rol').val() || '', cat = $('#id_cat_ocupacional').val() || '';
            const $tridente = $('#id_tridente'), $tipoSalario = $('#id_tipo_salario').val();
            if (!$tridente.length) return;

            const esCuadro = rol.toUpperCase().includes('CUADRO') || cat.toUpperCase().includes('CUADRO') || cat.includes('CDI') || cat.includes('CEJ');
            if (esCuadro || $tipoSalario === 'FIJ') {
                $tridente.val('').prop('disabled', true);
            } else {
                $tridente.prop('disabled', false);
            }

            if ($tridente.hasClass('select2-hidden-accessible')) {
                $tridente.trigger('change.select2');
            }

            $tridente.trigger('change', [{ omitirHtmx: true }]);
        }

        $('body').off('htmx:afterSwap.salarios').on('htmx:afterSwap.salarios', function(e) {
            if ($(e.target).attr('id') === 'resultados_salariales') {
                setTimeout(evaluarTridente, 50);
            }
        });

        // 5.b F. ALTA ENTIDAD: nunca posterior a F. de Contratación.
        //
        // Solo se mueve el tope 'max' para que coincida con la validación del servidor.
        // NO se autocompleta con la F. de Contratación: son dos datos distintos —la
        // fecha en que el trabajador entró POR PRIMERA VEZ en la entidad no tiene por
        // qué ser la de este contrato— y copiarla sola producía altas (y, al editar,
        // contratos históricos sin ella, regla CTR-016) con una fecha que nadie había
        // verificado. Nace vacía (amarilla) y hay que escribirla. En edición la F. de
        // Contratación no cambia, así que el tope se fija una sola vez, al arrancar.
        $('#id_fecha_alta').off('change.altaEntidad').on('change.altaEntidad', function() {
            $('#id_fecha_alta_entidad')
                .attr('max', $(this).val() || '')
                .trigger('change.val');
        });

        // 5.c Los Años de Servicio y su pago se recalculan en el servidor cada vez
        //     que cambia la fecha: la cuantía sale del nomenclador Escala de Años
        //     de Servicio y no se puede deducir en el navegador.
        $('#id_fecha_alta_entidad').off('change.annos').on('change.annos', function() {
            if (window.htmx) htmx.trigger('#disparador-annos', 'actualizarAnnos');
        });

        // Fechas del contrato con año mínimo. Espejo de `CAMPOS_FECHA_CONTRATO` y
        // `ANO_MINIMO_FECHAS` en `contratos/forms.py`: si cambia allí, cambia aquí.
        // En edición la F. de Contratación va oculta y no se valida aquí.
        const ANO_MINIMO = 1900;
        const CAMPOS_FECHA = ['fecha_alta_entidad', 'fecha_vence_lic', 'fecha_vence_recal', 'fecha_vence_seg']
            .concat(esEdicion ? [] : ['fecha_alta']);

        function fechaFueraDeRango(name, valor) {
            if (!valor) return false;
            var anio = parseInt(valor.split('-')[0], 10);
            if (isNaN(anio) || anio < ANO_MINIMO) return true;
            // F. Alta Entidad nunca posterior a F. de Contratación (misma regla que
            // `CAltaForm.clean`), para avisar antes de enviar y no después.
            if (name === 'fecha_alta_entidad') {
                var contratacion = $('#id_fecha_alta').val();
                if (contratacion && valor > contratacion) return true;
            }
            return false;
        }

        // 6. VALIDACIÓN VISUAL UNIVERSAL
        const reglas = {
            numericos: ['duracion', 'no_expediente'],
            obligatorios: [ 'no_expediente', 'tipo', 'tipo_salario', 'motivo', 'fecha_alta', 'fecha_alta_entidad', 'duracion', 'unidad', 'departamento', 'cargo', 'tridente', 'fecha_vence_lic', 'fecha_vence_recal', 'fecha_vence_seg', 'pais', 'reg_militar' ]
        };

        var timerExp = null;
        const expedienteOriginal = o.expedienteOriginal || '';

        $form.off('input.val change.val').on('input.val change.val', 'input, select, textarea', function() {
            let $el = $(this); let name = this.name;
            if (!name) return;
            // Las copias ocultas (`data-solo-para-calculo`: cargo, tridente y tipo de
            // salario bloqueados al editar) solo sirven para calcular el salario: no se
            // pueden rellenar, así que no se validan. Antes el tridente oculto y vacío de
            // un cuadro (Lisandra, Director de UEB) dejaba Guardar apagado para siempre.
            if (this.type === 'hidden' || $el.is('[data-solo-para-calculo]')) return;

            if (reglas.numericos.includes(name)) {
                let val = $el.val() || '';
                this.value = val.toString().replace(/[^0-9]/g, '');
            }

            if (name === 'no_expediente') {
                let errExist = $('#error_exp_exist');
                errExist.addClass('d-none');
                $el.removeClass('is-invalid border-danger border-success border-warning');
                clearTimeout(timerExp);

                if (this.value.length > 0) {
                    if (this.value === expedienteOriginal) {
                        $el.addClass('border-success');
                        evaluarBoton();
                        return;
                    }

                    timerExp = setTimeout(() => {
                        fetch(o.urls.validarExpediente + '?no_expediente=' + this.value)
                        .then(res => res.json())
                        .then(data => {
                            if (data.expediente_existe) {
                                errExist.removeClass('d-none');
                                $el.removeClass('border-success').addClass('is-invalid border-danger');
                            } else {
                                errExist.addClass('d-none');
                                $el.removeClass('is-invalid border-danger').addClass('border-success');
                            }
                            evaluarBoton();
                        }).catch(err => {
                            console.error("Error validando expediente:", err);
                        });
                    }, 300);
                }
            }

            if (reglas.obligatorios.includes(name)) {
                let esValido = true;
                if ($el.prop('disabled')) {
                    $el.removeClass('border-warning border-success is-invalid border-danger');
                    if ($el.hasClass('select2-hidden-accessible')) $el.next('.select2-container').find('.select2-selection').removeClass('border-warning border-success');
                } else {
                    esValido = this.value.trim() !== '';
                    if (['duracion', 'no_expediente'].includes(name)) { let num = parseInt(this.value); esValido = (!isNaN(num) && num > 0); }
                    let $target = $el.hasClass('select2-hidden-accessible') ? $el.next('.select2-container').find('.select2-selection') : $el;
                    // Las fechas tienen TRES estados, no dos: vacía (amarillo), escrita
                    // pero imposible (rojo, y el botón Guardar bloqueado por
                    // `evaluarBoton`, que cuenta los `.is-invalid`) y correcta (verde).
                    // El rojo es el que evita que un año a medio teclear —«0002»— llegue
                    // al servidor, que lo rechaza igual (`CAltaForm._validar_ano_minimo`).
                    if (CAMPOS_FECHA.includes(name)) {
                        $target.removeClass('border-warning border-success border-danger is-invalid');
                        if (!esValido) { $target.addClass('border-warning'); }
                        else if (fechaFueraDeRango(name, this.value)) { $target.addClass('border-danger is-invalid'); }
                        else { $target.addClass('border-success'); }
                    } else {
                        esValido ? $target.removeClass('border-warning').addClass('border-success') : $target.removeClass('border-success').addClass('border-warning');
                    }
                }
                evaluarBoton();
            }
        });

        function evaluarBoton() {
            $btnSubmit.prop('disabled', $form.find('.border-warning, .is-invalid').length > 0);
        }

        function repintar(html) {
            $form.closest('.modal').find('.modal-content').html($(html).find('.modal-content').html() || html);
            if (typeof o.reiniciar === 'function') o.reiniciar();
        }

        // 7. ENVÍO AJAX ROBUSTO
        $form.off('submit').on('submit', function(e) {
            e.preventDefault();

            $('#id_cargo').prop('disabled', false);

            if ($('#error_exp_exist').length && !$('#error_exp_exist').hasClass('d-none')) {
                Swal.fire({ title: 'Atención', text: 'El EXPEDIENTE LABORAL ya existe', icon: 'warning', customClass: {confirmButton: 'btn btn-primary'} });
                return;
            }

            $.ajax({
                url: formulario.action, type: formulario.method, data: $form.serialize(), dataType: 'json',
                success: function(data) {
                    if (typeof data === 'object' && data.form_is_valid) {
                        const modalEl = document.querySelector('.modal.show');
                        if (modalEl) { const instance = bootstrap.Modal.getInstance(modalEl); if (instance) instance.hide(); }
                        $('.modal-backdrop').remove(); $('body').removeClass('modal-open').css('overflow', '');

                        if (data.redirect_to_wizard) {
                            $.get(data.redirect_to_wizard, function(html) {
                                // Contenedor propio y visible (26-10-2026): en la Lista de Contratos
                                // `#editar_empl` es una ventana oculta y el movimiento no aparecía.
                                let caja = document.getElementById('contenedor_movimiento');
                                if (!caja) { caja = document.createElement('div'); caja.id = 'contenedor_movimiento'; document.body.appendChild(caja); }
                                $(caja).html(html); new bootstrap.Modal(caja.querySelector('#modalMovimientoContrato')).show();
                            });
                        } else if (o.alGuardarSinNavegar && window.OrbithGestorSinNavegar) {
                            // Abierto desde el Gestor de Plantilla: no se navega,
                            // se refrescan sus columnas y se conserva la selección.
                            window.OrbithGestorSinNavegar('Contrato actualizado.');
                        } else {
                            window.location.href = data.success_url || o.urls.lista;
                        }
                    }
                    else if (typeof data === 'object' && !data.form_is_valid) {
                        if (data.error_popup) Swal.fire({ title: 'Atención', text: data.error_popup, icon: 'error' });
                        repintar(data.html_form);
                    }
                },
                error: function(xhr) {
                    if (xhr.responseText && xhr.responseText.includes('errorlist')) {
                        repintar(xhr.responseText);
                    } else {
                        Swal.fire({ title: 'Error', text: 'Error de conexión del servidor o datos inválidos.', icon: 'error' });
                    }
                }
            });
        });

        // =======================================================
        // ARRANQUE INICIAL UNIFICADO Y LIMPIO
        // =======================================================
        $('#id_c_formal, #id_funcionario, #id_designado, #id_mision, #id_profesional').trigger('change.switches');
        $('#id_tipo').trigger('change.tipo');
        evaluarTridente();

        setTimeout(() => {
            $('#id_tipo').trigger('change.plaza');
            $('#id_fecha_alta').removeAttr('disabled').trigger('change.val');
            $('#id_fecha_alta_entidad').removeAttr('disabled').trigger('change.val');
            $('#id_fecha_alta').trigger('change.altaEntidad');
            reglas.obligatorios.forEach(name => { $form.find(`[name="${name}"]`).trigger('change.val'); });

            // CLA y las dos nocturnidades: `select_unificado.js` les da el mismo aspecto
            // que al resto y, además, buscador (el nomenclador de Condiciones Laborales
            // Anormales es largo).

            // Sincronizar UI sin mostrar alertas
            sincronizarEstadosEspeciales(false);
            aplicarExclusividadNocturnidad();
        }, 400);
    }

    /* Al cerrar Registrar o Editar contrato se borra su formulario (18-11-2026).
       Se quedaba escondido en la página y, al abrir el otro sin recargar, había dos
       `#contratoForm` con los mismos ids: el código se enganchaba al escondido y el
       visible no cargaba los motivos, ni la cascada, ni comprobaba nada al guardar.
       Solo el formulario: el marco de la ventana sigue ahí, y cada vez que se abre
       su contenido se vuelve a pedir al servidor. */
    $(document).on('hidden.bs.modal', '.modal', function () {
        $(this).find('#contratoForm').remove();
    });

    window.OrbithFormularioContrato = { iniciar: iniciar };
})();
