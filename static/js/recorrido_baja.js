/**
 * Recorridos visuales de la baja (tarea `primera_baja`).
 *
 * La baja se da desde la lista de Contratos o desde la columna de Contratos
 * del Gestor de Plantilla, con el botón rojo "Dar de Baja". Las dos pantallas
 * usan el MISMO Formulario de Baja (templates/pages/contrato/partials/
 * modal_baja.html), así que sus pasos se escriben una sola vez
 * (`pasosFormulario`) y cada entrada solo aporta su comienzo.
 *
 * Nunca da la baja por el usuario: señala, explica y espera.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const ESPERA_CAMPOS = 'Completa los campos obligatorios para continuar.';

  // Fechas y causa rellenas, y la Fecha de Baja sin el aviso de "no puede ser
  // anterior al último movimiento" (el formulario la pinta en amarillo).
  function fechasYCausaListas() {
    const fecha = document.getElementById('baja_fecha');
    const documento = document.getElementById('baja_fecha_efectiva');
    const causa = document.getElementById('baja_causa');
    if (!fecha || !documento || !causa) return '';
    const ok = fecha.value && documento.value && causa.value &&
      !document.querySelector('#formBajaContrato .error-cronologico');
    return ok ? 'si' : '';
  }

  function pasosFormulario(idEntrada) {
    const VOLVER = { a: idEntrada };
    return [
      {
        selector: '#bajaDatosTrabajador', interactivo: true, volver: VOLVER,
        titulo: 'Formulario de Baja',
        texto: 'El <strong>No. Expediente</strong> y el <strong>Trabajador</strong> vienen solos. La <strong>Actividad que realizaba</strong> llega con su cargo actual; puedes corregirla si hace falta.',
      },
      {
        selector: '#baja_fecha, #baja_fecha_efectiva, #baja_causa',
        interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Fechas y causa',
        texto: 'Las tres son obligatorias. La <strong>Fecha de Baja</strong> no puede ser anterior al último movimiento de nómina del trabajador: si lo es, el formulario te avisa debajo. ' +
               'Pon también la <strong>Fecha de Documento</strong> y elige la <strong>Causa de Baja</strong>.',
        esperar: fechasYCausaListas,
      },
      {
        selector: '#baja_observaciones, #bajaInterruptores',
        interactivo: true, opcional: true, volver: VOLVER,
        titulo: 'Observaciones e interruptores',
        texto: 'Las <strong>Observaciones</strong> son opcionales. Marca <strong>"Cobró sistema de pago"</strong> y <strong>"Completar cargo"</strong> si corresponden: quedan registrados en el informe de Altas y Bajas.',
      },
      {
        selector: '#btnConfirmarBaja',
        // Al pulsarlo, el formulario se cierra y sale la confirmación: mientras
        // está abierta el recorrido se aparta; si se cancela, vuelve el formulario.
        interactivo: true, terminarSiDesaparece: true, paciencia: 2000,
        titulo: 'Confirmar Baja',
        texto: 'El botón se enciende cuando todo está correcto. Pulsa <strong>"Confirmar Baja"</strong> y acepta con <strong>"Sí, dar de baja"</strong>. ' +
               'Orbith genera el movimiento de baja y te ofrece exportar su documento en Word (si pulsas <strong>"Exportar"</strong>, también consigues "Exporta un movimiento de nómina"); el trabajador pasa a la lista de Bajas. ¡Y consigues el logro!',
      },
    ];
  }

  function iniciar(pasos) {
    window.OrbithRecorrido.iniciar({ pasos: pasos });
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};

  // --- Lista de Contratos ---
  if (document.getElementById('filter_contratos_results') && document.getElementById('btn-baja')) {
    window.OrbithRecorridos['primera_baja:contratos'] = function () {
      iniciar([
        {
          id: 'entrada', selector: '#filter_contratos_results', interactivo: true,
          titulo: 'Elige al trabajador',
          texto: 'Haz clic en la fila del trabajador que causa baja: se resalta y se encienden los botones de arriba. Si no lo ves, búscalo: el buscador admite prefijos, por ejemplo <code>E:8855</code> o <code>N:Juan</code>.',
          esperar: function () {
            const el = document.querySelector('#filter_contratos_results .fila-contrato.table-active-row');
            return el ? el.dataset.id : '';
          },
        },
        {
          selector: '#btn-baja', interactivo: true, volver: { a: 'entrada', texto: 'Elegir otro trabajador' },
          titulo: 'Dar de Baja',
          texto: 'Pulsa el botón rojo <strong>"Dar de Baja"</strong> para abrir el Formulario de Baja.',
          esperar: function () { return document.querySelector('#modalBajaContrato.show') ? 'abierto' : ''; },
        },
      ].concat(pasosFormulario('entrada')));
    };
  }

  // --- Gestor de Plantilla ---
  if (document.getElementById('col-panel-contrato') && document.getElementById('btn-baja')) {
    window.OrbithRecorridos['primera_baja:gestor'] = function () {
      // Si ya hay un cargo elegido, no se repite unidad → departamento → cargo.
      const hayCargo = function () { return !!document.querySelector('#col-cargos .active-cargo'); };
      const seleccion = (window.OrbithPasosSeleccionGestor ? window.OrbithPasosSeleccionGestor() : [])
        .map(function (paso) { paso.saltarSi = hayCargo; return paso; });
      iniciar(seleccion.concat([
        {
          id: 'entrada', selector: '#col-contratos', interactivo: true,
          volver: { a: 'cargo', texto: '¿Plaza vacante? Elegir otro cargo' },
          titulo: 'Elige al trabajador',
          texto: 'En la columna <strong>4. Contratos</strong>, haz clic en la persona que causa baja.',
          esperar: function () {
            const el = document.querySelector('#col-contratos .active-contrato');
            return el ? el.dataset.pk : '';
          },
        },
        {
          selector: '#btn-baja', interactivo: true, volver: { a: 'entrada', texto: 'Elegir otro trabajador' },
          titulo: 'Dar de Baja',
          texto: 'Pulsa el botón rojo <strong>"Dar de Baja"</strong> (el de la persona con un menos) para abrir el Formulario de Baja.',
          esperar: function () { return document.querySelector('#modalBajaContrato.show') ? 'abierto' : ''; },
        },
      ]).concat(pasosFormulario('entrada')));
    };
  }
})();
