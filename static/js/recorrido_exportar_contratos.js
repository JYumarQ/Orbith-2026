/**
 * Recorridos de exportar de Contratos (categoría "Exportar" de la Guía).
 *
 * - `exportar_lista_contratos:contratos`: botón Excel de la lista de Contratos.
 * - `exportar_contrato_modificacion:contratos|gestor`: elegir al trabajador y
 *   abrir el Asistente de Exportación Legal; sigue allí con
 *   `exportar_contrato_modificacion:asistente` (versión rápida) o
 *   `:asistente_detalle` (campo a campo). La tarea pide los dos documentos:
 *   Contrato de Trabajo y Modificación.
 * - `exportar_movimiento_nomina:contratos|gestor` y
 *   `exportar_historico_trabajador:contratos|gestor`: desde el histórico del
 *   trabajador (doble clic en su fila).
 *
 * Lo carga la lista de Contratos, el Gestor de Plantilla y el propio Asistente
 * (templates/pages/contrato/exportar_contrato.html). Nunca descarga nada por
 * el usuario: señala, explica y espera.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const enContratos = !!document.getElementById('filter_contratos_results');
  const enGestor = !!document.getElementById('col-panel-contrato');
  const enAsistente = !!document.getElementById('formExportarContrato');

  // El Gestor abre el Asistente en OTRA pestaña, que no hereda el
  // sessionStorage de esta: el recorrido pendiente se deja en localStorage,
  // con caducidad corta para que no se lance por sorpresa más tarde.
  const CLAVE_PENDIENTE = 'orbith_recorrido_pendiente';

  function dejarPendiente(clave) {
    try {
      localStorage.setItem(CLAVE_PENDIENTE, JSON.stringify({ clave: clave, hasta: Date.now() + 30000 }));
    } catch (e) { /* sin localStorage, el usuario lo relanza con "¿Cómo funciona?" */ }
  }

  function tomarPendiente() {
    try {
      const datos = JSON.parse(localStorage.getItem(CLAVE_PENDIENTE));
      localStorage.removeItem(CLAVE_PENDIENTE);
      return datos && datos.hasta > Date.now() ? datos.clave : '';
    } catch (e) { return ''; }
  }

  function iniciar(pasos) {
    window.OrbithRecorrido.iniciar({ pasos: pasos });
  }

  // Marca de "se pulsó este botón": las descargas no avisan de nada, así que
  // basta con saber que el usuario lo pulsó.
  function vigilarClic(selector) {
    let pulsado = false;
    document.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest(selector) && !e.target.closest(selector).disabled) pulsado = true;
    }, true);
    return {
      reiniciar: function () { pulsado = false; },
      pulsado: function () { return pulsado ? 'si' : ''; },
    };
  }

  // ------------------------------------------------------------------
  // Elegir al trabajador (Contratos o Gestor)
  // ------------------------------------------------------------------
  function pasosElegirTrabajador(texto) {
    if (enContratos) {
      return [{
        id: 'trabajador', selector: '#filter_contratos_results', interactivo: true,
        titulo: 'Elige al trabajador',
        texto: texto || 'Haz clic en la fila del trabajador: se resalta y se encienden los botones de arriba. Si no lo ves, búscalo: el buscador admite prefijos, por ejemplo <code>E:8855</code> o <code>N:Juan</code>.',
        esperar: function () {
          const el = document.querySelector('#filter_contratos_results .fila-contrato.table-active-row');
          return el ? el.dataset.id : '';
        },
      }];
    }
    const hayCargo = function () { return !!document.querySelector('#col-cargos .active-cargo'); };
    const seleccion = (window.OrbithPasosSeleccionGestor ? window.OrbithPasosSeleccionGestor() : [])
      .map(function (paso) { paso.saltarSi = hayCargo; return paso; });
    return seleccion.concat([{
      id: 'trabajador', selector: '#col-contratos', interactivo: true,
      volver: { a: 'cargo', texto: '¿Plaza vacante? Elegir otro cargo' },
      titulo: 'Elige al trabajador',
      texto: texto || 'En la columna <strong>4. Contratos</strong>, haz clic en la persona.',
      esperar: function () {
        const el = document.querySelector('#col-contratos .active-contrato');
        return el ? el.dataset.pk : '';
      },
    }]);
  }

  // ------------------------------------------------------------------
  // Histórico del trabajador
  // ------------------------------------------------------------------
  const TEXTO_OTRAS_PANTALLAS = 'El histórico también se abre con doble clic en la lista de <strong>Mov. Nómina</strong>, en la de <strong>Aspirantes</strong> y en la de <strong>Bajas</strong>.';

  function pasoAbrirHistorico() {
    const selector = enContratos ? '#filter_contratos_results' : '#col-contratos';
    return {
      id: 'historico', selector: selector, interactivo: true,
      titulo: 'Abre el histórico',
      texto: (enContratos
        ? 'Haz <strong>doble clic</strong> en la fila de un trabajador: se abre su histórico. '
        : 'En la columna <strong>4. Contratos</strong>, haz <strong>doble clic</strong> en una persona: se abre su histórico. ') +
        TEXTO_OTRAS_PANTALLAS,
      esperar: function () { return document.querySelector('#modalHistorico.show') ? 'abierto' : ''; },
    };
  }

  const clicMovimiento = vigilarClic('#btnExportarMovimiento');
  const clicTodo = vigilarClic('#btnExportarGeneral');

  function pasosMovimiento() {
    const previos = enGestor ? (window.OrbithPasosSeleccionGestor ? window.OrbithPasosSeleccionGestor() : [])
      .map(function (paso) {
        paso.saltarSi = function () { return !!document.querySelector('#col-cargos .active-cargo'); };
        return paso;
      }) : [];
    return previos.concat([
      pasoAbrirHistorico(),
      {
        // Un solo paso: el histórico deselecciona el movimiento al hacer clic
        // fuera de la tabla (también en la tarjeta del recorrido), así que no
        // puede haber un "Siguiente" entre elegirlo y exportarlo.
        selector: '#tablaHistoricoBody, #btnExportarMovimiento', interactivo: true,
        volver: { a: 'historico' },
        alEntrar: clicMovimiento.reiniciar,
        titulo: 'Exportar Movimiento',
        texto: 'Haz clic en un <strong>movimiento</strong> de la tabla (alta, movimiento de nómina o baja): se resalta y se enciende <strong>"Exportar Movimiento"</strong>. Púlsalo.',
        textoEspera: 'Elige un movimiento y pulsa "Exportar Movimiento".',
        esperar: clicMovimiento.pulsado,
      },
      {
        selector: '#btnExportarMovimiento',
        titulo: '¡Documento en camino!',
        texto: 'El Word del movimiento se descarga desde una pestaña nueva. ' +
          'También cuenta el botón <strong>"Exportar"</strong> que Orbith ofrece al confirmar un alta, un movimiento de nómina o una baja. ¡Y consigues el logro!',
      },
    ]);
  }

  function pasosHistorico() {
    const previos = enGestor ? (window.OrbithPasosSeleccionGestor ? window.OrbithPasosSeleccionGestor() : [])
      .map(function (paso) {
        paso.saltarSi = function () { return !!document.querySelector('#col-cargos .active-cargo'); };
        return paso;
      }) : [];
    return previos.concat([
      pasoAbrirHistorico(),
      {
        selector: '#btnExportarGeneral', interactivo: true,
        volver: { a: 'historico' },
        alEntrar: clicTodo.reiniciar,
        titulo: 'Exportar Todo',
        texto: 'Pulsa <strong>"Exportar Todo"</strong>: genera un PDF con todos los movimientos del trabajador (altas, movimientos de nómina y bajas) y lo abre en otra pestaña.',
        textoEspera: 'Pulsa "Exportar Todo".',
        esperar: clicTodo.pulsado,
      },
      {
        selector: '#btnExportarGeneral',
        titulo: '¡Histórico exportado!',
        texto: 'Desde la pestaña nueva puedes guardarlo o imprimirlo. ¡Y consigues el logro!',
      },
    ]);
  }

  // ------------------------------------------------------------------
  // Lista de contratos a Excel (solo en Contratos)
  // ------------------------------------------------------------------
  // Desde el 24-10-2026 el botón descarga directamente lo que se ve en la lista
  // (filtros, búsqueda y orden): ya no hay ventana para elegir unidades.
  const clicExcel = vigilarClic('#btnExportarExcel');

  function pasosListaExcel() {
    return [
      {
        selector: 'button[title="Filtros"]',
        titulo: 'Primero, lo que quieres llevar',
        texto: 'El Excel lleva <strong>exactamente lo que ves en la lista</strong>: si filtras (por unidad, tipo de contrato, sexo…) o buscas a alguien, solo sale eso. Sin filtros, salen todos los contratos de tu alcance.',
      },
      {
        id: 'excel', selector: '#btnExportarExcel', interactivo: true,
        alEntrar: clicExcel.reiniciar,
        titulo: 'Exportar a Excel',
        texto: 'Pulsa el botón verde de <strong>Excel</strong>: se descarga la sábana con todas las columnas de cada contrato.',
        textoEspera: 'Pulsa el botón verde de Excel.',
        esperar: clicExcel.pulsado,
        paciencia: 3000,
      },
      {
        selector: '#btnExportarExcel',
        titulo: '¡Excel en camino!',
        texto: 'Lo encontrarás en tus <strong>descargas</strong>. ¡Y consigues el logro!',
      },
    ];
  }

  // ------------------------------------------------------------------
  // Contrato de Trabajo y Modificación: hasta el Asistente
  // ------------------------------------------------------------------
  const clicExportarContrato = vigilarClic('#btn-pdf');
  // Solo durante el paso "Exportar Contrato": el pendiente se deja JUSTO al
  // pulsar (antes de que el enlace navegue u abra la pestaña), no al entrar
  // en el paso, para que su caducidad corta no venza mientras el usuario lee.
  let pedirAsistente = false;
  document.addEventListener('click', function (e) {
    if (pedirAsistente && e.target.closest && e.target.closest('#btn-pdf')) {
      dejarPendiente('exportar_contrato_modificacion:asistente');
    }
  }, true);

  function pasosHastaAsistente() {
    return pasosElegirTrabajador().concat([
      {
        selector: '#btn-pdf', interactivo: true, volver: { a: 'trabajador', texto: 'Elegir otro trabajador' },
        alEntrar: function () {
          clicExportarContrato.reiniciar();
          pedirAsistente = true;
        },
        alSalir: function () { pedirAsistente = false; },
        titulo: 'Exportar Contrato',
        texto: 'Pulsa <strong>"Exportar Contrato"</strong> (el icono de documento): se abre el <strong>Asistente de Exportación Legal</strong>' +
          (enGestor ? ' en una pestaña nueva, y la guía sigue allí.' : ', y la guía sigue allí.'),
        esperar: clicExportarContrato.pulsado,
      },
      {
        // Solo en el Gestor: en Contratos la página ya cambió.
        selector: '#btn-pdf',
        saltarSi: function () { return !enGestor; },
        titulo: 'Sigue en la pestaña nueva',
        texto: 'El Asistente se abrió en otra pestaña. Allí continúa la guía.',
      },
    ]);
  }

  // ------------------------------------------------------------------
  // Asistente de Exportación Legal
  // ------------------------------------------------------------------
  const ETIQUETA_TIPO = { creacion: 'Contrato de Trabajo', modificacion: 'Modificación' };
  const hechas = new Set();
  let generado = false;

  function tipoElegido() {
    const radio = document.querySelector('input[name="tipo_documento"]:checked');
    return radio ? radio.value : 'creacion';
  }

  function estadoTipos() {
    return '<div class="d-flex gap-2 my-2">' + ['creacion', 'modificacion'].map(function (t) {
      const hecho = hechas.has(t);
      return '<span class="badge ' + (hecho ? 'bg-label-success' : 'bg-label-secondary') + '">' +
        (hecho ? '✔ ' : '') + ETIQUETA_TIPO[t] + '</span>';
    }).join('') + '</div>';
  }

  function faltaTipo() {
    return ['creacion', 'modificacion'].filter(function (t) { return !hechas.has(t); });
  }

  if (enAsistente && window.jQuery) {
    // Después del manejador propio del formulario: si este canceló el envío
    // (falta la firma), no cuenta.
    window.jQuery(document).ready(function () {
      window.jQuery('#formExportarContrato').on('submit', function (e) {
        if (e.isDefaultPrevented()) return;
        hechas.add(tipoElegido());
        generado = true;
      });
    });
  }

  function pasoTipo() {
    return {
      selector: '#bloqueTipoDocumento', interactivo: true,
      titulo: '¿Qué documento?',
      texto: function () {
        const falta = faltaTipo();
        return '<strong>Contrato de Trabajo (Creación)</strong> es el contrato inicial; <strong>Modificación</strong>, un cambio en un contrato que ya existe. ' +
          'Para el logro necesitas generar los dos.' + estadoTipos() +
          (falta.length === 2 ? 'Elige uno para empezar.'
            : falta.length ? 'Te falta: <strong>' + ETIQUETA_TIPO[falta[0]] + '</strong>.'
              : 'Ya tienes los dos: genera el que necesites.');
      },
    };
  }

  function pasoMotivo() {
    return {
      selector: '#id_observaciones', interactivo: true, avanceManual: true,
      saltarSi: function () { return tipoElegido() !== 'modificacion'; },
      titulo: 'Motivo del cambio',
      texto: 'En una Modificación es <strong>obligatorio</strong> explicar qué cambia y por qué: sale en el documento.',
      textoEspera: 'Escribe el motivo para continuar.',
      esperar: function () {
        const campo = document.getElementById('id_observaciones');
        return campo && campo.value.trim() ? 'si' : '';
      },
    };
  }

  function pasosGenerar() {
    return [
      {
        selector: '#btnGenerarContrato', interactivo: true,
        alEntrar: function () { generado = false; },
        titulo: 'Generar',
        texto: 'Pulsa <strong>"Generar Contrato"</strong>: Orbith rellena la plantilla oficial y se descarga el Word. ' +
          'Lo que cambies en esta pantalla solo va al documento: los datos de Orbith no se tocan.',
        textoEspera: 'Pulsa "Generar Contrato".',
        esperar: function () { return generado ? 'si' : ''; },
      },
      {
        selector: '#bloqueTipoDocumento',
        titulo: 'Documento generado',
        texto: function () {
          const falta = faltaTipo();
          return estadoTipos() + (falta.length
            ? 'Te falta la <strong>' + ETIQUETA_TIPO[falta[0]] + '</strong>: elígela arriba y vuelve a pulsar "Generar Contrato".'
            : '¡Logro conseguido! Generaste el Contrato de Trabajo y la Modificación. Los encontrarás en tus <strong>descargas</strong>.');
        },
      },
    ];
  }

  function pasosAsistenteRapido() {
    return [
      pasoTipo(),
      {
        selector: '#bloqueParametros', interactivo: true, avanceManual: true,
        titulo: 'Parámetros del documento',
        texto: 'Casi todo viene precargado. Solo es obligatoria la <strong>Firma</strong>: el cuadro directivo que firma como empleador.',
        textoEspera: 'Elige quién firma para continuar.',
        esperar: function () { return (window.jQuery && window.jQuery('#id_firma_cuadro').val()) ? 'si' : ''; },
        acciones: [{ texto: 'Ver campo a campo', icono: 'bx-list-ol', ejecutar: function () { iniciarAsistente(true); } }],
      },
      pasoMotivo(),
    ].concat(pasosGenerar());
  }

  function pasosAsistenteDetalle() {
    return [
      pasoTipo(),
      {
        selector: '#id_firma_cuadro', interactivo: true, avanceManual: true,
        titulo: 'Firma (obligatoria)',
        texto: 'El <strong>cuadro directivo activo</strong> que firma el contrato en nombre de la empresa. Escribe para buscarlo.',
        textoEspera: 'Elige quién firma para continuar.',
        esperar: function () { return (window.jQuery && window.jQuery('#id_firma_cuadro').val()) ? 'si' : ''; },
      },
      {
        selector: '#id_resolucion_salario_escala', interactivo: true, opcional: true,
        titulo: 'Resolución Salarial',
        texto: 'La resolución que aprueba la escala salarial aplicada, por ejemplo "Res. 12/2023".',
      },
      {
        selector: '#id_fecha_efectiva', interactivo: true, opcional: true,
        titulo: 'Fecha Efectiva de Firma',
        texto: 'Viene con la <strong>fecha de alta</strong> del contrato. Cámbiala si se firma otro día.',
      },
      {
        selector: '#id_provincia_entidad, #id_municipio_entidad', interactivo: true, opcional: true,
        titulo: 'Provincia y Municipio',
        texto: 'Dónde está la entidad. El municipio viene con el de la unidad del trabajador.',
      },
      {
        selector: '#id_sistema_pago, #id_periodo_pago', interactivo: true, opcional: true,
        titulo: 'Sistema y Período de Pago',
        texto: 'El <strong>sistema de pago</strong> del trabajador (por ejemplo, "Pago por Resultado") y si cobra <strong>quincenal</strong> o <strong>mensual</strong> (viene de Parámetros Generales).',
      },
      {
        selector: '#id_jornada_texto, #id_horario_texto, #id_nocturnidad_texto', interactivo: true, opcional: true,
        titulo: 'Jornada, horario y nocturnidad',
        texto: 'Los días de trabajo (por ejemplo, "Lunes a Viernes"), el horario y, si lo tiene, el horario nocturno, que viene del contrato.',
      },
      pasoMotivo(),
      {
        selector: '#bloqueDatosOrbith',
        titulo: 'Datos Base de Orbith',
        texto: 'Cargo, unidad, resolución, duración, motivo, tipo de contrato… salen del contrato y <strong>no se editan aquí</strong>. ' +
          'Si alguno está mal, corrígelo en el contrato antes de generar el documento.',
      },
    ].concat(pasosGenerar());
  }

  function iniciarAsistente(detalle) {
    hechas.clear();
    fetch('/progreso/tarea/exportar_contrato_modificacion/partes/', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }, cache: 'no-store',
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (datos) {
        (datos.partes || []).forEach(function (p) { if (p.hecha) hechas.add(p.clave); });
      })
      .catch(function () {})
      .then(function () { iniciar(detalle ? pasosAsistenteDetalle() : pasosAsistenteRapido()); });
  }

  // ------------------------------------------------------------------
  // Registro
  // ------------------------------------------------------------------
  window.OrbithRecorridos = window.OrbithRecorridos || {};
  const sufijo = enContratos ? 'contratos' : enGestor ? 'gestor' : '';

  if (sufijo && document.getElementById('btn-pdf')) {
    window.OrbithRecorridos['exportar_contrato_modificacion:' + sufijo] = function () { iniciar(pasosHastaAsistente()); };
  }
  // El histórico (#modalHistorico) se incluye más abajo en las dos páginas que
  // este script, así que aquí todavía no existe: no se comprueba.
  if (sufijo) {
    window.OrbithRecorridos['exportar_movimiento_nomina:' + sufijo] = function () { iniciar(pasosMovimiento()); };
    window.OrbithRecorridos['exportar_historico_trabajador:' + sufijo] = function () { iniciar(pasosHistorico()); };
  }
  if (enContratos && document.getElementById('btnExportarExcel')) {
    window.OrbithRecorridos['exportar_lista_contratos:contratos'] = function () { iniciar(pasosListaExcel()); };
  }
  if (enAsistente) {
    window.OrbithRecorridos['exportar_contrato_modificacion:asistente'] = function () { iniciarAsistente(false); };
    window.OrbithRecorridos['exportar_contrato_modificacion:asistente_detalle'] = function () { iniciarAsistente(true); };
    // Viene de "Exportar Contrato" con la guía en marcha (misma pestaña u otra).
    document.addEventListener('DOMContentLoaded', function () {
      const clave = tomarPendiente();
      if (clave && window.OrbithRecorridos[clave]) window.OrbithRecorridos[clave]();
    });
  }
})();
