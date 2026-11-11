from datetime import date
from pathlib import Path

import pytest
import yaml
from trovify import rutinas
from trovify.rutinas import unidad_caza
from trovify.vault.andamio import crear_vault


def test_unidad_de_caza():
    servicio, timer = unidad_caza(Path("/home/u/trovify-cerebro"), "/usr/local/bin/claude")
    assert "OnCalendar=Mon..Sat *-*-* 06:30:00 America/Bogota" in timer
    assert "/trovify:cazar --rutina" in servicio and "WorkingDirectory=/home/u/trovify-cerebro" in servicio
    assert "dangerously" not in servicio


def test_unidad_lista_de_herramientas():
    servicio, timer = unidad_caza(Path("/home/u/trovify-cerebro"), "/usr/local/bin/claude")
    assert ('ExecStart=/usr/local/bin/claude -p "/trovify:cazar --rutina" '
            '--allowedTools "Read,Bash(trovify caza *),Bash(trovify cerebro *)"') in servicio
    assert "Environment=TROVIFY_VAULT=/home/u/trovify-cerebro" in servicio
    assert "Unit=trovify-caza.service" in timer and "WantedBy=timers.target" in timer


def test_instalar_escribe_en_home_y_activa_el_timer(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    llamadas = []
    rutas = rutinas.instalar_caza(tmp_path / "cerebro", "/usr/bin/claude", ejecutar=llamadas.append)
    unidad = tmp_path / ".config/systemd/user"
    assert rutas == [unidad / "trovify-caza.service", unidad / "trovify-caza.timer"]
    assert all(r.exists() for r in rutas)
    assert llamadas == [["systemctl", "--user", "daemon-reload"],
                        ["systemctl", "--user", "enable", "--now", "trovify-caza.timer"]]


def test_registro_de_la_rutina(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    rutinas.registrar_ejecucion(v, "caza", date(2026, 11, 10), "Resumen uno", ok=True)
    carpeta = v / "rutinas/log/2026-11-10"
    assert (carpeta / "ok").exists() and "Resumen uno" in (carpeta / "caza.md").read_text()
    rutinas.registrar_ejecucion(v, "caza", date(2026, 11, 10), "Resumen dos: parada", ok=False)
    texto = (carpeta / "caza.md").read_text()
    assert "Resumen uno" in texto and "Resumen dos" in texto
    assert not (carpeta / "ok").exists()  # la última ejecución se paró: /vigia lo ve


def test_plantilla_caza_yaml_se_copia():
    raiz = Path(__file__).resolve().parents[2]
    datos = yaml.safe_load((raiz / "templates/cerebro/config/caza.yaml").read_text())
    assert datos["perfil"] == "tomi" and datos["nichos"] == [] and isinstance(datos["palabras"], dict)
    assert set(datos["regiones"]) == {"eeuu_gb", "br", "latam_es", "europa"}
    assert {"US", "GB"} <= set(datos["regiones"]["eeuu_gb"]) and datos["regiones"]["br"] == ["BR"]


def test_crear_vault_copia_caza_yaml(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    assert (v / "config/caza.yaml").exists()


def test_cli_rutinas_instalar(tmp_path, monkeypatch, capsys):
    from trovify import cli
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TROVIFY_VAULT", str(tmp_path / "cerebro"))
    llamadas = []
    monkeypatch.setattr(rutinas, "_systemctl", llamadas.append)
    monkeypatch.setattr(rutinas.shutil, "which", lambda n: f"/opt/bin/{n}")
    assert cli.main(["rutinas", "instalar", "caza"]) == 0
    assert len(llamadas) == 2 and (tmp_path / ".config/systemd/user/trovify-caza.timer").exists()
    assert "06:30" in capsys.readouterr().out


def test_cli_rutinas_sin_claude(tmp_path, monkeypatch, capsys):
    from trovify import cli
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(rutinas.shutil, "which", lambda n: None)
    monkeypatch.setattr(rutinas, "_systemctl", lambda c: pytest.fail("no debe llamar a systemctl"))
    assert cli.main(["rutinas", "instalar", "caza"]) != 0
    assert "claude" in capsys.readouterr().err
