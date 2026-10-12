/**
 * Recorridos de Solicitudes: las dos mitades del mismo proceso.
 *
 * - "Envía tu primera solicitud de cambio" (`primera_solicitud_enviada`, del
 *   Moderador): en el Gestor, editar un cargo → el formulario se convierte en
 *   solicitud → "Motivo de la solicitud" → "Enviar Solicitud" (el logro). Al
 *   final ofrece seguir en Solicitudes (`:solicitudes`).
 * - "Decide tu primera solicitud" (`primera_solicitud_decidida`, del
 *   Administrador): Solicitudes → En Espera → "Revisar" (`:revisar`, en la
 *   página de revisión) → comparación → Aprobar, Rechazar o Cancelar → y, tras
 *   la redirección, el final (`:hecho`).
 *
 * Lo cargan el Gestor de Plantilla, la lista de Solicitudes y la página de
 * revisión. Nunca decide por el usuario: señala, explica y espera.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const ENVIAR = 'primera_solicitud_enviada';
  const DECIDIR = 'primera_solicitud_decidida';

  const enGestor = !!document.getElementById('col-panel-cargo');
  const enLista = !!document.getElementById('filter_solicitudes_results');
  const enRevision = !!document.getElementById('form_aprobacion');

  function iniciar(pasos) {
    window.OrbithRecorrido.iniciar({ pasos: pasos });
  }

  function pedir(clave) {
    if (window.orbithIniciarGuia) window.orbithIniciarGuia(clave);
  }

  // ------------------------------------------------------------------
  // Enviar (Moderador, en el Gestor)
  // ------------------------------------------------------------------
  // El formulario del cargo envía por HTMX; una solicitud creada responde 204.
  let enviada = false;
  document.body.addEventListener('htmx:afterRequest', function (e) {
    const origen = e.detail.elt;
    if (origen && origen.id === 'cargoForm' && e.detail.xhr && e.detail.xhr.status === 204) enviada = true;
  });

  function pasosEnviar() {
    const hayCargo = function () { return !!document.querySelector('#col-cargos .active-cargo'); };
    const seleccion = (window.OrbithPasosSeleccionGestor ? window.OrbithPasosSeleccionGestor() : [])
      .map(function (paso) { paso.saltarSi = hayCargo; return paso; });
    return seleccion.concat([
      {
        id: 'editar',
        selector: '#btn-edit-cargo', interactivo: true,
        titulo: 'Editar el cargo',
        texto: 'Pulsa el lápiz, <strong>"Editar"</strong>, en la barra de la columna de Cargos.',
        esperar: function () { return document.querySelector('#modal_generic.show #cargoForm') ? 'abierto' : ''; },
      },
      {
        selector: '#cargoForm .alert-info', volver: { a: 'editar' },
        titulo: 'Se convierte en solicitud',
        texto: 'Como Moderador, tus cambios en la plantilla <strong>no se guardan directamente</strong>: se envían a un Administrador para que los apruebe. ' +
          'Hasta entonces, el cargo sigue como está.',
      },
      {
        selector: '#cargoForm', interactivo: true, volver: { a: 'editar' },
        titulo: 'Cambia lo que necesites',
        texto: 'Modifica los datos que quieres cambiar, por ejemplo la cantidad de plazas aprobadas.',
      },
      {
        selector: '#id_motivo_solicitud', interactivo: true, opcional: true, volver: { a: 'editar' },
        titulo: 'Motivo de la solicitud',
        texto: 'Explica <strong>por qué</strong> pides el cambio: es lo primero que leerá el Administrador para decidir.',
      },
      {
        selector: '#cargoForm [type="submit"]', interactivo: true, paciencia: 3000,
        volver: { a: 'editar' },
        alEntrar: function () { enviada = false; },
        titulo: 'Enviar Solicitud',
        texto: 'Pulsa <strong>"Enviar Solicitud"</strong>. ¡Y consigues el logro!',
        textoEspera: 'Pulsa "Enviar Solicitud".',
        esperar: function () { return enviada ? 'si' : ''; },
      },
      {
        selector: '#btn-edit-cargo',
        titulo: '¡Solicitud enviada!',
        texto: 'Pasa igual al añadir, editar o eliminar departamentos y cargos, al editar una unidad o un contrato y al eliminar un trabajador: ' +
          'el formulario lleva el "Motivo de la solicitud" y el botón "Enviar Solicitud".',
        acciones: [{
          texto: 'Ver mis solicitudes', icono: 'bx-list-check',
          ejecutar: function () { window.OrbithRecorrido.continuarEn('/solicitudes/?tab=espera', ENVIAR + ':solicitudes'); },
        }],
      },
    ]);
  }

  function pasosSeguimiento() {
    return [
      {
        selector: '.nav-pills',
        titulo: 'Tus solicitudes',
        texto: '<strong>En Espera</strong>: aún sin decidir (o un Administrador la está revisando). <strong>Aprobadas</strong>: el cambio ya se aplicó. ' +
          '<strong>Rechazadas</strong>: con el motivo del Administrador.',
      },
      {
        selector: '#filter_solicitudes_results',
        titulo: 'Editar o retirar',
        texto: 'Haz clic en una solicitud En Espera y usa el <strong>lápiz</strong> de la barra para corregirla, o la papelera para retirarla. ' +
          'Cuando un Administrador la decida, te llegará aviso en la <strong>campana</strong>.',
      },
    ];
  }

  // ------------------------------------------------------------------
  // Decidir (Administrador)
  // ------------------------------------------------------------------
  document.addEventListener('click', function (e) {
    if (!e.target.closest) return;
    if (pidiendoRevision && e.target.closest('#btn-revisar')) pedir(DECIDIR + ':revisar');
    // Aprobar pide confirmación (SweetAlert): el final se pide al confirmar, no
    // al pulsar "Aprobar", para que no quede pendiente si se vuelve atrás.
    if (pidiendoFinal && e.target.closest('.swal2-confirm, #form_aprobacion [formaction], #modal_rechazo [type="submit"]')) {
      pedir(DECIDIR + ':hecho');
    }
  }, true);
  let pidiendoRevision = false;
  let pidiendoFinal = false;

  function pestana() {
    return new URLSearchParams(window.location.search).get('tab') || 'espera';
  }

  function pasosDecidirLista() {
    if (pestana() !== 'espera') {
      return [{
        selector: '.nav-pills',
        titulo: 'Solicitudes en espera',
        texto: 'Las que esperan tu decisión están en <strong>"En Espera"</strong>.',
        accionSiguiente: {
          texto: 'Ir a En Espera',
          ejecutar: function () { window.OrbithRecorrido.continuarEn('/solicitudes/?tab=espera', DECIDIR + ':solicitudes'); },
        },
      }];
    }
    const revisables = document.querySelectorAll('#filter_solicitudes_results .fila-solicitud[data-puede-revisar="true"]').length;
    if (!revisables) {
      return [{
        selector: '#filter_solicitudes_results',
        titulo: 'Sin solicitudes pendientes',
        texto: 'Ahora no hay solicitudes esperando tu decisión. Las envían los Moderadores al cambiar la plantilla, una unidad o un contrato; ' +
          'cuando llegue una, te avisará la <strong>campana</strong> de notificaciones.',
      }];
    }
    return [
      {
        selector: '.nav-pills',
        titulo: 'Solicitudes',
        texto: 'Los cambios que piden los Moderadores. En <strong>"En Espera"</strong> están las que tienes que decidir.',
      },
      {
        id: 'fila',
        selector: '#filter_solicitudes_results', interactivo: true,
        titulo: 'Elige una solicitud',
        texto: 'Haz clic en una solicitud para seleccionarla: se encienden los botones de la barra.',
        esperar: function () {
          const f = document.querySelector('#filter_solicitudes_results .fila-solicitud.table-active-row');
          return f && f.dataset.puedeRevisar === 'true' ? (f.dataset.urlRevisar || 'si') : '';
        },
      },
      {
        selector: '#btn-revisar', interactivo: true, volver: { a: 'fila', texto: 'Elegir otra' },
        alEntrar: function () { pidiendoRevision = true; },
        alSalir: function () { pidiendoRevision = false; },
        titulo: 'Revisar',
        texto: 'Pulsa <strong>"Revisar"</strong>. Mientras la revisas, nadie más puede tocarla; si la dejas a medias, se libera sola a los 30 minutos.',
        textoEspera: 'Pulsa "Revisar".',
        esperar: function () { return ''; },
      },
    ];
  }

  function pasosRevision() {
    return [
      {
        selector: '#form_aprobacion',
        titulo: 'Actual frente a propuesto',
        texto: 'A la izquierda, cómo está ahora; a la derecha, lo que propone el Moderador. <strong>Lo que cambia aparece resaltado.</strong> ' +
          'Si hace falta, puedes corregir los valores propuestos antes de aprobar.',
      },
      {
        selector: '#btn_aprobar, #form_aprobacion [formaction], #form_aprobacion [onclick="abrirModalRechazo()"]', interactivo: true,
        alEntrar: function () { pidiendoFinal = true; },
        alSalir: function () { pidiendoFinal = false; },
        titulo: 'Decide',
        texto: '<ul class="mb-1 ps-3">' +
          '<li><strong>Aprobar</strong>: confirma con "Sí, aprobar" y el cambio se aplica en ese momento.</li>' +
          '<li><strong>Rechazar</strong>: escribe el motivo, que le llega al Moderador en su notificación.</li>' +
          '<li><strong>Cancelar revisión</strong>: la deja libre, en espera, sin guardar nada.</li>' +
          '</ul>Aprobar o rechazar te da el logro.',
        textoEspera: 'Aprueba, rechaza o cancela la revisión.',
        esperar: function () { return ''; },
      },
    ];
  }

  // Tras la redirección, el mensaje de Django dice qué pasó. base.html lo deja
  // en `#djangoMessages` (oculto) y lo vacía en DOMContentLoaded para pasarlo a
  // un aviso: se lee AHORA, al cargar este script, que es antes.
  const MENSAJES = (document.getElementById('djangoMessages') || {}).textContent || '';

  function pasosFinal() {
    const texto = MENSAJES;
    if (/Solicitud (aprobada|rechazada):/.test(texto)) {
      return [{
        selector: '#filter_solicitudes_results',
        titulo: '¡Logro conseguido!',
        texto: /Solicitud aprobada:/.test(texto)
          ? 'Aprobada: el cambio ya está aplicado y el Moderador recibe el aviso. La encontrarás en "Aprobadas".'
          : 'Rechazada: el Moderador recibe tu motivo en su notificación. La encontrarás en "Rechazadas".',
      }];
    }
    if (/Revisión cancelada/.test(texto)) {
      return [{
        selector: '#filter_solicitudes_results',
        titulo: 'Revisión cancelada',
        texto: 'La solicitud vuelve a quedar en espera, sin ningún cambio. Cuando la apruebes o la rechaces, conseguirás el logro.',
      }];
    }
    return [];
  }

  // ------------------------------------------------------------------
  // Registro
  // ------------------------------------------------------------------
  window.OrbithRecorridos = window.OrbithRecorridos || {};
  if (enGestor) window.OrbithRecorridos[ENVIAR + ':gestor'] = function () { iniciar(pasosEnviar()); };
  if (enLista) {
    window.OrbithRecorridos[ENVIAR + ':solicitudes'] = function () { iniciar(pasosSeguimiento()); };
    window.OrbithRecorridos[DECIDIR + ':solicitudes'] = function () { iniciar(pasosDecidirLista()); };
    window.OrbithRecorridos[DECIDIR + ':hecho'] = function () {
      const pasos = pasosFinal();
      if (pasos.length) iniciar(pasos);
    };
  }
  if (enRevision) window.OrbithRecorridos[DECIDIR + ':revisar'] = function () { iniciar(pasosRevision()); };
})();
