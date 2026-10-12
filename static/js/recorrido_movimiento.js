/**
 * Recorridos visuales del movimiento de nómina (tarea `primer_movimiento_interno`).
 *
 * Un movimiento tiene dos fases en dos pantallas:
 *
 *   Fase 1 — pedirlo: elegir al trabajador y pulsar "Enviar a Mov. Nómina".
 *            Se puede hacer desde la lista de Contratos o desde la columna de
 *            Contratos del Gestor de Plantilla.
 *   Fase 2 — ejecutarlo: en la pantalla Mov. Nómina, elegir al trabajador en
 *            "Solicitudes Pendientes", "Confirmar Movimiento", rellenar la
 *            Nueva Propuesta y confirmar.
 *
 * El recorrido de la fase 1 termina con el botón "Continuar en Mov. Nómina",
 * que abre esa pantalla y sigue allí con la fase 2 señalando al MISMO
 * trabajador (`OrbithRecorrido.continuarEn`, ver orbith_recorrido.js).
 *
 * Las fases se construyen con funciones (`fase1Contratos`, `fase1Gestor`,
 * `fase2`) y se reutilizan en las tareas del Moderador "Cede tu contrato"
 * (`primer_movimiento_cedido`: solo fase 1, sin ir a Mov. Nómina, porque la
 * fase 2 la hace el otro moderador) y "Recibe tu contrato"
 * (`primer_movimiento_recibido`: solo fase 2).
 *
 * Igual que el resto de recorridos, nunca escribe ni guarda nada: señala,
 * explica y espera a que el usuario lo haga.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const MOV = '#movimientoForm ';
  const ESPERA_CAMPOS = 'Completa los campos obligatorios para continuar.';
  const URL_MOV_NOMINA = '/contrato/movimientos/nomina/';
  const CLAVE_FASE2 = 'primer_movimiento_interno:fase2';

  // `document.querySelector('')` lanza un error. Los selectores de "la fila
  // del trabajador elegido" están vacíos mientras no se ha elegido ninguno
  // (o al entrar en Mov. Nómina sin venir de la fase 1), así que se pasa
  // siempre por aquí.
  function buscar(selector) {
    return selector ? document.querySelector(selector) : null;
  }

  function listos(nombres) {
    const form = document.querySelector('#movimientoForm');
    if (!form) return '';
    return nombres.every(function (nombre) {
      const el = form.querySelector('[name="' + nombre + '"]');
      if (!el || el.disabled) return true;
      return String(el.value || '').trim() && !el.classList.contains('is-invalid');
    }) ? 'si' : '';
  }

  function continuarAFase2(contratoId) {
    return {
      texto: 'Continuar en Mov. Nómina',
      ejecutar: function () {
        window.OrbithRecorrido.continuarEn(URL_MOV_NOMINA, CLAVE_FASE2, { contrato: contratoId });
      },
    };
  }

  // Texto del último paso de la fase 1. Tres casos: el usuario acaba de
  // pedirlo, ya estaba pedido de antes (y el paso de enviar se saltó), o
  // todavía no lo ha pedido (se saltó el paso a mano).
  function textoMovimientoPedido(pedido, yaEstaba) {
    if (!pedido) {
      return 'Este contrato <strong>todavía no está</strong> en Mov. Nómina. Vuelve con "Anterior" y pulsa "Enviar a Mov. Nómina".';
    }
    const inicio = yaEstaba
      ? 'Este contrato <strong>ya estaba</strong> en Mov. Nómina, así que no hacía falta volver a pedirlo (si pulsaras ahora "Enviar a Mov. Nómina", lo cancelarías). '
      : 'Listo: el contrato queda marcado <strong>en proceso</strong> de movimiento. ';
    return inicio + 'Ahora se termina en la pantalla <strong>Mov. Nómina</strong>. Pulsa <strong>"Continuar en Mov. Nómina"</strong> y te acompaño allí.';
  }

  // Texto del último paso cuando se CEDE el contrato a otro moderador: la
  // fase 2 la hace él desde su sesión, así que no se lleva a Mov. Nómina.
  function textoCedido(pedido, yaEstaba) {
    if (!pedido) {
      return 'Este contrato <strong>todavía no está</strong> en Mov. Nómina. Vuelve con "Anterior" y pulsa "Enviar a Mov. Nómina".';
    }
    const inicio = yaEstaba
      ? 'Este contrato <strong>ya estaba</strong> en Mov. Nómina, así que no hacía falta volver a pedirlo. '
      : 'Listo: el contrato queda marcado <strong>en proceso</strong> de movimiento. ';
    return inicio + 'El moderador de la unidad que lo recibe lo verá en su bandeja de <strong>Mov. Nómina</strong> y lo completará desde su propia sesión. ' +
      'Si te equivocaste, vuelve a seleccionar al trabajador y pulsa el mismo botón, que ahora es una <strong>X roja</strong> ("Cancelar Movimiento").';
  }

  // Último paso de la fase 1. `ceder` = true para "Cede tu contrato": termina
  // explicando; si no, ofrece "Continuar en Mov. Nómina".
  function pasoFinalFase1(selector, obtenerId, yaPedido, yaEstaba, ceder) {
    const paso = {
      selector: selector,
      titulo: ceder ? 'Contrato cedido' : 'Movimiento pedido',
      texto: function () {
        return ceder ? textoCedido(yaPedido(), yaEstaba()) : textoMovimientoPedido(yaPedido(), yaEstaba());
      },
    };
    if (!ceder) paso.accionSiguiente = continuarAFase2Dinamico(obtenerId);
    return paso;
  }

  // ------------------------------------------------------------------
  // Fase 1 desde la lista de Contratos
  // ------------------------------------------------------------------
  function fase1Contratos(opciones) {
    const ceder = !!(opciones && opciones.ceder);
    let elegido = '';
    let yaEstaba = false;
    const fila = function () {
      return elegido ? '#filter_contratos_results .fila-contrato[data-id="' + elegido + '"]' : '';
    };
    const yaPedido = function () {
      const el = buscar(fila());
      return !!el && el.dataset.enProceso === 'true';
    };
    return [
      {
        id: 'entrada', selector: '#filter_contratos_results', interactivo: true,
        titulo: 'Elige al trabajador',
        texto: ceder
          ? 'Haz clic en la fila del trabajador que pasa a la unidad de otro moderador: se resalta y se encienden los botones de arriba. Si no lo ves, búscalo: el buscador admite prefijos, por ejemplo <code>E:8855</code> o <code>N:Juan</code>.'
          : 'Haz clic en la fila del trabajador que va a cambiar de cargo, unidad o salario: se resalta y se encienden los botones de arriba. Si no lo ves, búscalo: el buscador admite prefijos, por ejemplo <code>E:8855</code> o <code>N:Juan</code>.',
        esperar: function () {
          const el = document.querySelector('#filter_contratos_results .fila-contrato.table-active-row');
          if (el && el.dataset.id !== elegido) {
            elegido = el.dataset.id;
            yaEstaba = el.dataset.enProceso === 'true';
          }
          return el ? el.dataset.id : '';
        },
      },
      {
        selector: '#btn-movimiento', interactivo: true, volver: { a: 'entrada', texto: 'Elegir otro trabajador' },
        saltarSi: yaPedido,
        titulo: 'Enviar a Mov. Nómina',
        texto: 'Pulsa el botón amarillo <strong>"Enviar a Mov. Nómina"</strong> (el de sincronizar) y confirma con <strong>"Sí, permitir"</strong>. ' +
               'El contrato queda marcado "en proceso" y pasa a la bandeja de Mov. Nómina.',
        esperar: function () { return yaPedido() ? 'pedido' : ''; },
      },
      pasoFinalFase1(function () { return fila(); }, function () { return elegido; },
                     yaPedido, function () { return yaEstaba; }, ceder),
    ];
  }

  // `accionSiguiente` que lee el contrato elegido en el momento de pulsar.
  function continuarAFase2Dinamico(obtenerId) {
    return {
      texto: 'Continuar en Mov. Nómina',
      ejecutar: function () { continuarAFase2(obtenerId()).ejecutar(); },
    };
  }

  // ------------------------------------------------------------------
  // Fase 1 desde el Gestor de Plantilla
  // ------------------------------------------------------------------
  function fase1Gestor(opciones) {
    const ceder = !!(opciones && opciones.ceder);
    let elegido = '';
    let yaEstaba = false;
    const tarjeta = function () {
      return elegido ? '#col-contratos .list-group-item[data-pk="' + elegido + '"]' : '';
    };
    const yaPedido = function () {
      const el = buscar(tarjeta());
      return !!el && el.dataset.enMovimiento === 'true';
    };
    // Si ya hay un cargo elegido, no se repite unidad → departamento → cargo.
    const hayCargo = function () { return !!document.querySelector('#col-cargos .active-cargo'); };
    const seleccion = (window.OrbithPasosSeleccionGestor ? window.OrbithPasosSeleccionGestor() : [])
      .map(function (paso) { paso.saltarSi = hayCargo; return paso; });

    return seleccion.concat([
      {
        id: 'entrada', selector: '#col-contratos', interactivo: true,
        volver: { a: 'cargo', texto: '¿Plaza vacante? Elegir otro cargo' },
        titulo: 'Elige al trabajador',
        texto: ceder
          ? 'En la columna <strong>4. Contratos</strong>, haz clic en la persona que pasa a la unidad de otro moderador.'
          : 'En la columna <strong>4. Contratos</strong>, haz clic en la persona que va a cambiar de cargo, unidad o salario.',
        esperar: function () {
          const el = document.querySelector('#col-contratos .active-contrato');
          if (el && el.dataset.pk !== elegido) {
            elegido = el.dataset.pk;
            yaEstaba = el.dataset.enMovimiento === 'true';
          }
          return el ? el.dataset.pk : '';
        },
      },
      {
        selector: '#btn-movimiento', interactivo: true, volver: { a: 'entrada', texto: 'Elegir otro trabajador' },
        saltarSi: yaPedido,
        titulo: 'Enviar a Mov. Nómina',
        texto: 'Pulsa el botón amarillo <strong>"Enviar a Mov. Nómina"</strong> (el de sincronizar) y confirma con <strong>"Sí, permitir"</strong>. ' +
               'El contrato queda marcado "en proceso" y pasa a la bandeja de Mov. Nómina.',
        esperar: function () { return yaPedido() ? 'pedido' : ''; },
      },
      pasoFinalFase1(function () { return tarjeta(); }, function () { return elegido; },
                     yaPedido, function () { return yaEstaba; }, ceder),
    ]);
  }

  // ------------------------------------------------------------------
  // Fase 2 en Mov. Nómina
  // ------------------------------------------------------------------
  function fase2(contratoId, opciones) {
    const recibir = !!(opciones && opciones.recibir);
    const filaDelContrato = function () {
      return contratoId ? '.fila-movimiento[data-pk="' + contratoId + '"]' : '';
    };
    const VOLVER = { a: 'entrada2' };
    return [
      {
        id: 'entrada2', interactivo: true,
        // Si se viene de la fase 1, se señala la fila de ESE trabajador; si
        // no (o si ya no está en la bandeja), toda la tabla.
        selector: function () {
          return buscar(filaDelContrato()) ? filaDelContrato() : '#tablaMovimientosPendientes';
        },
        titulo: 'Solicitudes Pendientes',
        texto: function () {
          const el = buscar(filaDelContrato());
          if (el) return 'Aquí está el trabajador que acabas de enviar. Haz clic en su fila para seleccionarla.';
          if (recibir) {
            return 'Aquí ves los contratos que cualquier moderador ha enviado a Mov. Nómina, de toda la empresa. Busca al trabajador que esperas recibir y haz clic en su fila. Con doble clic ves su histórico.';
          }
          return 'Estos son los contratos enviados a Mov. Nómina. Haz clic en la fila del trabajador cuyo movimiento vas a hacer. Con doble clic ves su histórico.';
        },
        esperar: function () {
          const el = document.querySelector('.fila-movimiento.table-active-row');
          return el ? (el.dataset.pk || 'si') : '';
        },
      },
      {
        selector: '#btn-confirmar-mov', interactivo: true, volver: { a: 'entrada2', texto: 'Elegir otro trabajador' },
        paciencia: 8000,
        titulo: 'Confirmar Movimiento',
        texto: 'Pulsa <strong>"Confirmar Movimiento"</strong>: se abre la ventana del movimiento.',
        esperar: function () {
          return document.querySelector('#modalMovimientoContrato.show #movimientoForm') ? 'abierto' : '';
        },
      },
      {
        selector: '#movColumnaActual, #movColumnaNueva', volver: VOLVER,
        titulo: 'Situación Actual y Nueva Propuesta',
        texto: 'A la izquierda, la <strong>Situación Actual</strong> del trabajador, tal como está hoy. A la derecha, la <strong>Nueva Propuesta</strong>: aquí escribes cómo queda después del movimiento.',
      },
      {
        selector: [MOV + '[name="unidad"]', MOV + '[name="departamento"]', MOV + '[name="cargo"]', '#mov_rol', '#mov_grupo', '#mov_cat'].join(', '),
        interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Nueva ubicación',
        texto: recibir
          ? 'Elige tu <strong>Unidad Organizativa</strong>, el <strong>Departamento</strong> y el <strong>Cargo</strong> de destino: el desplegable de Unidad solo te muestra las tuyas. ' +
            'El rol, el grupo escala y la categoría ocupacional salen del cargo.'
          : 'Elige la <strong>Unidad Organizativa</strong>, el <strong>Departamento</strong> y el <strong>Cargo</strong> de destino: cada uno filtra al siguiente. ' +
            'Si solo cambias el cargo o el salario, puedes repetir la misma unidad. El rol, el grupo escala y la categoría ocupacional salen del cargo.',
        esperar: function () { return listos(['unidad', 'departamento', 'cargo']); },
      },
      {
        selector: [MOV + '[name="tipo"]', MOV + '[name="motivo"]', MOV + '[name="duracion"]', MOV + '[name="tipo_salario"]', MOV + '[name="tridente"]'].join(', '),
        interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Condiciones',
        texto: 'Revisa el <strong>Tipo de Contrato</strong> (si lo exige, se enciende el <strong>Motivo</strong>, y si es indeterminado la <strong>Duración</strong> se apaga) y el <strong>Tipo de Salario</strong>. ' +
               'El <strong>Tridente</strong> solo se pide con salario Dinámico y si el cargo no es de cuadro.',
        esperar: function () { return listos(['tipo', 'motivo', 'duracion', 'tipo_salario', 'tridente']); },
      },
      {
        selector: MOV + '[name="fecha_efectiva"], ' + MOV + '[name="fecha_solicitud"]',
        interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER,
        titulo: 'Fechas',
        texto: 'Pon la <strong>Fecha Efectiva</strong> (desde cuándo rige el cambio; no puede ser anterior a la fecha de alta del contrato) y la <strong>Fecha de Solicitud</strong>. Las dos son obligatorias.',
        esperar: function () { return listos(['fecha_efectiva', 'fecha_solicitud']); },
      },
      {
        selector: MOV + '[name="observaciones"], #movNuevoSalario',
        interactivo: true, volver: VOLVER,
        titulo: 'Observaciones y Nuevo Salario',
        texto: 'Las <strong>Observaciones</strong> son opcionales. El <strong>Nuevo Salario</strong> se calcula solo con el cargo, el rol y el tridente; si sale en cero, el movimiento no se puede confirmar hasta revisar esos datos.',
      },
      {
        selector: MOV + 'button[type="submit"]',
        interactivo: true, terminarSiDesaparece: true,
        titulo: 'Confirmar Movimiento',
        texto: function () {
          return 'Pulsa <strong>"Confirmar Movimiento"</strong> y acepta con <strong>"Sí, aplicar"</strong>: se guarda el cambio y su histórico, y Orbith te ofrece exportar el documento en Word: si pulsas <strong>"Exportar"</strong>, también consigues "Exporta un movimiento de nómina". ' +
            (recibir ? 'El trabajador queda incorporado a tu unidad. ' : '') + '¡Y consigues el logro!';
        },
      },
    ];
  }

  function iniciar(pasos) {
    window.OrbithRecorrido.iniciar({ pasos: pasos });
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};

  // Fase 1 → fase 2, desde la lista de Contratos.
  if (document.getElementById('filter_contratos_results') && document.getElementById('btn-movimiento')) {
    window.OrbithRecorridos['primer_movimiento_interno:contratos'] = function () { iniciar(fase1Contratos()); };
  }

  // Fase 1 → fase 2, desde el Gestor de Plantilla.
  if (document.getElementById('col-panel-contrato') && document.getElementById('btn-movimiento')) {
    window.OrbithRecorridos['primer_movimiento_interno:gestor'] = function () { iniciar(fase1Gestor()); };
  }

  // Fase 2 en Mov. Nómina: viniendo de la fase 1 (con el contrato elegido) o
  // desde el menú "¿Cómo funciona?" de la propia pantalla.
  if (document.getElementById('tablaMovimientosPendientes')) {
    window.OrbithRecorridos[CLAVE_FASE2] = function () {
      iniciar(fase2(window.OrbithRecorrido.datosContinuacion().contrato));
    };
    window.OrbithRecorridos['primer_movimiento_interno:movnomina'] = function () { iniciar(fase2(null)); };
  }

  // --- Tareas del Moderador ---
  // "Cede tu contrato": solo la fase 1, terminando con la explicación.
  if (document.getElementById('filter_contratos_results') && document.getElementById('btn-movimiento')) {
    window.OrbithRecorridos['primer_movimiento_cedido:contratos'] = function () { iniciar(fase1Contratos({ ceder: true })); };
  }
  if (document.getElementById('col-panel-contrato') && document.getElementById('btn-movimiento')) {
    window.OrbithRecorridos['primer_movimiento_cedido:gestor'] = function () { iniciar(fase1Gestor({ ceder: true })); };
  }
  // "Recibe tu contrato": solo la fase 2, con los textos de quien recibe.
  if (document.getElementById('tablaMovimientosPendientes')) {
    window.OrbithRecorridos['primer_movimiento_recibido:movnomina'] = function () { iniciar(fase2(null, { recibir: true })); };
  }
})();
