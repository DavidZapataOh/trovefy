"""Orquestador de `trovefy ver-anuncios ver`: listado, ranking, medios locales, /watch y salidas del vault.

Todo lo ajeno (medios, fotogramas, transcripciones, textos) vive en la caché local; al vault solo llegan
las salidas propias de :mod:`trovefy.referencia.salida`. Cualquier fallo de listado, descarga o /watch
se convierte en «no medido» dentro del informe.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from trovefy.caza.mcp import cargar_lote
from trovefy.referencia import cache
from trovefy.referencia.config import cargar_umbrales_referencia
from trovefy.referencia.descarga import DescargaRechazada, descargar_medio
from trovefy.referencia.fuente import Listado, listar
from trovefy.referencia.ranking import rankear
from trovefy.referencia.ranking import top as top_de
from trovefy.referencia.salida import (
    Referencia,
    cargar_referencia,
    construir_referencia,
    escribir_referencia,
)
from trovefy.referencia.watch import (
    Entorno,
    InformeWatch,
    comprobar_entorno,
    ejecutar_watch,
)
from trovefy.vault.escritura import ZONA_NEGOCIO
from trovefy.vault.frontmatter import leer as fm_leer

_PAGE = re.compile(r"^\d{1,25}$")


@dataclass(frozen=True)
class Objetivo:
    producto: str
    oferta_id: str
    page_id: str
    pais: str
    idioma: str | None


@dataclass
class Resultado:
    ref: Referencia
    trabajo: list[dict]
    parada: str | None
    tipo_parada: Literal["meta", "errores"] | None
    avisos: list[str] = field(default_factory=list)
    busquedas_hoy: int | None = None


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else -1.0


def resolver_objetivo(vault: Path, producto: str, pais: str | None, page_id: str | None) -> Objetivo:
    vault = Path(vault)
    ruta_p = vault / "productos" / producto / "PRODUCTO.md"
    if not ruta_p.is_file():
        raise FileNotFoundError(
            f"no existe productos/{producto}/PRODUCTO.md: el producto sale de /trovefy:auditar"
        )
    meta, _ = fm_leer(ruta_p)
    oferta_id = meta.get("oferta_id")
    if not isinstance(oferta_id, str) or not oferta_id:
        raise FileNotFoundError(f"productos/{producto}/PRODUCTO.md no tiene oferta_id")
    ruta_o = vault / "wiki" / "ofertas" / f"{oferta_id}.md"
    if not ruta_o.is_file():
        raise FileNotFoundError(f"no existe la ficha wiki/ofertas/{oferta_id}.md de la oferta")
    ficha, _ = fm_leer(ruta_o)
    page_ids = [str(p) for p in ficha.get("page_ids") or []]
    original = ficha.get("original_page_id")
    if page_id is not None:
        validos = set(page_ids) | ({str(original)} if original else set())
        if page_id not in validos:
            raise ValueError(f"la página {page_id} no es una de las páginas de la oferta {oferta_id}")
        elegida = page_id
    elif page_ids:
        elegida = page_ids[0]
    else:
        raise FileNotFoundError(f"la ficha de {oferta_id} no tiene page_ids")
    if not _PAGE.fullmatch(elegida):
        raise ValueError("page_id inválido")
    paises = ficha.get("paises") if isinstance(ficha.get("paises"), dict) else {}
    if pais:
        elegido = pais.strip().upper()
    else:
        con_c8 = [(k, _num(v.get("c8"))) for k, v in paises.items() if isinstance(v, dict)]
        if not con_c8:
            raise ValueError(f"la ficha de {oferta_id} no tiene países medidos: indica --pais")
        elegido = min(con_c8, key=lambda kv: (-kv[1], kv[0]))[0]
    idiomas = ficha.get("idiomas")
    idioma = str(idiomas[0]) if isinstance(idiomas, list) and len(idiomas) == 1 else None
    return Objetivo(producto, oferta_id, elegida, elegido, idioma)


def _analisis_previos(vault: Path, producto: str) -> dict:
    try:
        return {
            f.library_id: f.analisis
            for f in cargar_referencia(vault, producto).fichas
            if f.analisis is not None
        }
    except Exception:  # noqa: BLE001 - un ranking.json ilegible no debe parar la lectura nueva
        return {}


def _guardar_textos(objetivo: Objetivo, listado: Listado, ahora: datetime, retencion: int) -> None:
    if not listado.anuncios:
        return
    datos = {
        a.library_id: {"texto": a.texto or "", "titulo": a.titulo or ""} for a in listado.anuncios
    }
    cache.guardar_textos(objetivo.producto, json.dumps(datos, ensure_ascii=False), ahora, retencion)


def _busquedas_hoy(vault: Path, hoy: date) -> int | None:
    try:
        from trovefy.caza.presupuesto import Presupuesto

        return int(Presupuesto.desde_umbrales(vault, hoy)._leer()["usadas"])
    except Exception:  # noqa: BLE001 - dato informativo
        return None


def ver(
    vault: Path,
    objetivo: Objetivo,
    *,
    top: int | None,
    lote: Path | None,
    sin_navegador: bool,
    ahora: datetime,
    navegador=None,
    resolver=None,
    conectar=None,
    ejecutar=None,
    entorno: Entorno | None = None,
) -> Resultado:
    vault = Path(vault)
    u = cargar_umbrales_referencia(vault)
    avisos: list[str] = []
    try:
        cache.limpiar(ahora)
    except OSError as e:
        avisos.append(f"no se pudo limpiar la caché ({type(e).__name__})")
    ent = entorno or comprobar_entorno()
    if lote is not None:
        cargar_lote(lote)  # LoteInvalido es error de uso: el CLI lo muestra con salida 2
    ranking_hoy = hoy = (ahora if ahora.tzinfo else ahora.replace(tzinfo=ZONA_NEGOCIO)).astimezone(ZONA_NEGOCIO).date()

    try:
        listado = listar(
            vault, objetivo.pais, objetivo.page_id,
            lote=lote, sin_navegador=sin_navegador, navegador=navegador, hoy=hoy,
        )  # fmt: skip
    except Exception as e:  # noqa: BLE001 - nunca un traceback: el listado queda «no medido»
        listado = Listado([], "publica", False, "", f"no medido: listado interrumpido ({type(e).__name__})")
    n = top if top is not None else u.top
    puestos = rankear(listado.anuncios, ranking_hoy, u)
    previos = _analisis_previos(vault, objetivo.producto)
    busquedas = _busquedas_hoy(vault, hoy)

    if listado.parada:
        ref = construir_referencia(
            objetivo.producto, objetivo.oferta_id, objetivo.page_id, objetivo.pais, ranking_hoy,
            listado, puestos, analisis=previos, top_n=n,
        )  # fmt: skip
        if listado.motivo_medios:
            ref.motivos.append(listado.motivo_medios)
        escribir_referencia(vault, ref, ahora)
        return Resultado(ref, [], listado.motivo_medios or "Meta bloqueó la lectura", listado.parada, avisos, busquedas)

    informes: dict[str, InformeWatch] = {}
    trabajo: list[dict] = []
    hubo_medios = False
    for p in top_de(puestos, n):
        med = listado.medios.get(p.library_id)
        item = {
            "library_id": p.library_id, "puesto": None, "formato": med.formato if med else None,
            "fotogramas": [], "transcripcion": None, "imagen": None, "motivo": None,
        }  # fmt: skip
        trabajo.append(item)
        if not med or not (med.videos or med.imagenes):
            item["motivo"] = "no medido: sin medios en la lectura pública"
            continue
        try:
            carpeta = cache.carpeta_anuncio(objetivo.producto, p.library_id, ahora, u.retencion_dias)
            medio = carpeta / "medio"
            medio.mkdir(mode=0o700, exist_ok=True)
            kw = {k: v for k, v in (("resolver", resolver), ("conectar", conectar)) if v is not None}
            es_video = bool(med.videos)
            ruta = descargar_medio((med.videos or med.imagenes)[0], medio / ("video" if es_video else "imagen"), **kw)
            hubo_medios = True
        except DescargaRechazada as e:
            item["motivo"] = f"no medido: medio no descargable ({e})"
            informes[p.library_id] = InformeWatch(None, (), None, None, item["motivo"])
            continue
        except Exception as e:  # noqa: BLE001
            item["motivo"] = f"no medido: medio no descargable ({type(e).__name__})"
            informes[p.library_id] = InformeWatch(None, (), None, None, item["motivo"])
            continue
        if not es_video:
            item["imagen"] = str(ruta)
            continue
        try:
            extra = {"ejecutar": ejecutar} if ejecutar is not None else {}
            inf = ejecutar_watch(ruta, carpeta, objetivo.idioma, ent, **extra)
            cache.carpeta_anuncio(objetivo.producto, p.library_id, ahora, u.retencion_dias)  # repone caduca.json
        except Exception as e:  # noqa: BLE001
            inf = InformeWatch(None, (), None, None, f"no medido: /watch falló ({type(e).__name__})")
        informes[p.library_id] = inf
        item["fotogramas"] = [str(f) for f in inf.fotogramas]
        if inf.transcripcion:
            item["transcripcion"] = str(carpeta / "watch.md")
        item["motivo"] = inf.motivo

    try:
        _guardar_textos(objetivo, listado, ahora, u.retencion_dias)
    except OSError as e:
        avisos.append(f"no se pudieron guardar los textos en la caché ({type(e).__name__}): anotar no podrá comprobarlos")
    ref = construir_referencia(
        objetivo.producto, objetivo.oferta_id, objetivo.page_id, objetivo.pais, ranking_hoy,
        listado, puestos, informes=informes, analisis=previos,
        medios_hasta=(ranking_hoy + timedelta(days=u.retencion_dias)) if hubo_medios else None, top_n=n,
    )  # fmt: skip
    for it in trabajo:
        f = next((x for x in ref.fichas if x.library_id == it["library_id"]), None)
        it["puesto"] = f.puesto if f else None
    escribir_referencia(vault, ref, ahora)
    return Resultado(ref, trabajo, None, None, avisos, busquedas)
