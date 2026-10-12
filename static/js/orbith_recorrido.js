/**
 * Recorrido visual de Orbith (técnica de "spotlight").
 *
 * Oscurece la página y deja uno o varios huecos sobre lo que se explica, con
 * una flecha señalando cada hueco y una tarjeta con el texto del paso. Lo usa
 * el modo guiado de la Guía de Orbith (ver `progreso_guia.js`) y el botón
 * "¿Cómo funciona?" de las pantallas que tienen recorrido propio.
 *
 * Uso:
 *   OrbithRecorrido.iniciar({ pasos: [ { selector, titulo, texto, ... } ] });
 *
 * Cada paso admite:
 *   selector     CSS de lo que se señala. Si encuentra VARIOS elementos (por
 *                ejemplo "#a, #b, #c"), abre un hueco con su flecha sobre cada
 *                uno: así un mismo paso puede resaltar a la vez los botones de
 *                varias columnas. Si no encuentra ninguno visible, el paso se
 *                salta solo (un botón que el rol no tiene no deja el recorrido
 *                señalando la nada).
 *   titulo       Título corto de la tarjeta.
 *   texto        Explicación (texto o función que lo devuelve, para pasos
 *                cuyo mensaje cambia según lo que haga el usuario). Puede
 *                llevar HTML: solo se usan textos escritos en el propio
 *                código, nunca datos del usuario.
 *   interactivo  true si el usuario debe hacer clic DENTRO del hueco (elegir
 *                una unidad, un cargo...). En los demás pasos toda la página
 *                está bloqueada: el recorrido explica botones como Eliminar o
 *                Dar de Baja, y un clic por error no debe ejecutarlos.
 *   esperar      Función que devuelve un valor "verdadero" (por ejemplo, el id
 *                de lo seleccionado) cuando el usuario ya hizo lo que pide el
 *                paso. Mientras devuelva algo falso, "Siguiente" queda apagado.
 *                El recorrido avanza solo cuando el valor CAMBIA respecto al
 *                que había al entrar en el paso: al volver con `volver` a
 *                "Elige una unidad", la unidad anterior sigue marcada y no
 *                debe saltarse el paso antes de que el usuario elija otra.
 *   id           Nombre del paso, para poder volver a él con `volver`.
 *   volver       { a: id, texto } — enlace que regresa a un paso anterior.
 *                Sirve cuando el usuario no puede cumplir el paso con lo que
 *                eligió (una unidad sin departamentos, un cargo vacante): el
 *                hueco no deja hacer clic en la columna anterior, así que
 *                hace falta un camino de vuelta. Si lo señalado desaparece
 *                (por ejemplo, el usuario cerró el formulario), el recorrido
 *                vuelve solo a ese paso. Sin `texto`, solo hace esto último y
 *                no se pinta el enlace.
 *   avanceManual true en pasos de formulario: `esperar` solo enciende
 *                "Siguiente" (campos obligatorios rellenos), pero el recorrido
 *                NO avanza solo, porque el valor cambia con cada tecla.
 *   opcional     true para marcar el paso con la etiqueta "Opcional".
 *   textoEspera  Aviso mientras `esperar` no se cumple (por defecto, "Hazlo en
 *                el área resaltada para continuar.").
 *   alEntrar /   Funciones que se ejecutan al llegar al paso y al dejarlo
 *   alSalir      (por ejemplo, desplegar un menú para enseñarlo y volver a
 *                plegarlo). Se llaman también si el recorrido se cierra.
 *   paciencia    Milisegundos que se espera antes de dar por desaparecido lo
 *                señalado (900 por defecto). Útil cuando una ventana se cierra
 *                y la siguiente tarda en abrirse.
 *   terminarSiDesaparece  true en el último paso de un formulario: si lo
 *                señalado desaparece (la ventana se cerró al guardar o al
 *                cancelar), el recorrido termina en vez de quedarse colgado.
 *   accionSiguiente  { texto, ejecutar }: el botón "Siguiente" de este paso
 *                muestra `texto` y, al pulsarlo, llama a `ejecutar` en vez de
 *                avanzar. Se usa con `OrbithRecorrido.continuarEn` para seguir
 *                el recorrido en otra pantalla.
 *   acciones     [{ texto, icono?, ejecutar }]: botones extra bajo el texto,
 *                para ofrecer "¿Y ahora qué?" al final de un recorrido (por
 *                ejemplo, lanzar otro recorrido con `OrbithRecorrido.iniciar`,
 *                que cierra el actual).
 *   saltarSi     Función: si devuelve true, el paso se salta (por ejemplo,
 *                "elige un cargo" cuando ya hay uno elegido).
 *   preparar     Función que deja visible lo que señala el paso cuando no lo
 *                está (por ejemplo, cambiar a la pestaña "Salario" de un
 *                formulario). Se llama al buscar el paso, antes de decidir si
 *                se salta por no verse.
 *
 * Menús "¿Cómo funciona?": cualquier elemento con `data-recorrido="clave"`
 * lanza el recorrido registrado en `window.OrbithRecorridos[clave]`. Así una
 * misma pantalla puede ofrecer varios (crear un aspirante, contratar...).
 *
 * En los pasos interactivos también se puede usar la lista desplegable de un
 * Select2 abierto: se añade como un hueco más mientras está abierta. Y si sale
 * una confirmación de SweetAlert ("¿Estás seguro…?"), el recorrido se oculta
 * hasta que se cierre, para no taparla.
 *
 * La tarjeta se puede arrastrar por su barra superior. La posición elegida se
 * guarda en localStorage y se respeta en los pasos y recorridos siguientes,
 * como la tarjeta del modo guiado de texto; el botón de la barra la devuelve
 * a la colocación automática.
 *
 * No depende de ninguna librería: lo oscuro es un SVG con una máscara que
 * recorta los huecos, y una capa transparente frena los clics.
 */
(function () {
  // base.html lo carga en todas las páginas (para la guía de "Reportar
  // problema", que vive en una ventana común) y muchas pantallas lo cargan
  // otra vez para sus propios recorridos: la segunda carga no hace nada.
  if (window.OrbithRecorrido) return;

  const RELLENO = 6;          // Margen del hueco alrededor del elemento.
  const SEPARACION = 14;      // Distancia entre el hueco y la tarjeta.
  const TAM_FLECHA = 40;
  const ANCHO_TARJETA = 320;
  const MARGEN = 12;
  const CLAVE_POSICION = 'orbith_recorrido_posicion';
  const CLAVE_CONTINUACION = 'orbith_recorrido_continuacion';
  const SVG = 'http://www.w3.org/2000/svg';

  const EVENTOS_INMEDIATOS = ['input', 'change', 'pointerdown'];

  let estado = null;          // Recorrido en curso: { pasos, indice, capa, ... }.

  function inyectarEstilos() {
    if (document.getElementById('orbithRecorridoEstilos')) return;
    const css = document.createElement('style');
    css.id = 'orbithRecorridoEstilos';
    css.textContent = [
      '#orbithRecorrido { position: fixed; inset: 0; z-index: 1095; pointer-events: none; }',
      '.or-mascara { position: fixed; inset: 0; width: 100%; height: 100%; pointer-events: none; }',
      '.or-marco { position: fixed; border-radius: 10px; pointer-events: none; outline: 3px solid #03c3ec;',
      '  transition: top .25s ease, left .25s ease, width .25s ease, height .25s ease; }',
      '.or-marco.or-interactivo { animation: or-latido 1.4s ease-in-out infinite; }',
      '@keyframes or-latido { 0%,100% { outline-color: #03c3ec; } 50% { outline-color: #71dd37; } }',
      '.or-bloqueo { position: fixed; inset: 0; pointer-events: auto; background: transparent; }',
      '.or-flecha { position: fixed; font-size: 2.4rem; color: #03c3ec; line-height: 1;',
      '  text-shadow: 0 2px 6px rgba(0,0,0,.45); pointer-events: none; }',
      '.or-flecha.or-arriba, .or-flecha.or-abajo { animation: or-rebote-v 1s ease-in-out infinite; }',
      '.or-flecha.or-izquierda, .or-flecha.or-derecha { animation: or-rebote-h 1s ease-in-out infinite; }',
      '@keyframes or-rebote-v { 0%,100% { transform: translateY(0); } 50% { transform: translateY(6px); } }',
      '@keyframes or-rebote-h { 0%,100% { transform: translateX(0); } 50% { transform: translateX(6px); } }',
      '.or-tarjeta { position: fixed; width: ' + ANCHO_TARJETA + 'px; max-width: calc(100vw - ' + (MARGEN * 2) + 'px);',
      '  pointer-events: auto; margin: 0; }',
      '.or-arrastre { cursor: grab; touch-action: none; user-select: none; }',
      '.or-tarjeta .or-texto { font-size: .875rem; }',
      '.or-tarjeta .or-espera { font-size: .8rem; }',
      '@media (prefers-reduced-motion: reduce) {',
      '  .or-marco, .or-flecha { animation: none !important; transition: none !important; } }',
    ].join('\n');
    document.head.appendChild(css);
  }

  function visible(el) {
    return !!el && el.getClientRects().length > 0 && el.getBoundingClientRect().width > 2;
  }

  // Select2 esconde el <select> original (queda de 1 px, con la clase
  // `select2-hidden-accessible`) y pinta en su lugar un contenedor hermano.
  // Señalar el original dejaba el hueco en una raya junto al control real.
  function elementoVisual(el) {
    if (el && el.classList.contains('select2-hidden-accessible')) {
      const hermano = el.nextElementSibling;
      if (hermano && hermano.classList.contains('select2-container')) return hermano;
    }
    return el;
  }

  function elementosDelPaso(paso) {
    // El selector puede ser una función: así un paso puede señalar "la fila
    // del trabajador que el usuario eligió antes", que no se sabe de antemano.
    const selector = typeof paso.selector === 'function' ? paso.selector() : paso.selector;
    if (!selector) return [];
    return Array.prototype.map.call(document.querySelectorAll(selector), elementoVisual)
      .filter(visible);
  }

  function escapar(texto) {
    const div = document.createElement('div');
    div.textContent = texto;
    return div.innerHTML;
  }

  // Lista desplegable de un Select2 abierto: en un paso interactivo se trata
  // como un hueco más, para que se vea y se pueda elegir una opción.
  function desplegablesAbiertos() {
    return Array.prototype.filter.call(
      document.querySelectorAll('.select2-container--open .select2-dropdown'), visible);
  }

  function textoDelPaso(paso) {
    return typeof paso.texto === 'function' ? paso.texto() : (paso.texto || '');
  }

  function leerPosicion() {
    try { return JSON.parse(localStorage.getItem(CLAVE_POSICION)); } catch (e) { return null; }
  }

  function guardarPosicion(pos) {
    // localStorage puede fallar en modo privado: la tarjeta simplemente vuelve
    // a colocarse sola la próxima vez.
    try {
      if (pos) localStorage.setItem(CLAVE_POSICION, JSON.stringify(pos));
      else localStorage.removeItem(CLAVE_POSICION);
    } catch (e) { /* no crítico */ }
  }

  function crearCapa() {
    const capa = document.createElement('div');
    capa.id = 'orbithRecorrido';
    capa.innerHTML =
      '<svg class="or-mascara" xmlns="' + SVG + '">' +
      '  <defs><mask id="orMascaraRecorrido"><rect width="100%" height="100%" fill="white"></rect>' +
      '    <g class="or-recortes"></g></mask></defs>' +
      '  <rect width="100%" height="100%" fill="rgba(15, 23, 42, .62)" mask="url(#orMascaraRecorrido)"></rect>' +
      '</svg>' +
      '<div class="or-marcos"></div>' +
      '<div class="or-flechas"></div>' +
      '<div class="or-bloqueo"></div>' +
      '<div class="card shadow-lg border-info or-tarjeta" role="dialog" aria-live="polite">' +
      '  <div class="card-header bg-label-info d-flex justify-content-between align-items-center py-2 px-3 or-arrastre"' +
      '       title="Arrastra para mover">' +
      '    <small class="fw-semibold"><i class="bx bx-move me-1"></i><span class="or-contador"></span></small>' +
      '    <span class="d-flex align-items-center gap-2">' +
      '      <button type="button" class="btn btn-sm p-0 border-0 or-recolocar d-none" title="Volver a colocar junto al elemento">' +
      '        <i class="bx bx-reset"></i></button>' +
      '      <button type="button" class="btn-close or-salir" aria-label="Salir del recorrido"></button>' +
      '    </span>' +
      '  </div>' +
      '  <div class="card-body p-3">' +
      '    <h6 class="fw-bold mb-1 or-titulo"></h6>' +
      '    <div class="or-texto"></div>' +
      '    <div class="or-espera text-info mt-2 d-none">' +
      '      <i class="bx bx-pointer me-1"></i><span class="or-espera-texto"></span>' +
      '      <button type="button" class="btn btn-link btn-sm p-0 ms-1 or-saltar">Saltar este paso</button>' +
      '    </div>' +
      '    <button type="button" class="btn btn-link btn-sm p-0 mt-1 d-none or-volver"></button>' +
      '    <div class="d-flex flex-wrap gap-2 mt-2 d-none or-acciones"></div>' +
      '  </div>' +
      '  <div class="card-footer d-flex justify-content-between py-2">' +
      '    <button type="button" class="btn btn-sm btn-label-secondary or-anterior">Anterior</button>' +
      '    <button type="button" class="btn btn-sm btn-info or-siguiente">Siguiente</button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(capa);

    capa.querySelector('.or-salir').addEventListener('click', terminar);
    capa.querySelector('.or-anterior').addEventListener('click', function () { mover(-1); });
    capa.querySelector('.or-siguiente').addEventListener('click', function () { mover(1); });
    capa.querySelector('.or-saltar').addEventListener('click', function () { mover(1, true); });
    capa.querySelector('.or-volver').addEventListener('click', function () {
      const destino = estado && estado.pasos[estado.indice].volver;
      if (!destino) return;
      const indice = estado.pasos.findIndex(function (p) { return p.id === destino.a; });
      if (indice !== -1) mostrar(indice);
    });
    capa.querySelector('.or-acciones').addEventListener('click', function (e) {
      const boton = e.target.closest('[data-accion]');
      const paso = estado && estado.pasos[estado.indice];
      const accion = boton && paso && paso.acciones && paso.acciones[Number(boton.dataset.accion)];
      if (accion && typeof accion.ejecutar === 'function') accion.ejecutar();
    });
    capa.querySelector('.or-recolocar').addEventListener('click', function () {
      guardarPosicion(null);
      if (estado) estado.recalcularHasta = Date.now() + 300;
      colocar();
    });
    habilitarArrastre(capa.querySelector('.or-tarjeta'));
    return capa;
  }

  // Arrastre con Pointer Events (ratón, lápiz y dedo con la misma API), igual
  // que la tarjeta del modo guiado de texto.
  function habilitarArrastre(tarjeta) {
    const agarradera = tarjeta.querySelector('.or-arrastre');
    let desplazamiento = null;

    agarradera.addEventListener('pointerdown', function (e) {
      if (e.target.closest('button')) return;
      const r = tarjeta.getBoundingClientRect();
      desplazamiento = { x: e.clientX - r.left, y: e.clientY - r.top };
      if (estado) estado.arrastrando = true;
      agarradera.setPointerCapture(e.pointerId);
      agarradera.style.cursor = 'grabbing';
    });
    agarradera.addEventListener('pointermove', function (e) {
      if (!desplazamiento) return;
      const pos = limitar({ top: e.clientY - desplazamiento.y, left: e.clientX - desplazamiento.x }, tarjeta);
      tarjeta.style.top = pos.top + 'px';
      tarjeta.style.left = pos.left + 'px';
    });
    function soltar() {
      if (!desplazamiento) return;
      desplazamiento = null;
      if (estado) estado.arrastrando = false;
      agarradera.style.cursor = '';
      guardarPosicion({ top: parseInt(tarjeta.style.top, 10), left: parseInt(tarjeta.style.left, 10) });
      if (estado) estado.capa.querySelector('.or-recolocar').classList.remove('d-none');
    }
    agarradera.addEventListener('pointerup', soltar);
    agarradera.addEventListener('pointercancel', soltar);
    // Si el navegador retira la captura del puntero (por ejemplo, al cambiar
    // de ventana a mitad del arrastre), se suelta igual: si no, la tarjeta se
    // quedaría marcada como "arrastrando" y dejaría de colocarse.
    agarradera.addEventListener('lostpointercapture', soltar);
  }

  function limitar(pos, tarjeta) {
    const tw = tarjeta.offsetWidth || ANCHO_TARJETA;
    const th = tarjeta.offsetHeight || 180;
    return {
      top: Math.min(Math.max(MARGEN, pos.top), Math.max(MARGEN, window.innerHeight - th - MARGEN)),
      left: Math.min(Math.max(MARGEN, pos.left), Math.max(MARGEN, window.innerWidth - tw - MARGEN)),
    };
  }

  // Siguiente paso visible en la dirección indicada, o -1 si no queda ninguno.
  // `soloMirar`: solo se quiere saber SI hay paso (para encender "Anterior"),
  // no ir a él. Entonces no se llama a `preparar`, que cambia la pantalla: al
  // comprobar el paso anterior volvía a abrir su pestaña y deshacía la del
  // paso actual (Subsanación: Dashboard → Hallazgos). Un paso con `preparar`
  // cuenta como disponible.
  function buscarPaso(desde, direccion, soloMirar) {
    for (let i = desde; i >= 0 && i < estado.pasos.length; i += direccion) {
      const paso = estado.pasos[i];
      if (typeof paso.saltarSi === 'function' && paso.saltarSi()) continue;
      if (soloMirar && typeof paso.preparar === 'function') return i;
      if (!elementosDelPaso(paso).length && typeof paso.preparar === 'function') {
        try { paso.preparar(); } catch (e) { /* si no se puede preparar, se salta */ }
      }
      if (elementosDelPaso(paso).length) return i;
    }
    return -1;
  }

  function mover(direccion, forzar) {
    if (!estado) return;
    const paso = estado.pasos[estado.indice];
    if (direccion > 0 && paso.esperar && !forzar && !paso.esperar()) return;
    // Paso con botón propio ("Continuar en Mov. Nómina"): hace su acción en
    // vez de pasar al siguiente paso.
    if (direccion > 0 && !forzar && paso.accionSiguiente) {
      paso.accionSiguiente.ejecutar();
      return;
    }

    const siguiente = buscarPaso(estado.indice + direccion, direccion);
    if (siguiente === -1) {
      if (direccion > 0) terminar();
      return;
    }
    mostrar(siguiente);
  }

  function mostrarEspera(visible) {
    estado.capa.querySelector('.or-espera').style.visibility = visible ? '' : 'hidden';
  }

  // Llama a `alSalir` del paso que se abandona (si lo tiene).
  function salirDelPaso() {
    const anterior = estado && estado.pasos[estado.indice];
    if (anterior && estado.entrado && typeof anterior.alSalir === 'function') {
      try { anterior.alSalir(); } catch (e) { /* un fallo aquí no debe parar el recorrido */ }
    }
    if (estado) estado.entrado = false;
  }

  function mostrar(indice) {
    salirDelPaso();
    estado.indice = indice;
    estado.cumplido = false;
    const paso = estado.pasos[indice];
    if (typeof paso.alEntrar === 'function') {
      try { paso.alEntrar(); } catch (e) { /* idem */ }
    }
    estado.entrado = true;
    estado.valorInicial = paso.esperar ? paso.esperar() : null;
    const capa = estado.capa;
    if (!elementosDelPaso(paso).length && typeof paso.preparar === 'function') {
      try { paso.preparar(); } catch (e) { /* idem */ }
    }
    const elementos = elementosDelPaso(paso);
    if (!elementos.length) { mover(1, true); return; }

    // Se cuentan todos los pasos del recorrido (cada pantalla ya los filtra por
    // rol), y no solo los que se ven ahora: los del formulario de Aspirantes,
    // por ejemplo, no existen hasta que se abre la ventana.
    capa.querySelector('.or-contador').textContent = 'Paso ' + (indice + 1) + ' de ' + estado.pasos.length;
    capa.querySelector('.or-titulo').innerHTML = escapar(paso.titulo || '') +
      (paso.opcional ? ' <span class="badge bg-label-secondary ms-1" style="font-size:.65rem;">Opcional</span>' : '');
    estado.textoMostrado = textoDelPaso(paso);
    capa.querySelector('.or-texto').innerHTML = estado.textoMostrado;

    estado.ausenteDesde = null;
    capa.querySelector('.or-espera-texto').textContent =
      paso.textoEspera || 'Hazlo en el área resaltada para continuar.';
    const esperando = !!paso.esperar && !estado.valorInicial;
    // El aviso de espera ocupa su sitio durante TODO el paso (si lo tiene) y
    // solo se vuelve invisible al cumplirse: si desapareciera del todo, la
    // tarjeta encogería y "Siguiente" se movería justo cuando el usuario va a
    // pulsarlo, y el primer clic caería en el vacío.
    capa.querySelector('.or-espera').classList.toggle('d-none', !paso.esperar);
    mostrarEspera(esperando);
    capa.querySelector('.or-siguiente').disabled = esperando;
    capa.querySelector('.or-anterior').disabled = buscarPaso(indice - 1, -1, true) === -1;
    capa.querySelector('.or-siguiente').textContent = paso.accionSiguiente
      ? paso.accionSiguiente.texto
      // "Entendido" también cuando los pasos que quedan se van a saltar (por
      // ejemplo, uno solo del Administrador visto por un Moderador).
      : (buscarPaso(indice + 1, 1, true) === -1 ? 'Entendido' : 'Siguiente');
    const volver = capa.querySelector('.or-volver');
    // Un `volver` sin texto solo sirve para regresar solo si lo señalado
    // desaparece: no se pinta el enlace.
    const conEnlace = !!(paso.volver && paso.volver.texto);
    volver.classList.toggle('d-none', !conEnlace);
    volver.innerHTML = conEnlace ? '<i class="bx bx-undo me-1"></i>' + paso.volver.texto : '';
    const acciones = capa.querySelector('.or-acciones');
    const lista = Array.isArray(paso.acciones) ? paso.acciones : [];
    acciones.classList.toggle('d-none', !lista.length);
    acciones.innerHTML = lista.map(function (accion, i) {
      return '<button type="button" class="btn btn-sm btn-outline-info" data-accion="' + i + '">' +
        (accion.icono ? '<i class="bx ' + escapar(accion.icono) + ' me-1"></i>' : '') + escapar(accion.texto) + '</button>';
    }).join('');
    capa.querySelector('.or-recolocar').classList.toggle('d-none', !leerPosicion());

    // La tarjeta se coloca durante los primeros 700 ms del paso (lo que dura
    // el desplazamiento suave) y después se queda fija hasta el siguiente.
    estado.posAuto = null;
    estado.recalcularHasta = Date.now() + 700;
    elementos[0].scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
    colocar();
    // El desplazamiento suave tarda: se recoloca cuando termina.
    setTimeout(colocar, 400);
  }

  // Funde los rectángulos que se solapan en el rectángulo que los abarca,
  // hasta que no quede ningún par solapado.
  function fundirSolapados(rects) {
    const lista = rects.map(function (r) { return { top: r.top, left: r.left, width: r.width, height: r.height }; });
    let fundido = true;
    while (fundido) {
      fundido = false;
      for (let i = 0; i < lista.length && !fundido; i++) {
        for (let j = i + 1; j < lista.length && !fundido; j++) {
          const a = lista[i];
          const b = lista[j];
          if (a.left < b.left + b.width && a.left + a.width > b.left &&
              a.top < b.top + b.height && a.top + a.height > b.top) {
            const top = Math.min(a.top, b.top);
            const left = Math.min(a.left, b.left);
            lista[i] = {
              top: top, left: left,
              width: Math.max(a.left + a.width, b.left + b.width) - left,
              height: Math.max(a.top + a.height, b.top + b.height) - top,
            };
            lista.splice(j, 1);
            fundido = true;
          }
        }
      }
    }
    return lista;
  }

  function rectHueco(el) {
    const r = el.getBoundingClientRect();
    return {
      top: Math.max(0, r.top - RELLENO),
      left: Math.max(0, r.left - RELLENO),
      width: r.width + RELLENO * 2,
      height: r.height + RELLENO * 2,
    };
  }

  function colocar() {
    if (!estado) return;
    const paso = estado.pasos[estado.indice];
    const elementos = elementosDelPaso(paso);
    if (!elementos.length) return;
    const capa = estado.capa;
    const huecos = elementos.map(rectHueco);
    // Los desplegables solo amplían lo pulsable; la tarjeta y las flechas se
    // siguen calculando sobre lo que señala el paso.
    const huecosPulsables = paso.interactivo ? huecos.concat(desplegablesAbiertos().map(rectHueco)) : [];
    const ancho = window.innerWidth;
    const alto = window.innerHeight;

    // 1. Recortes de la máscara (lo oscuro): un hueco por cada elemento del
    // paso y, en los interactivos, también por cada desplegable abierto.
    const recortados = paso.interactivo ? huecosPulsables : huecos;
    const recortes = capa.querySelector('.or-recortes');
    while (recortes.childNodes.length > recortados.length) recortes.lastChild.remove();
    recortados.forEach(function (h, i) {
      let rect = recortes.childNodes[i];
      if (!rect) {
        rect = document.createElementNS(SVG, 'rect');
        rect.setAttribute('rx', '10');
        rect.setAttribute('fill', 'black');
        recortes.appendChild(rect);
      }
      rect.setAttribute('x', h.left); rect.setAttribute('y', h.top);
      rect.setAttribute('width', h.width); rect.setAttribute('height', h.height);
    });

    // Una lista desplegable abierta debe verse limpia: los marcos y flechas
    // de los OTROS campos del bloque que caen encima de ella se ocultan
    // mientras está abierta (si no, el marco de "Dirección" o de "Grado
    // científico" cruzaba la lista de provincias o de niveles).
    const desplegables = paso.interactivo ? desplegablesAbiertos().map(function (d) { return d.getBoundingClientRect(); }) : [];
    function pisaDesplegable(top, left, width, height) {
      return desplegables.some(function (d) {
        return left < d.right && left + width > d.left && top < d.bottom && top + height > d.top;
      });
    }

    // Marcos de color: solo sobre lo que señala el paso.
    const marcos = capa.querySelector('.or-marcos');
    while (marcos.childNodes.length > huecos.length) marcos.lastChild.remove();
    huecos.forEach(function (h, i) {
      let marco = marcos.childNodes[i];
      if (!marco) { marco = document.createElement('div'); marco.className = 'or-marco'; marcos.appendChild(marco); }
      marco.classList.toggle('or-interactivo', !!paso.interactivo);
      marco.style.top = h.top + 'px'; marco.style.left = h.left + 'px';
      marco.style.width = h.width + 'px'; marco.style.height = h.height + 'px';
      marco.style.visibility = pisaDesplegable(h.top, h.left, h.width, h.height) ? 'hidden' : '';
    });

    // 2. Una sola capa transparente frena los clics en toda la pantalla. En
    // un paso interactivo se le recortan los huecos con `clip-path` (regla
    // evenodd): el navegador no le entrega clics en la parte recortada, así
    // que se puede escribir y elegir en TODOS los campos resaltados a la vez,
    // y un clic fuera no llega al fondo (ni cierra la ventana del formulario).
    // En los demás pasos la capa tapa todo, incluido lo resaltado.
    const bloqueo = capa.querySelector('.or-bloqueo');
    if (paso.interactivo) {
      // Con la regla evenodd, una zona cubierta por DOS huecos (la lista de
      // provincias abierta encima del campo "Dirección") vuelve a quedar
      // tapada: se recorta dos veces y se "descuenta". Por eso los huecos que
      // se solapan se funden antes en un único rectángulo que los abarca.
      const trazo = fundirSolapados(huecosPulsables).map(function (h) {
        return 'M' + h.left + ' ' + h.top + 'h' + h.width + 'v' + h.height + 'h' + (-h.width) + 'Z';
      }).join(' ');
      bloqueo.style.clipPath = "path(evenodd, 'M0 0H" + ancho + 'V' + alto + 'H0Z ' + trazo + "')";
    } else {
      bloqueo.style.clipPath = 'none';
    }

    // Mientras el usuario arrastra la tarjeta, no se toca: esta función se
    // ejecuta cada 300 ms y con cada desplazamiento de la página, y antes
    // devolvía la tarjeta a su última posición guardada a mitad del arrastre
    // (parpadeaba y a veces saltaba a otro sitio).
    if (!estado.arrastrando) {
      // 3. Tarjeta: donde la dejó el usuario o, si no la ha movido, junto a lo
      // resaltado (debajo si cabe; si no, encima; si tampoco, a un lado).
      const tarjeta = capa.querySelector('.or-tarjeta');
      const tw = tarjeta.offsetWidth || ANCHO_TARJETA;
      const th = tarjeta.offsetHeight || 180;
      const guardada = leerPosicion();
      let pos;
      if (guardada) {
        pos = limitar(guardada, tarjeta);
      } else if (estado.posAuto && Date.now() > estado.recalcularHasta) {
        // Ya colocada en este paso: se queda quieta. Si un aviso de validación
        // desplaza los campos, la tarjeta no debe moverse bajo el ratón.
        pos = limitar(estado.posAuto, tarjeta);
      } else {
        const caja = huecos.reduce(function (a, h) {
          const top = Math.min(a.top, h.top);
          const left = Math.min(a.left, h.left);
          return {
            top: top, left: left,
            width: Math.max(a.left + a.width, h.left + h.width) - left,
            height: Math.max(a.top + a.height, h.top + h.height) - top,
          };
        });
        const bajo = caja.top + caja.height;
        const der = caja.left + caja.width;
        const holgura = SEPARACION + TAM_FLECHA;
        if (bajo + holgura + th <= alto) {
          pos = { top: bajo + holgura, left: caja.left + caja.width / 2 - tw / 2 };
        } else if (caja.top - holgura - th >= 0) {
          pos = { top: caja.top - holgura - th, left: caja.left + caja.width / 2 - tw / 2 };
        } else if (der + holgura + tw <= ancho) {
          pos = { top: caja.top + caja.height / 2 - th / 2, left: der + holgura };
        } else if (caja.left - holgura - tw >= 0) {
          pos = { top: caja.top + caja.height / 2 - th / 2, left: caja.left - holgura - tw };
        } else {
          // Lo resaltado ocupa casi toda la pantalla: tarjeta abajo, encima.
          pos = { top: alto - th - MARGEN, left: ancho / 2 - tw / 2 };
        }
        pos = limitar(pos, tarjeta);
        estado.posAuto = pos;
      }
      tarjeta.style.top = pos.top + 'px';
      tarjeta.style.left = pos.left + 'px';

      // Una lista desplegable abierta encima de la tarjeta (se abren hacia
      // arriba si abajo no caben) quedaría tapada por ella y sus opciones no se
      // podrían pulsar: mientras dure, la tarjeta se aparta.
      const rt = tarjeta.getBoundingClientRect();
      const tapada = paso.interactivo && desplegablesAbiertos().some(function (d) {
        const rd = d.getBoundingClientRect();
        return rd.left < rt.right && rd.right > rt.left && rd.top < rt.bottom && rd.bottom > rt.top;
      });
      tarjeta.style.opacity = tapada ? '0.15' : '';
      tarjeta.style.pointerEvents = tapada ? 'none' : '';
    }

    // 4. Una flecha por hueco, del lado donde haya sitio, apuntando a él. Si
    // el hueco es casi toda la pantalla (el paso de bienvenida), sin flecha.
    const flechas = capa.querySelector('.or-flechas');
    while (flechas.childNodes.length > huecos.length) flechas.lastChild.remove();
    huecos.forEach(function (h, i) {
      let f = flechas.childNodes[i];
      if (!f) { f = document.createElement('i'); flechas.appendChild(f); }
      const bajo = h.top + h.height;
      const der = h.left + h.width;
      const cx = h.left + h.width / 2 - TAM_FLECHA / 2;
      const cy = h.top + h.height / 2 - TAM_FLECHA / 2;
      let dir = null;
      if (bajo + TAM_FLECHA + 4 <= alto) dir = 'arriba';
      else if (h.top - TAM_FLECHA - 4 >= 0) dir = 'abajo';
      else if (der + TAM_FLECHA + 4 <= ancho) dir = 'izquierda';
      else if (h.left - TAM_FLECHA - 4 >= 0) dir = 'derecha';
      const iconos = { arriba: 'bx-up-arrow-alt', abajo: 'bx-down-arrow-alt',
                       izquierda: 'bx-left-arrow-alt', derecha: 'bx-right-arrow-alt' };
      f.className = dir ? 'bx or-flecha ' + iconos[dir] + ' or-' + dir : 'd-none';
      if (dir === 'arriba') { f.style.top = (bajo + 4) + 'px'; f.style.left = cx + 'px'; }
      if (dir === 'abajo') { f.style.top = (h.top - TAM_FLECHA - 4) + 'px'; f.style.left = cx + 'px'; }
      if (dir === 'izquierda') { f.style.left = (der + 4) + 'px'; f.style.top = cy + 'px'; }
      if (dir === 'derecha') { f.style.left = (h.left - TAM_FLECHA - 4) + 'px'; f.style.top = cy + 'px'; }
      f.style.visibility = dir && pisaDesplegable(parseFloat(f.style.top), parseFloat(f.style.left), TAM_FLECHA, TAM_FLECHA)
        ? 'hidden' : '';
    });
  }

  // Cada 300 ms: actualiza el texto si cambió, comprueba si el paso
  // interactivo ya se cumplió y recoloca los huecos (las columnas del Gestor
  // cambian de tamaño al cargarse por HTMX).
  function vigilar() {
    if (!estado) return;
    const paso = estado.pasos[estado.indice];
    const capa = estado.capa;

    if (typeof paso.texto === 'function') {
      const texto = paso.texto();
      if (texto !== estado.textoMostrado) {
        estado.textoMostrado = texto;
        capa.querySelector('.or-texto').innerHTML = texto;
      }
    }

    // Confirmación de SweetAlert abierta ("¿Estás seguro…?"): el recorrido se
    // aparta hasta que se cierre. Los toasts (como el aviso de un logro) no
    // cuentan: no tapan nada.
    // Un aviso que ya se está cerrando (`swal2-hide`) no cuenta: si su
    // animación de cierre tarda o no llega a terminar, el recorrido no debe
    // quedarse oculto esperándola.
    const confirmacion = typeof Swal !== 'undefined' && Swal.isVisible() &&
      !document.querySelector('.swal2-container .swal2-toast') &&
      !document.querySelector('.swal2-popup.swal2-hide');
    capa.style.display = confirmacion ? 'none' : '';
    if (confirmacion) return;

    // Primero, ¿ya hizo el usuario lo que pide el paso? Se mira ANTES que la
    // desaparición: al pulsar "Continuar" el formulario se cierra y la ventana
    // siguiente tarda un poco en abrirse; eso no es "cerró la ventana".
    const valor = paso.esperar ? paso.esperar() : null;
    if (!paso.avanceManual && valor && valor !== estado.valorInicial && !estado.cumplido) {
      estado.cumplido = true;
      mostrarEspera(false);
      capa.querySelector('.or-siguiente').disabled = false;
      // Un instante para que el usuario vea el resultado de su clic.
      setTimeout(function () {
        if (estado && estado.pasos[estado.indice] === paso) mover(1, true);
      }, 700);
    }

    // Lo señalado desapareció (el usuario cerró el formulario, por ejemplo).
    // Se espera `paciencia` milisegundos (900 por defecto) antes de volver al
    // paso de `volver` o de terminar, por si es solo un cambio de ventana.
    if (!elementosDelPaso(paso).length) {
      if (estado.cumplido) return;
      if (!estado.ausenteDesde) estado.ausenteDesde = Date.now();
      if (Date.now() - estado.ausenteDesde < (paso.paciencia || 900)) return;
      if (paso.terminarSiDesaparece) { terminar(); return; }
      if (paso.volver) {
        const destino = estado.pasos.findIndex(function (p) { return p.id === paso.volver.a; });
        if (destino !== -1) { mostrar(destino); return; }
      }
      return;
    }
    estado.ausenteDesde = null;

    if (paso.avanceManual) {
      capa.querySelector('.or-siguiente').disabled = !valor;
      mostrarEspera(!valor);
    }
    colocar();
  }

  // Rueda del ratón. Chrome decide qué se desplaza con una prueba rápida que
  // ignora el recorte (`clip-path`) de la capa de bloqueo, así que con el
  // recorrido activo la rueda no movía ni la lista de provincias ni el
  // formulario. Se atiende aquí: se busca lo que hay DEBAJO de la capa en
  // ese punto y se desplaza su contenedor desplazable más cercano (la lista,
  // el cuerpo de la ventana o la página). Desplazar no cambia ningún dato.
  function alRodar(e) {
    if (!estado) return;
    if (e.target.closest && e.target.closest('.or-tarjeta')) return;  // dentro de la tarjeta: normal
    const capa = estado.capa;
    capa.style.visibility = 'hidden';
    const debajo = document.elementFromPoint(e.clientX, e.clientY);
    capa.style.visibility = '';
    let el = debajo;
    while (el && el !== document.body && el !== document.documentElement) {
      const estilo = getComputedStyle(el);
      if (/(auto|scroll)/.test(estilo.overflowY) && el.scrollHeight > el.clientHeight + 1) break;
      el = el.parentElement;
    }
    const destino = (el && el !== document.body && el !== document.documentElement)
      ? el : (document.scrollingElement || document.documentElement);
    const factor = e.deltaMode === 1 ? 16 : (e.deltaMode === 2 ? destino.clientHeight : 1);
    e.preventDefault();
    destino.scrollBy({ top: e.deltaY * factor, left: e.deltaX * factor });
  }

  function alRedimensionar() {
    if (!estado) return;
    estado.recalcularHasta = Date.now() + 300;
    colocar();
  }

  function alTeclear(e) {
    // Con una lista desplegable abierta, Esc es para cerrar esa lista, no
    // el recorrido entero.
    if (estado && e.key === 'Escape' && !desplegablesAbiertos().length) terminar();
  }

  function terminar() {
    if (!estado) return;
    salirDelPaso();
    clearInterval(estado.intervalo);
    window.removeEventListener('resize', alRedimensionar);
    document.removeEventListener('wheel', alRodar, { passive: false, capture: true });
    window.removeEventListener('scroll', colocar, true);
    EVENTOS_INMEDIATOS.forEach(function (tipo) { document.removeEventListener(tipo, vigilar, true); });
    if (window.jQuery) window.jQuery(document).off('.orbithRecorrido');
    document.removeEventListener('keydown', alTeclear);
    estado.capa.remove();
    const alTerminar = estado.alTerminar;
    estado = null;
    if (typeof alTerminar === 'function') alTerminar();
  }

  window.OrbithRecorrido = {
    iniciar: function (opciones) {
      if (estado) terminar();
      const pasos = (opciones && opciones.pasos) || [];
      if (!pasos.length) return;
      inyectarEstilos();
      estado = {
        pasos: pasos,
        indice: 0,
        cumplido: false,
        alTerminar: opciones.alTerminar,
        capa: crearCapa(),
      };
      window.addEventListener('resize', alRedimensionar);
      document.addEventListener('wheel', alRodar, { passive: false, capture: true });
      window.addEventListener('scroll', colocar, true);
      // Además de la revisión periódica, se revisa AL MOMENTO cuando cambia un
      // campo y cuando se pulsa el ratón (en fase de captura, antes de que
      // llegue el clic). Sin esto, quien elegía una opción y pulsaba
      // "Siguiente" enseguida encontraba el botón aún apagado —o la tarjeta
      // aún atenuada por la lista que acababa de cerrarse— y tenía que pulsar
      // dos veces.
      EVENTOS_INMEDIATOS.forEach(function (tipo) { document.addEventListener(tipo, vigilar, true); });
      // Select2 avisa de que una lista se cerró con un evento de jQuery, no
      // con uno nativo: se escucha aparte para devolver la tarjeta enseguida.
      if (window.jQuery) {
        window.jQuery(document).on('select2:close.orbithRecorrido select2:select.orbithRecorrido', function () {
          setTimeout(vigilar, 0);
        });
      }
      document.addEventListener('keydown', alTeclear);
      estado.intervalo = setInterval(vigilar, 300);

      const primero = buscarPaso(0, 1);
      if (primero === -1) { terminar(); return; }
      mostrar(primero);
    },
    terminar: terminar,
    activo: function () { return !!estado; },
    // Sigue el recorrido en otra pantalla: guarda `datos` (por ejemplo, qué
    // contrato eligió el usuario), deja pedido el recorrido `clave` y navega a
    // `url`. Allí `progreso_guia.js` lo lanza al cargar, y el recorrido lee
    // los datos con `datosContinuacion()`.
    continuarEn: function (url, clave, datos) {
      try { sessionStorage.setItem(CLAVE_CONTINUACION, JSON.stringify(datos || {})); } catch (e) { /* no crítico */ }
      if (window.orbithIniciarGuia) window.orbithIniciarGuia(clave);
      terminar();
      window.location.href = url;
    },
    datosContinuacion: function () {
      try { return JSON.parse(sessionStorage.getItem(CLAVE_CONTINUACION)) || {}; } catch (e) { return {}; }
    },
    // Lanza el recorrido registrado como `clave`. Si es una de las guías que
    // cambian datos reales (AVISOS), antes pide confirmación. La usan los
    // menús "¿Cómo funciona?", la Guía de Orbith (progreso_guia.js) y los
    // botones que encadenan una guía con otra.
    lanzar: lanzar,
  };

  // ------------------------------------------------------------------
  // Aviso "Antes de empezar" de las guías que trabajan con datos reales.
  // ------------------------------------------------------------------
  // Solo las ENTRADAS de las guías que crean, cambian o envían algo de verdad;
  // las de consultar, buscar o exportar no lo llevan, para que no se acabe
  // ignorando. Los tramos que siguen en otra página (`:hecho`, `:fase2`...)
  // no están aquí: el aviso ya se aceptó al empezar.
  const AVISOS = {
    'primer_aspirante': 'Si la completas, se registrará un aspirante nuevo.',
    'primera_contratacion:aspirantes': 'Si la completas, se creará un contrato de trabajo y el aspirante pasará a Activo.',
    'primera_contratacion:gestor': 'Si la completas, se creará un contrato de trabajo y el aspirante pasará a Activo.',
    'primera_contratacion:contratos': 'Si la completas, se creará un contrato de trabajo y el aspirante pasará a Activo.',
    'primer_movimiento_interno:contratos': 'Si la completas, se aplicará un movimiento de nómina: cambiará el cargo, la unidad o el salario del trabajador.',
    'primer_movimiento_interno:gestor': 'Si la completas, se aplicará un movimiento de nómina: cambiará el cargo, la unidad o el salario del trabajador.',
    'primer_movimiento_interno:movnomina': 'Si la completas, se aplicará un movimiento de nómina: cambiará el cargo, la unidad o el salario del trabajador.',
    'primer_movimiento_cedido:contratos': 'Si la completas, el contrato quedará en proceso para que otro moderador lo incorpore a su unidad.',
    'primer_movimiento_cedido:gestor': 'Si la completas, el contrato quedará en proceso para que otro moderador lo incorpore a su unidad.',
    'primer_movimiento_recibido:movnomina': 'Si la completas, el trabajador pasará a tu unidad con su nuevo cargo.',
    'primera_baja:contratos': 'Si la completas, el trabajador causará baja: su contrato termina y pasa a la lista de Bajas.',
    'primera_baja:gestor': 'Si la completas, el trabajador causará baja: su contrato termina y pasa a la lista de Bajas.',
    'primer_cierre_declarado:gestor': 'Si la completas, la unidad quedará declarada para el cierre del mes y se guardará su fotografía.',
    'primera_solicitud_enviada:gestor': 'Si la completas, se enviará a los Administradores una solicitud de cambio real.',
    'primera_solicitud_decidida:solicitudes': 'Si la completas, aprobarás o rechazarás una solicitud real de un Moderador. Si la apruebas, el cambio se aplica en ese momento.',
    'primera_solicitud_decidida:revisar': 'Si la completas, aprobarás o rechazarás una solicitud real de un Moderador. Si la apruebas, el cambio se aplica en ese momento.',
    'primer_recordatorio_creado:notificaciones': 'Si la completas, se enviará un recordatorio real a los moderadores de la unidad que elijas.',
    'primer_recordatorio_creado:administracion': 'Si la completas, se enviará un recordatorio real a los moderadores de la unidad que elijas.',
    'primer_recordatorio_completado:notificaciones': 'Si la completas, marcarás como hecho un recordatorio real: dejará de estar pendiente para todos.',
    'primer_recordatorio_completado:sistema': 'Si la completas, marcarás como hecho un recordatorio real: dejará de estar pendiente para todos.',
    'primera_revision_hallazgo:subsanacion': 'Si la completas, cambiarás el estado de un hallazgo real y quedará en su historial.',
    'primer_analisis_subsanacion:subsanacion': 'Si la completas, se analizará toda la base de datos. No modifica ningún dato, pero guarda sus resultados y puede tardar unos minutos.',
    'primer_reporte_problema:global': 'Si la completas, se enviará un reporte al Administrador.',
    'primer_informe_favorito:informe': 'Si la completas, se guardará un informe en tus favoritos (solo lo ves tú).',
  };
  // Aceptado una vez, no se repite durante un rato para la misma tarea: así no
  // vuelve a salir cuando la guía sigue en otra página.
  const CLAVE_AVISOS = 'orbith_recorrido_avisos';
  const VIGENCIA_AVISO = 15 * 60 * 1000;

  function grupoDe(clave) { return String(clave).split(':')[0]; }

  function avisoAceptado(clave) {
    try {
      const aceptados = JSON.parse(sessionStorage.getItem(CLAVE_AVISOS)) || {};
      return Date.now() - (aceptados[grupoDe(clave)] || 0) < VIGENCIA_AVISO;
    } catch (e) { return false; }
  }

  function recordarAviso(clave) {
    try {
      const aceptados = JSON.parse(sessionStorage.getItem(CLAVE_AVISOS)) || {};
      aceptados[grupoDe(clave)] = Date.now();
      sessionStorage.setItem(CLAVE_AVISOS, JSON.stringify(aceptados));
    } catch (e) { /* sin sessionStorage, el aviso sale cada vez: no es grave */ }
  }

  function pedirConfirmacion(texto, continuar) {
    const html = '<div class="text-start" style="font-size:.9rem;">' +
      '<p>Esta guía trabaja con <strong>datos reales</strong> de Orbith: lo que hagas en ella se guarda de verdad.</p>' +
      '<p>' + texto + '</p>' +
      '<p class="mb-0">Hazla solo si <strong>necesitas realizar esta actividad</strong> ahora.</p></div>';
    if (typeof Swal === 'undefined') {
      if (window.confirm('Esta guía trabaja con datos reales de Orbith. ' + texto + ' ¿Continuar?')) continuar();
      return;
    }
    Swal.fire({
      icon: 'warning',
      title: 'Antes de empezar',
      html: html,
      showCancelButton: true,
      confirmButtonText: 'Entendido, continuar',
      cancelButtonText: 'Ahora no',
      customClass: { confirmButton: 'btn btn-warning me-2', cancelButton: 'btn btn-label-secondary' },
      buttonsStyling: false,
    }).then(function (resultado) { if (resultado.isConfirmed) continuar(); });
  }

  function lanzar(clave) {
    const iniciar = (window.OrbithRecorridos || {})[clave];
    if (typeof iniciar !== 'function') return false;
    const aviso = AVISOS[clave];
    if (!aviso || avisoAceptado(clave)) { iniciar(); return true; }
    if (estado) terminar();
    pedirConfirmacion(aviso, function () { recordarAviso(clave); iniciar(); });
    return true;
  }

  // Menús "¿Cómo funciona?": un clic en `[data-recorrido]` lanza ese recorrido.
  document.addEventListener('click', function (e) {
    const disparador = e.target.closest && e.target.closest('[data-recorrido]');
    if (!disparador) return;
    if (typeof (window.OrbithRecorridos || {})[disparador.dataset.recorrido] !== 'function') return;
    e.preventDefault();
    lanzar(disparador.dataset.recorrido);
  });
})();
