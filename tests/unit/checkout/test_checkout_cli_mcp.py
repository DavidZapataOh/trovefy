"""`trovefy checkout plan | aprobar | releer` (plan 19, Tarea 11, versión MCP; M6 de la revisión T6–10).

Claude llama al MCP en la sesión; la CLI solo produce el plan de cada etapa, registra la aprobación con las palabras
literales del usuario y lee lo que Claude guardó de las respuestas. Aquí «Claude» es el test y el MCP es
`mcp_falso.MCPFalso`, que hace pasar cada llamada por la guarda real del hook. Ningún test llama al MCP real.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy import cli
from trovefy.checkout.mensajes import registrar_mensaje
from trovefy.checkout.receta import GUION_UPSELL, marcadores
from trovefy.tienda import mcp as mcp_mod
from trovefy.vault import frontmatter

from .mcp_falso import FRONT, STORE, URL_FIRMADA, GuardaDeniega, MCPFalso, fixture

RAIZ = Path(__file__).resolve().parents[3]
AHORA = datetime(2026, 11, 17, 12, 0, 0, tzinfo=ZoneInfo("America/Bogota"))
TOKEN_FALSO = "EAA" + "Bq7" * 10

EMAIL_BG = """---
asunto: Вашето ръководство е готово
---
Здравейте,

Благодарим ви за поръчката. Ръководството „Спокойно тяло“ е прикачено към този имейл и можете да го
изтеглите веднага. Ако имате въпроси, просто отговорете на това писмо и ще ви помогнем.

Поздрави,
Екипът на Somatix
"""


def pagina_u1(botones: bool = True) -> str:
    partes = [f"<!-- guion: {c} -->\n## {c}\n\nТекст за {c}.\n" for c, _ in GUION_UPSELL]
    if botones:
        partes.append("[[aceptar: Да, искам го]]\n\n[[rechazar: Не, благодаря]]\n")
    return "\n".join(partes)


class Reloj:
    def __init__(self) -> None:
        self.t = AHORA

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=30)
        return self.t


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    checkout_cli = importlib.import_module("trovefy.checkout_cli")
    v = vault_embudo(tmp_path)
    prod = v / "productos" / P
    (prod / "entregable").mkdir(parents=True, exist_ok=True)
    (prod / "entregable" / "prueba-bg-v1.pdf").write_bytes(b"%PDF-1.7 ficticio")
    (prod / "entregable" / "upsells" / "u1").mkdir(parents=True, exist_ok=True)
    (prod / "entregable" / "upsells" / "u1" / "u1-bg-v1.pdf").write_bytes(b"%PDF-1.7 ficticio")
    (prod / "entregable" / "medios").mkdir(parents=True, exist_ok=True)
    (prod / "entregable" / "medios" / "mockup.png").write_bytes(b"\x89PNG ficticio")
    pais = prod / "checkout" / PAIS
    (pais / "upsells").mkdir(parents=True, exist_ok=True)
    (pais / "upsells" / "u1.md").write_text(pagina_u1(), encoding="utf-8")
    (pais / "emails").mkdir(parents=True, exist_ok=True)
    (pais / "emails" / "entrega.md").write_text(EMAIL_BG, encoding="utf-8")
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    reloj = Reloj()
    monkeypatch.setattr(checkout_cli, "_ahora", reloj)
    monkeypatch.syspath_prepend(str(RAIZ / "hooks"))
    # La guarda carga el catálogo en cada llamada (en la sesión, cada llamada es un proceso): aquí, una vez.
    monkeypatch.setattr(mcp_mod, "cargar_catalogo", _catalogo_una_vez)
    guarda = importlib.import_module("impultienda_guard")
    return v, reloj, MCPFalso(guarda)


_CATALOGOS: dict[str, object] = {}
_CARGAR = mcp_mod.cargar_catalogo


def _catalogo_una_vez(ruta: Path = mcp_mod.RAIZ / "config/impultienda_tools.json"):
    clave = str(ruta)
    if clave not in _CATALOGOS:
        _CATALOGOS[clave] = _CARGAR(ruta)
    return _CATALOGOS[clave]


def _args(accion: str, *extra: str) -> list[str]:
    return ["checkout", accion, "--producto", P, "--pais", PAIS, *extra]


def _carpeta(v: Path) -> Path:
    return v / "productos" / P / "checkout" / PAIS


def _cache(tmp_path: Path) -> Path:
    return tmp_path / ".cache" / "trovefy" / "checkout" / P / PAIS


class Claude:
    """Lo que hace Claude en la sesión: llama al MCP, guarda las respuestas y ejecuta la CLI."""

    def __init__(self, v: Path, reloj: Reloj, mcp: MCPFalso, home: Path) -> None:
        self.v, self.reloj, self.mcp, self.home = v, reloj, mcp, home
        self.llamadas: list[dict] = []
        self.n = 0

    def llamar(self, herramienta: str, argumentos: dict) -> dict:
        r = self.mcp.llamar(herramienta, argumentos)
        self.llamadas.append({"herramienta": herramienta, "argumentos": argumentos, "respuesta": r})
        return r

    def lecturas_base(self) -> None:
        self.llamar("impultienda_listar_tiendas", {})
        for h in ("impultienda_listar_productos", "impultienda_ver_markets", "impultienda_ver_postcompra"):
            self.llamar(h, {"store_id": STORE})

    def guardar(self) -> Path:
        self.n += 1
        destino = _cache(self.home) / f"respuestas-{self.n}.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps({"llamadas": self.llamadas}, ensure_ascii=False), encoding="utf-8")
        self.llamadas = []
        return destino

    def releer(self) -> int:
        return cli.main(_args("releer", "--respuesta", str(self.guardar())))

    def plan(self) -> dict | None:
        assert cli.main(_args("plan")) in (0, 1)
        ruta = _carpeta(self.v) / "PLAN-MCP.json"
        return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None

    def aprobar(self, cita: str = "sí, dale") -> int:
        registrar_mensaje(cita, ahora=self.reloj().timestamp())
        return cli.main(_args("aprobar", "--cita", cita))

    def aplicar(self, plan: dict) -> None:
        for det, op in zip(plan["detalle"], plan["operaciones"], strict=True):
            h, a = op["herramienta"], op["argumentos"]
            if det["solo_vista_previa"] or not det["dos_pasos"]:
                r = self.llamar(h, a)
            else:
                vista = self.mcp.llamar(h, a)
                r = self.llamar(h, {**a, "confirmar": True, "token": vista["token"]})
            if h == "impultienda_cargar_entregable" and a["modo"] == "subir":
                self.mcp.subir_pdf(r["url_subida"])
            if h == "impultienda_link_subida_recursos":
                self.mcp.usuario_sube_recurso("mockup.webp")
        for lectura in plan["lecturas_despues"]:
            self.llamar(lectura["herramienta"], lectura["argumentos"])


def _todo(entorno, tmp_path) -> tuple[Claude, list[dict]]:
    v, reloj, mcp = entorno
    claude = Claude(v, reloj, mcp, tmp_path)
    claude.lecturas_base()
    assert claude.releer() == 0
    planes = []
    for _ in range(8):
        plan = claude.plan()
        if plan is None:
            break
        planes.append(plan)
        assert claude.aprobar() == 0
        claude.aplicar(plan)
        claude.releer()
    return claude, planes


# --- la secuencia completa, con el MCP falso --------------------------------------------------------------------


def test_secuencia_completa_por_etapas(entorno, tmp_path, capsys):
    v, _, mcp = entorno
    claude, planes = _todo(entorno, tmp_path)
    assert claude.plan() is None
    assert 3 <= len(planes) <= 6
    # Cada etapa solo lleva argumentos resueltos (M6): ningún marcador <…> llega al plan aprobado.
    for plan in planes:
        for op in plan["operaciones"]:
            assert not marcadores(op["argumentos"]), op
    # La tienda queda como pide la receta.
    t = mcp.tiendas[0]
    assert t["nombre"] == "Somatix" and t["idioma"] == "bg"
    assert mcp.markets_activo
    zz = next(m for m in mcp.mercados if not m["es_default"])
    assert zz["moneda"] == "EUR" and [p["codigo"] for p in zz["paises"]] == [PAIS]
    assert mcp.precios_fijos[(zz["id"], None)] == 13.9
    assert mcp.productos[0]["titulo"] == "Спокойно тяло"
    assert FRONT in mcp.entregables
    u1 = next(p for p in mcp.productos if p["tipo"] == "upsell")
    assert u1["solo_post_compra"] and mcp.precios_fijos[(zz["id"], u1["id"])] == 19.9 and u1["id"] in mcp.entregables
    assert mcp.diseno["minutos_timer_bump"] == 0
    assert mcp.checkout["pedir_telefono"] is True and mcp.checkout["pedir_apellido"] is False
    assert all(b["tipo"] not in ("countdown", "stock") for b in mcp.bloques["abajo"])
    assert mcp.bloques["arriba"][0]["url"].endswith("/mockup.webp")
    oferta = mcp.oferta_de(u1["id"])
    assert "data-pp-accept" in mcp.html[oferta]["html"] and mcp.html[oferta]["activo"] is True
    # Nada escrito dos veces y ningún producto duplicado.
    assert len([e for e in mcp.escrituras if e[0] == "impultienda_crear_producto"]) == 1
    # CHECKOUT.md con lo aplicado, la relectura y lo que va a mano.
    meta, cuerpo = frontmatter.leer(_carpeta(v) / "CHECKOUT.md")
    assert meta["estado"] in ("a_medias", "completo")
    assert meta["catalogo_huella"] and meta["plan_huella"]
    assert "| producto.front.precio | 13.90 |" in cuerpo
    assert "## A mano" in cuerpo and "emails.entrega" in cuerpo and "checkout.plantilla" in cuerpo
    assert "no disponible" in cuerpo
    prod, _ = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    co = prod["paises"][PAIS]["checkout"]
    assert co["plataforma"] == "impultienda" and co["precio"] == {"importe": "13.90", "moneda": "EUR"}
    assert co["url"].startswith("https://prueba.impultienda.example")


def test_cada_escritura_pasa_la_guarda_solo_con_su_aprobacion(entorno, tmp_path):
    v, reloj, mcp = entorno
    claude = Claude(v, reloj, mcp, tmp_path)
    claude.lecturas_base()
    assert claude.releer() == 0
    plan = claude.plan()
    op = plan["operaciones"][0]
    # Sin aprobación, la guarda deniega la primera escritura del plan.
    with pytest.raises(GuardaDeniega):
        mcp.llamar(op["herramienta"], op["argumentos"])
    assert claude.aprobar() == 0
    claude.aplicar(plan)
    assert claude.releer() in (0, 1)
    # Tras releer, la aprobación de esa etapa se retira: repetir la llamada ya no pasa.
    assert not (_carpeta(v) / "APROBACION.md").exists()
    with pytest.raises(GuardaDeniega):
        mcp.llamar(op["herramienta"], op["argumentos"])
    # Y queda en el historial de la etapa, con la cita literal.
    historial = _carpeta(v) / "mcp" / "etapa-1" / "APROBACION.md"
    meta, _ = frontmatter.leer(historial)
    assert meta["cita"] == "sí, dale" and meta["plan_huella"] == plan["huella"] and meta["etapa"] == 1


def test_releer_redacta_las_urls_firmadas(entorno, tmp_path):
    _todo(entorno, tmp_path)
    for archivo in _cache(tmp_path).glob("*.json"):
        assert "X-Amz-Signature" not in archivo.read_text(encoding="utf-8")
    v = entorno[0]
    for archivo in _carpeta(v).rglob("*"):
        if archivo.is_file():
            assert URL_FIRMADA not in archivo.read_text(encoding="utf-8", errors="replace")


# --- plan ---------------------------------------------------------------------------------------------------------


def test_plan_sin_lecturas_no_medido(entorno, capsys):
    assert cli.main(_args("plan")) == 1
    out = capsys.readouterr().out
    assert "no medido: faltan las lecturas del MCP" in out and "impultienda_listar_tiendas" in out
    assert not (_carpeta(entorno[0]) / "PLAN-MCP.json").exists()


def test_cli_estado_incorrecto(tmp_path, monkeypatch, capsys):
    v = vault_embudo(tmp_path, estado="producido")
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    assert cli.main(_args("plan")) == 2
    assert "con_landing" in capsys.readouterr().err


def test_plan_escribe_resumen_en_seco(entorno, tmp_path, capsys):
    v, reloj, mcp = entorno
    claude = Claude(v, reloj, mcp, tmp_path)
    claude.lecturas_base()
    claude.releer()
    capsys.readouterr()
    plan = claude.plan()
    out = capsys.readouterr().out
    resumen = (_carpeta(v) / "PLAN-MCP.md").read_text(encoding="utf-8")
    assert "Etapa 1" in resumen and resumen.strip() in out
    assert "impultienda_" not in resumen and STORE not in resumen
    assert "Poner el nombre de la tienda: «Somatix»" in resumen
    assert plan["etapa"] == 1 and plan["huella"]
    from trovefy.tienda.mcp import huella_plan
    assert huella_plan(plan["operaciones"]) == plan["huella"]


def test_plan_con_etapa_aprobada_sin_releer_se_niega(entorno, tmp_path, capsys):
    v, reloj, mcp = entorno
    claude = Claude(v, reloj, mcp, tmp_path)
    claude.lecturas_base()
    claude.releer()
    claude.plan()
    assert claude.aprobar() == 0
    capsys.readouterr()
    assert cli.main(_args("plan")) == 2
    assert "releer" in capsys.readouterr().err


# --- aprobar ------------------------------------------------------------------------------------------------------


def _plan_listo(entorno, tmp_path) -> Claude:
    v, reloj, mcp = entorno
    claude = Claude(v, reloj, mcp, tmp_path)
    claude.lecturas_base()
    claude.releer()
    claude.plan()
    return claude


def test_cita_sin_afirmacion_rechazada(entorno, tmp_path, capsys):
    claude = _plan_listo(entorno, tmp_path)
    for cita in ("", "   ", "luego lo vemos", "sí, pero todavía no", "no, espera"):
        registrar_mensaje(cita, ahora=claude.reloj().timestamp())
        assert cli.main(_args("aprobar", "--cita", cita)) == 2, cita
    assert not (_carpeta(entorno[0]) / "APROBACION.md").exists()


def test_cita_que_el_usuario_no_escribio_se_rechaza(entorno, tmp_path, capsys):
    _plan_listo(entorno, tmp_path)
    assert cli.main(_args("aprobar", "--cita", "sí, dale")) == 2
    assert "escríbelo tú" in capsys.readouterr().err.casefold()
    assert not (_carpeta(entorno[0]) / "APROBACION.md").exists()


def test_cita_anterior_al_plan_no_vale(entorno, tmp_path, capsys):
    registrar_mensaje("sí, dale", ahora=(AHORA - timedelta(hours=1)).timestamp())
    _plan_listo(entorno, tmp_path)
    assert cli.main(_args("aprobar", "--cita", "sí, dale")) == 2


def test_cita_con_secreto_rechazada(entorno, tmp_path):
    claude = _plan_listo(entorno, tmp_path)
    cita = f"sí, dale {TOKEN_FALSO}"
    registrar_mensaje(cita, ahora=claude.reloj().timestamp())
    assert cli.main(_args("aprobar", "--cita", cita)) == 2
    assert not (_carpeta(entorno[0]) / "APROBACION.md").exists()


def test_cita_en_la_terminal_del_usuario(entorno, tmp_path, monkeypatch):
    _plan_listo(entorno, tmp_path)
    from trovefy.checkout import mcp_cli
    monkeypatch.setattr(mcp_cli, "hay_terminal", lambda: True)
    assert cli.main(_args("aprobar", "--cita", "Sí, adelante")) == 0
    texto = (_carpeta(entorno[0]) / "APROBACION.md").read_text(encoding="utf-8")
    assert 'cita: "Sí, adelante"' in texto


# --- releer -------------------------------------------------------------------------------------------------------


def test_sin_aprobacion_no_se_acepta_escritura(entorno, tmp_path, capsys):
    claude = _plan_listo(entorno, tmp_path)
    claude.llamadas.append({"herramienta": "impultienda_fijar_precio",
                            "argumentos": {"store_id": STORE, "precio": 13.9},
                            "respuesta": fixture("fijar_precio-ok.json")})
    assert claude.releer() == 2
    assert "esa escritura no está en el plan aprobado" in capsys.readouterr().err


def test_plan_cambiado_invalida_aprobacion(entorno, tmp_path, capsys):
    v, _, mcp = entorno
    claude = _plan_listo(entorno, tmp_path)
    assert claude.aprobar() == 0
    # Se cambia el precio en ESCALERA.md y se rehace el plan a mano: la aprobación ya no casa.
    ruta = _carpeta(v) / "PLAN-MCP.json"
    plan = json.loads(ruta.read_text(encoding="utf-8"))
    plan["operaciones"][0]["argumentos"]["nombre"] = "Otra marca"
    from trovefy.tienda.mcp import huella_plan
    plan["huella"] = huella_plan(plan["operaciones"])
    ruta.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    op = plan["operaciones"][0]
    with pytest.raises(GuardaDeniega):
        mcp.llamar(op["herramienta"], op["argumentos"])
    claude.llamadas.append({"herramienta": op["herramienta"], "argumentos": op["argumentos"],
                            "respuesta": {"aplicado": ["nombre"]}})
    assert claude.releer() == 2
    assert "esa escritura no está en el plan aprobado" in capsys.readouterr().err


def test_releer_fuera_de_la_cache_se_niega(entorno, tmp_path, capsys):
    otro = tmp_path / "respuestas.json"
    otro.write_text(json.dumps({"llamadas": []}), encoding="utf-8")
    assert cli.main(_args("releer", "--respuesta", str(otro))) == 2
    assert ".cache/trovefy/checkout" in capsys.readouterr().err


def test_releer_herramienta_prohibida_se_niega(entorno, tmp_path, capsys):
    claude = Claude(*entorno, tmp_path)
    claude.llamadas.append({"herramienta": "impultienda_configurar_tracking", "argumentos": {}, "respuesta": {}})
    assert claude.releer() == 2


def test_respuesta_con_token_no_se_guarda(entorno, tmp_path, capsys):
    v, reloj, mcp = entorno
    claude = Claude(v, reloj, mcp, tmp_path)
    claude.lecturas_base()
    tiendas = claude.llamadas[0]["respuesta"]
    tiendas["tiendas"][0]["nombre"] = TOKEN_FALSO
    assert claude.releer() == 1
    out = capsys.readouterr().out
    assert "secreto" in out
    for archivo in list(_cache(tmp_path).glob("*.json")) + list(_carpeta(v).rglob("*.json")):
        assert TOKEN_FALSO not in archivo.read_text(encoding="utf-8")


def test_pendiente_aprobar_en_panel(entorno, tmp_path, capsys):
    v = entorno[0]
    claude = _plan_listo(entorno, tmp_path)
    plan = json.loads((_carpeta(v) / "PLAN-MCP.json").read_text(encoding="utf-8"))
    assert claude.aprobar() == 0
    op = plan["operaciones"][0]
    assert op["herramienta"] == "impultienda_configurar_tienda"
    claude.llamadas.append({"herramienta": op["herramienta"], "argumentos": op["argumentos"],
                            "respuesta": fixture("pendiente-aprobar.json")})
    claude.lecturas_base()
    assert claude.releer() == 1
    out = capsys.readouterr().out
    assert "https://impultienda.ar/panel/cambios/aprobar" in out
    meta, cuerpo = frontmatter.leer(_carpeta(v) / "CHECKOUT.md")
    assert meta["estado"] == "a_medias"
    assert "pendiente_aprobar_panel" in cuerpo and "https://impultienda.ar/panel/cambios/aprobar" in cuerpo
    # Lo que espera la aprobación del panel no se vuelve a escribir en la etapa siguiente.
    siguiente = claude.plan()
    assert all(o["herramienta"] != "impultienda_configurar_tienda" for o in siguiente["operaciones"])


def test_distinto_dos_veces_pasa_a_mano(entorno, tmp_path, capsys):
    v, reloj, mcp = entorno
    mcp.nombre_tienda_falla = True  # el panel no guarda el nombre
    claude = Claude(v, reloj, mcp, tmp_path)
    claude.lecturas_base()
    claude.releer()
    vistas = 0
    for _ in range(4):
        plan = claude.plan()
        if plan is None or not any(o["herramienta"] == "impultienda_configurar_tienda"
                                   for o in plan["operaciones"]):
            break
        vistas += 1
        assert claude.aprobar() == 0
        claude.aplicar(plan)
        claude.releer()
    assert vistas == 2  # se aplica y se corrige una sola vez
    estado = json.loads((_carpeta(v) / "MCP-ESTADO.json").read_text(encoding="utf-8"))
    assert any("tienda.nombre" in m["ajustes"] for m in estado["manuales"].values())
    meta, cuerpo = frontmatter.leer(_carpeta(v) / "CHECKOUT.md")
    assert meta["estado"] == "parado"
    assert "tienda.nombre" in cuerpo.split("## A mano")[1]


def test_reaplicar_no_reescribe_lo_igual(entorno, tmp_path):
    claude, _ = _todo(entorno, tmp_path)
    escrituras = len(claude.mcp.escrituras)
    # Lecturas nuevas de una tienda ya montada: el plan no tiene nada que escribir.
    claude.lecturas_base()
    claude.releer()
    assert claude.plan() is None
    assert len(claude.mcp.escrituras) == escrituras


def test_checkout_md_y_producto(entorno, tmp_path):
    _todo(entorno, tmp_path)
    v = entorno[0]
    meta, cuerpo = frontmatter.leer(_carpeta(v) / "CHECKOUT.md")
    assert set(meta) >= {"estado", "fecha", "plan_huella", "catalogo_huella", "tienda_plan"}
    assert "| ajuste | pedido | releído | fuente | evidencia |" in cuerpo
    assert "| mcp |" in cuerpo
    prod, _ = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    co = prod["paises"][PAIS]["checkout"]
    assert set(co) == {"estado", "fecha", "plataforma", "url", "precio"}
    log = (v / "log.md").read_text(encoding="utf-8")
    assert "checkout" in log


def test_pagina_sin_botones_va_a_mano(entorno, tmp_path):
    v = entorno[0]
    (_carpeta(v) / "upsells" / "u1.md").write_text(pagina_u1(botones=False), encoding="utf-8")
    _, planes = _todo(entorno, tmp_path)
    assert all(o["herramienta"] != "impultienda_guardar_html_postcompra" for p in planes for o in p["operaciones"])
    _, cuerpo = frontmatter.leer(_carpeta(v) / "CHECKOUT.md")
    assert "postcompra.u1.pagina" in cuerpo.split("## A mano")[1]
    assert "[[aceptar:" in cuerpo


def test_estado_sin_ids_de_mas(entorno, tmp_path):
    _todo(entorno, tmp_path)
    v = entorno[0]
    estado = yaml.safe_load((_carpeta(v) / "MCP-ESTADO.json").read_text(encoding="utf-8"))
    assert estado["valores"]["<store_id>"] == STORE
    assert "respuesta" not in json.dumps(estado)  # al vault solo pasan valores normalizados


def test_checkout_md_integra_la_comprobacion_desde_fuera(entorno, tmp_path):
    """Lo que `trovefy checkout comprobar` (Tarea 12) dejó en COMPROBACION.md entra en CHECKOUT.md: lo visto mal desde
    fuera queda a medias aunque el MCP lo relea bien; lo de a mano con captura se cierra; escasez → parado."""
    from trovefy.checkout.fuera import EstadoFuera, escribir_comprobacion
    from trovefy.embudo.contexto import cargar_contexto

    v = entorno[0]
    _todo(entorno, tmp_path)
    ctx = cargar_contexto(v, P, PAIS)
    estados = [EstadoFuera("producto.front.precio", "falla", "13,90 EUR", "0,00 EUR", "el checkout muestra 0",
                           "fuera", "https://prueba.impultienda.example/checkout")]
    manuales = [EstadoFuera("checkout.plantilla", "captura", "Bambú", "Bambú", "hecho a mano, con captura",
                            "captura", "checkout/ZZ/evidencia/checkout-1.png"),
                EstadoFuera("checkout.clarity", "no_medido", "fuera del checkout", None, "no medido: falta la evidencia")]
    escribir_comprobacion(v, ctx, estados, manuales, AHORA)
    assert cli.main(_args("plan")) == 0  # no queda nada: reescribe CHECKOUT.md con la comprobación
    meta, cuerpo = frontmatter.leer(_carpeta(v) / "CHECKOUT.md")
    medias, mano = cuerpo.split("## A medias")[1].split("## A mano")
    assert "producto.front.precio: visto desde fuera: falla" in medias
    assert "checkout.plantilla" not in mano.split("##")[0] and "checkout.clarity" in mano.split("##")[0]
    assert "| checkout.plantilla | Bambú | Bambú | captura |" in cuerpo
    assert meta["estado"] == "a_medias"
    escribir_comprobacion(v, ctx, [*estados, EstadoFuera("checkout.escasez", "parado", "sin escasez", "5 души",
                                                         "prueba social inventada (D-01)", "fuera")], manuales, AHORA)
    assert cli.main(_args("plan")) == 0
    meta, cuerpo = frontmatter.leer(_carpeta(v) / "CHECKOUT.md")
    assert meta["estado"] == "parado" and "checkout.escasez: visto desde fuera: parado" in cuerpo


def test_tienda_que_no_es_clasica_no_se_planifica(entorno, tmp_path, capsys):
    v, reloj, mcp = entorno
    mcp.tiendas[0]["tipo"] = "checkout"
    claude = Claude(v, reloj, mcp, tmp_path)
    claude.lecturas_base()
    claude.releer()
    capsys.readouterr()
    assert cli.main(_args("plan")) == 1
    assert "tienda clásica" in capsys.readouterr().out
    assert not (_carpeta(v) / "PLAN-MCP.json").exists()
