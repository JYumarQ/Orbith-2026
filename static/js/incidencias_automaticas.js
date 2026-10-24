/*
 * Búsqueda automática de incidencias desde el navegador (Fase 2, 23-10-2026).
 *
 * El servidor no tiene tareas programadas, así que las lanza la primera página que
 * abre cada usuario (ver subsanacion/automatico.py):
 *   - Análisis completo diario de Subsanación: el primer inicio de sesión del día,
 *     de cualquier rol. Va módulo a módulo, una petición por módulo.
 *   - Búsqueda ligera de su alcance (Administrador y Moderador), como mucho cada 4 h.
 * Todo en segundo plano: si algo falla, no molesta al usuario; lo retoma el
 * siguiente que entre.
 */
(function () {
    'use strict';

    var cfg = document.getElementById('cfg-incidencias-automaticas');
    if (!cfg || !window.fetch) return;
    var URL_ESTADO = cfg.dataset.urlEstado;
    var URL_INICIAR = cfg.dataset.urlIniciar;
    var URL_BUSCAR = cfg.dataset.urlBuscar;
    var BASE_AUTO = URL_INICIAR.replace(/iniciar\/$/, '');

    function csrf() {
        var m = document.cookie.match('(^|;)\\s*csrftoken\\s*=\\s*([^;]+)');
        return m ? m.pop() : '';
    }

    function post(url) {
        return fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, credentials: 'same-origin' })
            .then(function (r) { return r.json(); });
    }

    // Indicador discreto mientras dura el análisis diario.
    var indicador = null;
    function mostrar(texto) {
        if (!indicador) {
            indicador = document.createElement('div');
            indicador.setAttribute('role', 'status');
            indicador.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:1080;font-size:.75rem;' +
                'background:rgba(30,41,59,.85);color:#fff;padding:.3rem .65rem;border-radius:999px;' +
                'box-shadow:0 2px 8px rgba(0,0,0,.2);pointer-events:none;';
            document.body.appendChild(indicador);
        }
        indicador.textContent = texto;
    }
    function ocultar() { if (indicador) { indicador.remove(); indicador = null; } }

    // Evita que dos pestañas del mismo navegador lo intenten a la vez (el servidor
    // también lo impide, esto solo ahorra peticiones).
    function tomarTurno() {
        try {
            var ahora = Date.now();
            var previo = parseInt(localStorage.getItem('orbithAnalisisDiario') || '0', 10);
            if (ahora - previo < 10 * 60 * 1000) return false;
            localStorage.setItem('orbithAnalisisDiario', String(ahora));
        } catch (e) { /* sin almacenamiento: se intenta igual */ }
        return true;
    }

    function analisisDiario() {
        if (!tomarTurno()) return Promise.resolve();
        return post(URL_INICIAR).then(function (d) {
            if (!d || !d.pk) return;
            var modulos = d.modulos || [];
            var i = 0;
            function siguiente() {
                if (i >= modulos.length) {
                    mostrar('Revisión diaria de datos: terminando…');
                    return post(BASE_AUTO + d.pk + '/finalizar/');
                }
                mostrar('Revisión diaria de datos ' + (i + 1) + '/' + modulos.length + '…');
                return post(BASE_AUTO + d.pk + '/modulo/' + encodeURIComponent(modulos[i]) + '/')
                    .then(function (r) { if (r && r.ok) { i++; return siguiente(); } });
            }
            return siguiente();
        }).catch(function () { /* silencioso: lo retoma el siguiente */ }).then(ocultar, ocultar);
    }

    function empezar() {
        fetch(URL_ESTADO, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (e) {
                if (!e) return;
                var cadena = Promise.resolve();
                if (e.analizar) cadena = cadena.then(analisisDiario);
                if (e.buscar) cadena = cadena.then(function () { return post(URL_BUSCAR); });
                return cadena;
            })
            .catch(function () { /* silencioso */ });
    }

    // Se espera un poco tras cargar la página: primero lo que el usuario vino a ver.
    if (document.readyState === 'complete') setTimeout(empezar, 3000);
    else window.addEventListener('load', function () { setTimeout(empezar, 3000); });
})();
