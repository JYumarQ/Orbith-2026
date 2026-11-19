#!/bin/bash
# =============================================================================
#  actualizar.sh - Actualiza Orbith en el servidor SIN internet.
#
#  Desde la 3.10.0 (peticion de Informatica, 19-11-2026) Orbith vive SIEMPRE en
#  la misma carpeta, /home/ebm/orbith: Informatica renombra la version actual
#  con la fecha (orbith-AAAA-MM-DD), descomprime orbith.tar.gz (que crea la
#  carpeta orbith nueva) y ejecuta este script. Asi el servicio y Nginx no se
#  cambian nunca. Los paquetes de Python van en despliegue/paquetes.
#
#  Pregunta UNA vez y lo hace todo seguido. Se detiene ante el primer error y
#  muestra las ordenes exactas para volver a la version anterior.
#
#  Lo que NUNCA hace:
#    - usar sudo ni ejecutarse como root;
#    - borrar o sobrescribir nada: la carpeta de la version anterior queda
#      intacta y, si la nueva ya esta preparada, se detiene;
#    - parar, arrancar o cambiar el servicio de Orbith ni Nginx (eso lo hace
#      el Jefe de Informatica, como siempre);
#    - restaurar la base de datos por su cuenta;
#    - conectarse a internet (pip con --no-index).
#
#  Uso (como el usuario que corre Orbith, NO como root, con el servicio parado):
#      bash /home/ebm/orbith/despliegue/actualizar.sh /home/ebm/orbith-AAAA-MM-DD
#
#  Todo lo que sale en pantalla se guarda tambien en un registro
#  (orbith-actualizacion-<version>-<fecha>.log, junto a la carpeta de Orbith)
#  para enviarlo a Juan si algo falla.
# =============================================================================

set -Eeuo pipefail

NUEVA="$(cd "$(dirname "$0")/.." && pwd)"
PAQUETES="$NUEVA/despliegue/paquetes"

if [ ! -f "$NUEVA/manage.py" ] || [ ! -f "$NUEVA/core/changelog.py" ]; then
    echo "ALTO: este script tiene que estar en la carpeta despliegue de Orbith."
    exit 1
fi

# La version vigente es la primera de CHANGELOG (core/changelog.py).
VERSION="$(sed -n '/^CHANGELOG = \[/,$p' "$NUEVA/core/changelog.py" | grep -m 1 -oE '"version": "[^"]+"' | cut -d'"' -f4 || true)"
[ -n "$VERSION" ] || { echo "ALTO: no se encuentra la version en core/changelog.py."; exit 1; }

ANTERIOR="${1:-}"
if [ -z "$ANTERIOR" ]; then
    echo "Uso: bash $0 <carpeta-de-la-version-anterior>"
    echo "     ejemplo: bash $0 /home/ebm/orbith-$(date +%F)"
    exit 1
fi
if [ "$(id -u)" -eq 0 ]; then
    echo "ALTO: no lo ejecute como root. Use el usuario que corre Orbith."
    exit 1
fi
if [ ! -f "$ANTERIOR/manage.py" ] || [ ! -f "$ANTERIOR/core/.env" ]; then
    echo "ALTO: $ANTERIOR no parece la version anterior de Orbith (falta manage.py o core/.env)."
    exit 1
fi
ANTERIOR="$(cd "$ANTERIOR" && pwd)"
if [ "$ANTERIOR" = "$NUEVA" ]; then
    echo "ALTO: indique la carpeta de la version ANTERIOR (la renombrada con la fecha), no $NUEVA."
    exit 1
fi

BASE="$(dirname "$NUEVA")"
RESPALDOS="$BASE/orbith-respaldos"
COPIA=""
BASE_TOCADA=0

# --- Registro: todo lo que sale en pantalla va tambien al archivo ---
LOG="$BASE/orbith-actualizacion-$VERSION-$(date +%Y%m%d_%H%M).log"
exec > >(tee -a "$LOG") 2>&1

# Valor de una linea CLAVE=valor del .env de la version anterior, sin comillas.
# Vacio si no esta. No muestra nada en pantalla.
leer_env() {
    local valor
    valor="$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$ANTERIOR/core/.env" | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"
    valor="$(printf '%s' "$valor" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    valor="${valor#\"}"; valor="${valor%\"}"
    valor="${valor#\'}"; valor="${valor%\'}"
    printf '%s' "$valor"
}

# Las ordenes para volver a la version anterior, segun hasta donde se llego.
volver() {
    echo
    if [ "${1:-}" != "sin_registro" ]; then
        echo "*** Envie a Juan el registro: $LOG"
    fi
    echo "*** Para VOLVER a la version anterior, con el servicio de Orbith detenido:"
    if [ "$BASE_TOCADA" -eq 1 ] && [ -n "$COPIA" ]; then
        local host puerto
        host="$(leer_env DATABASE_HOST)"; puerto="$(leer_env DATABASE_PORT)"
        echo "      pg_restore --clean --if-exists --no-owner${host:+ -h $host}${puerto:+ -p $puerto} -U $(leer_env DATABASE_USER) -d $(leer_env DATABASE_NAME) $COPIA"
        echo "      (pide la contrasena de la base: es DATABASE_PASSWORD en $ANTERIOR/core/.env)"
    fi
    echo "      mv $NUEVA $NUEVA-fallida-$(date +%Y%m%d_%H%M)"
    echo "      mv $ANTERIOR $NUEVA"
    echo "*** y arranque el servicio."
    if [ "$BASE_TOCADA" -eq 0 ]; then
        echo "*** La base de datos NO se ha tocado."
    fi
}

trap 'echo; echo "*** ERROR en la linea $LINENO. El script se detuvo aqui."; volver' ERR

alto() {
    echo
    echo "*** ALTO: $1"
    volver
    exit 1
}

paso() {
    echo
    echo "--- $1"
}

echo "==============================================================================="
echo " Orbith $VERSION - actualizacion sin internet"
echo "   Version anterior (no se toca): $ANTERIOR"
echo "   Version nueva:                 $NUEVA"
echo "   Registro:                      $LOG"
echo "==============================================================================="

# -----------------------------------------------------------------------------
paso "Comprobar el servidor (no cambia nada)"
python="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" || alto "no se encuentra python3."
maquina="$(uname -m)"
libre="$(df -Pm "$BASE" | awk 'NR==2 {print $4}')"
echo "Python $python, maquina $maquina, $libre MB libres en $BASE"
[ "$python" = "3.12" ] || alto "los paquetes son para Python 3.12 y el servidor tiene $python."
[ "$maquina" = "x86_64" ] || alto "los paquetes son para maquinas x86_64 y esta es $maquina."
[ "$libre" -ge 600 ] || alto "hacen falta unos 600 MB libres en $BASE."
ls "$PAQUETES"/*.whl >/dev/null 2>&1 || alto "faltan los paquetes de Python en $PAQUETES."
command -v pg_dump >/dev/null || alto "no se encuentra pg_dump (hace falta para la copia de la base)."
# Ya se ejecuto en esta carpeta: no se repite ni se aconseja volver atras (si
# termino bien, Orbith ya esta actualizado).
if [ -e "$NUEVA/core/.env" ] || [ -e "$NUEVA/venv" ]; then
    echo
    echo "*** ALTO: $NUEVA ya esta preparada (tiene core/.env o venv). No se sobrescribe nada."
    echo "*** Si la actualizacion ya termino bien, no hace falta repetirla. Si fallo, siga las"
    echo "*** instrucciones del registro de aquella vez o envie el registro a Juan."
    exit 1
fi
echo "Todo correcto."

echo
echo "==============================================================================="
echo " El servicio de Orbith tiene que estar DETENIDO."
echo " Se copiara la base de datos y despues se actualizara. Tarda unos minutos."
echo "==============================================================================="
read -r -p "Continuar? (s/n): " respuesta
if [ "$respuesta" != "s" ]; then
    echo "Detenido por usted. No se ha cambiado nada."
    volver sin_registro
    exit 0
fi

# -----------------------------------------------------------------------------
paso "Configuracion: copiar core/.env de la version anterior (claves y base de datos)"
cp -p "$ANTERIOR/core/.env" "$NUEVA/core/.env"

paso "Fotos de los usuarios (media)"
if [ -n "$(leer_env MEDIA_DIR)" ]; then
    echo "El .env tiene MEDIA_DIR: las fotos estan fuera de la carpeta, no hay que copiarlas."
elif [ -d "$ANTERIOR/media" ]; then
    cp -a "$ANTERIOR/media" "$NUEVA/"
    echo "Copiada la carpeta media de la version anterior."
else
    echo "No hay carpeta media que copiar."
fi

paso "Registro de errores (logs)"
if [ -n "$(leer_env LOG_DIR)" ]; then
    echo "El .env tiene LOG_DIR: el registro esta fuera de la carpeta, no hay que copiarlo."
elif [ -d "$ANTERIOR/logs" ]; then
    cp -a "$ANTERIOR/logs" "$NUEVA/"
    echo "Copiado el registro de errores de la version anterior."
else
    echo "No hay registro de errores que copiar."
fi

paso "Entorno de Python e instalacion de paquetes SIN internet"
python3 -m venv "$NUEVA/venv"
"$NUEVA/venv/bin/pip" install --no-index --find-links="$PAQUETES" -r "$NUEVA/requirements.txt"
cd "$NUEVA"

paso "Comprobar Orbith (no toca la base)"
venv/bin/python manage.py check

paso "Archivos estaticos (estilos, imagenes, JavaScript): los sirve Orbith"
venv/bin/python manage.py collectstatic --noinput

# -----------------------------------------------------------------------------
paso "Copia de la base de datos"
nombre="$(leer_env DATABASE_NAME)"
usuario="$(leer_env DATABASE_USER)"
host="$(leer_env DATABASE_HOST)"
puerto="$(leer_env DATABASE_PORT)"
clave="$(leer_env DATABASE_PASSWORD)"
if [ -z "$nombre" ] || [ -z "$usuario" ]; then
    alto "el .env no tiene DATABASE_NAME o DATABASE_USER."
fi
conexion=(-d "$nombre" -U "$usuario")
if [ -n "$host" ]; then conexion+=(-h "$host"); fi
if [ -n "$puerto" ]; then conexion+=(-p "$puerto"); fi
mkdir -p "$RESPALDOS"
COPIA="$RESPALDOS/orbith_antes_${VERSION}_$(date +%Y%m%d_%H%M).dump"
echo "En $COPIA"
# La contrasena se toma del .env y no se muestra ni se guarda en el registro.
PGPASSWORD="$clave" pg_dump -Fc "${conexion[@]}" -f "$COPIA"
tablas="$(pg_restore -l "$COPIA" | grep -c "TABLE DATA" || true)"
echo "La copia ocupa $(du -h "$COPIA" | cut -f1) y contiene $tablas tablas."
[ "$tablas" -gt 0 ] || alto "la copia de la base no se puede leer."

# -----------------------------------------------------------------------------
paso "Actualizar la base de datos (migrate)"
BASE_TOCADA=1
venv/bin/python manage.py migrate --noinput

paso "Comprobar que no queda nada pendiente"
if venv/bin/python manage.py showmigrations | grep "\[ \]"; then
    alto "quedan cambios de la base sin aplicar (los de arriba)."
fi
echo "Ninguno pendiente."

# Tipo de contrato y motivo que faltan en el historico (decision del 18-11-2026):
# solo lo que se sabe con certeza; todo o nada. Si ya esta completo, no hace nada.
paso "Completar el tipo de contrato y el motivo que faltan en el historico"
if ! venv/bin/python manage.py reparar_tipos_historico --aplicar; then
    echo "*** AVISO: no se pudo completar el historico (no se cambio nada en el)."
    echo "*** Orbith funciona igual. Envie a Juan el registro: $LOG"
fi

echo
echo "==============================================================================="
echo " TERMINADO. Ahora usted:"
echo "  1. Arranque el servicio de Orbith (sin cambiar nada en el ni en Nginx)."
echo "  2. En Orbith: menu del usuario -> Acerca de Orbith -> debe decir $VERSION."
echo "  3. Quite el modo mantenimiento."
echo
echo " Version anterior, intacta:   $ANTERIOR"
echo " Copia de la base de antes:   $COPIA"
echo " Registro:                    $LOG"
echo "==============================================================================="
