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
 * pestaña o al terminar/cerrar la guía manualmente. Cada carga de página
 * vuelve a consultar el servidor (`/progreso/tarea/<codigo>/`) por si los
 * pasos cambiaron, pero el acompañamiento se muestra siempre igual, haya
 * completado el usuario la tarea antes o no: quien pulsa "Ir a X" quiere
 * repasar el procedimiento, así que la guía no se cierra sola con un aviso
 * de "ya lo hiciste" — eso frustraba a quien volvía a consultarla a
 * propósito. Se cierra solo cuando el usuario pulsa "Cerrar" o llega al
 * último paso y pulsa "Entendido".
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
      'width:' + ANCHO_WIDGET + 'px;max-width:calc(100vw - ' + (MARGEN * 2) + 'px);z-index:1093;';
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

  // ------------------------------------------------------------------
  // Logros de la Guía
  //
  // El servidor deja los logros recién conseguidos en la cookie
  // `orbith_logros` (ver `progreso.middleware.LogrosGuiaMiddleware`). Llega
  // con cualquier respuesta —una página, un fragmento HTMX, un JSON o una
  // descarga—, así que basta con mirarla al cargar y una vez por segundo:
  // leer una cookie no hace ninguna petición y no pesa nada.
  //
  // Se muestran con el mismo toast de SweetAlert que `window.mostrarToast`
  // (esquina superior derecha, fondo blanco), uno detrás de otro.
  // ------------------------------------------------------------------
  const COOKIE_LOGROS = 'orbith_logros';
  const CLAVE_LOGROS_MOSTRADOS = 'orbith_logros_mostrados';
  const colaLogros = [];
  let mostrandoLogro = false;

  function escapar(texto) {
    const div = document.createElement('div');
    div.textContent = texto == null ? '' : String(texto);
    return div.innerHTML;
  }

  function idsMostrados() {
    try {
      return JSON.parse(sessionStorage.getItem(CLAVE_LOGROS_MOSTRADOS)) || [];
    } catch (e) {
      return [];
    }
  }

  function recordarMostrado(id) {
    try {
      const ids = idsMostrados();
      ids.push(id);
      sessionStorage.setItem(CLAVE_LOGROS_MOSTRADOS, JSON.stringify(ids.slice(-50)));
    } catch (e) {
      // Sin sessionStorage, como mucho un logro se vería dos veces.
    }
  }

  function leerCookieLogros() {
    const par = document.cookie.split('; ').find(function (c) {
      return c.indexOf(COOKIE_LOGROS + '=') === 0;
    });
    if (!par) return [];
    // Se borra antes de procesarla para no mostrarla dos veces.
    document.cookie = COOKIE_LOGROS + '=; Max-Age=0; path=/; SameSite=Lax';
    try {
      const logros = JSON.parse(decodeURIComponent(par.slice(COOKIE_LOGROS.length + 1)));
      return Array.isArray(logros) ? logros : [];
    } catch (e) {
      return [];
    }
  }

  function abrirPanelGuia() {
    const modal = document.getElementById('modalGuiaOrbith');
    if (modal && window.bootstrap) bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  function mostrarSiguienteLogro() {
    if (mostrandoLogro || !colaLogros.length || typeof Swal === 'undefined') return;
    // SweetAlert solo muestra una ventana a la vez: si está saliendo otro
    // aviso (por ejemplo "Aspirante creado correctamente"), el logro espera a
    // que termine en vez de cortarlo.
    if (Swal.isVisible() && !document.querySelector('.swal2-popup.swal2-hide')) {
      setTimeout(mostrarSiguienteLogro, 500);
      return;
    }
    mostrandoLogro = true;
    const logro = colaLogros.shift();
    const total = Number(logro.total) || 0;
    const hechas = Number(logro.completadas) || 0;
    const porcentaje = total ? Math.round(100 * hechas / total) : 0;

    Swal.fire({
      toast: true,
      position: 'top-end',
      icon: 'success',
      title: escapar(logro.titulo),
      html:
        '<div class="text-start" style="font-size:.8125rem;">' +
        '  <div class="fw-semibold mb-1">' + escapar(logro.texto) + '</div>' +
        (total ?
        '  <div class="progress mb-1" style="height:5px;"><div class="progress-bar bg-info" style="width:' + porcentaje + '%;"></div></div>' +
        '  <div class="d-flex justify-content-between align-items-center">' +
        '    <small class="text-muted">' + hechas + ' de ' + total + ' en tu Guía</small>' +
        '    <a href="#" class="small fw-semibold orbith-ver-guia">Ver mi Guía</a>' +
        '  </div>' : '') +
        '</div>',
      showConfirmButton: false,
      // `avance`: una parte de una tarea ("✔ PDF — 1 de 3"), aviso breve.
      timer: logro.tipo === 'avance' ? 3500 : (logro.tipo === 'tarea' ? 5000 : 7000),
      timerProgressBar: true,
      background: '#fff',
      color: '#697a8d',
      customClass: { popup: 'border shadow-lg' },
      didOpen: function (toast) {
        toast.addEventListener('mouseenter', Swal.stopTimer);
        toast.addEventListener('mouseleave', Swal.resumeTimer);
        const enlace = toast.querySelector('.orbith-ver-guia');
        if (enlace) {
          enlace.addEventListener('click', function (e) {
            e.preventDefault();
            Swal.close();
            abrirPanelGuia();
          });
        }
      },
      // `didDestroy` y no `didClose`: también se ejecuta si otro aviso
      // reemplaza a este antes de tiempo, y así la cola nunca se queda parada.
      didDestroy: function () {
        mostrandoLogro = false;
        setTimeout(mostrarSiguienteLogro, 300);
      },
    });
  }

  function revisarLogros() {
    const nuevos = leerCookieLogros();
    if (!nuevos.length) return;
    const ya = idsMostrados();
    nuevos.forEach(function (logro) {
      if (!logro || !logro.id || ya.indexOf(logro.id) !== -1) return;
      recordarMostrado(logro.id);
      ya.push(logro.id);
      colaLogros.push(logro);
    });
    mostrarSiguienteLogro();
  }

  document.addEventListener('DOMContentLoaded', function () {
    revisarLogros();
    setInterval(revisarLogros, 1000);
  });

  // ------------------------------------------------------------------
  // Filtros del panel de la Guía (Todas / Pendientes / Completadas)
  //
  // El panel llega por fetch y se inyecta con innerHTML, así que sus
  // botones se atienden aquí con delegación. El filtro elegido se recuerda
  // en localStorage para la próxima vez que se abra la Guía.
  // ------------------------------------------------------------------
  const CLAVE_FILTRO = 'orbith_guia_filtro';

  function aplicarFiltroGuia(contenedor, filtro) {
    if (!contenedor || !contenedor.querySelector('[data-guia-filtro]')) return;
    if (['todas', 'pendiente', 'completada'].indexOf(filtro) === -1) filtro = 'todas';

    contenedor.querySelectorAll('[data-guia-filtro]').forEach(function (boton) {
      const activo = boton.dataset.guiaFiltro === filtro;
      boton.classList.toggle('activo', activo);
      boton.setAttribute('aria-pressed', activo ? 'true' : 'false');
    });

    let visibles = 0;
    contenedor.querySelectorAll('.guia-tarea').forEach(function (tarea) {
      const mostrar = filtro === 'todas' || tarea.dataset.guiaEstado === filtro;
      tarea.classList.toggle('d-none', !mostrar);
      if (mostrar) visibles += 1;
    });
    // Un grupo sin tareas visibles se oculta entero (no deja su título solo).
    contenedor.querySelectorAll('.guia-bloque').forEach(function (bloque) {
      bloque.classList.toggle('d-none', !bloque.querySelector('.guia-tarea:not(.d-none)'));
    });
    contenedor.querySelectorAll('[data-guia-vacio]').forEach(function (aviso) {
      aviso.classList.toggle('d-none', !(visibles === 0 && aviso.dataset.guiaVacio === filtro));
    });
  }

  document.addEventListener('click', function (e) {
    const boton = e.target.closest && e.target.closest('[data-guia-filtro]');
    if (!boton) return;
    try { localStorage.setItem(CLAVE_FILTRO, boton.dataset.guiaFiltro); } catch (err) { /* no crítico */ }
    aplicarFiltroGuia(boton.closest('#contenidoGuiaOrbith') || document, boton.dataset.guiaFiltro);
  });

  // La llama modales_usuario.html justo después de pintar el panel.
  window.orbithGuiaPanelCargado = function (contenedor) {
    let filtro = 'todas';
    try { filtro = localStorage.getItem(CLAVE_FILTRO) || 'todas'; } catch (err) { /* no crítico */ }
    aplicarFiltroGuia(contenedor, filtro);
  };

  document.addEventListener('DOMContentLoaded', function () {
    const estado = leerEstado();
    if (!estado || !estado.codigo) return;

    // Si esta pantalla tiene un recorrido visual para la tarea (por ejemplo,
    // el Gestor de Plantilla, ver `recorrido_gestor.js`), se usa ese en vez de
    // la tarjeta de texto. El estado se borra: el recorrido es de una sola
    // vez y se repite con el botón "¿Cómo funciona?" de la propia pantalla.
    const recorridos = window.OrbithRecorridos || {};
    if (typeof recorridos[estado.codigo] === 'function') {
      cerrarGuia();
      // Por `lanzar`: las guías que cambian datos reales piden confirmación
      // antes (salvo si ya se aceptó al empezar, en un tramo anterior).
      if (window.OrbithRecorrido && window.OrbithRecorrido.lanzar) window.OrbithRecorrido.lanzar(estado.codigo);
      else recorridos[estado.codigo]();
      return;
    }

    // Una clave con acceso concreto ("primera_contratacion:gestor") usa los
    // pasos escritos de su tarea si la pantalla no tiene ese recorrido.
    const codigoTarea = String(estado.codigo).split(':')[0];
    fetch('/progreso/tarea/' + encodeURIComponent(codigoTarea) + '/', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      cache: 'no-store',
    })
      .then(function (respuesta) {
        return respuesta.ok ? respuesta.json() : Promise.reject();
      })
      .then(function (datos) {
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
