#!/usr/bin/env bash
# Instalador del «ejecutor» de Trovefy (plan 12). Lo ejecutas tú, una vez y cuando quieras actualizar:
#
#     sudo bash scripts/instalar-ejecutor.sh [--vault RUTA]
#     bash scripts/instalar-ejecutor.sh --simular [--vault RUTA]   # solo imprime lo que haría
#
# Es idempotente: cada paso comprueba antes de actuar y un segundo pase no cambia nada; nunca sobrescribe
# secretos.env ni limites.yaml. Nunca muestra el contenido de secretos.env. Nunca borra carpetas.
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
if ((SIMULAR == 0)); then
    [[ -d "$VAULT" && ! -L "$VAULT" ]] || morir "--vault: $VAULT no es una carpeta (¿hiciste /arranque?)"
    [[ "$(stat -c %U -- "$VAULT")" == "$USUARIO" ]] || morir "--vault: $VAULT no es de $USUARIO"
    [[ -f "$REPO/pyproject.toml" && -f "$REPO/templates/systemd/trovefy-ejecutor.service" ]] \
        || morir "no encuentro el repo de Trovefy en $REPO"
fi

# -- utilidades ----------------------------------------------------------------------------------------
paso() { printf '\n[%d/%d] %s\n' "$1" "$TOTAL" "$2"; }
nota() { printf '      %s\n' "$*"; }

# Ejecuta, o en --simular solo imprime «+ comando».
cmd() {
    if ((SIMULAR)); then printf '+ %s\n' "$*"; else "$@"; fi
}

# Igual que cmd, con la salida estándar a un archivo.
cmd_a() {
    local destino="$1"; shift
    if ((SIMULAR)); then printf '+ %s > %s\n' "$*" "$destino"; else "$@" > "$destino"; fi
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

# Sin «cmd | grep -q» (con pipefail, un SIGPIPE daría un falso negativo).
en_grupo() { local g; g="$(id -nG -- "$1")" && [[ " $g " == *" $GRUPO "* ]]; }
tiene_acl() { local a; a="$(getfacl -p --omit-header -- "$1")" && grep -q -- "^$2" <<< "$a"; }
tiene_acls_rw() {
    tiene_acl "$1" "user:$EXEC:rwx" && tiene_acl "$1" "default:user:$EXEC:rwx" \
        && tiene_acl "$1" "default:user:$USUARIO:rwx"
}
como_exec() { sudo -u "$EXEC" -H "$@"; }

# Carpeta con dueño y modo exactos. Con «solo_crear», si ya existe no se toca.
asegurar_dir() {
    local ruta="$1" modo="$2" dueno="$3" solo_crear="${4:-}"
    local u="${dueno%:*}" g="${dueno#*:}"
    if ((SIMULAR == 0)); then
        [[ ! -L "$ruta" ]] || morir "$ruta es un enlace simbólico: revísalo a mano"
        if [[ -d "$ruta" ]]; then
            if [[ -n "$solo_crear" ]]; then return 0; fi
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

# Archivo existente: exige dueño trovefy-exec y 0600 (lo corrige si hace falta; nunca lo lee).
asegurar_archivo_privado() {
    local ruta="$1"
    ((SIMULAR == 0)) || return 0
    [[ -f "$ruta" && ! -L "$ruta" ]] || morir "$ruta no es un archivo regular: revísalo a mano"
    if [[ "$(stat -c '%U:%G %a' -- "$ruta")" != "$EXEC:$EXEC 600" ]]; then
        cmd chown "$EXEC:$EXEC" "$ruta"
        cmd chmod 0600 "$ruta"
    fi
}

if ((SIMULAR)); then
    printf 'SIMULACIÓN: no se ejecuta nada. «+ » = lo que haría; «? » = consulta (se da por negativa).\n'
fi
printf 'Instalando el ejecutor de Trovefy para %s con el vault %s\n' "$USUARIO" "$VAULT"

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
asegurar_dir "$EXEC_HOME" 0750 "$EXEC:$EXEC"

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
asegurar_dir "$SPOOL" 0750 "root:$GRUPO"
asegurar_dir "$SPOOL/entrada" 2770 "$EXEC:$GRUPO"
asegurar_dir "$SPOOL/procesadas" 2750 "$EXEC:$GRUPO"
asegurar_dir "$SPOOL/estado" 2750 "$EXEC:$GRUPO"

# -- 5. uv -----------------------------------------------------------------------------------------------
paso 5 "uv en $UV"
if consulta "test -x $UV" test -x "$UV"; then
    nota "ya está"
else
    ORIGEN_UV=""
    for c in "$HOME_USUARIO/.local/bin/uv" "$HOME_USUARIO/.cargo/bin/uv"; do
        if ((SIMULAR)) || [[ -x "$c" && ! -L "$c" ]]; then ORIGEN_UV="$c"; break; fi
    done
    [[ -n "$ORIGEN_UV" ]] || morir "no encuentro uv de $USUARIO: instálalo (https://docs.astral.sh/uv/) y repite"
    cmd install -m 0755 -o root -g root "$ORIGEN_UV" "$UV"
fi

# -- 6. wheel fijado -------------------------------------------------------------------------------------
paso 6 "Wheel de Trovefy y dependencias fijadas (uv.lock), como $USUARIO"
CONSTRUCCION="$HOME_USUARIO/.cache/trovefy-ejecutor-wheel"   # fuera del repo
if ((SIMULAR == 0)) && [[ -d "$CONSTRUCCION" ]]; then
    viejos=("$CONSTRUCCION"/trovefy-*.whl)
    if [[ -e "${viejos[0]}" ]]; then cmd rm -f -- "${viejos[@]}"; fi
fi
cmd sudo -u "$USUARIO" -H "$UV" build --wheel --out-dir "$CONSTRUCCION" "$REPO"
cmd sudo -u "$USUARIO" -H "$UV" export --frozen --no-dev --no-hashes --no-emit-project \
    --project "$REPO" -o "$CONSTRUCCION/constraints.txt"
if ((SIMULAR)); then
    WHEEL="$CONSTRUCCION/trovefy-VERSION-py3-none-any.whl"
else
    ruedas=("$CONSTRUCCION"/trovefy-*.whl)
    [[ ${#ruedas[@]} -eq 1 && -f "${ruedas[0]}" ]] || morir "uv build no dejó exactamente un wheel en $CONSTRUCCION"
    WHEEL="${ruedas[0]}"
fi
NOMBRE_WHEEL="${WHEEL##*/}"

# -- 7. instalación como trovefy-exec --------------------------------------------------------------------
paso 7 "Instalar el wheel para $EXEC (uv tool) y comprobar tzdata"
asegurar_dir "$EXEC_HOME/.cache" 0700 "$EXEC:$EXEC" solo_crear
asegurar_dir "$ENTREGA" 0700 "$EXEC:$EXEC"
cmd install -m 0600 -o "$EXEC" -g "$EXEC" "$WHEEL" "$ENTREGA/$NOMBRE_WHEEL"
cmd install -m 0600 -o "$EXEC" -g "$EXEC" "$CONSTRUCCION/constraints.txt" "$ENTREGA/constraints.txt"
cmd sudo -u "$EXEC" -H "$UV" tool install --force --python 3.12 --constraints "$ENTREGA/constraints.txt" \
    "$ENTREGA/$NOMBRE_WHEEL"
cmd rm -f -- "$ENTREGA/$NOMBRE_WHEEL" "$ENTREGA/constraints.txt"
ZONA_PY='import zoneinfo; zoneinfo.ZoneInfo("America/Bogota")'
if consulta "sudo -u $EXEC $PY -I -c '$ZONA_PY'" como_exec "$PY" -I -c "$ZONA_PY"; then
    nota "zona horaria disponible (tzdata)"
else
    cmd apt-get install -y tzdata
    if ((SIMULAR == 0)) && ! como_exec "$PY" -I -c "$ZONA_PY" > /dev/null 2>&1; then
        morir "Python no encuentra la zona America/Bogota: instala tzdata («sudo apt-get install -y tzdata») y repite"
    fi
fi

# -- 8. secretos -----------------------------------------------------------------------------------------
paso 8 "Configuración y secretos.env (0600, solo si no existe)"
asegurar_dir "$EXEC_HOME/.config" 0700 "$EXEC:$EXEC" solo_crear
asegurar_dir "$CONFIG" 0700 "$EXEC:$EXEC"
if consulta "test -e $SECRETOS" test -e "$SECRETOS"; then
    asegurar_archivo_privado "$SECRETOS"
    nota "secretos.env ya existe: no se toca"
else
    cmd install -m 0600 -o "$EXEC" -g "$EXEC" /dev/null "$SECRETOS"
    if ((SIMULAR)); then
        # shellcheck disable=SC2016  # se imprime el comando, no su resultado
        printf '+ %s >> %s\n' 'printf "HMAC_CLAVE=%s\n" "$(openssl rand -hex 32)"' "$SECRETOS"
        printf '+ %s >> %s\n' "printf \"CLAUDE_UID=%s\\n\" \"\$(id -u $USUARIO)\"" "$SECRETOS"
        printf '+ %s >> %s\n' 'printf "META_TOKEN=\nTELEGRAM_BOT_TOKEN=\n"' "$SECRETOS"
    else
        clave_hmac="$(openssl rand -hex 32)"
        uid_claude="$(id -u "$USUARIO")"
        [[ "$clave_hmac" =~ ^[0-9a-f]{64}$ && "$uid_claude" =~ ^[0-9]+$ ]] || morir "no se pudo generar secretos.env"
        printf 'HMAC_CLAVE=%s\nCLAUDE_UID=%s\nMETA_TOKEN=\nTELEGRAM_BOT_TOKEN=\n' \
            "$clave_hmac" "$uid_claude" >> "$SECRETOS"
        unset clave_hmac
    fi
    nota "Faltan META_TOKEN y TELEGRAM_BOT_TOKEN: rellénalas tú con «sudo -u $EXEC nano $SECRETOS»."
fi

# -- 9. límites ------------------------------------------------------------------------------------------
paso 9 "limites.yaml (0600)"
if consulta "test -e $LIMITES" test -e "$LIMITES"; then
    asegurar_archivo_privado "$LIMITES"
    nota "limites.yaml ya existe: no se sobrescribe"
    if consulta "test -f $SPOOL/estado/meta.json" test -f "$SPOOL/estado/meta.json"; then
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
        cmd sudo -u "$EXEC" -H "$PY" -I -c "$OFFSET_PY" "$LIMITES" "$SPOOL/estado/meta.json" \
            || morir "offset no fijado: revisa limites.yaml y estado/meta.json (P-21)"
    else
        nota "Sin estado/meta.json todavía: el offset queda en null hasta «trovefy-ejecutor comprobar-meta»."
    fi
else
    ARRANQUE="$VAULT/config/arranque.yaml"
    PLANTILLA="$REPO/templates/ejecutor/limites.yaml"
    asegurar_dir "$ENTREGA" 0700 "$EXEC:$EXEC"
    if ((SIMULAR == 0)); then
        [[ -f "$ARRANQUE" && ! -L "$ARRANQUE" ]] || morir "no existe $ARRANQUE: completa el paso 06 de /arranque"
    fi
    # Copias para trovefy-exec (no lee tu vault ni tu repo); root nunca ejecuta su Python.
    cmd install -m 0600 -o "$EXEC" -g "$EXEC" "$ARRANQUE" "$ENTREGA/arranque.yaml"
    cmd install -m 0600 -o "$EXEC" -g "$EXEC" "$PLANTILLA" "$ENTREGA/limites.plantilla.yaml"
    if ((SIMULAR)); then
        printf '+ read ACT MON ZONA < <(sudo -u %s -H %s -I -m trovefy_ejecutor.instalacion cuenta %s)   # %s\n' \
            "$EXEC" "$PY" "$ENTREGA/arranque.yaml" "copia de $ARRANQUE"
        # shellcheck disable=SC2016  # en la simulación se imprimen los nombres de las variables
        ACT='"$ACT"'
        # shellcheck disable=SC2016
        MON='"$MON"'
        # shellcheck disable=SC2016
        ZONA='"$ZONA"'
    else
        if ! CUENTA="$(como_exec "$PY" -I -m trovefy_ejecutor.instalacion cuenta "$ENTREGA/arranque.yaml")"; then
            cmd rm -f -- "$ENTREGA/arranque.yaml" "$ENTREGA/limites.plantilla.yaml"
            morir "completa el paso 06 de /arranque (cuenta publicitaria) y repite"
        fi
        read -r ACT MON ZONA <<< "$CUENTA"
        [[ "${ACT:-}" =~ ^act_[0-9]+$ && "${MON:-}" =~ ^[A-Z]{3}$ && -n "${ZONA:-}" ]] \
            || morir "completa el paso 06 de /arranque (cuenta publicitaria) y repite"
    fi
    cmd install -m 0600 -o "$EXEC" -g "$EXEC" /dev/null "$LIMITES.nuevo"
    cmd_a "$LIMITES.nuevo" sudo -u "$EXEC" -H "$PY" -I -m trovefy_ejecutor.instalacion limites \
        "$ENTREGA/limites.plantilla.yaml" "$ACT" "$MON" "$ZONA" \
        || { cmd rm -f -- "$LIMITES.nuevo"; morir "no se pudo generar limites.yaml (¿moneda distinta de COP? P-21)"; }
    cmd sudo -u "$EXEC" -H "$PY" -I -c \
        'import sys; from trovefy_ejecutor.limites import cargar_limites; cargar_limites(sys.argv[1])' "$LIMITES.nuevo" \
        || { cmd rm -f -- "$LIMITES.nuevo"; morir "el limites.yaml generado no es válido"; }
    cmd mv -- "$LIMITES.nuevo" "$LIMITES"
    cmd rm -f -- "$ENTREGA/arranque.yaml" "$ENTREGA/limites.plantilla.yaml"
    nota "limites.yaml creado para la cuenta del paso 06 (moneda $MON, offset: null)."
fi

# -- 10. datos -------------------------------------------------------------------------------------------
paso 10 "Datos del ejecutor $DATOS (0700)"
asegurar_dir "$EXEC_HOME/.local" 0700 "$EXEC:$EXEC" solo_crear
asegurar_dir "$EXEC_HOME/.local/share" 0700 "$EXEC:$EXEC" solo_crear
asegurar_dir "$DATOS" 0700 "$EXEC:$EXEC"

# -- 11. vault (ACL) -------------------------------------------------------------------------------------
paso 11 "Permisos de $EXEC en el vault (ACL)"
if consulta "command -v setfacl" command -v setfacl; then
    nota "acl ya está"
else
    cmd apt-get install -y acl
fi
CARPETAS_RW=("$VAULT/propuestas" "$VAULT/ledger/auditoria" "$VAULT/raw/telegram" "$VAULT/raw/telegram/motivos")
faltan=()
for d in "${CARPETAS_RW[@]}"; do
    if ((SIMULAR)) || [[ ! -d "$d" ]]; then faltan+=("$d"); fi
done
if ((${#faltan[@]})); then cmd sudo -u "$USUARIO" mkdir -p -- "${faltan[@]}"; fi
for d in "$HOME_USUARIO" "$VAULT" "$VAULT/ledger" "$VAULT/raw"; do
    if consulta "getfacl $d (user:$EXEC:--x)" tiene_acl "$d" "user:$EXEC:--x"; then
        nota "$d ya tiene user:$EXEC:--x"
    else
        cmd setfacl -m "u:$EXEC:--x" "$d"
    fi
done
for d in "${CARPETAS_RW[@]}"; do
    if consulta "getfacl $d (user:$EXEC:rwx y defaults)" tiene_acls_rw "$d"; then
        nota "$d ya tiene las ACL"
    else
        cmd setfacl -m "u:$EXEC:rwx,d:u:$EXEC:rwx,d:u:$USUARIO:rwx" "$d"
    fi
done
if ((SIMULAR == 0)) && ! { como_exec test -w "$VAULT/propuestas" && como_exec test -x "$VAULT/propuestas"; }; then
    morir "$EXEC no llega a $VAULT/propuestas: revisa los permisos de las carpetas que contienen el vault"
fi

# -- 12. unidad ------------------------------------------------------------------------------------------
paso 12 "Unidad de systemd $UNIDAD"
FUENTE_UNIDAD="$REPO/templates/systemd/trovefy-ejecutor.service"
if ((SIMULAR)); then
    printf '+ sustituir {vault} por %s en %s\n' "$VAULT" "$FUENTE_UNIDAD"
    cmd install -m 0644 -o root -g root /dev/null "$UNIDAD.nuevo"
    printf '+ printf "%%s\\n" "<unidad con TROVEFY_VAULT=%s>" > %s\n' "$VAULT" "$UNIDAD.nuevo"
    cmd mv -- "$UNIDAD.nuevo" "$UNIDAD"
    cmd systemctl daemon-reload
else
    plantilla="$(< "$FUENTE_UNIDAD")"
    contenido="${plantilla//"{vault}"/"$VAULT"}"
    [[ "$contenido" != *"{vault}"* ]] || morir "no se pudo sustituir {vault} en la unidad"
    if [[ -f "$UNIDAD" && ! -L "$UNIDAD" && "$(< "$UNIDAD")" == "$contenido" ]]; then
        nota "la unidad ya está al día"
    else
        cmd install -m 0644 -o root -g root /dev/null "$UNIDAD.nuevo"
        printf '%s\n' "$contenido" > "$UNIDAD.nuevo"
        cmd mv -- "$UNIDAD.nuevo" "$UNIDAD"
        cmd systemctl daemon-reload
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
    grep -Eq '^TELEGRAM_BOT_TOKEN=[^[:space:]]+' "$SECRETOS" && grep -Eq '^TELEGRAM_CHAT_ID=-?[0-9]+$' "$SECRETOS"
}
if consulta "¿secretos.env tiene TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID? (sin mostrarlos)" secretos_emparejados; then
    cmd systemctl restart trovefy-ejecutor
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
printf 'Para reparar la auditoría, para antes el servicio: sudo systemctl stop trovefy-ejecutor\n'
if ((SIMULAR == 0)); then
    systemctl --no-pager status trovefy-ejecutor || true
fi
