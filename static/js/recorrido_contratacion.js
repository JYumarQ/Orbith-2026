/**
 * Recorridos visuales de la contratación (tarea `primera_contratacion`).
 *
 * Hay tres formas de contratar y las tres acaban en el mismo formulario
 * ("Registrar Contrato") y en la misma segunda ventana ("Movimiento de
 * Nómina"):
 *
 *   primera_contratacion:aspirantes  Lista de Aspirantes → fila → "Contrato".
 *   primera_contratacion:gestor      Gestor de Plantilla → cargo → "+" →
 *                                    ventana "Nuevo contrato".
 *   primera_contratacion:contratos   Lista de Contratos → "Nuevo" → ventana
 *                                    "Nuevo contrato".
 *
 * Los pasos del formulario y del movimiento se escriben UNA sola vez
 * (`pasosFormulario`): cada entrada solo aporta su comienzo. Este archivo se
 * carga en las tres pantallas y registra únicamente la entrada de la pantalla
 * en la que está (lo deduce de los elementos que encuentra).
 *
 * Igual que el resto de recorridos, nunca escribe ni guarda nada: señala,
 * explica y espera a que el usuario lo haga.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const F = '#contratoForm ';
  const MOV = '#movimientoForm ';
  const ESPERA_CAMPOS = 'Completa los campos obligatorios para continuar.';

  // Un campo cuenta si está encendido: los que el formulario apaga según otra
  // elección (motivo, duración, tridente, país, resoluciones, vencimientos)
  // no se exigen mientras estén apagados.
  function listos(formulario, nombres) {
    const form = document.querySelector(formulario);
    if (!form) return '';
    return nombres.every(function (nombre) {
      const el = form.querySelector('[name="' + nombre + '"]');
      if (!el || el.disabled) return true;
      return String(el.value || '').trim() && !el.classList.contains('is-invalid');
    }) ? 'si' : '';
  }

  function mostrarPestana(destino) {
    const boton = document.querySelector(F + '[data-bs-target="' + destino + '"]');
    if (boton && window.bootstrap) bootstrap.Tab.getOrCreateInstance(boton).show();
  }
  function pestanaPlantilla() { mostrarPestana('#navs-justified-plantilla'); }
  function pestanaSalario() { mostrarPestana('#navs-justified-salario'); }

  function formularioAbierto() {
    return document.querySelector('#crear_contrato.show #contratoForm') ? 'abierto' : '';
  }

  // ------------------------------------------------------------------
  // Pasos comunes: formulario "Registrar Contrato" + "Movimiento de Nómina"
  // ------------------------------------------------------------------
  function pasosFormulario(idEntrada) {
    // Si el usuario cierra una ventana a medias, se vuelve al comienzo de
    // la entrada (sin enlace: ver `volver` en orbith_recorrido.js).
    const VOLVER = { a: idEntrada };
    return [
      {
        selector: [F + '#id_no_expediente', F + '#id_tipo', F + '#id_motivo', F + '#id_fecha_alta',
                   F + '#id_fecha_alta_entidad', F + '#id_annos_servicio', F + '#id_duracion'].join(', '),
        preparar: pestanaPlantilla, interactivo: true, avanceManual: true,
        textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Datos del contrato',
        texto: 'Escribe el <strong>Exp. Laboral</strong> (solo números, hasta 5 dígitos; si ya existe se marca en rojo) y elige el <strong>Tipo de Contrato</strong>: ' +
               'si ese tipo lo exige se enciende el <strong>Motivo</strong>, y si es indeterminado la <strong>D. de Contrato</strong> (duración) se apaga. ' +
               'Pon la <strong>F. de Contratación</strong> y la <strong>F. Alta Entidad</strong> (desde cuándo trabaja sin interrupción en la Unión Eléctrica; tras una baja, normalmente la de este contrato; no puede ser posterior a la contratación). ' +
               'Los <strong>Años Servicio</strong> se calculan solos.',
        esperar: function () {
          return listos('#contratoForm', ['no_expediente', 'tipo', 'motivo', 'fecha_alta', 'fecha_alta_entidad', 'duracion']);
        },
      },
      {
        selector: [F + '#id_unidad', F + '#id_departamento', F + '#id_cargo'].join(', '),
        preparar: pestanaPlantilla, interactivo: true, avanceManual: true,
        textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Ubicación en la plantilla',
        texto: 'Elige la <strong>Unidad Organizativa</strong>, el <strong>Departamento</strong> y el <strong>Cargo</strong>: cada uno filtra al siguiente. ' +
               'Cada cargo muestra sus plazas; si no quedan, o si el cargo está fuera de la plantilla aprobada, se bloquean los tipos de contrato que ocupan plaza. ' +
               'Si empezaste desde el Gestor, ya vienen elegidos.',
        esperar: function () { return listos('#contratoForm', ['unidad', 'departamento', 'cargo']); },
      },
      {
        selector: ['#bloqueCFormal', '#bloqueFuncionario', '#bloqueDesignado', '#bloqueChoferJubilado',
                   F + '[name="fecha_vence_lic"]', F + '[name="fecha_vence_recal"]', F + '[name="fecha_vence_seg"]', '#bloqueMision'].join(', '),
        preparar: pestanaPlantilla, interactivo: true, avanceManual: true,
        textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Condiciones especiales',
        texto: 'Solo hace falta rellenar lo que se encienda:' +
               '<ul class="ps-3 mb-0 mt-1">' +
               '<li><strong>C. Formal</strong>: al marcarlo se enciende su No. de Resolución.</li>' +
               '<li><strong>Funcionario</strong> y <strong>Designado</strong> se marcan solos según el cargo y encienden su No. de Resolución.</li>' +
               '<li>Los <strong>números de resolución</strong> son opcionales: si aún no los tienes, déjalos vacíos. Puedes escribirlos en el Alta Inicial o más tarde; Subsanación te recordará los que falten.</li>' +
               '<li><strong>Chofer Profesional</strong>: al marcarlo son obligatorios los vencimientos de licencia, recalificación y seguro.</li>' +
               '<li><strong>Jubilado Recontratado</strong>: márcalo si corresponde.</li>' +
               '<li><strong>Misión</strong>: al marcarlo, elige el País.</li>' +
               '</ul>',
        esperar: function () {
          // Los números de resolución no se esperan: son opcionales (25-10-2026).
          return listos('#contratoForm', ['fecha_vence_lic', 'fecha_vence_recal', 'fecha_vence_seg', 'pais']);
        },
      },
      {
        selector: F + '#id_reg_militar',
        preparar: pestanaPlantilla, interactivo: true, avanceManual: true,
        textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Registro Militar',
        texto: 'Elige el <strong>Registro Militar</strong>: es obligatorio.',
        esperar: function () { return listos('#contratoForm', ['reg_militar']); },
      },
      {
        selector: F + '[data-bs-target="#navs-justified-salario"]',
        interactivo: true, volver: VOLVER,
        titulo: 'Pestaña Salario',
        texto: 'Pulsa la pestaña <strong>"Salario"</strong> para seguir.',
        esperar: function () { return document.querySelector('#navs-justified-salario.active') ? 'si' : ''; },
      },
      {
        selector: [F + '#id_tipo_salario', F + '#id_cat_ocupacional', F + '#id_grupo_escala', F + '#id_rol',
                   F + '#id_tridente', '#bloqueCalculosSalario'].join(', '),
        preparar: pestanaSalario, interactivo: true, avanceManual: true,
        textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Tipo de salario',
        texto: 'Elige el <strong>Tipo de Salario</strong> (Fijo o Dinámico). La <strong>Categoría Ocupacional</strong>, el <strong>Grupo Escala</strong> y el <strong>Rol</strong> vienen del cargo. ' +
               'El <strong>Tridente</strong> solo se pide con salario Dinámico y si el cargo no es de cuadro. ' +
               'El <strong>Salario Escala</strong>, las tarifas y el <strong>Pago Años de Servicio</strong> se calculan solos.',
        esperar: function () { return listos('#contratoForm', ['tipo_salario', 'tridente']); },
      },
      {
        selector: ['#txt_maestria', '#txt_doctorado', F + '#id_instructor_nomenclador',
                   F + '#id_cnci_nomenclador', '#bloqueCondicionesLaborales'].join(', '),
        preparar: pestanaSalario, interactivo: true, opcional: true, volver: VOLVER,
        titulo: 'Complementos',
        texto: 'La <strong>Maestría</strong> y el <strong>Doctorado</strong> se rellenan solos según el grado científico del trabajador. ' +
               '<strong>Instructor</strong> y <strong>CNCI</strong> se eligen del nomenclador si corresponden. ' +
               'Abajo, la <strong>CLA</strong> y las dos <strong>Nocturnidades</strong>, que no pueden ser la misma.',
      },
      {
        selector: F + 'button[type="submit"]',
        // El formulario se cierra y "Movimiento de Nómina" tarda en abrirse:
        // se le da margen antes de pensar que el usuario cerró la ventana.
        interactivo: true, volver: VOLVER, paciencia: 8000,
        titulo: 'Continuar',
        texto: 'Revisa los colores: <strong>amarillo</strong> es lo que falta y <strong>rojo</strong> un error. El botón se apaga mientras quede alguno. ' +
               'Pulsa <strong>"Continuar"</strong>: todavía no se guarda nada, se abre la ventana del movimiento de nómina.',
        esperar: function () {
          return document.querySelector('#modalMovimientoContrato.show #movimientoForm') ? 'movimiento' : '';
        },
      },
      {
        selector: '#movColumnaActual, #movColumnaNueva',
        volver: VOLVER,
        titulo: 'Movimiento de Nómina',
        texto: 'A la izquierda, la <strong>Situación Actual</strong>: vacía, porque es un contrato nuevo. A la derecha, la <strong>Nueva Propuesta</strong> con lo que acabas de rellenar, bloqueada; la <strong>Fecha Efectiva</strong> ya viene puesta y abajo ves el <strong>Nuevo Salario</strong>. ' +
               'Si algo está mal, cierra la ventana con la <strong>X</strong>: todavía no se ha guardado nada. Ojo: "Cancelar" pregunta si quieres guardar el contrato sin movimiento.',
      },
      {
        selector: MOV + '[name="fecha_solicitud"], ' + MOV + '[name="observaciones"], #bloque-resoluciones-mov',
        interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Fecha de Solicitud',
        texto: 'Escribe la <strong>Fecha de Solicitud</strong>. Las <strong>Observaciones</strong> son opcionales. ' +
               'En <strong>Resoluciones</strong> llegan los números escritos en el contrato: puedes completarlos o corregirlos aquí, y lo que quede en esta ventana es lo que se guarda.',
        esperar: function () { return listos('#movimientoForm', ['fecha_solicitud']); },
      },
      {
        selector: MOV + 'button[type="submit"]',
        interactivo: true, terminarSiDesaparece: true,
        titulo: 'Confirmar Movimiento',
        texto: 'Pulsa <strong>"Confirmar Movimiento"</strong> y acepta con "Sí, aplicar". El aspirante pasa a <strong>Activo</strong> y Orbith te ofrece exportar el documento del movimiento en Word: si pulsas <strong>"Exportar"</strong>, también consigues "Exporta un movimiento de nómina". ¡Y consigues el logro!',
      },
    ];
  }

  // Un solo paso para la ventana "Nuevo contrato" (Gestor y Contratos).
  function pasoElegirAspirante(idEntrada) {
    return {
      selector: '#modalNuevoContrato.show .modal-content',
      // Esta ventana se cierra y el formulario tarda en abrirse.
      interactivo: true, volver: { a: idEntrada }, paciencia: 8000,
      titulo: 'Elige al aspirante',
      texto: 'Busca al aspirante por <strong>nombre, apellido o carnet</strong>, haz clic en su fila (abajo verás "Seleccionado: …") y pulsa <strong>"Contratar Aspirante"</strong>. ' +
             'Solo aparecen los aspirantes disponibles: quien ya tiene contrato o está de baja no se lista.',
      esperar: formularioAbierto,
    };
  }

  function iniciar(pasos) {
    window.OrbithRecorrido.iniciar({ pasos: pasos });
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};

  // --- 1. Lista de Aspirantes ---
  if (document.getElementById('tablaAspirantesCard') && document.getElementById('btn-contrato')) {
    window.OrbithRecorridos['primera_contratacion:aspirantes'] = function () {
      iniciar([
        {
          id: 'entrada', selector: '#filter_aspirantes_results', interactivo: true,
          titulo: 'Elige a quién contratar',
          texto: 'Haz clic en la fila del aspirante que vas a contratar: se resalta y se encienden los botones de arriba.',
          esperar: function () {
            const fila = document.querySelector('#filter_aspirantes_results .table-active-row');
            return fila ? fila.dataset.id : '';
          },
        },
        {
          selector: '#btn-contrato', interactivo: true, volver: { a: 'entrada' },
          titulo: 'Contrato',
          texto: 'Pulsa el botón verde <strong>"Contrato"</strong> (el de la firma) para abrir el formulario.',
          esperar: formularioAbierto,
        },
      ].concat(pasosFormulario('entrada')));
    };
  }

  // --- 2. Gestor de Plantilla ---
  if (document.getElementById('col-panel-contrato') && window.OrbithPasosSeleccionGestor) {
    window.OrbithRecorridos['primera_contratacion:gestor'] = function () {
      // Si ya hay un cargo elegido, se empieza directamente en el "+".
      const hayCargo = function () { return !!document.querySelector('#col-cargos .active-cargo'); };
      const seleccion = window.OrbithPasosSeleccionGestor().map(function (paso) {
        paso.saltarSi = hayCargo;
        return paso;
      });
      iniciar(seleccion.concat([
        {
          id: 'entrada', selector: '#btn-add-personal', interactivo: true,
          volver: { a: 'cargo', texto: '¿Otro cargo? Volver a elegirlo' },
          titulo: 'Contratar en este cargo',
          texto: 'Pulsa el botón <strong>"+"</strong> de la columna de Contratos: se abre la ventana para elegir al aspirante y el formulario llegará con este cargo ya puesto.',
          esperar: function () { return document.querySelector('#modalNuevoContrato.show') ? 'abierto' : ''; },
        },
        pasoElegirAspirante('entrada'),
      ]).concat(pasosFormulario('entrada')));
    };
  }

  // --- 3. Lista de Contratos ---
  if (document.getElementById('btn-nuevo-contrato')) {
    window.OrbithRecorridos['primera_contratacion:contratos'] = function () {
      iniciar([
        {
          id: 'entrada', selector: '#btn-nuevo-contrato', interactivo: true,
          titulo: 'Nuevo contrato',
          texto: 'Pulsa <strong>"Nuevo"</strong>: se abre la ventana para elegir al aspirante que vas a contratar.',
          esperar: function () { return document.querySelector('#modalNuevoContrato.show') ? 'abierto' : ''; },
        },
        pasoElegirAspirante('entrada'),
      ].concat(pasosFormulario('entrada')));
    };
  }
})();
