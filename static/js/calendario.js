/* Pre-Nómina → Calendario: selección de filas, edición en línea y asignación.
 *
 * Todo va DELEGADO en `document.body` y no enganchado a cada elemento: las tres
 * tarjetas se reemplazan enteras en cada intercambio de HTMX, así que cualquier
 * manejador puesto sobre un nodo concreto moriría con el primer refresco. Con
 * delegación no hay nada que reenganchar.
 *
 * La selección de fila reutiliza las clases que ya existen en
 * `static/css/nomencladores.css` (`table-active-row`, `toolbar-disabled`): es el
 * mismo mecanismo del Nomenclador de Cargos, no uno nuevo.
 */
(function () {
  'use strict';

  // ----------------------------------------------------------------------- //
  // Select2: mismo patrón que Unid. Org., Departamento y Cargo en
  // `contrato/add_contrato.html::initSelect2Cascada`.
  //
  // Se copia entero, incluido el puente con HTMX, porque el original vive dentro
  // de un `<script>` de esa plantilla y no es importable. Los dos detalles que
  // NO se pueden quitar, ambos documentados allí:
  //
  // * `theme: 'bootstrap-5'` es obligatorio. Sin él el contenedor se pinta como
  //   `select2-container--default`, ni el tema ni `select2-sneat-fix.css`
  //   aplican, y el control encoge ~11px al inicializarse (parpadeo visible).
  // * El puente HTMX: Select2 avisa del cambio con el `trigger()` sintético de
  //   jQuery, que HTMX —basado en `addEventListener` nativo— no detecta, así que
  //   sin él el `hx-get` del filtro no se dispararía nunca.
  //
  // `dropdownParent` apunta al padre del propio select para que, dentro de un
  // modal, el desplegable se pinte en su contexto y no quede recortado.
  // ----------------------------------------------------------------------- //

  function initSelect2(selector) {
    if (!window.jQuery) return;
    const $select = jQuery(selector);
    if (!$select.length) return;
    if ($select.hasClass('select2-hidden-accessible')) $select.select2('destroy');

    $select.select2({
      dropdownParent: $select.parent(),
      width: '100%',
      theme: 'bootstrap-5',
      placeholder: $select.data('placeholder') || '',
      allowClear: Boolean($select.data('placeholder')),
      templateSelection: function (s) { return s.text; },
    });

    $select.off('select2:select.htmxBridge select2:unselect.htmxBridge select2:clear.htmxBridge')
           .on('select2:select.htmxBridge select2:unselect.htmxBridge select2:clear.htmxBridge',
               function () {
                 this.dispatchEvent(new Event('change', { bubbles: true }));
               });
  }

  /* Se reinicializan tras cada intercambio de HTMX porque las tarjetas y los
     modales se repintan enteros: el `<select>` que había quedó destruido con su
     instancia de Select2, y el nuevo llega sin inicializar. `initSelect2` ya
     destruye la instancia previa si la hubiera, así que llamarlo de más es
     inofensivo. */
  const SELECTS = '#filtro_unidad_trabajadores, #id_calendario_asignar';

  function initSelectsCalendario() {
    document.querySelectorAll(SELECTS).forEach(function (select) {
      initSelect2('#' + select.id);
    });
  }

  document.addEventListener('DOMContentLoaded', initSelectsCalendario);
  document.body.addEventListener('htmx:afterSettle', initSelectsCalendario);
  // Al abrir el modal por primera vez el contenido llega por HTMX, pero si
  // Bootstrap lo muestra después del `afterSettle` el desplegable se posiciona
  // mal: se rehace al terminar la animación de apertura.
  document.body.addEventListener('shown.bs.modal', initSelectsCalendario);
  initSelectsCalendario();

  // ----------------------------------------------------------------------- //
  // Selección de fila (tarjetas 1 y 2)
  // ----------------------------------------------------------------------- //

  /* Cada tarjeta con selección declara aquí su tabla, su toolbar y dónde
     guardar la fila elegida. Añadir una cuarta tarjeta es añadir una entrada. */
  const SELECCIONABLES = [
    { fila: '.fila-calendario', tbody: '#calendarios-tbody', toolbar: '#calendarios-toolbar' },
    { fila: '.fila-detalle', tbody: '#periodo-tbody', toolbar: '#periodo-toolbar' },
  ];

  const seleccion = {};   // { '.fila-calendario': HTMLElement | null }

  function limpiar(config) {
    const cuerpo = document.querySelector(config.tbody);
    if (cuerpo) {
      cuerpo.querySelectorAll('tr').forEach(function (tr) {
        tr.classList.remove('table-active-row');
      });
    }
    const toolbar = document.querySelector(config.toolbar);
    if (toolbar) toolbar.classList.add('toolbar-disabled');
    seleccion[config.fila] = null;
  }

  function seleccionar(config, tr) {
    // Un segundo clic sobre la misma fila la deselecciona: es lo que permite
    // volver a dejar los botones apagados sin recargar.
    if (seleccion[config.fila] === tr) {
      limpiar(config);
      return;
    }
    limpiar(config);
    tr.classList.add('table-active-row');
    seleccion[config.fila] = tr;
    const toolbar = document.querySelector(config.toolbar);
    if (toolbar) toolbar.classList.remove('toolbar-disabled');
  }

  document.body.addEventListener('click', function (e) {
    SELECCIONABLES.forEach(function (config) {
      const tr = e.target.closest(config.fila);
      if (!tr) return;
      // Un clic dentro de un input de edición en línea no debe cambiar la
      // selección: se está escribiendo, no eligiendo fila.
      if (e.target.closest('input, button, a')) return;
      seleccionar(config, tr);
    });
  });

  /* Tras cada intercambio de HTMX la fila seleccionada ya no existe en el DOM:
     se olvida la referencia y se apagan los botones, que es el estado correcto
     para una tabla recién pintada. */
  document.body.addEventListener('htmx:afterSwap', function () {
    SELECCIONABLES.forEach(function (config) {
      if (document.querySelector(config.tbody)) limpiar(config);
    });
  });

  function filaSeleccionada(claseFila) {
    return seleccion[claseFila] || null;
  }

  // ----------------------------------------------------------------------- //
  // Tarjeta 1: editar y eliminar el calendario seleccionado
  // ----------------------------------------------------------------------- //

  document.body.addEventListener('click', function (e) {
    const botonEditar = e.target.closest('#btn-editar-calendario');
    if (botonEditar) {
      const tr = filaSeleccionada('.fila-calendario');
      if (!tr) return;
      htmx.ajax('GET', tr.dataset.editar, { target: '#modal_generic', swap: 'innerHTML' });
      return;
    }

    const botonEliminar = e.target.closest('#btn-eliminar-calendario');
    if (botonEliminar) {
      const tr = filaSeleccionada('.fila-calendario');
      if (!tr) return;
      Swal.fire({
        title: '¿Eliminar el calendario?',
        text: '«' + tr.dataset.descripcion + '» se eliminará si no se ha usado en ningún Calendario de Pago.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Eliminar',
        cancelButtonText: 'Cancelar',
        customClass: { confirmButton: 'btn btn-danger', cancelButton: 'btn btn-outline-secondary ms-2' },
        buttonsStyling: false,
      }).then(function (resultado) {
        if (resultado.isConfirmed) {
          htmx.ajax('POST', tr.dataset.eliminar, { swap: 'none' });
        }
      });
    }
  });

  // ----------------------------------------------------------------------- //
  // Tarjeta 2: quitar una línea del período
  // ----------------------------------------------------------------------- //

  document.body.addEventListener('click', function (e) {
    if (!e.target.closest('#btn-quitar-detalle')) return;
    const tr = filaSeleccionada('.fila-detalle');
    if (!tr) return;
    Swal.fire({
      title: '¿Quitar del período?',
      text: '«' + tr.dataset.descripcion + '» dejará de formar parte de este Calendario de Pago.',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Quitar',
      cancelButtonText: 'Cancelar',
      customClass: { confirmButton: 'btn btn-danger', cancelButton: 'btn btn-outline-secondary ms-2' },
      buttonsStyling: false,
    }).then(function (resultado) {
      if (resultado.isConfirmed) {
        htmx.ajax('POST', tr.dataset.quitar, { swap: 'none' });
      }
    });
  });

  // ----------------------------------------------------------------------- //
  // Edición en línea de las horas (doble clic sobre la celda)
  //
  // Sin modal, como pide el requisito: la celda se convierte en un input, se
  // confirma con Enter o al salir del campo, y se cancela con Escape. Al
  // confirmar se manda la quincena editada y el servidor devuelve la FILA
  // entera, porque «Horas Mes» es calculada y tiene que repintarse.
  //
  // Las celdas de un período cerrado no llevan `.pn-celda-editable`, así que
  // este manejador no las encuentra: el bloqueo está en el marcado.
  // ----------------------------------------------------------------------- //

  let editando = null;

  function cerrarEdicion(celda, valorOriginal) {
    celda.innerHTML = '';
    celda.textContent = parseFloat(valorOriginal).toFixed(2);
    editando = null;
  }

  document.body.addEventListener('dblclick', function (e) {
    const celda = e.target.closest('.pn-celda-editable');
    if (!celda || editando) return;

    editando = celda;
    const original = celda.dataset.valor;

    const input = document.createElement('input');
    input.type = 'text';
    input.inputMode = 'decimal';
    input.className = 'form-control form-control-sm text-end';
    input.value = original;
    celda.innerHTML = '';
    celda.appendChild(input);
    input.focus();
    input.select();

    let confirmado = false;

    function confirmar() {
      if (confirmado) return;
      confirmado = true;

      const valor = input.value.trim();
      if (valor === original) {   // sin cambios: no se molesta al servidor
        cerrarEdicion(celda, original);
        return;
      }

      const parametros = {};
      parametros[celda.dataset.campo] = valor;
      editando = null;
      htmx.ajax('POST', celda.dataset.url, {
        target: '#' + celda.closest('tr').id,
        swap: 'outerHTML',
        values: parametros,
      });
    }

    input.addEventListener('keydown', function (evento) {
      if (evento.key === 'Enter') {
        evento.preventDefault();
        confirmar();
      } else if (evento.key === 'Escape') {
        evento.preventDefault();
        confirmado = true;
        cerrarEdicion(celda, original);
      }
    });
    input.addEventListener('blur', confirmar);
  });

  // ----------------------------------------------------------------------- //
  // Tarjeta 3: selección múltiple y asignación masiva
  // ----------------------------------------------------------------------- //

  // ----------------------------------------------------------------------- //
  // Casilla «Todos»
  //
  // Genérica: cualquier checkbox con `data-todos="<selector>"` manda sobre los
  // que casen con ese selector. Se usa en el modal de selección de calendarios
  // y en la lista de trabajadores, así que el comportamiento —incluido el
  // estado intermedio— se escribe una sola vez.
  //
  // Los deshabilitados quedan fuera a propósito: son los calendarios inactivos y
  // los ya incluidos en el período, que no se pueden elegir.
  // ----------------------------------------------------------------------- //

  function hijosDe(maestro) {
    return Array.from(document.querySelectorAll(maestro.dataset.todos))
                .filter(function (check) { return !check.disabled; });
  }

  function sincronizarMaestro(maestro) {
    const hijos = hijosDe(maestro);
    const marcados = hijos.filter(function (c) { return c.checked; });
    maestro.checked = hijos.length > 0 && marcados.length === hijos.length;
    // Estado intermedio cuando hay algunos pero no todos: sin él, «Todos»
    // aparecería desmarcado con media lista seleccionada, que se lee como si no
    // hubiera nada elegido.
    maestro.indeterminate = marcados.length > 0 && !maestro.checked;
  }

  function maestroDe(hijo) {
    return Array.from(document.querySelectorAll('input[data-todos]'))
                .find(function (maestro) {
                  return hijo.matches(maestro.dataset.todos);
                });
  }

  document.body.addEventListener('change', function (e) {
    const maestro = e.target.matches('input[data-todos]') ? e.target : null;
    if (maestro) {
      hijosDe(maestro).forEach(function (check) { check.checked = maestro.checked; });
      maestro.indeterminate = false;
      refrescarBotonesTrabajadores();
      return;
    }
    if (e.target.type === 'checkbox') {
      const suyo = maestroDe(e.target);
      if (suyo) sincronizarMaestro(suyo);
    }
  });

  // Tras cada intercambio de HTMX (y al abrir el modal) el maestro se recalcula:
  // el marcado llega recién pintado y hay que ponerlo en su estado real.
  document.body.addEventListener('htmx:afterSwap', function () {
    document.querySelectorAll('input[data-todos]').forEach(sincronizarMaestro);
  });

  function marcados() {
    return Array.from(document.querySelectorAll('.check-trabajador:checked'));
  }

  function refrescarBotonesTrabajadores() {
    const cuantos = marcados().length;
    const asignar = document.getElementById('btn-asignar');
    const desasignar = document.getElementById('btn-desasignar');
    const contador = document.getElementById('contador-trabajadores');

    if (asignar) asignar.disabled = cuantos === 0;
    if (desasignar) desasignar.disabled = cuantos === 0;
    if (contador) {
      contador.textContent = cuantos;
      contador.classList.toggle('d-none', cuantos === 0);
    }
  }

  // El maestro «Todos» de la lista lo lleva el manejador genérico de más arriba;
  // aquí solo queda refrescar el contador y los botones al marcar una fila.
  document.body.addEventListener('change', function (e) {
    if (e.target.classList.contains('check-trabajador')) {
      refrescarBotonesTrabajadores();
    }
  });

  document.body.addEventListener('htmx:afterSwap', refrescarBotonesTrabajadores);

  document.body.addEventListener('click', function (e) {
    if (e.target.closest('#btn-asignar')) {
      const valores = marcados().map(function (c) { return c.value; });
      if (!valores.length) return;
      // `values` con un array manda un parámetro repetido, que es justo lo que
      // `request.GET.getlist('trabajadores')` espera al otro lado.
      htmx.ajax('GET', document.getElementById('btn-asignar').dataset.url, {
        target: '#modal_generic',
        swap: 'innerHTML',
        values: { trabajadores: valores },
      });
      return;
    }

    if (e.target.closest('#btn-desasignar')) {
      const valores = marcados().map(function (c) { return c.value; });
      if (!valores.length) return;
      Swal.fire({
        title: '¿Quitar la asignación?',
        text: valores.length + ' trabajador(es) quedarán sin calendario asignado.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Quitar',
        cancelButtonText: 'Cancelar',
        customClass: { confirmButton: 'btn btn-danger', cancelButton: 'btn btn-outline-secondary ms-2' },
        buttonsStyling: false,
      }).then(function (resultado) {
        if (resultado.isConfirmed) {
          htmx.ajax('POST', document.getElementById('btn-desasignar').dataset.url, {
            swap: 'none',
            values: { trabajadores: valores },
          });
        }
      });
    }
  });

  // ----------------------------------------------------------------------- //
  // Buscador de la tarjeta 1: filtrado en el navegador
  //
  // No pasa por el servidor porque el catálogo personal de un usuario son unas
  // pocas filas y ya están todas en la página.
  // ----------------------------------------------------------------------- //

  document.body.addEventListener('input', function (e) {
    if (e.target.id !== 'buscar-calendario') return;
    const texto = e.target.value.trim().toLowerCase();
    document.querySelectorAll('#calendarios-tbody .fila-calendario').forEach(function (tr) {
      tr.style.display = tr.textContent.toLowerCase().includes(texto) ? '' : 'none';
    });
  });
})();
