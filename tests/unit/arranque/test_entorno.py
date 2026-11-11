import json
import sys
import time

from trovefy.arranque.estado import ResultadoVerificacion, cargar
from trovefy.arranque.verificadores import REGISTRO, base
from trovefy.arranque.verificadores.entorno import comprobar_entorno
from trovefy.cli import main


def falso(respuestas):
    def correr(cmd, timeout=10):
        return respuestas.get(cmd[0], (0, "ok"))

    return correr


BIEN = {"node": (0, "v22.11.0"), "systemctl": (0, "running"), "ldconfig": (0, "libpango-1.0.so.0")}


def _casa_completa(tmp_path):
    (tmp_path / ".cache/ms-playwright/chromium-1200").mkdir(parents=True)
    obs = tmp_path / "Obsidian.exe"
    obs.write_text("")
    return obs


def test_todo_bien(tmp_path):
    obs = _casa_completa(tmp_path)
    elementos = comprobar_entorno(falso(BIEN), home=tmp_path, obsidian=[obs])
    assert all(e.ok for e in elementos), [e for e in elementos if not e.ok]
    assert [e.nombre for e in elementos] == [
        "uv", "python", "node", "git", "ffmpeg", "poppler", "weasyprint", "playwright", "systemd", "obsidian",
    ]


def test_comando_colgado_falla_por_tiempo(tmp_path):
    elementos = comprobar_entorno(falso({"ffmpeg": (None, "tiempo agotado")}), home=tmp_path, obsidian=[])
    ff = next(e for e in elementos if e.nombre == "ffmpeg")
    assert not ff.ok and "apt install -y ffmpeg" in ff.arreglo and "tiempo agotado" in ff.detalle


def test_systemd_apagado(tmp_path):
    elementos = comprobar_entorno(falso({"systemctl": (1, "offline")}), home=tmp_path, obsidian=[])
    s = next(e for e in elementos if e.nombre == "systemd")
    assert not s.ok and "systemd=true" in s.arreglo and "wsl --shutdown" in s.arreglo


def test_systemd_degradado_vale(tmp_path):
    elementos = comprobar_entorno(falso({"systemctl": (1, "degraded\n")}), home=tmp_path, obsidian=[])
    assert next(e for e in elementos if e.nombre == "systemd").ok


def test_node_viejo_y_poppler_ausente(tmp_path):
    r = {"node": (0, "v18.19.0"), "pdfinfo": (None, "no instalado")}
    elementos = {e.nombre: e for e in comprobar_entorno(falso(r), home=tmp_path, obsidian=[])}
    assert not elementos["node"].ok and "20" in elementos["node"].detalle
    assert not elementos["poppler"].ok and "poppler-utils" in elementos["poppler"].arreglo


def test_playwright_sin_navegador_no_usa_npx_suelto(tmp_path):
    elementos = {e.nombre: e for e in comprobar_entorno(falso(BIEN), home=tmp_path, obsidian=[])}
    pw = elementos["playwright"]
    assert not pw.ok and "cd ~/trovefy/trovefy && uv run playwright install chromium" in pw.arreglo and "@latest" not in pw.arreglo
    assert "npx" not in pw.arreglo
    assert not elementos["obsidian"].ok


def test_weasyprint_sin_pango(tmp_path):
    elementos = {e.nombre: e for e in comprobar_entorno(falso({"ldconfig": (0, "libc.so")}), home=tmp_path, obsidian=[])}
    assert not elementos["weasyprint"].ok and "libpango-1.0-0" in elementos["weasyprint"].arreglo


def test_correr_no_instalado_y_tiempo():
    assert base.correr(["comando-que-no-existe-xyz"]) == (None, "no instalado")
    t = time.monotonic()
    assert base.correr([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5) == (None, "tiempo agotado")
    assert time.monotonic() - t < 5
    assert base.correr([sys.executable, "-c", "print('hola')"]) == (0, "hola")


def test_guardar_evidencia(tmp_path):
    ruta = base.guardar_evidencia(tmp_path, "00", "entorno", {"a": "ñ"})
    assert ruta.startswith("config/evidencia/00-entorno-") and ruta.endswith(".json")
    texto = (tmp_path / ruta).read_text(encoding="utf-8")
    assert json.loads(texto) == {"a": "ñ"} and "ñ" in texto and '\n  "a"' in texto
    png = base.guardar_evidencia(tmp_path, "00", "captura", b"\x89PNG")
    assert png.endswith(".png") and (tmp_path / png).read_bytes() == b"\x89PNG"


def test_registro_tiene_el_00():
    assert "00" in REGISTRO


def test_cli_verificar(tmp_path, capsys, monkeypatch):
    v = str(tmp_path)
    assert main(["arranque", "verificar", "99", "--vault", v]) == 2
    assert main(["arranque", "verificar", "11", "--vault", v]) == 2  # sin verificador
    assert "no tiene verificador" in capsys.readouterr().err

    def fallo(vault):
        return ResultadoVerificacion(False, [], "falta ffmpeg", ["sudo apt install -y ffmpeg"], {}, ["✗ ffmpeg — tiempo agotado"])

    monkeypatch.setitem(REGISTRO, "00", fallo)
    assert main(["arranque", "verificar", "00", "--vault", v]) == 1
    out = capsys.readouterr().out
    assert "✗ ffmpeg — tiempo agotado" in out and "sudo apt install -y ffmpeg" in out
    assert "falló" in (tmp_path / "log.md").read_text(encoding="utf-8")

    monkeypatch.setitem(REGISTRO, "00", lambda vault: ResultadoVerificacion(None, [], "no medido: sin red", []))
    assert main(["arranque", "verificar", "00", "--vault", v]) == 3
    assert main(["arranque", "verificar", "00", "--vault", v]) == 3
    assert (tmp_path / "log.md").read_text(encoding="utf-8").count("verificar 00") == 3  # una por ejecución

    monkeypatch.setitem(REGISTRO, "00", lambda vault: ResultadoVerificacion(True, ["config/evidencia/x.json"], "entorno listo", []))
    assert main(["arranque", "verificar", "00", "--vault", v]) == 0
    assert next(p for p in cargar(tmp_path) if p.id == "00").estado == "verificado"


def test_verificador_00_guarda_evidencia(tmp_path, monkeypatch):
    from trovefy.arranque.verificadores import entorno

    monkeypatch.setattr(entorno, "comprobar_entorno", lambda *a, **k: [entorno.Elemento("git", True, "git 2", None)])
    r = REGISTRO["00"](tmp_path)
    assert r.ok is True and r.evidencia and (tmp_path / r.evidencia[0]).exists()
    assert r.lineas == ["✓ git — git 2"]
    monkeypatch.setattr(entorno, "comprobar_entorno", lambda *a, **k: [entorno.Elemento("git", False, "no instalado", "sudo apt install -y git")])
    r = REGISTRO["00"](tmp_path)
    assert r.ok is False and r.arreglos == ["git: sudo apt install -y git"]
