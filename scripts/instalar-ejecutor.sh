#!/usr/bin/env bash
# Instalador del «ejecutor» de Trovefy (plan 12). Lo ejecutas tú, una vez y cuando quieras actualizar:
#
#     sudo bash scripts/instalar-ejecutor.sh [--vault RUTA]
#     bash scripts/instalar-ejecutor.sh --simular [--vault RUTA]   # solo imprime lo que haría
#
# Es idempotente: cada paso comprueba antes de actuar y un segundo pase no cambia nada; nunca sobrescribe
# secretos.env ni limites.yaml. Root solo actúa en /etc y /var/spool: lo de tu home se hace como tú y lo
# de /home/trovefy-exec como trovefy-exec. Nunca muestra el contenido de secretos.env. Nunca borra carpetas.
# Con --simular no ejecuta ningún comando: las líneas «+ » son lo que haría y las «? » son consultas que,
# en la simulación, se dan por negativas (como si nada estuviera instalado).
set -euo pipefail

readonly EXEC=trovefy-exec
readonly GRUPO=trovefy
readonly EXEC_HOME=/home/trovefy-exec
readonly SPOOL=/var/spool/trovefy
readonly PY=/home/trovefy-exec/.local/share/uv/tools/trovefy/bin/python
readonly BIN=/home/trovefy-exec/.local/bin/trovefy-ejecutor
readonly CONFIG="$EXEC_HOME/.config/trovefy-ejecutor"
readonly DATOS="$EXEC_HOME/.local/share/trovefy-ejecutor"
readonly ENTREGA="$EXEC_HOME/.cache/trovefy-instalar"
readonly SECRETOS="$CONFIG/secretos.env"
readonly LIMITES="$CONFIG/limites.yaml"
readonly UNIDAD=/etc/systemd/system/trovefy-ejecutor.service
readonly UV=/usr/local/bin/uv
readonly TOTAL=13
readonly COMO="ejecútalo así: sudo bash scripts/instalar-ejecutor.sh"

# Raíz del repo sin comandos externos (en --simular no se ejecuta nada).
if [[ "${BASH_SOURCE[0]}" == */* ]]; then _dir="${BASH_SOURCE[0]%/*}"; else _dir="."; fi
REPO="$(cd -- "$_dir/.." && pwd -P)"
readonly REPO
cd /

morir() { printf 'Error: %s\n' "$*" >&2; exit 1; }

uso() {
    printf 'Uso: sudo bash scripts/instalar-ejecutor.sh [--vault RUTA]\n'
    printf '     bash scripts/instalar-ejecutor.sh --simular [--vault RUTA]\n'
}

SIMULAR=0
VAULT=""
VAULT_DADO=0
while (($#)); do
    case "$1" in
        --simular) SIMULAR=1 ;;
        --vault)
            (($# >= 2)) || morir "--vault necesita una ruta"
            VAULT="$2"; VAULT_DADO=1; shift ;;
        --vault=*) VAULT="${1#--vault=}"; VAULT_DADO=1 ;;
        -h | --help) uso; exit 0 ;;
        *) uso >&2; morir "opción desconocida: $1" ;;
    esac
    shift
done
readonly SIMULAR

if ((SIMULAR == 0)); then
    if [[ "$EUID" -ne 0 || -z "${SUDO_USER:-}" ]]; then
        printf 'Este instalador necesita root y saber quién eres: %s\n' "$COMO" >&2
        exit 1
    fi
    USUARIO="$SUDO_USER"
else
    USUARIO="${SUDO_USER:-${USER:-usuario}}"
fi
[[ "$USUARIO" =~ ^[a-z_][a-z0-9_-]{0,31}$ && "$USUARIO" != root ]] \
    || morir "SUDO_USER no válido: lanza el instalador con sudo desde tu usuario normal ($COMO)"
readonly USUARIO

if ((SIMULAR)); then
    HOME_USUARIO="/home/$USUARIO"
else
    HOME_USUARIO="$(getent passwd "$USUARIO" | cut -d: -f6)"
    [[ "$HOME_USUARIO" == /* && -d "$HOME_USUARIO" ]] || morir "no encuentro el home de $USUARIO"
fi
readonly HOME_USUARIO
((VAULT_DADO)) || VAULT="$HOME_USUARIO/trovefy-cerebro"

# --vault: absoluta, sin comillas, barras invertidas, %, espacios ni caracteres de control (va tal cual a
# la unidad de systemd, donde «%» es un especificador y los espacios separan rutas), sin «.» ni «..».
validar_vault() {
    local v="$1"
    [[ -n "$v" ]] || morir "--vault vacía"
    [[ "$v" == /* ]] || morir "--vault debe ser una ruta absoluta"
    [[ "$v" != *[\"\\%]* ]] || morir "--vault no admite comillas, barras invertidas ni «%»"
    [[ ! "$v" =~ [[:space:][:cntrl:]] ]] || morir "--vault no admite espacios, saltos de línea ni caracteres de control"
    [[ "/$v/" != */./* && "/$v/" != */../* && "$v" != *//* ]] || morir "--vault no admite «.», «..» ni «//»"
    [[ "$v" != / ]] || morir "--vault no puede ser /"
}
VAULT="${VAULT%/}"
validar_vault "$VAULT"
readonly VAULT

# -- separación de privilegios -----------------------------------------------------------------------------
# Root solo actúa en /etc y /var/spool (y crea el usuario). Todo lo que hay bajo el home de $USUARIO (repo,
# vault, uv) se lee o modifica COMO $USUARIO, y todo lo de $EXEC_HOME COMO trovefy-exec: root nunca sigue
# un enlace simbólico puesto por otro usuario ni escribe en un árbol que no es suyo.
COMO_USUARIO=(sudo -u "$USUARIO" -H)
COMO_EXEC=(sudo -u "$EXEC" -H)
readonly COMO_USUARIO COMO_EXEC
como_usuario() { "${COMO_USUARIO[@]}" "$@"; }
como_exec() { "${COMO_EXEC[@]}" "$@"; }

if ((SIMULAR == 0)); then
    if ! { como_usuario test -d "$VAULT" && ! como_usuario test -L "$VAULT"; }; then
        morir "--vault: $VAULT no es una carpeta (¿hiciste /arranque?)"
    fi
    [[ "$(como_usuario stat -c %U -- "$VAULT")" == "$USUARIO" ]] || morir "--vault: $VAULT no es de $USUARIO"
    if ! { como_usuario test -f "$REPO/pyproject.toml" \
        && como_usuario test -f "$REPO/templates/systemd/trovefy-ejecutor.service"; }; then
        morir "no encuentro el repo de Trovefy en $REPO"
    fi
fi

# -- utilidades ----------------------------------------------------------------------------------------
paso() { printf '\n[%d/%d] %s\n' "$1" "$TOTAL" "$2"; }
nota() { printf '      %s\n' "$*"; }

# Ejecuta, o en --simular solo imprime «+ comando».
cmd() {
    if ((SIMULAR)); then printf '+ %s\n' "$*"; else "$@"; fi
}

# Consulta sin efectos. En --simular no se ejecuta y se da por negativa.
consulta() {
    local descripcion="$1"; shift
    if ((SIMULAR)); then
        printf '? %s   (simulación: no)\n' "$descripcion"
        return 1
    fi
    "$@" > /dev/null 2>&1
}

# Copia un archivo de $USUARIO a $EXEC: lo lee $USUARIO y lo escribe trovefy-exec (0600).
copiar_a_exec() {
    local origen="$1" destino="$2"
    cmd "${COMO_EXEC[@]}" install -m 0600 /dev/null "$destino"
    if ((SIMULAR)); then
        printf '+ %s cat -- %s | %s tee -- %s > /dev/null\n' "${COMO_USUARIO[*]}" "$origen" "${COMO_EXEC[*]}" "$destino"
    else
        PENDIENTES_EXEC+=("$destino")
        como_usuario cat -- "$origen" | como_exec tee -- "$destino" > /dev/null
    fi
}

# Limpieza de copias temporales si algo falla a medias (y también al final: rm -f de lo ya movido no hace nada).
PENDIENTES_EXEC=()
PENDIENTES_ROOT=()
limpiar() {
    ((SIMULAR == 0)) || return 0
    local f
    for f in "${PENDIENTES_ROOT[@]}"; do rm -f -- "$f" || true; done
    for f in "${PENDIENTES_EXEC[@]}"; do como_exec rm -f -- "$f" || true; done
}
trap limpiar EXIT

# Sin «cmd | grep -q» (con pipefail, un SIGPIPE daría un falso negativo).
en_grupo() { local g; g="$(id -nG -- "$1")" && [[ " $g " == *" $GRUPO "* ]]; }
tiene_acl() { local a; a="$(como_usuario getfacl -p --omit-header -- "$1")" && grep -q -- "^$2" <<< "$a"; }
tiene_acls_rw() {
    tiene_acl "$1" "user:$EXEC:rwx" && tiene_acl "$1" "default:user:$EXEC:rwx" \
        && tiene_acl "$1" "default:user:$USUARIO:rwx"
}

# Carpeta de root en /var/spool con dueño y modo exactos.
asegurar_dir_spool() {
    local ruta="$1" modo="$2" dueno="$3"
    local u="${dueno%:*}" g="${dueno#*:}"
    if ((SIMULAR == 0)); then
        [[ ! -L "$ruta" ]] || morir "$ruta es un enlace simbólico: revísalo a mano"
        if [[ -d "$ruta" ]]; then
            if [[ "$(stat -c '%U:%G %a' -- "$ruta")" == "$u:$g ${modo#0}" ]]; then
                nota "$ruta ya está ($dueno $modo)"
                return 0
            fi
            [[ "$(stat -c '%U:%G' -- "$ruta")" == "$u:$g" ]] || cmd chown "$u:$g" "$ruta"
            cmd chmod "$modo" "$ruta"
            return 0
        fi
        [[ ! -e "$ruta" ]] || morir "$ruta existe y no es una carpeta"
    fi
    cmd install -d -m 0700 -o "$u" -g "$g" "$ruta"
    cmd chmod "$modo" "$ruta"
}

# Carpeta bajo $EXEC_HOME, creada y ajustada por trovefy-exec. Con «solo_crear», si ya existe no se toca.
asegurar_dir_exec() {
    local ruta="$1" modo="$2" solo_crear="${3:-}" st
    if ((SIMULAR == 0)); then
        ! como_exec test -L "$ruta" || morir "$ruta es un enlace simbólico: revísalo a mano"
        if como_exec test -d "$ruta"; then
            [[ -z "$solo_crear" ]] || return 0
            st="$(como_exec stat -c '%U %a' -- "$ruta")"
            [[ "${st%% *}" == "$EXEC" ]] || morir "$ruta no es de $EXEC: revísalo a mano"
            if [[ "$st" == "$EXEC ${modo#0}" ]]; then nota "$ruta ya está ($modo)"; return 0; fi
            cmd "${COMO_EXEC[@]}" chmod "$modo" "$ruta"
            return 0
        fi
        ! como_exec test -e "$ruta" || morir "$ruta existe y no es una carpeta"
    fi
    cmd "${COMO_EXEC[@]}" install -d -m "$modo" "$ruta"
}

# Archivo existente de trovefy-exec: exige que sea suyo y regular, y lo deja en 0600 (nunca lo lee).
asegurar_archivo_privado() {
    local ruta="$1" st
    ((SIMULAR == 0)) || return 0
    if ! { como_exec test -f "$ruta" && ! como_exec test -L "$ruta"; }; then
        morir "$ruta no es un archivo regular: revísalo a mano"
    fi
    st="$(como_exec stat -c '%U %a' -- "$ruta")"
    [[ "${st%% *}" == "$EXEC" ]] || morir "$ruta no es de $EXEC: revísalo a mano"
    [[ "$st" == "$EXEC 600" ]] || cmd "${COMO_EXEC[@]}" chmod 0600 "$ruta"
}

# Ruta del árbol de $USUARIO que va a recibir una ACL: ni enlace ni de otro dueño.
exigir_de_usuario() {
    local ruta="$1"
    ((SIMULAR == 0)) || return 0
    ! como_usuario test -L "$ruta" || morir "$ruta es un enlace simbólico: no se le ponen ACL (revísalo a mano)"
    [[ "$(como_usuario stat -c %U -- "$ruta")" == "$USUARIO" ]] \
        || morir "$ruta no es de $USUARIO: no se le ponen ACL (revísalo a mano)"
}

if ((SIMULAR)); then
    printf 'SIMULACIÓN: no se ejecuta nada. «+ » = lo que haría; «? » = consulta (se da por negativa).\n'
    cmd "${COMO_USUARIO[@]}" git -C "$REPO" describe --dirty --always
else
    VERSION_CODIGO="$(como_usuario git -C "$REPO" describe --dirty --always 2> /dev/null || printf 'desconocida')"
    printf 'Código: %s (%s)\n' "$VERSION_CODIGO" "$REPO"
fi
printf 'Instalando el ejecutor de Trovefy para %s con el vault %s\n' "$USUARIO" "$VAULT"
CAMBIO_WHEEL=0
CAMBIO_UNIDAD=0

# -- 1. grupo --------------------------------------------------------------------------------------------
paso 1 "Grupo $GRUPO"
if consulta "getent group $GRUPO" getent group "$GRUPO"; then
    nota "ya existe"
else
    cmd groupadd "$GRUPO"
fi

# -- 2. usuario de sistema -------------------------------------------------------------------------------
paso 2 "Usuario de sistema $EXEC (sin shell)"
if consulta "id -u $EXEC" id -u "$EXEC"; then
    nota "ya existe"
else
    cmd useradd --system --create-home --home-dir "$EXEC_HOME" --shell /usr/sbin/nologin --user-group "$EXEC"
fi
if ((SIMULAR)); then
    cmd "${COMO_EXEC[@]}" chmod 0750 "$EXEC_HOME"
else
    asegurar_dir_exec "$EXEC_HOME" 0750
fi

# -- 3. grupos -------------------------------------------------------------------------------------------
paso 3 "$USUARIO y $EXEC en el grupo $GRUPO"
AVISO_GRUPO=0
for u in "$USUARIO" "$EXEC"; do
    if consulta "¿$u está en $GRUPO? (id -nG $u)" en_grupo "$u"; then
        nota "$u ya está en $GRUPO"
    else
        cmd usermod -aG "$GRUPO" "$u"
        [[ "$u" != "$USUARIO" ]] || AVISO_GRUPO=1
    fi
done
if ((AVISO_GRUPO)); then
    nota "Cierra y abre la terminal (o «wsl --shutdown» desde Windows) para que $USUARIO vea el grupo $GRUPO."
fi

# -- 4. buzón --------------------------------------------------------------------------------------------
paso 4 "Buzón $SPOOL"
asegurar_dir_spool "$SPOOL" 0750 "root:$GRUPO"
asegurar_dir_spool "$SPOOL/entrada" 2770 "$EXEC:$GRUPO"
asegurar_dir_spool "$SPOOL/procesadas" 2750 "$EXEC:$GRUPO"
asegurar_dir_spool "$SPOOL/estado" 2750 "$EXEC:$GRUPO"

# -- 5. uv -----------------------------------------------------------------------------------------------
paso 5 "uv en $UV"
if consulta "test -x $UV" test -x "$UV"; then
    nota "ya está"
else
    ORIGEN_UV=""
    for c in "$HOME_USUARIO/.local/bin/uv" "$HOME_USUARIO/.cargo/bin/uv"; do
        if ((SIMULAR)) || como_usuario test -x "$c"; then ORIGEN_UV="$c"; break; fi
    done
    [[ -n "$ORIGEN_UV" ]] || morir "no encuentro uv de $USUARIO: instálalo (https://docs.astral.sh/uv/) y repite"
    # Lo lee $USUARIO; root solo escribe su propio temporal en /usr/local/bin y lo mueve.
    # shellcheck disable=SC2016  # en la simulación se imprime "$TMP_UV" literal
    if ((SIMULAR)); then
        printf '+ TMP_UV=$(mktemp /usr/local/bin/.uv.XXXXXX)\n'
        printf '+ %s cat -- %s > "$TMP_UV"\n' "${COMO_USUARIO[*]}" "$ORIGEN_UV"
        printf '+ chmod 0755 "$TMP_UV"\n'
        printf '+ mv -f -- "$TMP_UV" %s\n' "$UV"
    else
        TMP_UV="$(mktemp /usr/local/bin/.uv.XXXXXX)"
        PENDIENTES_ROOT+=("$TMP_UV")
        como_usuario cat -- "$ORIGEN_UV" > "$TMP_UV"
        chmod 0755 "$TMP_UV"
        mv -f -- "$TMP_UV" "$UV"
    fi
fi

# -- 6. wheel fijado -------------------------------------------------------------------------------------
paso 6 "Wheel de Trovefy y dependencias fijadas (uv.lock), como $USUARIO"
CONSTRUCCION="$HOME_USUARIO/.cache/trovefy-ejecutor-wheel"   # fuera del repo
# shellcheck disable=SC2016  # el glob lo expande la shell de $USUARIO
cmd "${COMO_USUARIO[@]}" bash -c 'rm -f -- "$1"/trovefy-*.whl' _ "$CONSTRUCCION"
cmd "${COMO_USUARIO[@]}" "$UV" build --wheel --out-dir "$CONSTRUCCION" "$REPO"
cmd "${COMO_USUARIO[@]}" "$UV" export --frozen --no-dev --no-hashes --no-emit-project \
    --project "$REPO" -o "$CONSTRUCCION/constraints.txt"
if ((SIMULAR)); then
    WHEEL="$CONSTRUCCION/trovefy-VERSION-py3-none-any.whl"
else
    ruedas=()
    while IFS= read -r w; do ruedas+=("$w"); done \
        < <(como_usuario find "$CONSTRUCCION" -maxdepth 1 -type f -name 'trovefy-*.whl')
    [[ ${#ruedas[@]} -eq 1 ]] || morir "uv build no dejó exactamente un wheel en $CONSTRUCCION"
    WHEEL="${ruedas[0]}"
fi
NOMBRE_WHEEL="${WHEEL##*/}"
[[ "$NOMBRE_WHEEL" =~ ^trovefy-[A-Za-z0-9._+-]+\.whl$ ]] || morir "nombre de wheel inesperado: $NOMBRE_WHEEL"

# -- 7. instalación como trovefy-exec --------------------------------------------------------------------
paso 7 "Instalar el wheel para $EXEC (uv tool) y comprobar tzdata"
asegurar_dir_exec "$EXEC_HOME/.cache" 0700 solo_crear
asegurar_dir_exec "$ENTREGA" 0700
copiar_a_exec "$WHEEL" "$ENTREGA/$NOMBRE_WHEEL"
copiar_a_exec "$CONSTRUCCION/constraints.txt" "$ENTREGA/constraints.txt"
# Solo se reinstala (y luego se reinicia el servicio) si cambia el wheel o las dependencias fijadas.
HUELLA=""
if ((SIMULAR == 0)); then
    HUELLA="$(como_exec sha256sum -- "$ENTREGA/$NOMBRE_WHEEL" "$ENTREGA/constraints.txt" | cut -d' ' -f1 | tr -d '\n')"
fi
wheel_instalado() {
    [[ -n "$HUELLA" && "$(como_exec cat -- "$ENTREGA/instalado.sha256" 2> /dev/null)" == "$HUELLA" ]] \
        && como_exec test -x "$PY"
}
if consulta "¿el wheel es el ya instalado? (${COMO_EXEC[*]} sha256sum, comparado con $ENTREGA/instalado.sha256)" \
    wheel_instalado; then
    nota "el código instalado ya es este: no se reinstala"
else
    cmd "${COMO_EXEC[@]}" "$UV" tool install --force --python 3.12 --constraints "$ENTREGA/constraints.txt" \
        "$ENTREGA/$NOMBRE_WHEEL"
    if ((SIMULAR)); then
        printf '+ printf "%%s" "<sha256 del wheel>" | %s tee -- %s > /dev/null\n' "${COMO_EXEC[*]}" "$ENTREGA/instalado.sha256"
    else
        printf '%s' "$HUELLA" | como_exec tee -- "$ENTREGA/instalado.sha256" > /dev/null
    fi
    CAMBIO_WHEEL=1
fi
cmd "${COMO_EXEC[@]}" rm -f -- "$ENTREGA/$NOMBRE_WHEEL" "$ENTREGA/constraints.txt"
ZONA_PY='import zoneinfo; zoneinfo.ZoneInfo("America/Bogota")'
if consulta "${COMO_EXEC[*]} $PY -I -c '$ZONA_PY'" como_exec "$PY" -I -c "$ZONA_PY"; then
    nota "zona horaria disponible (tzdata)"
else
    cmd apt-get install -y tzdata
    if ((SIMULAR == 0)) && ! como_exec "$PY" -I -c "$ZONA_PY" > /dev/null 2>&1; then
        morir "Python no encuentra la zona America/Bogota: instala tzdata («sudo apt-get install -y tzdata») y repite"
    fi
fi

# -- 8. secretos -----------------------------------------------------------------------------------------
paso 8 "Configuración y secretos.env (0600, solo si no existe)"
asegurar_dir_exec "$EXEC_HOME/.config" 0700 solo_crear
asegurar_dir_exec "$CONFIG" 0700
if consulta "${COMO_EXEC[*]} test -e $SECRETOS" como_exec test -e "$SECRETOS"; then
    asegurar_archivo_privado "$SECRETOS"
    nota "secretos.env ya existe: no se toca"
else
    cmd "${COMO_EXEC[@]}" install -m 0600 /dev/null "$SECRETOS"
    if ((SIMULAR)); then
        # shellcheck disable=SC2016  # se imprime el comando, no su resultado
        printf '+ %s | %s tee -a -- %s > /dev/null\n' \
            'printf "HMAC_CLAVE=%s\nCLAUDE_UID=%s\nMETA_TOKEN=\nTELEGRAM_BOT_TOKEN=\n" "$(openssl rand -hex 32)" "$(id -u '"$USUARIO"')"' \
            "${COMO_EXEC[*]}" "$SECRETOS"
    else
        clave_hmac="$(openssl rand -hex 32)"
        uid_claude="$(id -u "$USUARIO")"
        [[ "$clave_hmac" =~ ^[0-9a-f]{64}$ && "$uid_claude" =~ ^[0-9]+$ ]] || morir "no se pudo generar secretos.env"
        # printf es interno de bash: la clave no aparece en la lista de procesos.
        printf 'HMAC_CLAVE=%s\nCLAUDE_UID=%s\nMETA_TOKEN=\nTELEGRAM_BOT_TOKEN=\n' "$clave_hmac" "$uid_claude" \
            | como_exec tee -a -- "$SECRETOS" > /dev/null
        unset clave_hmac
    fi
    nota "Faltan META_TOKEN y TELEGRAM_BOT_TOKEN: rellénalas tú con «sudo -u $EXEC nano $SECRETOS»."
fi

# -- 9. límites ------------------------------------------------------------------------------------------
paso 9 "limites.yaml (0600)"
if consulta "${COMO_EXEC[*]} test -e $LIMITES" como_exec test -e "$LIMITES"; then
    asegurar_archivo_privado "$LIMITES"
    nota "limites.yaml ya existe: no se sobrescribe"
    if consulta "${COMO_EXEC[*]} test -f $SPOOL/estado/meta.json" como_exec test -f "$SPOOL/estado/meta.json"; then
        OFFSET_PY='import json, sys
from pathlib import Path
from trovefy_ejecutor.instalacion import OffsetDistinto, fijar_offset
try:
    meta = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    n = fijar_offset(Path(sys.argv[1]), meta if isinstance(meta, dict) else {})
except OffsetDistinto as e:
    print(e, file=sys.stderr)
    sys.exit(3)
except Exception as e:
    print(f"no se pudo fijar el offset ({type(e).__name__})", file=sys.stderr)
    sys.exit(2)
print(f"offset fijado a {n} (moneda leída por Graph)" if n is not None else "offset sin cambios")'
        cmd "${COMO_EXEC[@]}" "$PY" -I -c "$OFFSET_PY" "$LIMITES" "$SPOOL/estado/meta.json" \
            || morir "offset no fijado: revisa limites.yaml y estado/meta.json (P-21)"
    else
        nota "Sin estado/meta.json todavía: el offset queda en null hasta «trovefy-ejecutor comprobar-meta»."
    fi
else
    ARRANQUE="$VAULT/config/arranque.yaml"
    PLANTILLA="$REPO/templates/ejecutor/limites.yaml"
    asegurar_dir_exec "$ENTREGA" 0700
    if ((SIMULAR == 0)); then
        como_usuario test -f "$ARRANQUE" || morir "no existe $ARRANQUE: completa el paso 06 de /arranque"
    fi
    # Copias para trovefy-exec (no lee tu vault ni tu repo); root nunca ejecuta su Python.
    copiar_a_exec "$ARRANQUE" "$ENTREGA/arranque.yaml"
    copiar_a_exec "$PLANTILLA" "$ENTREGA/limites.plantilla.yaml"
    if ((SIMULAR)); then
        printf '+ %s %s -I -m trovefy_ejecutor.instalacion cuenta %s   # → read ACT MON ZONA\n' \
            "${COMO_EXEC[*]}" "$PY" "$ENTREGA/arranque.yaml"
        # shellcheck disable=SC2016  # en la simulación se imprimen los nombres de las variables
        ACT='"$ACT"'
        # shellcheck disable=SC2016
        MON='"$MON"'
        # shellcheck disable=SC2016
        ZONA='"$ZONA"'
    else
        CUENTA="$(como_exec "$PY" -I -m trovefy_ejecutor.instalacion cuenta "$ENTREGA/arranque.yaml")" \
            || morir "completa el paso 06 de /arranque (cuenta publicitaria) y repite"
        read -r ACT MON ZONA <<< "$CUENTA"
        [[ "${ACT:-}" =~ ^act_[0-9]+$ && "${MON:-}" =~ ^[A-Z]{3}$ && -n "${ZONA:-}" ]] \
            || morir "completa el paso 06 de /arranque (cuenta publicitaria) y repite"
    fi
    # limites.yaml.nuevo lo escribe, valida y mueve trovefy-exec.
    cmd "${COMO_EXEC[@]}" install -m 0600 /dev/null "$LIMITES.nuevo"
    if ((SIMULAR)); then
        printf '+ %s %s -I -m trovefy_ejecutor.instalacion limites %s %s %s %s | %s tee -- %s > /dev/null\n' \
            "${COMO_EXEC[*]}" "$PY" "$ENTREGA/limites.plantilla.yaml" "$ACT" "$MON" "$ZONA" "${COMO_EXEC[*]}" "$LIMITES.nuevo"
    else
        PENDIENTES_EXEC+=("$LIMITES.nuevo")
        como_exec "$PY" -I -m trovefy_ejecutor.instalacion limites "$ENTREGA/limites.plantilla.yaml" \
            "$ACT" "$MON" "$ZONA" | como_exec tee -- "$LIMITES.nuevo" > /dev/null \
            || morir "no se pudo generar limites.yaml (¿moneda distinta de COP? P-21)"
    fi
    cmd "${COMO_EXEC[@]}" "$PY" -I -c \
        'import sys; from trovefy_ejecutor.limites import cargar_limites; cargar_limites(sys.argv[1])' "$LIMITES.nuevo" \
        || morir "el limites.yaml generado no es válido"
    cmd "${COMO_EXEC[@]}" mv -- "$LIMITES.nuevo" "$LIMITES"
    cmd "${COMO_EXEC[@]}" rm -f -- "$ENTREGA/arranque.yaml" "$ENTREGA/limites.plantilla.yaml"
    nota "limites.yaml creado para la cuenta del paso 06 (moneda $MON, offset: null)."
fi

# -- 10. datos -------------------------------------------------------------------------------------------
paso 10 "Datos del ejecutor $DATOS (0700)"
asegurar_dir_exec "$EXEC_HOME/.local" 0700 solo_crear
asegurar_dir_exec "$EXEC_HOME/.local/share" 0700 solo_crear
asegurar_dir_exec "$DATOS" 0700

# -- 11. vault (ACL, como $USUARIO) ----------------------------------------------------------------------
paso 11 "Permisos de $EXEC en el vault (ACL puestas por $USUARIO)"
if consulta "command -v setfacl" command -v setfacl; then
    nota "acl ya está"
else
    cmd apt-get install -y acl
fi
CARPETAS_RW=("$VAULT/propuestas" "$VAULT/ledger/auditoria" "$VAULT/raw/telegram" "$VAULT/raw/telegram/motivos")
CARPETAS_X=("$HOME_USUARIO" "$VAULT" "$VAULT/ledger" "$VAULT/raw")
faltan=()
for d in "${CARPETAS_RW[@]}"; do
    if ((SIMULAR)) || ! como_usuario test -d "$d"; then faltan+=("$d"); fi
done
if ((${#faltan[@]})); then cmd "${COMO_USUARIO[@]}" mkdir -p -- "${faltan[@]}"; fi
for d in "${CARPETAS_X[@]}" "${CARPETAS_RW[@]}"; do exigir_de_usuario "$d"; done
for d in "${CARPETAS_X[@]}"; do
    if consulta "${COMO_USUARIO[*]} getfacl $d (user:$EXEC:--x)" tiene_acl "$d" "user:$EXEC:--x"; then
        nota "$d ya tiene user:$EXEC:--x"
    else
        cmd "${COMO_USUARIO[@]}" setfacl -m "u:$EXEC:--x" "$d"
    fi
done
for d in "${CARPETAS_RW[@]}"; do
    if consulta "${COMO_USUARIO[*]} getfacl $d (user:$EXEC:rwx y defaults)" tiene_acls_rw "$d"; then
        nota "$d ya tiene las ACL"
    else
        cmd "${COMO_USUARIO[@]}" setfacl -m "u:$EXEC:rwx,d:u:$EXEC:rwx,d:u:$USUARIO:rwx" "$d"
    fi
done
if ((SIMULAR == 0)) && ! { como_exec test -w "$VAULT/propuestas" && como_exec test -x "$VAULT/propuestas"; }; then
    morir "$EXEC no llega a $VAULT/propuestas: revisa los permisos de las carpetas que contienen el vault"
fi

# -- 12. unidad (root, en /etc) --------------------------------------------------------------------------
paso 12 "Unidad de systemd $UNIDAD"
FUENTE_UNIDAD="$REPO/templates/systemd/trovefy-ejecutor.service"
# shellcheck disable=SC2016  # en la simulación se imprime "$TMP_UNIDAD" literal
if ((SIMULAR)); then
    printf '+ TMP_UNIDAD=$(mktemp /etc/systemd/system/.trovefy-ejecutor.XXXXXX)\n'
    printf '+ %s cat -- %s | <sustituir {vault} por %s> > "$TMP_UNIDAD"   # /etc/systemd/system/\n' \
        "${COMO_USUARIO[*]}" "$FUENTE_UNIDAD" "$VAULT"
    printf '+ chmod 0644 "$TMP_UNIDAD"\n'
    printf '+ mv -f -- "$TMP_UNIDAD" %s\n' "$UNIDAD"
    cmd systemctl daemon-reload
    CAMBIO_UNIDAD=1
else
    plantilla="$(como_usuario cat -- "$FUENTE_UNIDAD")"
    contenido="${plantilla//"{vault}"/"$VAULT"}"
    [[ "$contenido" != *"{vault}"* ]] || morir "no se pudo sustituir {vault} en la unidad"
    if [[ -f "$UNIDAD" && ! -L "$UNIDAD" && "$(< "$UNIDAD")" == "$contenido" ]]; then
        nota "la unidad ya está al día"
    else
        TMP_UNIDAD="$(mktemp /etc/systemd/system/.trovefy-ejecutor.XXXXXX)"
        PENDIENTES_ROOT+=("$TMP_UNIDAD")
        printf '%s\n' "$contenido" > "$TMP_UNIDAD"
        chmod 0644 "$TMP_UNIDAD"
        mv -f -- "$TMP_UNIDAD" "$UNIDAD"
        cmd systemctl daemon-reload
        CAMBIO_UNIDAD=1
    fi
fi
if consulta "systemctl is-enabled trovefy-ejecutor" systemctl is-enabled --quiet trovefy-ejecutor; then
    nota "ya está habilitada"
else
    cmd systemctl enable trovefy-ejecutor
fi

# -- 13. arranque ----------------------------------------------------------------------------------------
paso 13 "Arranque"
secretos_emparejados() {
    como_exec grep -Eq '^TELEGRAM_BOT_TOKEN=[^[:space:]]+' "$SECRETOS" \
        && como_exec grep -Eq '^TELEGRAM_CHAT_ID=-?[0-9]+$' "$SECRETOS"
}
if consulta "¿secretos.env tiene TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID? (sin mostrarlos)" secretos_emparejados; then
    if ((CAMBIO_WHEEL || CAMBIO_UNIDAD)); then
        nota "Cambió el código o la unidad: se reinicia el servicio."
        cmd systemctl restart trovefy-ejecutor
    else
        nota "Nada cambió: no se reinicia (si estaba parado, se arranca)."
        cmd systemctl start trovefy-ejecutor
    fi
else
    nota "Aún no se arranca. Rellena TELEGRAM_BOT_TOKEN y META_TOKEN, empareja primero:"
    nota "    sudo -u $EXEC $BIN emparejar"
    nota "y luego:"
    nota "    sudo systemctl start trovefy-ejecutor"
fi

# -- resumen ---------------------------------------------------------------------------------------------
if ((SIMULAR)); then printf '\nListo (simulación: no se ejecutó nada).\n'; else printf '\nListo.\n'; fi
printf 'Comprueba:\n'
printf '    systemctl status trovefy-ejecutor\n'
printf '    trovefy buzon estado        # tras cerrar y abrir la terminal (grupo %s)\n' "$GRUPO"
printf 'Si el servicio para con código 5 (auditoría corrupta), repárala con el servicio parado:\n'
printf '    sudo systemctl stop trovefy-ejecutor\n'
printf '    sudo -u %s %s auditoria reparar\n' "$EXEC" "$BIN"
printf '    sudo systemctl start trovefy-ejecutor\n'
printf 'Si Telegram no responde, STOP de respaldo: sudo -u %s %s stop "motivo"\n' "$EXEC" "$BIN"
if ((SIMULAR == 0)); then
    systemctl --no-pager status trovefy-ejecutor || true
fi
