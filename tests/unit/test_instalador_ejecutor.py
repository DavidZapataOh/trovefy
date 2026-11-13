"""Unidad de systemd e instalador del ejecutor (plan 12, tarea 8).

El instalador solo se ejecuta aquí con ``--simular`` (salvo «sin root explica», que sale antes de hacer nada).
"""

import os
import pathlib
import re
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]
UNIDAD = RAIZ / "templates/systemd/trovefy-ejecutor.service"
INSTALADOR = RAIZ / "scripts/instalar-ejecutor.sh"
DOC = RAIZ / "docs/ejecutor-windows.md"

# Comandos externos que el instalador podría llamar: en --simular ninguno debe ejecutarse.
EXTERNOS = [
    "groupadd", "useradd", "usermod", "id", "getent", "install", "chmod", "chown", "chgrp", "mkdir",
    "systemctl", "sudo", "uv", "openssl", "setfacl", "getfacl", "apt-get", "stat", "cmp", "cp", "mv",
    "rm", "mktemp", "cat", "grep", "sed", "dirname", "readlink", "realpath", "python3", "touch", "ls",
    "find", "tee", "env", "awk", "cut", "head", "basename", "wsl.exe", "nano", "git", "sha256sum",
]


def _simular(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = {"PATH": os.environ["PATH"], "SUDO_USER": "david"} if env is None else env
    return subprocess.run(["bash", str(INSTALADOR), "--simular", *args], check=False, capture_output=True, text=True, env=e)


def test_unidad_endurecida():
    u = UNIDAD.read_text()
    for linea in [
        "After=network-online.target time-sync.target", "Wants=network-online.target",
        "Type=simple", "User=trovefy-exec", "Group=trovefy-exec", "SupplementaryGroups=trovefy",
        "Environment=TROVEFY_VAULT={vault}", "Environment=TROVEFY_SPOOL=/var/spool/trovefy",
        "ExecStart=/home/trovefy-exec/.local/bin/trovefy-ejecutor servir",
        "Restart=on-failure", "RestartSec=10", "UMask=0077",
        "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=read-only", "PrivateTmp=yes",
        "PrivateDevices=yes", "ProtectKernelTunables=yes", "ProtectKernelModules=yes",
        "ProtectControlGroups=yes", "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
        "RestrictNamespaces=yes", "LockPersonality=yes", "SystemCallArchitectures=native",
        "WantedBy=multi-user.target", "RestartPreventExitStatus=2 4",
    ]:
        assert linea in u.splitlines(), linea
    assert "CapabilityBoundingSet=" in u.splitlines()
    assert "UMask=0027" not in u
    rw = next(ln for ln in u.splitlines() if ln.startswith("ReadWritePaths="))
    assert rw.split("=", 1)[1].split() == [
        "/var/spool/trovefy", "/home/trovefy-exec/.local/share/trovefy-ejecutor",
        "/home/trovefy-exec/.config/trovefy-ejecutor", "{vault}/propuestas", "{vault}/ledger/auditoria",
        "{vault}/raw/telegram",
    ]
    assert "{vault}/wiki" not in u
    assert "226/NAMESPACE" in u and u.index("PrivateDevices") < u.index("RestrictNamespaces")


def test_instalador_simulado_lista_los_pasos():
    r = _simular("--vault", "/tmp/v")
    assert r.returncode == 0, r.stderr
    marcas = [f"[{n}/13]" for n in range(1, 14)]
    pos = [r.stdout.index(m) for m in marcas]
    assert pos == sorted(pos)
    for cmd in [
        "groupadd trovefy", "useradd --system", "/usr/sbin/nologin",
        "usermod -aG trovefy david", "usermod -aG trovefy trovefy-exec",
        "chmod 0750 /var/spool/trovefy", "chmod 2770 /var/spool/trovefy/entrada",
        "chmod 2750 /var/spool/trovefy/procesadas", "chmod 2750 /var/spool/trovefy/estado",
        "/usr/local/bin/uv", "uv build --wheel",
        "uv export --frozen --no-dev --no-hashes --no-emit-project",
        "uv tool install --force --python 3.12 --constraints",
        'zoneinfo.ZoneInfo("America/Bogota")', "apt-get install -y tzdata",
        "openssl rand -hex 32", "trovefy_ejecutor.instalacion cuenta",
        "/tmp/v/config/arranque.yaml",
        "trovefy_ejecutor.instalacion limites",
        "setfacl -m u:trovefy-exec:--x /home/david", "setfacl -m u:trovefy-exec:rwx",
        "d:u:david:rwx", "/tmp/v/raw/telegram/motivos",
        "/etc/systemd/system/trovefy-ejecutor.service", "systemctl daemon-reload",
        "systemctl enable trovefy-ejecutor", "trovefy-ejecutor emparejar",
    ]:
        assert cmd in r.stdout, cmd
    assert "rm -rf" not in r.stdout
    # --simular nunca muestra una clave HMAC generada (64 hex), solo el comando.
    assert not re.search(r"\b[0-9a-f]{64}\b", r.stdout)
    # Sin TELEGRAM_* (las consultas se dan por negativas) no se arranca el servicio.
    assert "systemctl restart trovefy-ejecutor" not in r.stdout


def test_simular_no_ejecuta_nada(tmp_path):
    falsos = tmp_path / "bin"
    falsos.mkdir()
    registro = tmp_path / "llamadas.log"
    for nombre in EXTERNOS:
        f = falsos / nombre
        f.write_text(f'#!/bin/sh\necho "{nombre} $*" >> "{registro}"\nexit 0\n')
        f.chmod(0o755)
    bash = shutil.which("bash")
    r = subprocess.run([bash, str(INSTALADOR), "--simular", "--vault", "/tmp/v"], check=False, capture_output=True,
                       text=True, env={"PATH": str(falsos), "SUDO_USER": "david"})
    assert r.returncode == 0, r.stderr
    assert "[13/13]" in r.stdout
    assert not registro.exists(), registro.read_text()


def test_simular_vault_por_defecto():
    r = _simular()
    assert r.returncode == 0, r.stderr
    assert "/home/david/trovefy-cerebro/config/arranque.yaml" in r.stdout


@pytest.mark.parametrize("vault", ["relativa/v", "/tmp/a\"b", "/tmp/a\\b", "/tmp/a%b", "/tmp/a\nb",
                                   "/tmp/a b", "/tmp/../etc", ""])
def test_vault_invalida_se_rechaza_sin_hacer_nada(vault):
    r = _simular("--vault", vault)
    assert r.returncode != 0
    assert "--vault" in r.stderr
    assert "+ " not in r.stdout and "[1/13]" not in r.stdout


def test_opcion_desconocida():
    r = _simular("--borrar")
    assert r.returncode != 0 and "--borrar" in r.stderr


_CIFRAS = re.compile(r"\d{15,17}")
_ACT = re.compile(r"act_\d+")


def _sin_cuenta_real(texto: str) -> None:
    for m in _ACT.findall(texto):
        assert m == "act_0000000000000000", "cuenta no ficticia"
    for m in _CIFRAS.findall(texto):
        assert set(m) == {"0"}, "número de cuenta no ficticio"


def test_repo_sin_cuenta_real():
    for f in [INSTALADOR, UNIDAD, DOC]:
        _sin_cuenta_real(f.read_text())
    _sin_cuenta_real(_simular("--vault", "/tmp/v").stdout)


@pytest.mark.skipif(os.geteuid() == 0, reason="el test comprueba el caso sin root")
def test_instalador_sin_root_explica():
    r = subprocess.run(["bash", str(INSTALADOR)], check=False, capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"]})
    assert r.returncode != 0
    assert "sudo bash scripts/instalar-ejecutor.sh" in r.stderr
    r = subprocess.run(["bash", str(INSTALADOR), "--vault", "/tmp/v"], check=False, capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "SUDO_USER": "david"})
    assert r.returncode != 0 and "sudo bash scripts/instalar-ejecutor.sh" in r.stderr
    assert "[1/13]" not in r.stdout


def test_instalador_sintaxis():
    assert subprocess.run(["bash", "-n", str(INSTALADOR)], check=False).returncode == 0
    texto = INSTALADOR.read_text()
    assert texto.startswith("#!/usr/bin/env bash\n") and "set -euo pipefail" in texto
    assert "rm -rf" not in texto
    assert "PY=/home/trovefy-exec/.local/share/uv/tools/trovefy/bin/python" in texto


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck no instalado")
def test_instalador_shellcheck():
    r = subprocess.run(["shellcheck", "-S", "style", str(INSTALADOR)], check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_doc_windows():
    d = DOC.read_text()
    for s in ["[wsl2]", "vmIdleTimeout=-1",
              'schtasks /Create /SC ONLOGON /TN TrovefyWSL /TR "wsl.exe -d Ubuntu --exec /bin/true"']:
        assert s in d
    assert "no se ejecuta nada" in d
    assert "systemctl edit trovefy-ejecutor" in d


# -- separación de privilegios (fix round 1): root solo actúa en /etc y /var/spool --------------------------
_RUTAS_AJENAS = ("/home/david", "/home/trovefy-exec", "/tmp/v")


def _lineas_root(salida: str) -> list[str]:
    """Tramos de las líneas «+ » que ejecutaría root (los que no empiezan por «sudo -u»)."""
    tramos = []
    for ln in salida.splitlines():
        if not ln.startswith("+ "):
            continue
        for tramo in ln[2:].split(" | "):
            if not tramo.startswith("sudo -u "):
                tramos.append(tramo)
    return tramos


def test_root_no_toca_rutas_de_otros_usuarios():
    r = _simular("--vault", "/tmp/v")
    assert r.returncode == 0, r.stderr
    for tramo in _lineas_root(r.stdout):
        if tramo.startswith("useradd ") or "/etc/systemd/system/" in tramo:
            continue  # crear el usuario es de root; la unidad la escribe root en /etc
        assert not any(x in tramo for x in _RUTAS_AJENAS), tramo


def test_simular_muestra_las_formas_sudo_u():
    r = _simular("--vault", "/tmp/v")
    out = r.stdout
    for s in [
        "+ sudo -u david -H git -C ", "describe --dirty --always",
        "+ sudo -u david -H setfacl -m u:trovefy-exec:--x /home/david",
        "+ sudo -u david -H setfacl -m u:trovefy-exec:rwx,d:u:trovefy-exec:rwx,d:u:david:rwx /tmp/v/propuestas",
        "? sudo -u david -H getfacl",
        "+ sudo -u david -H cat -- /home/david/.local/bin/uv",
        "mktemp /usr/local/bin/",
        "+ sudo -u trovefy-exec -H install -d -m 0700 /home/trovefy-exec/.config/trovefy-ejecutor",
        "+ sudo -u trovefy-exec -H install -m 0600 /dev/null /home/trovefy-exec/.config/trovefy-ejecutor/secretos.env",
        "| sudo -u trovefy-exec -H tee -a -- /home/trovefy-exec/.config/trovefy-ejecutor/secretos.env",
        "+ sudo -u david -H cat -- /tmp/v/config/arranque.yaml | sudo -u trovefy-exec -H tee -- ",
        "| sudo -u trovefy-exec -H tee -- /home/trovefy-exec/.config/trovefy-ejecutor/limites.yaml.nuevo",
        "+ sudo -u trovefy-exec -H mv -- /home/trovefy-exec/.config/trovefy-ejecutor/limites.yaml.nuevo",
    ]:
        assert s in out, s
    assert out.index("describe --dirty --always") < out.index("[1/13]")
    assert "+ setfacl" not in out and "+ install -m 0600 -o" not in out and "+ chown" not in out
