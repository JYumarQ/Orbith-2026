/**
 * Recorrido "Reportar un problema" (tarea `primer_reporte_problema`, los tres
 * roles).
 *
 * El formulario vive en la ventana común "Acerca de Orbith"
 * (templates/base/partials/modales_usuario.html), así que este recorrido se
 * carga en todas las páginas desde base.html. Clave: `primer_reporte_problema:global`.
 *
 * Pasos: foto de perfil → "Acerca de Orbith" → "Reportar problema" →
 * descripción → consola y capturas (opcionales) → "Enviar reporte" (el logro)
 * → y, para el Administrador, dónde llegan: "Reportes de Problemas".
 */
(function () {
  if (!window.OrbithRecorrido || !document.getElementById('formReporte')) return;

  function abierto(selector) { return !!document.querySelector(selector); }
  function formularioVisible() {
    const f = document.getElementById('formReporte');
    return !!f && !f.classList.contains('d-none');
  }

  // Envío correcto: se pulsó "Enviar reporte" y el formulario se volvió a
  // plegar (así lo deja la ventana cuando el servidor responde que sí).
  let enviado = false;
  document.addEventListener('submit', function (e) {
    if (e.target && e.target.id === 'formReporte') enviado = true;
  }, true);

  // El enlace a la bandeja solo existe en el menú del Administrador.
  function enlaceBandeja() {
    const enlace = document.querySelector('a[href="/soporte/reportes/"]');
    if (!enlace) return '';
    if (enlace.getBoundingClientRect().width > 2) return 'a[href="/soporte/reportes/"]';
    // Dentro del acordeón "Administración" plegado: se señala su cabecera.
    const item = enlace.closest('.menu-item');
    const cabecera = item && item.querySelector('.menu-link');
    if (!cabecera) return '';
    if (!cabecera.id) cabecera.id = 'orMenuAdministracion';
    return '#' + cabecera.id;
  }

  function pasos() {
    const modalYaAbierto = function () { return abierto('#modalAcercaDe.show'); };
    return [
      {
        selector: '#userDropdown', interactivo: true, saltarSi: modalYaAbierto,
        titulo: 'Tu menú',
        texto: '¿Algo no funciona como esperabas? Se avisa desde aquí. Pulsa tu <strong>foto de perfil</strong>.',
        esperar: function () { return abierto('#menu-user.show') ? 'abierto' : ''; },
      },
      {
        selector: '#menu-user [data-bs-target="#modalAcercaDe"]', interactivo: true, saltarSi: modalYaAbierto,
        titulo: 'Acerca de Orbith',
        texto: 'Pulsa <strong>"Acerca de Orbith"</strong>.',
        esperar: function () { return modalYaAbierto() ? 'abierto' : ''; },
      },
      {
        selector: '#btnAbrirReporte', interactivo: true,
        saltarSi: formularioVisible,
        titulo: 'Reportar problema',
        texto: 'Pulsa <strong>"Reportar problema"</strong>: se abre un formulario corto.',
        esperar: function () { return formularioVisible() ? 'abierto' : ''; },
      },
      {
        selector: '#formReporte textarea[name="mensaje"]', interactivo: true, avanceManual: true,
        titulo: 'Describe el problema',
        texto: 'Cuenta <strong>qué ocurrió</strong>, <strong>en qué pantalla</strong> y <strong>qué esperabas</strong> que pasara. ' +
          'Si ahora no tienes ningún problema, escribe <strong>"Prueba de la Guía"</strong>: el Administrador lo marcará como resuelto.',
        textoEspera: 'Escribe la descripción para continuar.',
        esperar: function () {
          const t = document.querySelector('#formReporte textarea[name="mensaje"]');
          return t && t.value.trim() ? 'si' : '';
        },
      },
      {
        selector: '#btnToggleErrorConsola, #btnAnadirImagenReporte', interactivo: true, opcional: true,
        titulo: 'Error de consola y capturas',
        texto: 'Si viste un error en la consola del navegador (tecla <strong>F12</strong>), pégalo en su apartado. ' +
          'Y añade hasta <strong>4 capturas</strong> de pantalla (JPG, PNG o WEBP, de 2 MB como máximo): ayudan mucho a entender el problema.',
      },
      {
        selector: '#formReporte [type="submit"]', interactivo: true, paciencia: 3000,
        alEntrar: function () { enviado = false; },
        titulo: 'Enviar reporte',
        texto: 'Pulsa <strong>"Enviar reporte"</strong>. Se guarda con la pantalla desde la que lo envías; no se manda ningún correo. ¡Y consigues el logro!',
        textoEspera: 'Pulsa "Enviar reporte".',
        esperar: function () { return enviado && !formularioVisible() ? 'enviado' : ''; },
      },
      {
        selector: '#btnAbrirReporte',
        titulo: '¡Reporte enviado!',
        texto: 'El Administrador lo revisará. Puedes reportar otro problema cuando quieras desde esta misma ventana.',
      },
      {
        // Solo el Administrador tiene este enlace: para los demás, se salta.
        selector: enlaceBandeja,
        // En `alEntrar` y no en `preparar`: `preparar` también corre cuando el
        // paso se salta, y cerraría la ventana a quien no es Administrador.
        alEntrar: function () {
          const modal = document.getElementById('modalAcercaDe');
          if (modal && modal.classList.contains('show') && window.bootstrap) bootstrap.Modal.getOrCreateInstance(modal).hide();
        },
        titulo: 'Dónde llegan',
        texto: 'Como Administrador, los reportes te llegan a <strong>Administración → "Reportes de Problemas"</strong>, con su descripción, sus capturas y la pantalla desde la que se enviaron.',
      },
    ];
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};
  window.OrbithRecorridos['primer_reporte_problema:global'] = function () {
    window.OrbithRecorrido.iniciar({ pasos: pasos() });
  };
})();
