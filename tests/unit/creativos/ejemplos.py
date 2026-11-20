"""Vault ficticio para los tests de /creativos: p-0099-prueba-abc123 en ZZ (búlgaro, EUR)."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image
from trovefy.creativos.config import iniciar_config
from trovefy.producto.medios import escribir_medio, registrar_medio
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO

P = "p-0099-prueba-abc123"
PAIS = "ZZ"
LANDING = "https://prueba.example/"
AHORA = datetime(2026, 11, 20, 10, 0, tzinfo=ZONA_NEGOCIO)

MERCADOS = {"ZZ": {"idioma": "bg", "moneda": "EUR", "zona": "Europe/Sofia", "banda_eur": [9, 19],
                   "estado": "activo"}}
CORE = {
    "angulo": "спокойствие без хапчета", "promesa_h1": "Заспи за 10 минути без хапчета",
    "villano": "нощното превъртане на мисли", "mecanismo_nombre": "Ruta Calma 3R",
    "mecanismo_pasos": ["Разпознай", "Регулирай", "Почивай"], "avatar": "жени 30-55, които не спят",
    "bonos": [{"nombre": "Бонус 1", "objecion": "нямам време"}, {"nombre": "Бонус 2", "objecion": "не вярвам"}],
    "garantia_dias": 7, "formato": "PDF", "unidad_venta": "PDF от 40 страници",
}


def png(ancho: int = 800, alto: int = 1000, color=(120, 160, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (ancho, alto), color).save(buf, "PNG")
    return buf.getvalue()


def pdf(paginas: int = 3) -> bytes:
    buf = io.BytesIO()
    hojas = [Image.new("RGB", (595, 842), (250, 250, 250 - 20 * i)) for i in range(paginas)]
    hojas[0].save(buf, "PDF", save_all=True, append_images=hojas[1:])
    return buf.getvalue()


def _md(ruta: Path, meta: dict, cuerpo: str = "") -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    frontmatter.escribir(ruta, meta, cuerpo or f"# {ruta.stem}\n")


def crear_vault(vault: Path, *, estado: str = "listo", mezcla: str | None = None, landing: str | None = LANDING,
                config: bool = True) -> Path:
    vault = Path(vault)
    (vault / "config").mkdir(parents=True, exist_ok=True)
    (vault / "config" / "mercados.yaml").write_text(yaml.safe_dump(MERCADOS), encoding="utf-8")
    if config:
        iniciar_config(vault)
    carpeta = vault / "productos" / P
    bloque: dict = {"estado": estado}
    if landing:
        bloque["landing"] = {"url": landing}
    _md(carpeta / "PRODUCTO.md", {
        "tipo": "producto", "producto": P, "paises": {PAIS: bloque},
        "entregable": {"bg": {"principal": {"version": 1, "pdf": "entregable/versiones/v1.pdf", "paginas": 3}}}})
    _md(carpeta / "OFERTA.md", {"tipo": "oferta", "core": CORE,
                                "angulos_referencia": ["сън без хапчета", "5 минути вечер"]})
    _md(carpeta / "BRANDBOOK.md", {"nombre_local": "Соматика", "tono": "спокоен и близък",
                                   "paleta": {"fondo": "#F4EFE6", "texto": "#1E2A38", "acento": "#C8553D"},
                                   "tipografias": [{"uso": "titulos", "familia": "Ubuntu"},
                                                   {"uso": "texto", "familia": "Noto Sans"}]})
    _md(carpeta / "ESCALERA.md", {"paises": {PAIS: {"moneda": "EUR", "pasos": {"front": {"precio": "13.90"}}}}})
    (carpeta / "referencia").mkdir(parents=True, exist_ok=True)
    (carpeta / "referencia" / "mezcla.md").write_text(
        mezcla or "# Mezcla\n\n## Top (0 ganadores)\n\n- no medido: ningún formato leído (Meta 403)\n",
        encoding="utf-8")
    ent = carpeta / "entregable"
    (ent / "versiones").mkdir(parents=True, exist_ok=True)
    (ent / "versiones" / "v1.pdf").write_bytes(pdf())
    for id_, color in (("mockup", (200, 120, 90)), ("portada", (90, 120, 200)), ("ficha-01", (60, 160, 90))):
        sha = escribir_medio(ent / "medios" / f"{id_}.png", png(color=color), base=vault)
        registrar_medio(ent, id_, f"{id_}.png", sha, "propio", base=vault)
    return vault


GANCHOS = ["Не можеш да заспиш вечер", "Мислите не спират през нощта", "Пет минути преди сън",
           "Без хапчета и без стрес", "Умората идва, сънят не", "Тялото е будно в два"]
ANGULOS = [("сън без хапчета", "dormir sin pastillas"), ("пет минути вечер", "cinco minutos por la noche"),
           ("спри мислите", "parar los pensamientos"), ("метод в три стъпки", "método de tres pasos")]
FORMATOS_ELEGIDOS = ["tipografico", "broll_voz", "ugc", "mockup", "claymation",  # AD01-AD05 al test
                     "3d", "scroll_pdf", "zoom_lento", "ficha_del_producto", "scroll_pdf"]
VIDEOS = {"broll_voz", "ugc", "claymation", "3d", "scroll_pdf", "zoom_lento"}


def candidato(n: int, formato: str = "tipografico", angulo: int = 0) -> dict:
    gancho = GANCHOS[n % len(GANCHOS)]
    ang, ang_es = ANGULOS[angulo % len(ANGULOS)]
    d = {
        "id": f"b{n:02d}", "objetivo": "probar el ángulo", "audiencia": "mujeres 30-55 que duermen mal",
        "linea_ancla": "dormir sin pastillas", "tono": "cercano", "restricciones": "sin promesas de salud",
        "angulo": ang, "angulo_es": ang_es, "respaldo": "core.mecanismo_pasos[0]", "hook": "sujeto_dolor",
        "formato": formato, "gancho": gancho,
        "texto": (f"{gancho}? Методът Ruta Calma 3R ти помага да заспиш спокойно и без хапчета. "
                  "Само по пет минути вечер, с прости стъпки за тялото и ума. Вземи ръководството днес."),
        "titulo": "Заспи спокойно тази вечер", "descripcion": "Ръководство в PDF",
        "precio_dicho": "само 13,90 €",
    }
    if formato in VIDEOS:
        d["voz"] = f"{gancho}. Три прости стъпки за спокоен сън. Натисни бутона отдолу."
    return d


def brief_ok(formatos: list[str] | None = None) -> dict:
    formatos = formatos or FORMATOS_ELEGIDOS
    candidatos = [candidato(i + 1, formatos[i], angulo=i % 4) for i in range(10)]
    candidatos += [candidato(i + 1, "tipografico", angulo=i % 4) for i in range(10, 20)]
    elegidos = [{"ad": f"AD{i + 1:02d}", "brief": f"b{i + 1:02d}", "uso": "test" if i < 5 else "reserva",
                 "orden": i + 1, "angulo_corto": ANGULOS[i % 4][0]} for i in range(10)]
    return {"tanda": "t1", "grupo": "G1", "candidatos": candidatos, "elegidos": elegidos}


def guion_video(plantilla: str = "broll_voz", segmentos: int = 4, segundos: float = 5, **extra) -> dict:
    segs = []
    for i in range(1, segmentos + 1):
        s = {"texto_voz": f"Стъпка {i}: дишай бавно и пусни мислите.", "texto_pantalla": f"Стъпка {i}",
             "segundos": segundos}
        if plantilla in ("broll_voz", "claymation", "3d", "objeto_que_habla"):
            s["clip"] = {"prompt": f"plano {i} de una habitación en calma", "tipo": "texto"}
        elif plantilla == "ugc":
            s["clip"] = {"prompt": "mujer de 40 años habla a cámara", "tipo": "imagen", "ref": "e01"}
        elif plantilla == "zoom_lento":
            s["imagen"] = "mockup"
        elif plantilla == "scroll_pdf":
            s["paginas"] = [1, 2]
        segs.append(s)
    return {"plantilla": plantilla, "gancho": "Не можеш да заспиш вечер?",
            "clip_gancho": {"prompt": "primer plano de un reloj a las 3 de la mañana", "segundos": 3},
            "segmentos": segs, "cierre": {"texto": "Ruta Calma 3R · 13,90 €", "cta": "Натисни бутона отдолу",
                                          "segundos": 3},
            "voz": True, **extra}
