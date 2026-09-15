/* ==========================================================================
   Validación visual de formularios de Orbith
   ==========================================================================

   Un solo criterio de color para TODOS los formularios de la aplicación:

     AMARILLO  el campo es OBLIGATORIO y todavía está vacío.
     ROJO      el campo tiene datos, pero no son válidos o están incompletos.
     VERDE     el campo tiene datos y son válidos.

   Un campo opcional vacío no lleva color: el amarillo significa «esto hace
   falta», y usarlo también para lo que se puede dejar en blanco convierte la
   pantalla en un mar amarillo donde ya no se distingue lo que de verdad falta.

   Y el botón Guardar queda bloqueado mientras quede algún obligatorio en
   amarillo o cualquier campo en rojo.

   Es el criterio que estrenó a mano el formulario de contrato (bloque
   «VALIDACIÓN VISUAL UNIVERSAL» de `updt_contrato.html`), extraído aquí para
   que cambiarlo cambie la aplicación entera en vez de una plantilla.

   MODO AUTOMÁTICO
   ---------------
   Si no se pasa `obligatorios`, se deducen del propio formulario: son los
   campos con `required` (o `aria-required="true"`), que es justo lo que Django
   escribe en el widget de todo campo obligatorio. Así una plantilla nueva no
   tiene que mantener a mano una lista que se desincroniza en cuanto alguien
   toca el formulario de Python.

   Se puede seguir pasando la lista a mano para forzar un criterio distinto del
   que dice el HTML — por ejemplo el `padre` de una unidad organizativa, que el
   modelo exige solo a las subunidades y por tanto no lleva `required`.

   DE DÓNDE SALE EL ROJO
   ---------------------
   De dos fuentes que se suman:

     1. `checkValidity()` del propio navegador: patrón, longitud mínima, tipo
        (correo, fecha), rango de un número... Es gratis y ya está definido en el
        widget, así que no hay que repetir la regla en JavaScript.
     2. La clase `is-invalid` que ponen otras validaciones del proyecto (el Orden
        de Prioridad la pone tras preguntar al servidor si la posición está
        ocupada). Se respeta pero no se toca: el color propio de este ayudante
        usa su propia clase, `campo-invalido`, para no pisar a nadie.

   El rojo se aplica a CUALQUIER campo con datos inválidos, sea obligatorio o no:
   un correo mal escrito es un error aunque el campo se pudiera dejar vacío.

   Uso:

       OrbithValidacionVisual.activar({ form: '#aspiranteForm' });

       OrbithValidacionVisual.activar({
           form: '#cargoForm',
           obligatorios: ['ncargo', 'cant_aprobada'],   // opcional
           recomendados: ['rol', 'nivel_preparacion'],  // se pintan, no bloquean
           excluir: ['buscador']                        // nunca se pintan
       });

   Detalles que hacen falta para que funcione en Orbith:

     * Select2: `select_unificado.js` convierte todos los <select> de la
       aplicación, y entonces el <select> real queda oculto. El color hay que
       ponerlo en el `.select2-selection` que se ve, no en el <select>.
     * Campos deshabilitados: se les quita todo color. Un campo que el propio
       formulario ha bloqueado (el Padre de una unidad que no es subunidad, el
       Municipio sin provincia configurada) no es un campo pendiente.
   ========================================================================== */

(function () {
    'use strict';

    if (typeof jQuery === 'undefined') {
        console.warn('[Orbith] jQuery no está disponible: sin validación visual.');
        return;
    }

    var $ = jQuery;

    // Marca los campos que se pintan pero no bloquean el botón Guardar.
    var CLASE_OPCIONAL = 'campo-recomendado';
    // Rojo propio de este ayudante. Deliberadamente NO es `is-invalid`, que la
    // pone y la quita otro código del proyecto.
    var CLASE_ROJO = 'campo-invalido';
    var CLASES_COLOR = 'border-warning border-success ' + CLASE_ROJO;

    // Controles que nunca son un dato del formulario.
    var TIPOS_IGNORADOS = ['hidden', 'submit', 'button', 'reset', 'image', 'file'];

    /* Elemento sobre el que se ve el color.
     *
     * Para un <select> ya convertido por Select2 el control visible es el
     * `.select2-selection` del contenedor hermano; para todo lo demás, el
     * propio campo. */
    function objetivoVisual($campo) {
        if ($campo.hasClass('select2-hidden-accessible')) {
            var $seleccion = $campo.next('.select2-container').find('.select2-selection');
            if ($seleccion.length) return $seleccion;
        }
        return $campo;
    }

    function estaVacio(campo) {
        if (campo.type === 'checkbox') return !campo.checked;

        /* UN GRUPO DE RADIOS ES UN SOLO DATO, no uno por opción.
         *
         * Solo está vacío si NINGUNA de sus opciones está marcada. Comprobando
         * `campo.checked` a secas, la opción NO elegida de un toggle contaba
         * como dato pendiente: se pintaba de amarillo y `evaluarBoton()` dejaba
         * Guardar bloqueado para siempre. Y encima de forma invisible, porque
         * esos radios suelen ir ocultos por CSS detrás de la pastilla (el
         * Período de Pago de Parámetros Generales, Quincenal/Mensual). */
        if (campo.type === 'radio') {
            var nombre = campo.name;
            if (!nombre) return !campo.checked;
            var ambito = campo.form || document;
            var hermanos = ambito.querySelectorAll('input[type="radio"]');
            for (var i = 0; i < hermanos.length; i++) {
                if (hermanos[i].name === nombre && hermanos[i].checked) return false;
            }
            return true;
        }

        var valor = campo.value;
        return valor === null || valor === undefined || String(valor).trim() === '';
    }

    /* ¿El navegador considera que lo escrito NO vale?
     *
     * `valueMissing` se descarta a propósito: ese es el caso «vacío», que se
     * pinta de amarillo y se comprueba antes. Aquí solo interesa el resto —
     * patrón, tipo, rango, longitud—, es decir «hay datos pero están mal».
     *
     * `badInput` sí cuenta aunque el campo parezca vacío: es lo que devuelve un
     * <input type="date"> o `number` con algo escrito que no llega a ser una
     * fecha o un número, y en ese caso `value` viene en blanco. Sin esto, una
     * fecha a medias se pintaba de amarillo como si no hubiera nada escrito. */
    function datoInvalido(campo) {
        if (typeof campo.checkValidity !== 'function') return false;
        var validez = campo.validity;
        if (!validez) return false;
        try {
            if (validez.badInput) return true;
            return !validez.valid && !validez.valueMissing;
        } catch (e) {
            /* Leer `validity.valid` LANZA si el campo lleva un `pattern` que el
             * navegador no sabe compilar. Pasaba de verdad: el REUP de Parámetros
             * Generales tenía `pattern="[0-9-]*"`, inválido con la bandera `v` que
             * usan los navegadores modernos para este atributo.
             *
             * Sin este `try`, un solo patrón mal escrito en cualquier formulario
             * tumbaba el repintado ENTERO de ese formulario, y ningún campo se
             * pintaba. Se prefiere no pintarlo de rojo —el patrón está roto, no el
             * dato del usuario— y dejar constancia en la consola para quien lo
             * mantenga. */
            console.warn('[Orbith] El campo «' + (campo.name || campo.id) +
                         '» tiene un `pattern` que el navegador no puede compilar: ' +
                         campo.getAttribute('pattern'));
            return false;
        }
    }

    function nombreDe(campo) {
        return campo.getAttribute('name') || '';
    }

    function esCampoDeDatos(campo) {
        if (!nombreDe(campo)) return false;
        if (nombreDe(campo) === 'csrfmiddlewaretoken') return false;
        return TIPOS_IGNORADOS.indexOf(campo.type) === -1;
    }

    function activar(opciones) {
        var $form = $(opciones.form);
        if (!$form.length) return;

        var excluir = opciones.excluir || [];
        var recomendados = (opciones.recomendados || [])
            .filter(function (n) { return excluir.indexOf(n) === -1; });

        var $boton = opciones.boton
            ? $form.find(opciones.boton)
            : $form.find('button[type="submit"]');

        /* Los obligatorios se recalculan en cada repintado y no una sola vez al
           arrancar: hay formularios que ponen y quitan `required` sobre la
           marcha (el Motivo del contrato solo es obligatorio con ciertos tipos),
           y una lista congelada al principio se quedaría desfasada. */
        function obligatoriosAhora() {
            if (opciones.obligatorios) {
                return opciones.obligatorios.filter(function (n) {
                    return excluir.indexOf(n) === -1;
                });
            }
            var nombres = [];
            $form.find('input, select, textarea').each(function () {
                var nombre = nombreDe(this);
                if (!esCampoDeDatos(this)) return;
                if (excluir.indexOf(nombre) !== -1) return;
                if (recomendados.indexOf(nombre) !== -1) return;
                var exigido = this.required || this.getAttribute('aria-required') === 'true';
                if (exigido && nombres.indexOf(nombre) === -1) nombres.push(nombre);
            });
            return nombres;
        }

        function pintarCampo(campo, obligatorios) {
            var $campo = $(campo);
            var nombre = nombreDe(campo);
            var $objetivo = objetivoVisual($campo);
            $objetivo.removeClass(CLASES_COLOR);

            // Deshabilitado: el formulario lo ha bloqueado a propósito, no es
            // un dato que el usuario tenga pendiente.
            if ($campo.prop('disabled')) {
                $objetivo.removeClass(CLASE_OPCIONAL);
                return;
            }

            var esRecomendado = recomendados.indexOf(nombre) !== -1;
            var esObligatorio = obligatorios.indexOf(nombre) !== -1;
            $objetivo.toggleClass(CLASE_OPCIONAL, esRecomendado);

            // ROJO antes que nada: un dato equivocado importa más que si el
            // campo era obligatorio o no, así que se pinta siempre.
            if (datoInvalido(campo)) {
                $objetivo.addClass(CLASE_ROJO);
                // Sin la marca de opcional, para que el rojo SÍ bloquee incluso
                // en un campo que solo estaba recomendado.
                $objetivo.removeClass(CLASE_OPCIONAL);
                return;
            }

            /* Rojo de OTRA validación: se respeta y no se pinta encima.
             *
             * Varias pantallas marcan `is-invalid` con reglas que este ayudante
             * no puede conocer —el carnet cubano, la serie, un expediente ya
             * usado, una fecha posterior a otra—. Casi siempre son campos que
             * para el navegador son perfectamente válidos, así que sin esta
             * comprobación se pintarían de VERDE encima del rojo ajeno y el
             * usuario vería un campo correcto que el formulario rechaza.
             *
             * No se le añade `CLASE_ROJO`: la clase ajena ya lo pinta, y
             * `evaluarBoton()` cuenta los `.is-invalid` igual para bloquear
             * Guardar. */
            if ($campo.hasClass('is-invalid') || $objetivo.hasClass('is-invalid')) {
                $objetivo.removeClass(CLASE_OPCIONAL);
                return;
            }

            /* AMARILLO SOLO PARA LOS OBLIGATORIOS.
             *
             * Un campo que se puede dejar en blanco no puede pedir atención con
             * el mismo color que uno que hace falta: en el formulario de
             * aspirante, con diez campos «recomendados», la pantalla entera
             * salía amarilla y parecía que todo era obligatorio.
             *
             * Los recomendados siguen pintándose de VERDE al rellenarlos —esa
             * mitad sí ayuda, confirma que el dato vale— pero vacíos se quedan
             * sin color. */
            if (estaVacio(campo)) {
                if (esObligatorio) $objetivo.addClass('border-warning');
                return;
            }
            if (esObligatorio || esRecomendado) $objetivo.addClass('border-success');
        }

        /* El botón se bloquea si queda algún obligatorio en amarillo, o
           cualquier campo en rojo (el propio o el `is-invalid` de otras
           validaciones). El amarillo de un recomendado lleva la marca
           `CLASE_OPCIONAL` y por eso no cuenta. */
        function evaluarBoton() {
            var pendientes = $form.find(
                '.border-warning:not(.' + CLASE_OPCIONAL + '), .' + CLASE_ROJO + ', .is-invalid'
            ).length;
            $boton.prop('disabled', pendientes > 0);
        }

        function repintar() {
            // Se repintan TODOS los campos en cada cambio, no solo el que se
            // tocó: en estos formularios un campo habilita o deshabilita a otro
            // (el Tipo de unidad decide si el Padre está disponible), así que el
            // estado de uno puede depender de lo que se acaba de tocar.
            var obligatorios = obligatoriosAhora();
            $form.find('input, select, textarea').each(function () {
                if (esCampoDeDatos(this)) pintarCampo(this, obligatorios);
            });
            evaluarBoton();
        }

        $form.off('.validacionVisual')
             .on('input.validacionVisual change.validacionVisual blur.validacionVisual',
                 'input, select, textarea', repintar);

        /* CAMBIOS QUE NO LOS HACE EL USUARIO
         *
         * Media aplicación cambia unos campos desde otros: la cascada del
         * contrato (unidad → departamento → cargo) sustituye el <select> entero
         * por HTMX, y el formulario de aspirante deduce el sexo del carnet y lo
         * escribe solo. Ninguna de las dos cosas emite un `input` ni un
         * `change` que llegue hasta aquí, así que el campo se quedaba con el
         * color anterior: departamento y cargo seguían VERDES después de
         * vaciarse, y el sexo autorrellenado seguía AMARILLO.
         *
         * Se vigila el formulario entero: cualquier cambio de valor, de estado
         * o de estructura dispara un repintado completo. Se agrupa con
         * `requestAnimationFrame` para que una ráfaga de mutaciones —lo que
         * hace HTMX al reemplazar un <select> con todas sus opciones— cueste un
         * solo repaso y no uno por nodo. */
        var repintadoPendiente = null;
        function repintarAplazado() {
            if (repintadoPendiente) return;
            repintadoPendiente = window.requestAnimationFrame(function () {
                repintadoPendiente = null;
                repintar();
            });
        }

        if (window.MutationObserver) {
            if (opciones._vigilante) opciones._vigilante.disconnect();
            var vigilante = new MutationObserver(repintarAplazado);
            opciones._vigilante = vigilante;

            /* NO se vigila el atributo `class`, por mucho que sea tentador para
             * enterarse del `is-invalid` que ponen otras validaciones: el propio
             * repintado cambia clases, así que vigilarlas sería un bucle
             * infinito. El rojo ajeno se recoge igual, porque `evaluarBoton()`
             * consulta `.is-invalid` en cada pasada.
             *
             * Tampoco se vigila `value`: asignar `input.value = 'M'` desde
             * JavaScript cambia la PROPIEDAD, no el atributo, y no produce
             * ninguna mutación. Ese caso se cubre desde el otro lado — quien
             * escribe el valor lanza un `change`, que es lo que debería hacer
             * de todas formas. */
            vigilante.observe($form.get(0), {
                childList: true,   // HTMX sustituye el <select> entero (la cascada)
                subtree: true,
                attributes: true,
                attributeFilter: ['disabled', 'selected', 'readonly'],
            });
        }

        // Arranque. Se espera un instante porque Select2 se inicializa después
        // de que la plantilla se inserte en la página, y hasta entonces no
        // existe el `.select2-selection` que hay que pintar.
        repintar();
        setTimeout(repintar, 450);

        // Devuelto para que la plantilla pueda repintar tras un cambio que no
        // pase por un evento del formulario (una respuesta HTMX, por ejemplo).
        return repintar;
    }

    /* ----------------------------------------------------------------------
       ACTIVACIÓN POR MARCADOR
       ----------------------------------------------------------------------

       Un formulario se apunta poniendo `data-validacion-visual` en su etiqueta
       <form>, y ya está:

           <form id="aspiranteForm" data-validacion-visual>

       Las listas opcionales viajan en los mismos `data-`, separadas por comas:

           data-recomendados="rol,nivel_preparacion"
           data-excluir="buscador"
           data-obligatorios="tipo,descripcion,padre"

       Se prefirió el marcador a una llamada de JavaScript en cada plantilla
       porque son unas veinte, la mitad llegan por HTMX o dentro de un modal —y
       ahí un <script> incrustado no se ejecuta de forma fiable— y una línea de
       atributo se lee de un vistazo junto al formulario que describe.

       La llamada `OrbithValidacionVisual.activar({...})` sigue existiendo para
       los formularios que necesitan pasar algo que no cabe en un atributo.
       ---------------------------------------------------------------------- */

    function lista(form, atributo) {
        var crudo = form.getAttribute(atributo);
        if (!crudo) return null;
        return crudo.split(',')
                    .map(function (n) { return n.trim(); })
                    .filter(function (n) { return n; });
    }

    function activarEn(raiz) {
        var contexto = raiz || document;
        var formularios = [];

        if (contexto.matches && contexto.matches('form[data-validacion-visual]')) {
            formularios.push(contexto);
        }
        if (contexto.querySelectorAll) {
            Array.prototype.push.apply(
                formularios,
                contexto.querySelectorAll('form[data-validacion-visual]'));
        }

        formularios.forEach(function (form) {
            // Reactivar es inofensivo —`activar()` sustituye sus propios
            // manejadores con el espacio de nombres `.validacionVisual`— y hace
            // falta: tras un intercambio de HTMX el formulario puede ser otro.
            var opciones = { form: form };
            var obligatorios = lista(form, 'data-obligatorios');
            if (obligatorios) opciones.obligatorios = obligatorios;
            opciones.recomendados = lista(form, 'data-recomendados') || [];
            opciones.excluir = lista(form, 'data-excluir') || [];
            if (form.getAttribute('data-boton')) {
                opciones.boton = form.getAttribute('data-boton');
            }
            activar(opciones);
        });
    }

    /* `objetivo` se publica para las pantallas que pintan por su cuenta y no
       pueden usar `activar()` —el modal de Baja de contrato tiene su botón
       fuera del <form> y una regla cronológica propia—. Sin esto pintaban el
       <select> original, que Select2 mantiene oculto, y el color no se veía:
       era el caso de «Causa de Baja». */
    window.OrbithValidacionVisual = {
        activar: activar,
        activarEn: activarEn,
        objetivo: function (campo) { return objetivoVisual($(campo)); }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { activarEn(document); });
    } else {
        activarEn(document);
    }

    // Formularios que nacen después: cascadas y tarjetas de HTMX, y los modales
    // que se cargan por AJAX.
    document.addEventListener('htmx:afterSettle', function (evt) {
        activarEn(evt.target || document);
    });
    document.addEventListener('shown.bs.modal', function (evt) {
        activarEn(evt.target);
    });
})();
