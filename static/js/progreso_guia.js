/**
 * Modo guiado de la Guía de Orbith.
 *
 * Acompaña al usuario paso a paso en la pantalla a la que llega desde el
 * botón "Ir a X" del panel de la Guía — y SOLO en ese caso: el widget nunca
 * aparece por navegación normal, porque solo se activa cuando
 * `window.orbithIniciarGuia(codigo)` se llama explícitamente desde ese botón
 * (ver templates/pages/progreso/partials/panel_guia.html).
 *
 * El estado (qué tarea, en qué paso) vive en sessionStorage: sobrevive a la
 * navegación normal dentro de la pestaña, pero desaparece solo al cerrar la
 * pestaña o completar/cerrar la guía. Cada carga de página vuelve a
 * consultar el servidor (`/progreso/tarea/<codigo>/`) para saber si la tarea
 * ya se completó de verdad, y si es así cierra el widget solo — no hace
 * falta que el usuario le diga "ya terminé".
 *
 * Es arrastrable: no existe una posición fija que no estorbe en algún
 * formulario o modal de Orbith, así que el usuario lo mueve donde le
 * convenga. La posición elegida se recuerda en localStorage (no
 * sessionStorage: es una preferencia de uso, no parte del estado de "guía
 * activa") para que no vuelva a la esquina por defecto en cada pantalla del
 * mismo recorrido.
 */
(function () {
  const CLAVE_ESTADO = 'orbith_guia_activa';
  const CLAVE_POSICION = 'orbith_guia_posicion';
  const ID_WIDGET = 'orbithGuiaFlotante';
  const ANCHO_WIDGET = 300;
  const MARGEN = 16;

  function leerEstado() {
    try {
      return JSON.parse(sessionStorage.getItem(CLAVE_ESTADO));
    } catch (e) {
      return null;
    }
  }

  function guardarEstado(estado) {
    sessionStorage.setItem(CLAVE_ESTADO, JSON.stringify(estado));
  }

  function cerrarGuia() {
    sessionStorage.removeItem(CLAVE_ESTADO);
    const widget = document.getElementById(ID_WIDGET);
    if (widget) widget.remove();
  }

  window.orbithIniciarGuia = function (codigo) {
    guardarEstado({ codigo: codigo, paso: 0 });
  };

  function leerPosicionGuardada() {
    try {
      return JSON.parse(localStorage.getItem(CLAVE_POSICION));
    } catch (e) {
      return null;
    }
  }

  function guardarPosicion(top, left) {
    try {
      localStorage.setItem(CLAVE_POSICION, JSON.stringify({ top: top, left: left }));
    } catch (e) {
      // localStorage puede fallar en modo privado con cuota 0: no es crítico,
      // el widget simplemente vuelve a la posición por defecto la próxima vez.
    }
  }

  function posicionInicial() {
    const guardada = leerPosicionGuardada();
    if (guardada) return guardada;
    // Por defecto: arriba a la derecha, debajo del navbar. Es solo el punto
    // de partida — el usuario lo arrastra a donde le convenga y desde ahí
    // se recuerda esa posición.
    return {
      top: 80,
      left: Math.max(MARGEN, window.innerWidth - ANCHO_WIDGET - MARGEN),
    };
  }

  function limitarAlViewport(top, left, widget) {
    const ancho = widget.offsetWidth || ANCHO_WIDGET;
    const alto = widget.offsetHeight || 120;
    const maxLeft = Math.max(0, window.innerWidth - ancho);
    const maxTop = Math.max(0, window.innerHeight - alto);
    return {
      top: Math.min(Math.max(0, top), maxTop),
      left: Math.min(Math.max(0, left), maxLeft),
    };
  }

  function crearWidget() {
    const widget = document.createElement('div');
    widget.id = ID_WIDGET;
    const pos = posicionInicial();
    widget.style.cssText =
      'position:fixed;top:' + pos.top + 'px;left:' + pos.left + 'px;' +
      'width:' + ANCHO_WIDGET + 'px;max-width:calc(100vw - ' + (MARGEN * 2) + 'px);z-index:1080;';
    document.body.appendChild(widget);
    return widget;
  }

  // Arrastre con Pointer Events: cubre mouse, lápiz y dedo con la misma API.
  // Se reengancha en cada renderWidget() porque innerHTML reemplaza el header.
  function habilitarArrastre(widget) {
    const agarradera = widget.querySelector('.orbith-guia-agarradera');
    if (!agarradera) return;

    let arrastrando = false;
    let offsetX = 0;
    let offsetY = 0;

    agarradera.addEventListener('pointerdown', function (e) {
      if (e.target.closest('#orbithGuiaCerrar')) return;
      arrastrando = true;
      const rect = widget.getBoundingClientRect();
      offsetX = e.clientX - rect.left;
      offsetY = e.clientY - rect.top;
      agarradera.setPointerCapture(e.pointerId);
      agarradera.style.cursor = 'grabbing';
    });

    agarradera.addEventListener('pointermove', function (e) {
      if (!arrastrando) return;
      const limitado = limitarAlViewport(e.clientY - offsetY, e.clientX - offsetX, widget);
      widget.style.top = limitado.top + 'px';
      widget.style.left = limitado.left + 'px';
    });

    function terminarArrastre(e) {
      if (!arrastrando) return;
      arrastrando = false;
      agarradera.style.cursor = 'grab';
      guardarPosicion(parseInt(widget.style.top, 10), parseInt(widget.style.left, 10));
    }

    agarradera.addEventListener('pointerup', terminarArrastre);
    agarradera.addEventListener('pointercancel', terminarArrastre);
  }

  function renderWidget(datos, estado) {
    const widget = document.getElementById(ID_WIDGET) || crearWidget();
    const totalPasos = datos.pasos.length;
    const pasoActual = datos.pasos[estado.paso] || '';
    const esUltimo = estado.paso + 1 >= totalPasos;

    widget.innerHTML =
      '<div class="card shadow-lg border-info">' +
      '  <div class="card-header bg-label-info d-flex align-items-center justify-content-between py-2 orbith-guia-agarradera"' +
      '       style="cursor:grab;touch-action:none;" title="Arrastra para mover">' +
      '    <span class="fw-semibold text-truncate me-2" style="font-size:.8125rem;">' +
      '      <i class="bx bx-move me-1"></i><i class="bx bx-compass me-1"></i>' + datos.titulo +
      '    </span>' +
      '    <button type="button" class="btn-close" id="orbithGuiaCerrar" aria-label="Cerrar"></button>' +
      '  </div>' +
      '  <div class="card-body py-2">' +
      '    <div class="text-muted mb-1" style="font-size:.7rem;">Paso ' + (estado.paso + 1) + ' de ' + totalPasos + '</div>' +
      '    <div style="font-size:.875rem;">' + pasoActual + '</div>' +
      '  </div>' +
      '  <div class="card-footer d-flex justify-content-between py-2">' +
      '    <button type="button" class="btn btn-sm btn-label-secondary" id="orbithGuiaAnterior"' +
      (estado.paso === 0 ? ' disabled' : '') + '>Anterior</button>' +
      '    <button type="button" class="btn btn-sm btn-info" id="orbithGuiaSiguiente">' +
      (esUltimo ? 'Entendido' : 'Siguiente') + '</button>' +
      '  </div>' +
      '</div>';

    document.getElementById('orbithGuiaCerrar').addEventListener('click', cerrarGuia);

    document.getElementById('orbithGuiaAnterior').addEventListener('click', function () {
      estado.paso = Math.max(0, estado.paso - 1);
      guardarEstado(estado);
      renderWidget(datos, estado);
    });

    document.getElementById('orbithGuiaSiguiente').addEventListener('click', function () {
      if (esUltimo) {
        cerrarGuia();
        return;
      }
      estado.paso += 1;
      guardarEstado(estado);
      renderWidget(datos, estado);
    });

    habilitarArrastre(widget);
  }

  document.addEventListener('DOMContentLoaded', function () {
    const estado = leerEstado();
    if (!estado || !estado.codigo) return;

    fetch('/progreso/tarea/' + encodeURIComponent(estado.codigo) + '/', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      cache: 'no-store',
    })
      .then(function (respuesta) {
        return respuesta.ok ? respuesta.json() : Promise.reject();
      })
      .then(function (datos) {
        if (datos.completada) {
          cerrarGuia();
          if (typeof window.mostrarToast === 'function') {
            window.mostrarToast('✅ ¡Completaste "' + datos.titulo + '"!', 'success');
          }
          return;
        }
        if (!datos.pasos || !datos.pasos.length) {
          cerrarGuia();
          return;
        }
        // El paso guardado puede haber quedado fuera de rango si la tarea
        // cambió de contenido entre una visita y otra.
        estado.paso = Math.min(estado.paso, datos.pasos.length - 1);
        renderWidget(datos, estado);
      })
      .catch(cerrarGuia);
  });
})();
