/* Inicializador reutilizable de Select2 para paneles de filtro.
 *
 * No existía hasta ahora una función central: cada plantilla del proyecto que usa
 * Select2 (usuarios, cargo, informes...) repite su propia inicialización inline. Este
 * archivo centraliza SOLO el caso de "panel de filtros con varios <select multiple>",
 * empezando por el de Advertencias — el patrón de destruir/recrear es el mismo que ya
 * usa `refrescarSelectDesglose()` en informe_inteligente.js.
 */
window.OrbithNotificaciones = window.OrbithNotificaciones || {};

OrbithNotificaciones.initSelect2Filtros = function (selector) {
  if (!window.jQuery || !jQuery.fn.select2) return;

  jQuery(selector).each(function () {
    var $select = jQuery(this);
    if ($select.hasClass('select2-hidden-accessible')) {
      $select.select2('destroy');
    }
    $select.select2({
      theme: 'bootstrap-5',
      width: '100%',
      allowClear: true,
      placeholder: 'Todos',
    });
  });
};

function _obtenerCookie(nombre) {
  var coincidencia = document.cookie.match('(^|;)\\s*' + nombre + '\\s*=\\s*([^;]+)');
  return coincidencia ? decodeURIComponent(coincidencia.pop()) : null;
}

/* Barra de acciones por selección de fila (`partials/toolbar_notificacion.html` +
 * `partials/_tabla.html`), mismo patrón que ya usa
 * `templates/pages/contrato/list_contrato.html` (`seleccionarContrato()`/
 * `deseleccionarTodo()`/`#contrato-toolbar`): clic en una fila la marca activa y
 * habilita, en la barra externa, solo los botones cuyo `data-url-*` esa fila
 * realmente tiene (vacío = no aplica para esa fila o ese rol, botón deshabilitado).
 * Sustituye a los antiguos botones "Marcar leída"/"Descartar" por fila y a las
 * columnas "Registro"/"Acciones" — reemplaza también a la función
 * `activarDescartarAdvertencias()` que existía antes de este mecanismo.
 *
 * El listener se ata al CONTENEDOR (`tablaContenedorSelector`, ej.
 * `#resultados-advertencias`), no a cada fila: ese contenedor es el `hx-target` que
 * HTMX reemplaza por dentro (`hx-swap="innerHTML"`) al filtrar Advertencias, así que
 * el propio div persiste entre swaps y el listener delegado sigue funcionando sin
 * tener que reinstalarlo después de cada filtro.
 */
OrbithNotificaciones.activarBarraDeAcciones = function (tablaContenedorSelector, toolbarSelector) {
  var contenedor = document.querySelector(tablaContenedorSelector);
  var toolbar = document.querySelector(toolbarSelector);
  if (!contenedor || !toolbar) return;

  var botones = {
    enlace: toolbar.querySelector('#btn-abrir-registro'),
    marcarLeida: toolbar.querySelector('#btn-marcar-leida-toolbar'),
    descartar: toolbar.querySelector('#btn-descartar-toolbar'),
    reactivar: toolbar.querySelector('#btn-reactivar-toolbar'),
  };

  function actualizarBoton(boton, url) {
    if (!boton) return;
    boton.disabled = !url;
    boton.dataset.url = url || '';
  }

  function deseleccionarTodo() {
    contenedor.querySelectorAll('.fila-notificacion.table-active-row').forEach(function (f) {
      f.classList.remove('table-active-row');
    });
    actualizarBoton(botones.enlace, '');
    actualizarBoton(botones.marcarLeida, '');
    actualizarBoton(botones.descartar, '');
    actualizarBoton(botones.reactivar, '');
  }

  contenedor.addEventListener('click', function (evento) {
    var fila = evento.target.closest('.fila-notificacion');
    if (!fila) return;

    contenedor.querySelectorAll('.fila-notificacion').forEach(function (f) {
      f.classList.remove('table-active-row');
    });
    fila.classList.add('table-active-row');

    actualizarBoton(botones.enlace, fila.dataset.urlEnlace);
    actualizarBoton(botones.marcarLeida, fila.dataset.urlMarcarLeida);
    actualizarBoton(botones.descartar, fila.dataset.urlDescartar);
    actualizarBoton(botones.reactivar, fila.dataset.urlReactivar);
  });

  // El contenido de `contenedor` cambia al filtrar (HTMX); la fila seleccionada ya no
  // existe en el nuevo HTML, así que hay que soltar la selección y deshabilitar todo.
  document.body.addEventListener('htmx:afterSwap', function (evento) {
    if (evento.detail.target === contenedor) deseleccionarTodo();
  });

  function accionSimple(boton) {
    if (!boton) return;
    boton.addEventListener('click', function () {
      var url = boton.dataset.url;
      if (!url) return;
      fetch(url, { method: 'POST', headers: { 'X-CSRFToken': _obtenerCookie('csrftoken') } })
        .then(function (res) { if (res.ok) window.location.reload(); });
    });
  }

  function accionConConfirmacion(boton, opciones) {
    if (!boton) return;
    boton.addEventListener('click', function () {
      var url = boton.dataset.url;
      if (!url || !window.Swal) return;
      Swal.fire(opciones).then(function (resultado) {
        if (!resultado.isConfirmed) return;
        fetch(url, { method: 'POST', headers: { 'X-CSRFToken': _obtenerCookie('csrftoken') } })
          .then(function (res) { if (res.ok) window.location.reload(); });
      });
    });
  }

  if (botones.enlace) {
    botones.enlace.addEventListener('click', function () {
      if (botones.enlace.dataset.url) window.location.href = botones.enlace.dataset.url;
    });
  }
  accionSimple(botones.marcarLeida);
  accionConConfirmacion(botones.descartar, {
    title: '¿Descartar esta advertencia?',
    text: 'Se marcará como falso positivo o caso aceptado y no volverá a activarse automáticamente.',
    icon: 'warning', showCancelButton: true,
    confirmButtonText: 'Sí, descartar', cancelButtonText: 'Cancelar', confirmButtonColor: '#d33',
  });
  accionConConfirmacion(botones.reactivar, {
    title: '¿Reactivar esta advertencia?',
    text: 'Volverá a estar activa y visible en la bandeja de trabajo.',
    icon: 'question', showCancelButton: true,
    confirmButtonText: 'Sí, reactivar', cancelButtonText: 'Cancelar',
  });
};

/* Clic-a-campo del panel "otras advertencias del registro"
 * (`templates/base/partials/panel_advertencias_registro.html`): al pulsar un ítem con
 * `data-campo-formulario`, hace scroll+foco al campo real del formulario que abrió el
 * modal, evitando que el usuario tenga que buscarlo manualmente.
 *
 * Si el campo vive dentro de una pestaña Bootstrap no activa (caso del formulario de
 * Contrato, con pestañas Plantilla/Salario/...), primero abre esa pestaña: sin esto,
 * `scrollIntoView` no tendría ningún efecto visible sobre un elemento oculto.
 */
OrbithNotificaciones.activarClicACampo = function (contenedorSelector) {
  var contenedor = document.querySelector(contenedorSelector);
  if (!contenedor) return;

  contenedor.querySelectorAll('.advertencia-clicable').forEach(function (item) {
    item.addEventListener('click', function () {
      var campo = item.getAttribute('data-campo-formulario');
      if (!campo) return;
      var elemento = document.getElementById('id_' + campo);
      if (!elemento) return;

      var pestana = elemento.closest('.tab-pane');
      if (pestana && !pestana.classList.contains('active')) {
        var boton = document.querySelector('[data-bs-target="#' + pestana.id + '"]');
        if (boton) boton.click();
      }

      elemento.scrollIntoView({ behavior: 'smooth', block: 'center' });
      elemento.focus();
    });
  });
};
