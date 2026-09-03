/* Select2 (tema bootstrap-5) sobre selects que conviven con HTMX.
 *
 * Mismo patrón que ya usaba el formulario de Contrato (add_contrato.html /
 * updt_contrato.html), pero extraído aquí para no triplicarlo a mano en un
 * tercer formulario. El puente hacia HTMX es necesario porque Select2
 * confirma la selección disparando un 'change' vía jQuery, y jQuery no
 * dispara un evento nativo del DOM para 'change' (no hay un `elem.change()`
 * nativo como sí lo hay para 'click' o 'submit'). El listener nativo de HTMX
 * (`hx-trigger="change"`) nunca se entera si no se le reenvía como evento
 * real del navegador.
 */
window.OrbithSelect2 = window.OrbithSelect2 || {};

/**
 * Inicializa (o reinicializa) Select2 sobre un <select> ya presente en el DOM.
 * Seguro de llamar varias veces sobre el mismo elemento: si ya tenía Select2
 * montado, lo destruye antes de volver a montarlo.
 *
 * @param {string} selector CSS selector del <select> (normalmente un #id).
 */
OrbithSelect2.iniciar = function (selector) {
  if (!window.jQuery) return;
  var $select = jQuery(selector);
  if (!$select.length) return;

  // `.data('select2')` es la fuente de verdad de si hay una instancia viva
  // (y por tanto algo real que destruir): la clase CSS `select2-hidden-accessible`
  // puede quedar puesta sin que la instancia siga existiendo (p. ej. tras un
  // swap de HTMX que reemplaza el <select> pero no limpia del todo el estado
  // anterior), y llamar a `.select2('destroy')` en ese caso lanza "Cannot
  // read properties of undefined (reading 'destroy')" y aborta toda la
  // función a mitad de camino, dejando el campo sin Select2 montado.
  if ($select.data('select2')) {
    try { $select.select2('destroy'); } catch (e) { /* ya no hay nada real que destruir */ }
  }

  $select.select2({
    dropdownParent: $select.parent(),
    width: '100%',
    theme: 'bootstrap-5',
  });

  $select.off('select2:select.htmxBridge select2:unselect.htmxBridge select2:clear.htmxBridge')
    .on('select2:select.htmxBridge select2:unselect.htmxBridge select2:clear.htmxBridge', function () {
      this.dispatchEvent(new Event('change', { bubbles: true }));
    });
};

/**
 * Variante para los <select> que HTMX actualiza con `hx-swap="innerHTML"`, es
 * decir, cambiando solo sus <option> y dejando el <select> en su sitio.
 *
 * Es el caso de Municipio en el formulario de Aspirante. Ahí NO hay que
 * destruir ni volver a montar Select2 (el nodo nunca desaparece), y por eso
 * tampoco hay parpadeo: basta con avisar a Select2 de que la lista cambió y
 * ajustar el estado habilitado/deshabilitado, que antes venía impuesto por el
 * <select> que mandaba el servidor.
 *
 * @param {string[]} selectores Selectores ('#id_municipio', ...) a vigilar.
 */
OrbithSelect2.refrescarTrasSwapDeOpciones = function (selectores) {
  document.body.addEventListener('htmx:afterSwap', function (evento) {
    var destino = evento.target;
    if (!destino || !destino.matches) return;

    var coincide = selectores.some(function (selector) {
      return destino.matches(selector);
    });
    if (!coincide) return;

    // Solo hay opciones reales si además de la de cortesía ("Selec. municipio")
    // llegó alguna más: sin provincia elegida el campo debe quedar bloqueado.
    var hayOpciones = destino.querySelectorAll('option[value]:not([value=""])').length > 0;
    destino.disabled = !hayOpciones;
    destino.value = '';

    // Select2 mantiene su propia copia del texto mostrado; sin este aviso
    // seguiría enseñando el municipio de la provincia anterior.
    if (window.jQuery && jQuery(destino).data('select2')) {
      jQuery(destino).trigger('change.select2');
    }

    // El semáforo de color del campo lo repinta `aspirante_formulario.js` al
    // escuchar este mismo cambio de opciones.
    destino.dispatchEvent(new Event('opciones:actualizadas', { bubbles: true }));
  });
};
