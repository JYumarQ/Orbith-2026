/* ==========================================================================
   Selector de Unidades Organizativas de Orbith
   ==========================================================================

   Fichas + buscador sobre un `<select multiple>` oculto que sigue siendo la
   fuente de verdad. El control nació en el Dashboard y vivía dentro de
   `dashboard.html`; aquí se extrae para que las tres pantallas que filtran por
   unidad usen exactamente el mismo, en vez de tres controles distintos:

     * Dashboard
     * Informes RRHH
     * Informe Inteligente

   QUÉ SE LE AÑADIÓ AL SACARLO
   ---------------------------
   1. JERARQUÍA. Antes listaba las unidades planas y en orden alfabético, así
      que «Camagüey» y «Oficina Central» parecían hermanas cuando la primera
      cuelga de la segunda. Ahora cada subunidad va indentada bajo su principal.

   2. BÚSQUEDA POR RAMA. Escribir el nombre de una principal deja visibles
      también sus subunidades. Sin eso, buscar «Oficina» escondía justo las
      unidades que cuelgan de ella, que es lo que se estaba buscando.

   3. AVISO AL CERRAR. Al cerrar el panel, si la selección cambió, se lanza
      `orbith:unidades` sobre el contenedor. Cada pantalla decide qué hacer:
      el Dashboard envía su formulario, Informes RRHH recarga con `?ueb=`, e
      Informe Inteligente vuelve a generar el informe. El componente no sabe
      nada de ninguna de las tres.

   Lo que NO cambia: el `<select>` oculto se sigue enviando tal cual en el GET,
   así que el servidor recibe exactamente lo mismo que antes.

   La suma de subunidades al filtrar (elegir una principal trae a sus hijas) NO
   se hace aquí: es cosa del servidor, que es quien no se puede saltar.
   ========================================================================== */

(function (global) {
    'use strict';

    function iniciar(raiz) {
        if (!raiz || raiz.dataset.iniciado === '1') return;
        raiz.dataset.iniciado = '1';

        var nativo = raiz.querySelector('.chip-multiselect-native');
        var caja = raiz.querySelector('.chip-multiselect-box');
        var fichas = raiz.querySelector('.chip-multiselect-chips');
        var contador = raiz.querySelector('.chip-multiselect-badge');
        var panel = raiz.querySelector('.chip-multiselect-panel');
        var buscador = raiz.querySelector('.chip-multiselect-search');
        var lista = raiz.querySelector('.chip-multiselect-options');
        if (!nativo || !caja || !lista) return;

        var opciones = Array.prototype.map.call(nativo.options, function (o) {
            return {
                valor: o.value,
                etiqueta: o.text,
                nivel: parseInt(o.dataset.nivel || '0', 10),
                // Nombre del padre, para que la búsqueda por rama funcione.
                padre: o.dataset.padre || '',
                el: o
            };
        });

        lista.innerHTML = '';
        opciones.forEach(function (op) {
            var item = document.createElement('div');
            item.className = 'chip-multiselect-option'
                + (op.nivel ? ' chip-multiselect-option--hija' : '');
            item.dataset.value = op.valor;
            item.innerHTML = '<i class="bx bx-check"></i><span></span>';
            item.querySelector('span').textContent = op.etiqueta;
            item.addEventListener('click', function (e) {
                e.stopPropagation();
                op.el.selected = !op.el.selected;
                pintar();
            });
            lista.appendChild(item);
            op.itemEl = item;
        });

        var vacio = document.createElement('div');
        vacio.className = 'chip-multiselect-empty';
        vacio.textContent = 'Sin resultados.';
        vacio.style.display = 'none';
        lista.appendChild(vacio);

        function seleccionActual() {
            return opciones.filter(function (op) { return op.el.selected; })
                           .map(function (op) { return op.valor; })
                           .join(',');
        }

        function pintar() {
            fichas.innerHTML = '';
            var cuantas = 0;
            opciones.forEach(function (op) {
                var elegida = op.el.selected;
                op.itemEl.classList.toggle('selected', elegida);
                if (!elegida) return;
                cuantas++;

                var ficha = document.createElement('span');
                ficha.className = 'chip-multiselect-chip';
                var texto = document.createElement('span');
                texto.textContent = op.etiqueta;
                var quitar = document.createElement('button');
                quitar.type = 'button';
                quitar.innerHTML = '&times;';
                quitar.title = 'Quitar ' + op.etiqueta;
                quitar.addEventListener('click', function (e) {
                    e.stopPropagation();
                    op.el.selected = false;
                    pintar();
                });
                ficha.appendChild(texto);
                ficha.appendChild(quitar);
                fichas.appendChild(ficha);
            });
            contador.textContent = cuantas;
            contador.classList.toggle('show', cuantas > 0);
        }

        /* La búsqueda mira el nombre de la unidad Y el de su padre: escribir el
           nombre de una principal tiene que dejar visibles a sus hijas, que es
           justo lo que se está buscando cuando se teclea una dirección. */
        function filtrar(texto) {
            var t = texto.trim().toLowerCase();
            var visibles = 0;
            opciones.forEach(function (op) {
                var coincide = !t
                    || op.etiqueta.toLowerCase().indexOf(t) !== -1
                    || (op.padre && op.padre.toLowerCase().indexOf(t) !== -1);
                op.itemEl.classList.toggle('hidden', !coincide);
                if (coincide) visibles++;
            });
            vacio.style.display = visibles === 0 ? 'block' : 'none';
        }

        //: Selección con la que se abrió el panel, para saber al cerrar si cambió.
        var seleccionAlAbrir = null;

        function abrir() {
            document.querySelectorAll('.chip-multiselect.open').forEach(function (otro) {
                if (otro !== raiz) cerrarUno(otro);
            });
            seleccionAlAbrir = seleccionActual();
            raiz.classList.add('open');
            buscador.value = '';
            filtrar('');
            buscador.focus();
        }

        function cerrar() {
            if (!raiz.classList.contains('open')) return;
            raiz.classList.remove('open');
            // Solo se avisa si de verdad cambió algo: abrir y cerrar sin tocar
            // nada no debe recargar la pantalla.
            if (seleccionAlAbrir !== null && seleccionActual() !== seleccionAlAbrir) {
                raiz.dispatchEvent(new CustomEvent('orbith:unidades', {
                    bubbles: true,
                    detail: { valores: seleccionActual().split(',').filter(Boolean) }
                }));
            }
            seleccionAlAbrir = null;
        }

        raiz._orbithCerrar = cerrar;
        raiz._orbithRepintar = pintar;

        caja.addEventListener('click', function (e) {
            e.stopPropagation();
            if (raiz.classList.contains('open')) cerrar(); else abrir();
        });
        // Con teclado: Enter o Espacio abren, Escape cierra.
        caja.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (raiz.classList.contains('open')) cerrar(); else abrir();
            } else if (e.key === 'Escape') {
                cerrar();
            }
        });

        buscador.addEventListener('click', function (e) { e.stopPropagation(); });
        buscador.addEventListener('input', function () { filtrar(this.value); });
        panel.addEventListener('click', function (e) { e.stopPropagation(); });

        pintar();
    }

    function cerrarUno(raiz) {
        if (raiz._orbithCerrar) raiz._orbithCerrar();
        else raiz.classList.remove('open');
    }

    /* Deja el control sin nada marcado. Lo usa «Reset» en los filtros del
       listado de contratos: ese botón recorre los <select> del panel buscando
       una opción vacía, y este control no tiene ninguna (es múltiple), así que
       sin esto se quedaba con las fichas puestas mientras la tabla ya se había
       recargado sin filtro. NO lanza `orbith:unidades`: quien limpia ya sabe
       lo que hizo y va a recargar él mismo. */
    function limpiar(raiz) {
        if (!raiz) return;
        var nativo = raiz.querySelector('.chip-multiselect-native');
        if (!nativo) return;
        Array.prototype.forEach.call(nativo.options, function (o) {
            o.selected = false;
        });
        if (raiz._orbithRepintar) raiz._orbithRepintar();
    }

    /* Repinta fichas y contador a partir del <select> oculto, para cuando la
       seleccion se cambia POR CODIGO (una configuracion guardada, un favorito).

       Existe porque la alternativa que se usaba antes —borrar `data-iniciado` y
       volver a llamar a `iniciar()`— dejaba el control MUERTO: `iniciar()` ata
       otro `click` sobre la misma caja, asi que con dos manejadores el panel se
       abria y se cerraba en el mismo clic y parecia que no hacia nada. */
    function sincronizar(raiz) {
        if (!raiz) return;
        if (raiz._orbithRepintar) raiz._orbithRepintar();
        else iniciar(raiz);
    }

    function iniciarEn(contexto) {
        (contexto || document)
            .querySelectorAll('.chip-multiselect')
            .forEach(iniciar);
    }

    global.OrbithSelectorUnidades = {
        iniciar: iniciar,
        iniciarEn: iniciarEn,
        limpiar: limpiar,
        sincronizar: sincronizar
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { iniciarEn(document); });
    } else {
        iniciarEn(document);
    }

    // Un clic fuera cierra el panel abierto (y avisa del cambio, si lo hubo).
    document.addEventListener('click', function () {
        document.querySelectorAll('.chip-multiselect.open').forEach(cerrarUno);
    });

    // Contenido que llega después: tarjetas de HTMX y modales.
    document.addEventListener('htmx:afterSettle', function (evt) {
        iniciarEn(evt.target || document);
    });
    document.addEventListener('shown.bs.modal', function (evt) {
        iniciarEn(evt.target);
    });
})(window);
