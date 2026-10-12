/**
 * Recorridos de Recordatorios (Notificaciones → pestaña "Recordatorios").
 *
 * - "Completa tu primer recordatorio" (`primer_recordatorio_completado`, del
 *   Moderador): subpestaña Sistema (automáticos) → Administración → "Marcar
 *   completado".
 * - "Crea tu primer recordatorio" (`primer_recordatorio_creado`, del
 *   Administrador): Administración → "Nuevo recordatorio" → los cuatro campos
 *   → "Crear recordatorio".
 *
 * Las subpestañas son navegaciones reales y las dos acciones recargan la
 * página, así que cada recorrido va por tramos que siguen solos después de la
 * recarga (`OrbithRecorrido.continuarEn` / `orbithIniciarGuia`):
 *   <codigo>:notificaciones  desde cualquier pestaña: lleva a la que toca.
 *   <codigo>:sistema / :administracion  el tramo de esa subpestaña.
 *   <codigo>:hecho  el final, después de completar o de crear.
 *
 * Lo carga templates/pages/notificaciones/lista.html.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const COMPLETAR = 'primer_recordatorio_completado';
  const CREAR = 'primer_recordatorio_creado';

  const parametros = new URLSearchParams(window.location.search);
  const tab = parametros.get('tab') || '';
  const sub = parametros.get('sub') || '';

  function urlSub(subpestana) {
    return window.location.pathname + '?tab=recordatorios&sub=' + subpestana;
  }

  function iniciar(pasos) {
    window.OrbithRecorrido.iniciar({ pasos: pasos });
  }

  // Paso que lleva a una subpestaña (recarga la página y sigue allí).
  function pasoIr(selector, titulo, texto, subpestana, siguienteClave) {
    return {
      selector: selector,
      titulo: titulo,
      texto: texto,
      accionSiguiente: {
        texto: subpestana === 'sistema' ? 'Abrir Recordatorios' : 'Ir a Administración',
        ejecutar: function () { window.OrbithRecorrido.continuarEn(urlSub(subpestana), siguienteClave); },
      },
    };
  }

  const PESTANA = 'a.nav-link[href="?tab=recordatorios"]';
  const SUB_SISTEMA = 'a.nav-link[href="?tab=recordatorios&sub=sistema"]';
  const SUB_ADMIN = 'a.nav-link[href="?tab=recordatorios&sub=administracion"]';

  // Al pulsar el botón que recarga la página, deja pedido el tramo final.
  let pedirFinal = '';
  document.addEventListener('click', function (e) {
    if (pedirFinal && e.target.closest && e.target.closest('.btn-completar-recordatorio') && window.orbithIniciarGuia) {
      window.orbithIniciarGuia(pedirFinal);
    }
  }, true);
  document.addEventListener('submit', function (e) {
    if (pedirFinal && e.target.closest && e.target.closest('#modalNuevoRecordatorio') && window.orbithIniciarGuia) {
      window.orbithIniciarGuia(pedirFinal);
    }
  }, true);

  // ------------------------------------------------------------------
  // Completar (Moderador)
  // ------------------------------------------------------------------
  function completarEntrada() {
    return [pasoIr(PESTANA, 'Recordatorios',
      'Los recordatorios avisan de algo que hay que hacer en tu unidad antes de una fecha. Viven en la pestaña <strong>"Recordatorios"</strong>.',
      'sistema', COMPLETAR + ':sistema')];
  }

  function completarSistema() {
    return [
      {
        selector: SUB_SISTEMA + ', ' + SUB_ADMIN,
        titulo: 'Dos tipos de recordatorio',
        texto: '<strong>Sistema</strong>: los crea Orbith solo (un contrato que vence, un dato que falta…) y se resuelven solos cuando se arregla lo que avisan. ' +
          '<strong>Administración</strong>: los crea un Administrador para tu unidad, y eres tú quien los marca como hechos.',
      },
      {
        selector: '#chips-prioridad-recordatorios',
        titulo: 'Prioridad',
        texto: 'Filtra por lo urgente: 🔴 vencido o para hoy, 🟡 próximo, 🟠 cercano y 🟢 lejano, según su fecha objetivo.',
      },
      {
        selector: '#resultados-recordatorios',
        titulo: 'La lista',
        texto: 'Cada recordatorio dice qué hay que hacer, para cuándo y de qué unidad es. El botón de la columna <strong>Registro</strong> te lleva directo a lo que hay que corregir.',
      },
      pasoIr(SUB_ADMIN, 'Administración',
        'Ahora, los que te envía un Administrador.', 'administracion', COMPLETAR + ':administracion'),
    ];
  }

  function completarAdministracion() {
    const hay = !!document.querySelector('#resultados-recordatorios .btn-completar-recordatorio');
    if (!hay) {
      return [{
        selector: '#resultados-recordatorios',
        titulo: 'Sin recordatorios pendientes',
        texto: 'Aún no tienes recordatorios de un Administrador. Cuando te cree uno para tu unidad, te llegará aviso en la <strong>campana</strong> de notificaciones y aparecerá aquí, con su botón <strong>"Marcar completado"</strong>.',
      }];
    }
    return [{
      selector: '#resultados-recordatorios', interactivo: true,
      alEntrar: function () { pedirFinal = COMPLETAR + ':hecho'; },
      alSalir: function () { pedirFinal = ''; },
      titulo: 'Marcar completado',
      texto: 'Lee el título, el mensaje y la fecha objetivo. Cuando hayas hecho lo que pide, pulsa <strong>"Marcar completado"</strong> en su fila.',
      textoEspera: 'Pulsa "Marcar completado" en un recordatorio.',
      esperar: function () { return ''; },
    }];
  }

  function completarHecho() {
    return [{
      selector: '#resultados-recordatorios',
      titulo: '¡Logro conseguido!',
      texto: 'El recordatorio deja de estar pendiente para todos los que lo recibieron, y el Administrador lo ve como completado.',
    }];
  }

  // ------------------------------------------------------------------
  // Crear (Administrador)
  // ------------------------------------------------------------------
  function crearEntrada() {
    return [pasoIr(PESTANA, 'Recordatorios',
      'Con un recordatorio pides a los responsables de una unidad que hagan algo antes de una fecha. Se crean en <strong>"Recordatorios" → "Administración"</strong>.',
      'administracion', CREAR + ':administracion')];
  }

  function relleno(ids) {
    return function () {
      return ids.every(function (id) {
        const el = document.getElementById(id);
        return el && String(el.value).trim();
      }) ? 'si' : '';
    };
  }

  function crearAdministracion() {
    return [
      {
        id: 'nuevo',
        selector: '[data-bs-target="#modalNuevoRecordatorio"]', interactivo: true,
        titulo: 'Nuevo recordatorio',
        texto: 'Pulsa <strong>"Nuevo recordatorio"</strong>.',
        esperar: function () { return document.querySelector('#modalNuevoRecordatorio.show') ? 'abierto' : ''; },
      },
      {
        selector: '#id_rec_titulo, #id_rec_mensaje', interactivo: true, avanceManual: true,
        volver: { a: 'nuevo' },
        titulo: 'Título y mensaje',
        texto: 'Un <strong>título</strong> corto y un <strong>mensaje</strong> que diga exactamente qué hay que hacer. Los dos son obligatorios.',
        textoEspera: 'Escribe el título y el mensaje para continuar.',
        esperar: relleno(['id_rec_titulo', 'id_rec_mensaje']),
      },
      {
        selector: '#id_rec_fecha, #id_rec_unidad', interactivo: true, avanceManual: true,
        volver: { a: 'nuevo' },
        titulo: 'Fecha y unidad',
        texto: 'La <strong>fecha objetivo</strong> marca su prioridad (vencido, próximo, cercano o lejano). La <strong>unidad</strong> decide quién lo recibe: sus moderadores.',
        textoEspera: 'Elige la fecha y la unidad para continuar.',
        esperar: relleno(['id_rec_fecha', 'id_rec_unidad']),
      },
      {
        selector: '#btnCrearRecordatorio', interactivo: true,
        volver: { a: 'nuevo' }, terminarSiDesaparece: true, paciencia: 2000,
        alEntrar: function () { pedirFinal = CREAR + ':hecho'; },
        alSalir: function () { pedirFinal = ''; },
        titulo: 'Crear recordatorio',
        texto: 'Pulsa <strong>"Crear recordatorio"</strong>. ¡Y consigues el logro!',
      },
    ];
  }

  function crearHecho() {
    return [{
      selector: '#resultados-recordatorios',
      titulo: '¡Logro conseguido!',
      texto: 'Lo reciben los moderadores de esa unidad y los administradores, con aviso en la campana. ' +
        'Cuando alguno lo marque como completado, deja de estar pendiente. Si la unidad no tiene a nadie asignado, Orbith te lo avisa arriba.',
    }];
  }

  // ------------------------------------------------------------------
  // Registro: cada clave arranca en el tramo que corresponde a la página.
  // ------------------------------------------------------------------
  const enSistema = tab === 'recordatorios' && sub !== 'administracion';
  const enAdministracion = tab === 'recordatorios' && sub === 'administracion';

  window.OrbithRecorridos = window.OrbithRecorridos || {};
  window.OrbithRecorridos[COMPLETAR + ':notificaciones'] = function () {
    iniciar(enSistema ? completarSistema() : enAdministracion ? completarAdministracion() : completarEntrada());
  };
  window.OrbithRecorridos[COMPLETAR + ':sistema'] = function () {
    iniciar(enSistema ? completarSistema() : completarEntrada());
  };
  window.OrbithRecorridos[COMPLETAR + ':administracion'] = function () {
    iniciar(enAdministracion ? completarAdministracion() : completarEntrada());
  };
  window.OrbithRecorridos[COMPLETAR + ':hecho'] = function () { iniciar(completarHecho()); };

  window.OrbithRecorridos[CREAR + ':notificaciones'] = function () {
    iniciar(enAdministracion ? crearAdministracion() : crearEntrada());
  };
  window.OrbithRecorridos[CREAR + ':administracion'] = function () {
    iniciar(enAdministracion ? crearAdministracion() : crearEntrada());
  };
  window.OrbithRecorridos[CREAR + ':hecho'] = function () { iniciar(crearHecho()); };
})();
