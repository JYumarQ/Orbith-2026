/* ==========================================================================
   Selector de período de Orbith (año + mes)
   ==========================================================================

   Una rejilla de doce meses con flechas de año, dentro de un desplegable de
   Bootstrap. Sustituye a las parejas de <select> «Año» y «Mes» repartidas por
   la aplicación.

   POR QUÉ NO ES UN <select>
   -------------------------
   El componente nació en Informe Inteligente y su comentario explicaba la razón:
   la lista de períodos crece DOCE opciones cada año, así que a los dos años un
   desplegable plano ya es inmanejable. La rejilla ocupa lo mismo con un año que
   con veinte, y de un vistazo se ve qué meses tienen dato y cuáles no.

   Aquí se extrae para que Informes RRHH y Pre-Nómina usen exactamente el mismo
   control, en vez de tres parejas de <select> distintas.

   MODOS
   -----
   Qué meses se pueden pulsar depende de `data-modo`:

     * `solo-con-datos`: solo los que están en `data-con-datos`. Es el caso de
       Informes RRHH, donde únicamente hay fotografía de los meses cerrados.
     * `solo-sin-datos`: justo al revés, solo los que NO existen todavía. Es el
       de «Crear Período» de Pre-Nómina: crear uno que ya existe es un error, así
       que no se ofrece.
     * `todos`: todos pulsables, resaltando los que tienen dato. Es el de las
       pantallas de consulta de Pre-Nómina, donde mirar un mes vacío es legítimo
       (la tarjeta responde «no hay período»).

   `data-minimo` («AAAA-MM») apaga además todo lo anterior o igual a ese mes.
   «Crear Período» lo usa para la regla de que un período nuevo debe ser
   posterior al último registrado.

   CÓMO SE INTEGRA
   ---------------
   El componente NO navega ni envía nada por su cuenta. Escribe el año y el mes
   elegidos en sus dos <input type="hidden"> y lanza el evento `orbith:periodo`
   sobre su contenedor. Cada pantalla decide qué hacer con eso:

     * dentro de un <form>, los hidden viajan solos y no hace falta nada más;
     * con HTMX, basta `hx-trigger="orbith:periodo"` en el propio contenedor;
     * en Informes RRHH, un puñado de líneas arman la URL y recargan.

   Así el componente no sabe nada de las pantallas que lo usan, y cada pantalla
   conserva la forma de recargar que ya tenía.
   ========================================================================== */

(function (global) {
    'use strict';

    var MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
                 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
    var MESES_CORTOS = MESES.map(function (nombre) { return nombre.slice(0, 3); });

    function leerLista(caja, atributo) {
        try {
            var crudo = caja.getAttribute(atributo);
            return crudo ? JSON.parse(crudo) : [];
        } catch (e) {
            console.warn('[Orbith] selector de período: ' + atributo + ' no es JSON válido.');
            return [];
        }
    }

    function clave(anno, mes) {
        return anno + '-' + String(mes).padStart(2, '0');
    }

    function activar(caja) {
        if (!caja || caja.dataset.activo === '1') return;
        caja.dataset.activo = '1';

        function parte(papel) { return caja.querySelector('[data-papel="' + papel + '"]'); }

        var campoAnno = parte('anno');
        var campoMes = parte('mes');
        var etiqueta = parte('etiqueta');
        var rejilla = parte('rejilla');
        var tituloAnno = parte('anno-visible');
        var botonAnterior = parte('anno-anterior');
        var botonSiguiente = parte('anno-siguiente');
        var botonLimpiar = parte('limpiar');
        var boton = parte('boton');

        if (!campoAnno || !campoMes || !rejilla) return;

        var modo = caja.dataset.modo || 'todos';
        var minimo = caja.dataset.minimo || '';
        var etiquetaVacia = caja.dataset.etiquetaVacia || 'Sin elegir';
        var conDatos = {};
        leerLista(caja, 'data-con-datos').forEach(function (valor) {
            conDatos[String(valor)] = true;
        });
        var annos = leerLista(caja, 'data-annos').map(Number)
                                                 .filter(function (n) { return !isNaN(n); });
        annos.sort(function (a, b) { return a - b; });

        var annoElegido = parseInt(campoAnno.value, 10);
        var annoVisible = !isNaN(annoElegido) ? annoElegido
                        : (annos.length ? annos[annos.length - 1] : new Date().getFullYear());

        function hayDato(anno, mes) {
            return conDatos[clave(anno, mes)] === true;
        }

        /* Un mes se puede pulsar según el modo, y nunca si cae en o por debajo
           del mínimo. Se compara como texto «AAAA-MM», que ordena igual que la
           fecha por estar el mes rellenado con cero. */
        function sePuedePulsar(anno, mes) {
            if (minimo && clave(anno, mes) <= minimo) return false;
            if (modo === 'solo-con-datos') return hayDato(anno, mes);
            if (modo === 'solo-sin-datos') return !hayDato(anno, mes);
            return true;
        }

        function textoDe(anno, mes) {
            if (!anno) return etiquetaVacia;
            // Año sin mes es un estado válido donde la pantalla lo permita: en la
            // lista de Reportes de Pago se puede filtrar por todo un año.
            if (!mes) {
                return (caja.dataset.plantillaAnnoCompleto || 'Todo {anno}')
                    .replace('{anno}', anno);
            }
            var plantilla = caja.dataset.plantillaEtiqueta || '{mes} {anno}';
            return plantilla.replace('{mes}', MESES[mes - 1]).replace('{anno}', anno);
        }

        function refrescarEtiqueta() {
            if (!etiqueta) return;
            etiqueta.textContent = textoDe(parseInt(campoAnno.value, 10),
                                           parseInt(campoMes.value, 10));
        }

        function cerrarPanel() {
            if (!boton || !global.bootstrap) return;
            var menu = global.bootstrap.Dropdown.getInstance(boton);
            if (menu) menu.hide();
        }

        function pintar() {
            if (tituloAnno) tituloAnno.textContent = annoVisible;

            /* Las flechas solo se mueven entre los años ofrecidos: navegar a un
               año que la pantalla no contempla no lleva a ninguna parte. */
            var indice = annos.indexOf(annoVisible);
            if (botonAnterior) botonAnterior.disabled = indice <= 0;
            if (botonSiguiente) {
                botonSiguiente.disabled = indice === -1 || indice >= annos.length - 1;
            }

            var annoActual = parseInt(campoAnno.value, 10);
            var mesActual = parseInt(campoMes.value, 10);

            rejilla.innerHTML = '';
            for (var mes = 1; mes <= 12; mes++) {
                (function (mes) {
                    var tiene = hayDato(annoVisible, mes);
                    var pulsable = sePuedePulsar(annoVisible, mes);
                    var esElegido = annoActual === annoVisible && mesActual === mes;

                    var boton = document.createElement('button');
                    boton.type = 'button';
                    boton.textContent = MESES_CORTOS[mes - 1];
                    boton.className = 'btn btn-sm ' + (esElegido
                        ? 'btn-primary'
                        : (tiene ? 'btn-outline-primary' : 'btn-light text-muted'));
                    boton.disabled = !pulsable;
                    boton.title = MESES[mes - 1] + ' ' + annoVisible
                        + (tiene ? '' : ' · ' + (caja.dataset.textoSinDato || 'sin datos'));

                    if (pulsable) {
                        boton.addEventListener('click', function () {
                            fijar(annoVisible, mes);
                            cerrarPanel();
                        });
                    }
                    rejilla.appendChild(boton);
                })(mes);
            }
        }

        function fijar(anno, mes, silencioso) {
            campoAnno.value = anno || '';
            campoMes.value = mes || '';
            refrescarEtiqueta();
            pintar();
            if (silencioso) return;
            // El contenedor es quien lo lanza para que `hx-trigger` pueda
            // engancharse a él sin conocer los campos ocultos de dentro.
            caja.dispatchEvent(new CustomEvent('orbith:periodo', {
                bubbles: true,
                detail: { anno: anno || '', mes: mes || '', clave: anno && mes ? clave(anno, mes) : '' }
            }));
        }

        /* API por instancia, para las pantallas que necesitan cambiar el período
           desde su propio código. El botón «Limpiar filtros» de la lista de
           Reportes de Pago es el caso: vacía varios controles y lanza UNA sola
           recarga, así que necesita poner el período a cero SIN que el componente
           dispare la suya. Poner `.value` a mano en los campos ocultos no vale:
           la etiqueta del botón se quedaría con el período anterior. */
        caja.orbithFijar = fijar;

        if (botonAnterior) {
            botonAnterior.addEventListener('click', function () {
                var i = annos.indexOf(annoVisible);
                if (i > 0) { annoVisible = annos[i - 1]; pintar(); }
            });
        }
        if (botonSiguiente) {
            botonSiguiente.addEventListener('click', function () {
                var i = annos.indexOf(annoVisible);
                if (i !== -1 && i < annos.length - 1) { annoVisible = annos[i + 1]; pintar(); }
            });
        }
        if (botonLimpiar) {
            botonLimpiar.addEventListener('click', function () {
                fijar('', '');
                cerrarPanel();
            });
        }
        /* «Todo el año»: fija el año y deja el mes vacío. Existe para no perder
           una capacidad que los <select> sí tenían — en la lista de Reportes de
           Pago se podía elegir un año con «Todos los meses»— y que una rejilla
           de meses, por sí sola, no permitiría expresar. */
        var botonAnnoCompleto = parte('anno-completo');
        if (botonAnnoCompleto) {
            botonAnnoCompleto.addEventListener('click', function () {
                fijar(annoVisible, '');
                cerrarPanel();
            });
        }

        refrescarEtiqueta();
        pintar();
    }

    function activarEn(raiz) {
        (raiz || document).querySelectorAll('[data-selector-periodo]').forEach(activar);
    }

    global.OrbithSelectorPeriodo = { activar: activar, activarEn: activarEn };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { activarEn(document); });
    } else {
        activarEn(document);
    }

    /* Las tarjetas de Pre-Nómina llegan por HTMX y los modales por AJAX, así que
       el selector nace después de la carga inicial más veces de las que nace con
       ella. Se reactiva en ambos casos; la marca `data-activo` evita duplicar
       manejadores si un elemento pasa dos veces por aquí. */
    document.addEventListener('htmx:afterSettle', function (evt) {
        activarEn(evt.target || document);
    });
    document.addEventListener('shown.bs.modal', function (evt) {
        activarEn(evt.target);
    });
})(window);
