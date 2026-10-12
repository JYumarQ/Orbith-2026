/**
 * Comportamiento común de las tablas de Orbith (static/css/orbith-tablas.css).
 *
 * - «Justa en la pantalla»: la tarjeta de la tabla mide como mucho lo que queda
 *   de pantalla debajo de ella, así que al abrir la página se ve entera —con la
 *   paginación— y la página no se desplaza nunca: solo las filas, dentro de la
 *   tarjeta. Se calcula al cargar y al cambiar el tamaño de la ventana (el CSS
 *   da un valor aproximado por si este script no llegara a ejecutarse). Una
 *   tabla con pocas filas sigue midiendo lo suyo.
 * - «Filas por página»: el pie (base/partials/tabla_paginacion.html) recarga la
 *   tabla con HTMX; aquí solo se GUARDA el valor en las preferencias del
 *   usuario, que es uno para todas las tablas.
 * - Al cambiar de página, filtrar o buscar, la tabla vuelve a su primera fila.
 */
(function () {
  if (window.OrbithTablas) return;
  window.OrbithTablas = true;

  // Alto mínimo de la tarjeta (pantallas muy bajas): por debajo de esto,
  // mejor que se desplace la página que no ver casi ninguna fila.
  const ALTO_MINIMO = 288;

  function px(valor) { return parseFloat(valor) || 0; }

  /** Lo que ocupa la página DEBAJO de la tarjeta: su margen, lo que la sigue
   *  (el bloque de firmas de los Anexos…) y el relleno inferior de cada
   *  contenedor. Se suma pieza a pieza y no con «alto de la página − final de la
   *  tarjeta»: cuando la página es más corta que la pantalla, eso contaría también
   *  el hueco vacío hasta abajo y la tarjeta se quedaría pequeña. */
  function espacioDebajo(tarjeta) {
    let total = 0;
    let el = tarjeta;
    while (el.parentElement && el !== document.body) {
      // El margen inferior de la tarjeta y de cada contenedor (p. ej. el `mb-4` de
      // las pestañas de Notificaciones) también empuja el final de la página.
      total += px(getComputedStyle(el).marginBottom);
      for (let hermano = el.nextElementSibling; hermano; hermano = hermano.nextElementSibling) {
        const estilo = getComputedStyle(hermano);
        if (estilo.display === 'none' || estilo.position === 'fixed' || estilo.position === 'absolute') continue;
        total += hermano.offsetHeight + px(estilo.marginTop) + px(estilo.marginBottom);
      }
      const padre = el.parentElement;
      const estiloPadre = getComputedStyle(padre);
      total += px(estiloPadre.paddingBottom) + px(estiloPadre.borderBottomWidth);
      if (padre.classList.contains('layout-page')) break;
      el = padre;
    }
    return total;
  }

  function ajustarTarjetas() {
    const tarjetas = document.querySelectorAll('.orb-tabla-card');
    if (!tarjetas.length) return;
    tarjetas.forEach(function (tarjeta) {
      if (!tarjeta.offsetParent) return;  // oculta (pestaña no activa): se ajusta al mostrarse
      tarjeta.style.maxHeight = 'none';
      tarjeta.classList.remove('orb-tabla-sin-encaje');
      const arriba = tarjeta.getBoundingClientRect().top + window.scrollY;
      const debajo = espacioDebajo(tarjeta);
      // -1: margen por los redondeos de medio píxel, que si no dejaban 1 px de barra.
      const alto = Math.floor(window.innerHeight - arriba - debajo) - 1;
      if (alto < ALTO_MINIMO) {
        // No cabe con una altura razonable (mucho contenido encima o pantalla muy
        // baja): en vez de encogerla, la tabla pasa a un alto máximo propio con la
        // cabecera fija dentro, y la página se desplaza (ver .orb-tabla-sin-encaje).
        tarjeta.classList.add('orb-tabla-sin-encaje');
        return;
      }
      tarjeta.style.maxHeight = alto + 'px';
    });
  }

  let temporizador = null;
  function ajustarEnBreve() {
    clearTimeout(temporizador);
    temporizador = setTimeout(ajustarTarjetas, 100);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ajustarTarjetas);
  } else {
    ajustarTarjetas();
  }
  // Las fuentes y los avisos de la parte de arriba pueden cambiar el alto al terminar de cargar.
  window.addEventListener('load', ajustarTarjetas);
  window.addEventListener('resize', ajustarEnBreve);
  // Tablas dentro de pestañas (Subsanación): mientras la pestaña está oculta no
  // se puede medir, así que se recalcula al mostrarla.
  document.addEventListener('shown.bs.tab', ajustarEnBreve);

  document.addEventListener('change', function (e) {
    const selector = e.target.closest && e.target.closest('select.orb-filas');
    if (!selector) return;
    if (window.orbithGuardarPreferencias) {
      window.orbithGuardarPreferencias({ filas_por_pagina: selector.value });
    }
    // Tablas que pasan de página con enlaces (base/partials/tabla_paginacion_enlaces.html):
    // se recarga en la página 1 con las filas nuevas. `filas` va al final para que
    // gane a uno anterior que pudiera traer la querystring.
    if (selector.dataset.navegar) {
      window.location.href = selector.dataset.navegar + '&filas=' + encodeURIComponent(selector.value);
    }
  });

  document.body.addEventListener('htmx:afterSwap', function (e) {
    const destino = e.detail && e.detail.target;
    const scroll = destino && destino.closest && destino.closest('.orb-tabla-scroll');
    if (scroll) scroll.scrollTop = 0;
    ajustarEnBreve();
  });
})();
