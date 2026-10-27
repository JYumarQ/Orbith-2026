/*
 * Orden por arrastre de los nomencladores (3.8.2, decisión del 27-10-2026).
 *
 * Cualquier <tbody data-orden="slug"> se reordena arrastrando el asa (⋮⋮) que este
 * script añade al principio de cada fila con data-id, también a las que se crean
 * después. Otras listas (las tarjetas de Familias de cargos) dicen qué elementos se
 * ordenan con `data-orden-elemento` y dónde va el asa con `data-orden-lugar`.
 * Al soltar, se manda la lista completa de ids a /nomencladores/api/orden/<slug>/; ese orden es el de TODO Orbith (tarjetas,
 * desplegables, filtros e informes). Si el servidor lo rechaza, la fila vuelve a
 * su sitio y un aviso explica por qué.
 *
 * Las tarjetas que llegan por HTMX (Instructor, CNCI y las de Pre-Nómina) se
 * preparan al llegar (`htmx:afterSwap`).
 */
(function () {
  'use strict';

  var ERROR_GENERICO = 'No se pudo guardar el orden. Inténtelo de nuevo y, si se repite, avise al administrador de Orbith.';

  function csrf() {
    var campo = document.querySelector('[name=csrfmiddlewaretoken]');
    if (campo && campo.value) return campo.value;
    var cookie = document.cookie.split('; ').find(function (c) { return c.indexOf('csrftoken=') === 0; });
    return cookie ? cookie.split('=')[1] : '';
  }

  function avisar(texto, tipo) {
    if (window.mostrarToast) window.mostrarToast(texto, tipo);
    else window.alert(texto);
  }

  function selector(cuerpo) {
    return cuerpo.dataset.ordenElemento || 'tr[data-id]';
  }

  function filas(cuerpo) {
    var cual = selector(cuerpo);
    return Array.prototype.filter.call(cuerpo.children, function (f) { return f.matches(cual) && f.dataset.id; });
  }

  function ponerAsas(cuerpo) {
    filas(cuerpo).forEach(function (fila) {
      if (fila.querySelector('.orb-asa-orden')) return;
      var celda = fila.querySelector('[data-orden-lugar]') || fila.querySelector('td') || fila.firstElementChild;
      if (!celda) return;
      var asa = document.createElement('span');
      asa.className = 'orb-asa-orden';
      asa.title = 'Arrastre para ordenar';
      asa.setAttribute('aria-hidden', 'true');
      asa.innerHTML = '<i class="fas fa-grip-vertical"></i>';
      celda.insertBefore(asa, celda.firstChild);
    });
  }

  function guardar(cuerpo, deshacer) {
    var ids = filas(cuerpo).map(function (f) { return f.dataset.id; });
    fetch('/nomencladores/api/orden/' + cuerpo.dataset.orden + '/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({ ids: ids })
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (!r.ok || d.error) throw new Error(d.error || ERROR_GENERICO);
        });
      })
      .then(function () { avisar('Orden guardado.', 'success'); })
      .catch(function (error) {
        deshacer();
        avisar(error.message || ERROR_GENERICO, 'warning');
      });
  }

  function preparar(cuerpo) {
    ponerAsas(cuerpo);
    if (cuerpo.dataset.ordenListo || !window.Sortable) return;
    cuerpo.dataset.ordenListo = '1';
    // También dentro de las filas: editar un tipo de unidad reescribe la fila entera.
    new MutationObserver(function () { ponerAsas(cuerpo); }).observe(cuerpo, { childList: true, subtree: true });
    window.Sortable.create(cuerpo, {
      handle: '.orb-asa-orden',
      draggable: selector(cuerpo),
      animation: 150,
      onEnd: function (ev) {
        // Posiciones entre los elementos que se ordenan (sin filas de «lista vacía»).
        var desde = ev.oldDraggableIndex !== undefined ? ev.oldDraggableIndex : ev.oldIndex;
        var hasta = ev.newDraggableIndex !== undefined ? ev.newDraggableIndex : ev.newIndex;
        if (desde === hasta) return;
        var fila = ev.item;
        guardar(cuerpo, function () {
          var resto = filas(cuerpo).filter(function (f) { return f !== fila; });
          cuerpo.insertBefore(fila, resto[desde] || null);
        });
      }
    });
  }

  function buscar(raiz) {
    var base = raiz && raiz.querySelectorAll ? raiz : document;
    if (base.matches && base.matches('[data-orden]')) preparar(base);
    base.querySelectorAll('[data-orden]').forEach(preparar);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { buscar(); });
  else buscar();
  document.addEventListener('htmx:afterSwap', function (ev) { buscar(ev.target); });
  window.OrbithOrdenNomencladores = { buscar: buscar };
})();
