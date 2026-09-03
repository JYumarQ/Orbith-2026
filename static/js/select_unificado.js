/* ==========================================================================
   Selects unificados de Orbith
   ==========================================================================

   Convierte TODOS los <select> de la aplicación en el mismo control: con
   buscador que filtra al escribir y con el aspecto definido en
   `orbith-controles.css`.

   Se hace desde un único inicializador global y no plantilla por plantilla
   porque los <select> de Orbith están repartidos en más de veinticinco
   archivos, y porque los que nacen después de cargar la página —las cascadas
   HTMX de unidad/departamento/cargo, los formularios que se abren en un modal
   por AJAX— quedarían fuera de cualquier arreglo puntual.

   Select2 ya venía cargado en todas las páginas (`base.html` y
   `scripts.html`), así que esto no añade ninguna dependencia nueva: solo lo
   activa donde faltaba y unifica sus opciones.

   PARA EXCLUIR UN SELECT: `data-sin-select2` en el elemento. Se respeta
   siempre, en la carga inicial y en cada reinicio.
   ========================================================================== */

(function () {
    'use strict';

    if (typeof jQuery === 'undefined' || typeof jQuery.fn.select2 === 'undefined') {
        console.warn('[Orbith] Select2 no está disponible: los selects quedan nativos.');
        return;
    }

    var $ = jQuery;

    // Textos en español. Select2 trae traducciones en archivos aparte que este
    // proyecto no carga, y sin esto el usuario vería "No results found".
    var IDIOMA = {
        noResults: function () { return 'Sin resultados'; },
        searching: function () { return 'Buscando…'; },
        inputTooShort: function () { return 'Escriba para filtrar'; },
        removeAllItems: function () { return 'Quitar todo'; },
        removeItem: function () { return 'Quitar'; }
    };

    /* ¿Este <select> debe quedarse como está?
     *
     * - `data-sin-select2`: la marca de exclusión explícita.
     * - `.chip-multiselect-native`: es el almacén de datos del multi-select del
     *   Dashboard, que ya pinta su propia interfaz encima.
     * - `size > 1`: es una lista abierta de varias filas, no un desplegable.
     * - ya inicializado: se deja en paz para no destruir opciones propias de
     *   una pantalla (por ejemplo el select de Cargo del contrato, que pinta
     *   un badge de plazas en cada opción con su propio `templateResult`).
     *
     * Los `<select hidden>` SÍ se inicializan. Están ocultos de forma temporal
     * —el de período de Informes RRHH aparece al elegir «sincronizar con cierre
     * de mes»— y saltárselos dejaba un select nativo suelto en medio de una
     * pantalla ya unificada. De que no se vea mientras siga oculto se encarga
     * el CSS (`select[hidden] + .select2-container`), que además lo revela solo
     * en cuanto la pantalla le quita el atributo.
     */
    function debeOmitirse(el) {
        return el.hasAttribute('data-sin-select2')
            || el.classList.contains('chip-multiselect-native')
            || el.classList.contains('select2-hidden-accessible')
            || esControlInternoDeSweetAlert(el)
            || (el.size && el.size > 1);
    }

    /* Los controles que SweetAlert2 lleva dentro de su propio diálogo.
     *
     * SweetAlert2 monta SIEMPRE su juego completo de campos —`swal2-input`,
     * `swal2-select`, `swal2-textarea`…— y esconde con `display: none` los que
     * ese diálogo concreto no use. Como Select2 crea su caja como HERMANA del
     * <select>, esa caja NO hereda el `display: none` del original: quedaba un
     * desplegable vacío de 44px visible dentro de CUALQUIER SweetAlert de la
     * aplicación, incluidos los toasts. Es el «select que nunca existió» que
     * aparecía en media aplicación.
     *
     * Se excluye por la clase propia de la librería, no por estar dentro del
     * diálogo: los <select> que las pantallas del proyecto SÍ ponen dentro de un
     * SweetAlert —el de familia destino de Familias de Cargos— tienen que
     * seguir convirtiéndose con normalidad. */
    function esControlInternoDeSweetAlert(el) {
        return el.classList.contains('swal2-select');
    }

    /* Hueco reservado para un icono superpuesto.
     *
     * El patrón se repite en varias pantallas: un contenedor en posición
     * relativa, un icono colocado en absoluto sobre el borde izquierdo, y un
     * `padding-left` generoso en el control para que el texto no se le monte
     * encima (`.modern-input-wrapper` de Parámetros Generales es el ejemplo).
     * Ese relleno vive en el <select> original, que Select2 oculta, así que sin
     * esto el texto de la opción arrancaba justo debajo del icono.
     *
     * Se lee el valor ya calculado en lugar de buscar clases conocidas: así
     * funciona en cualquier pantalla que use el patrón, tenga el nombre que
     * tenga su contenedor. El umbral descarta el relleno normal de un
     * `.form-select` de Sneat (0.875rem = 14px). */
    var RELLENO_NORMAL = 20;

    function huecoDeIcono(el) {
        var relleno = parseFloat(window.getComputedStyle(el).paddingLeft);
        return (relleno && relleno > RELLENO_NORMAL) ? relleno : 0;
    }

    /* Dentro de un modal el panel tiene que colgar del propio modal o queda
     * por debajo de su fondo oscuro; fuera de él cuelga de <body>, que es lo
     * que evita que una tarjeta con `overflow: hidden` lo recorte.
     *
     * Dentro del modal cuelga del `.modal-content`, NO del `.modal`. La
     * diferencia importa: el `.modal` es el elemento que HACE SCROLL, y Select2
     * calcula la posición del panel sin tener en cuenta el desplazamiento de su
     * contenedor. En un formulario largo —el de contrato— eso desplazaba el
     * panel tantos píxeles hacia arriba como se hubiera bajado: medido, 352 px
     * de error al abrir «Registro Militar». Colgándolo del `.modal-content`,
     * que no se desplaza, el error es cero.
     *
     * Se cae al `.modal` si no hubiera `.modal-content`, para no dejar ningún
     * modal con el panel debajo del fondo oscuro. */
    function contenedorDelPanel($el) {
        var $contenido = $el.closest('.modal-content');
        if ($contenido.length) return $contenido;
        var $modal = $el.closest('.modal');
        return $modal.length ? $modal : $(document.body);
    }

    function inicializarUno(el) {
        if (debeOmitirse(el)) return;

        var $el = $(el);
        var hueco = huecoDeIcono(el);

        $el.select2({
            // Obligatorio: sin el tema, el contenedor se pinta como
            // `select2-container--default` y no le aplica ninguna de las hojas
            // de estilo del proyecto (el control encoge de golpe al
            // inicializarse, con parpadeo visible).
            theme: 'bootstrap-5',
            // Se respeta el ancho que el maquetado le hubiera puesto en línea.
            // Varias tablas de Nomencladores usan anchos fijos muy pequeños
            // (`width: 80px` en las nocturnidades, `70px` en los AM/PM) para que
            // quepan en su celda, y forzarlos al 100% deformaba la tabla entera.
            // `auto` también viaja tal cual, para los controles que se ajustan a
            // su texto dentro de una fila flexible.
            width: (el.style && el.style.width) ? el.style.width : '100%',
            dropdownParent: contenedorDelPanel($el),
            // Buscador SIEMPRE, incluso en listas de dos o tres opciones: lo
            // contrario deja al usuario adivinando en cuáles puede escribir.
            minimumResultsForSearch: 0,
            language: IDIOMA,
            templateSelection: function (opcion) { return opcion.text; }
        });

        // El tamaño compacto y el ancho automático NO se marcan aquí: los resuelve
        // `orbith-controles.css` con un selector de hermano adyacente sobre el
        // <select> original. Marcarlos con una clase en el contenedor era frágil,
        // porque las pantallas que reinicializan Select2 por su cuenta lo destruyen
        // y se llevan la clase por delante.
        var $contenedor = $el.next('.select2-container');

        if (hueco) {
            // `setProperty(..., 'important')` y no una clase: `select2-sneat-fix.css`
            // fija el relleno con `!important`, y una declaración en línea solo lo
            // gana si también lo lleva.
            var caja = $contenedor.find('.select2-selection')[0];
            if (caja) caja.style.setProperty('padding-left', hueco + 'px', 'important');
        }

        enlazarPuenteHtmx($el);
        enlazarTextoDelBuscador($el);
        enlazarPanelDentroDeDropdown($el);
    }

    /* EL PANEL NO DEBE CERRAR EL DESPLEGABLE DE BOOTSTRAP QUE LO CONTIENE
     *
     * El panel de resultados de Select2 se cuelga de <body>, no del control. Si
     * el <select> vive dentro de un `.dropdown-menu` de Bootstrap —el panel de
     * Filtros de la lista de Contratos es el caso—, pulsar una opción es, para
     * Bootstrap, un clic FUERA del menú: lo cerraba entero y el usuario se
     * quedaba con la lista de Select2 flotando sobre la nada, habiendo perdido
     * el resto de los filtros.
     *
     * No se resuelve colgando el panel dentro del menú, que sería lo natural:
     * ese menú tiene `overflow: auto` para poder desplazarse, así que el panel
     * quedaría recortado dentro de él.
     *
     * Lo que se hace es cortar la propagación del clic en el propio panel. Los
     * manejadores de Select2 están en elementos de DENTRO (la lista de
     * resultados), así que se ejecutan antes; el evento se detiene aquí y nunca
     * llega al listener de `document` con el que Bootstrap cierra sus menús.
     */
    function enlazarPanelDentroDeDropdown($el) {
        if (!$el.closest('.dropdown-menu').length) return;

        $el.off('select2:open.orbDropdown').on('select2:open.orbDropdown', function () {
            var panel = document.querySelector('.select2-container--open .select2-dropdown');
            if (!panel || panel.dataset.orbCortaPropagacion === '1') return;
            panel.dataset.orbCortaPropagacion = '1';
            ['mousedown', 'click'].forEach(function (evento) {
                panel.addEventListener(evento, function (e) { e.stopPropagation(); });
            });
        });
    }

    /* El buscador del panel nace sin texto de ayuda y queda como una caja vacía
     * que no se entiende. El componente del Dashboard sí lo tiene («Buscar
     * unidad…»), así que se replica. Se pone al abrir y no una sola vez porque
     * Select2 crea el campo de búsqueda cada vez que despliega el panel. */
    function enlazarTextoDelBuscador($el) {
        $el.off('select2:open.orbBuscador').on('select2:open.orbBuscador', function () {
            var campo = document.querySelector('.select2-container--open .select2-search__field');
            if (campo) campo.placeholder = 'Escriba para filtrar…';
        });
    }

    /* PUENTE HTMX <-> SELECT2
     *
     * Select2 avisa del cambio con el `trigger()` sintético de jQuery, que
     * HTMX —basado en addEventListener nativo— no llega a ver. Sin esto,
     * cualquier select con `hx-get` deja de disparar su petición en cuanto se
     * le pone Select2 encima, y las cascadas (unidad → departamento → cargo,
     * provincia → municipio) se quedan mudas sin dar ningún error.
     *
     * Se escucha el evento propio de Select2 y no `change`, porque despachar
     * un `change` desde el manejador de `change` crearía un bucle infinito.
     */
    function enlazarPuenteHtmx($el) {
        var eventos = 'select2:select.orbHtmx select2:unselect.orbHtmx select2:clear.orbHtmx';
        $el.off(eventos).on(eventos, function () {
            this.dispatchEvent(new Event('change', { bubbles: true }));
        });
    }

    /* Cuando HTMX reemplaza un <select> entero (por ejemplo el partial de
     * municipios, que devuelve el elemento completo), el contenedor visual que
     * Select2 había creado al lado queda huérfano en el DOM y se vería un
     * control duplicado. Se barren los que ya no acompañan a ningún select. */
    function limpiarHuerfanos(raiz) {
        $(raiz).find('.select2-container').each(function () {
            var anterior = this.previousElementSibling;
            var vivo = anterior
                && anterior.tagName === 'SELECT'
                && anterior.classList.contains('select2-hidden-accessible');
            if (!vivo) this.remove();
        });
    }

    /* Punto de entrada público. Las plantillas que inyectan HTML por su cuenta
     * (SweetAlert, respuestas AJAX propias) pueden llamarlo para que sus
     * selects nuevos entren por el mismo aro. */
    function inicializar(raiz) {
        var contexto = raiz || document;
        limpiarHuerfanos(contexto);
        $(contexto).find('select').each(function () { inicializarUno(this); });
        if (contexto !== document && contexto.tagName === 'SELECT') {
            inicializarUno(contexto);
        }
    }

    window.orbithInitSelects = inicializar;

    $(function () { inicializar(document); });

    // Contenido que llega después: HTMX y modales de Bootstrap. `afterSettle`
    // y no `afterSwap` porque el primero espera a que HTMX termine de asentar
    // el DOM, incluidas las transiciones.
    document.body.addEventListener('htmx:afterSettle', function (evt) {
        inicializar(evt.target || document);
    });

    // Un modal oculto tiene ancho cero: si Select2 se inicializa antes de que
    // se muestre, calcula mal el ancho y el control sale encogido.
    document.body.addEventListener('shown.bs.modal', function (evt) {
        inicializar(evt.target);
    });

    /* Y contenido que aparece sin avisar por ninguna de las dos vías anteriores.
     *
     * Varias pantallas construyen <select> con JavaScript puro: Informe
     * Inteligente añade una fila entera cada vez que se pulsa «Añadir filtro»,
     * y Familias de Cargos monta uno dentro de un SweetAlert. Ahí no hay ni
     * intercambio de HTMX ni apertura de modal, así que sin este vigilante esos
     * controles se quedaban nativos en medio de una pantalla ya unificada.
     *
     * El trabajo se aplaza a `requestAnimationFrame` por dos motivos: agrupa
     * ráfagas de mutaciones en una sola pasada, y —más importante— deja correr
     * antes al código de la propia pantalla. Las que inicializan Select2 con
     * opciones propias lo hacen de forma síncrona justo después de insertar el
     * elemento (Informe Inteligente le pone un `templateResult` a su select de
     * campo), así que cuando llega este turno el control ya está montado y
     * `debeOmitirse` lo respeta en lugar de pisarlo.
     */
    var pendiente = null;
    var porRevisar = [];

    function programarRevision(nodo) {
        porRevisar.push(nodo);
        if (pendiente) return;
        pendiente = window.requestAnimationFrame(function () {
            pendiente = null;
            var lote = porRevisar;
            porRevisar = [];
            lote.forEach(inicializar);
        });
    }

    new MutationObserver(function (mutaciones) {
        for (var i = 0; i < mutaciones.length; i++) {
            var agregados = mutaciones[i].addedNodes;
            for (var j = 0; j < agregados.length; j++) {
                var nodo = agregados[j];
                if (nodo.nodeType !== 1) continue;
                // Se filtra aquí, y no dentro de `inicializar`, para que el caso
                // habitual —una mutación que no trae ningún <select>— no cueste
                // más que una comprobación.
                if (nodo.tagName === 'SELECT' || nodo.querySelector('select')) {
                    programarRevision(nodo);
                }
            }
        }
    }).observe(document.body, { childList: true, subtree: true });
})();
