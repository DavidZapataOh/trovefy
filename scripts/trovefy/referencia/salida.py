"""Salidas de la referencia en el vault: anuncios.md, mezcla.md, galeria.html, ranking.json y PRODUCTO.md.

Solo se guarda texto de análisis propio. Nada ajeno entra al vault: ni el texto del anuncio, ni URLs de
medios, ni ``ad_snapshot_url``. La galería enlaza la ficha pública de la Biblioteca (``?id=<id>``).
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.parse import quote

from trovefy.referencia.fuente import Listado
from trovefy.referencia.medios import Formato
from trovefy.referencia.ranking import Estado, Puesto
from trovefy.referencia.watch import InformeWatch
from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.frontmatter import leer as fm_leer
from trovefy.vault.frontmatter import renderizar

PENDIENTE = "pendiente: análisis"
_ENLACE = "https://www.facebook.com/ads/library/?id="
_NOMBRE_FORMATO = {
    "video": "vídeo",
    "imagen": "imagen",
    "carrusel": "carrusel",
    "dinamico": "dinámico",
    "otro": "otro",
}


@dataclass
class Analisis:
    transcripcion_resumida: str
    hook_sujeto: str
    hook_dolor_o_resultado: str
    angulo: str
    cta: str
    objecion: str


@dataclass
class FichaReferencia:
    puesto: int | None
    library_id: str
    estado: Estado
    dias: int | None
    variantes: int
    variantes_cota: bool
    puntuacion: int | None
    formato: Formato | None
    duracion_s: Decimal | None
    transcrito: bool
    enlace: str
    medios_hasta: date | None
    analisis: Analisis | None
    motivos: list[str] = field(default_factory=list)


@dataclass
class Referencia:
    producto: str
    oferta_id: str
    page_id: str
    pais: str
    fecha: date
    via: str
    via_medios: str | None
    completo: bool
    fichas: list[FichaReferencia]
    motivos: list[str] = field(default_factory=list)


def enlace_publico(library_id: str) -> str:
    return _ENLACE + quote(str(library_id), safe="")


def construir_referencia(
    producto: str,
    oferta_id: str,
    page_id: str,
    pais: str,
    fecha: date,
    listado: Listado,
    puestos: list[Puesto],
    *,
    informes: dict[str, InformeWatch] | None = None,
    analisis: dict[str, Analisis] | None = None,
    medios_hasta: date | None = None,
    top_n: int = 10,
) -> Referencia:
    """Reduce un listado y su ranking a fichas propias: sin texto ni URLs de medios del anuncio."""
    informes = informes or {}
    analisis = analisis or {}
    fichas: list[FichaReferencia] = []
    n = 0
    for p in puestos:
        if p.estado == "ganador":
            if n >= top_n:
                continue
            n += 1
        med = listado.medios.get(p.library_id)
        inf = informes.get(p.library_id)
        motivos = [m for m in (p.motivo,) if m]
        if inf is not None and inf.motivo:
            motivos.append(inf.motivo)
        fichas.append(
            FichaReferencia(
                puesto=n if p.estado == "ganador" else None,
                library_id=p.library_id,
                estado=p.estado,
                dias=p.dias,
                variantes=p.variantes,
                variantes_cota=p.variantes_cota,
                puntuacion=p.puntuacion,
                formato=med.formato if med else None,
                duracion_s=inf.duracion_s if inf else None,
                transcrito=bool(inf and inf.transcripcion),
                enlace=enlace_publico(p.library_id),
                medios_hasta=medios_hasta,
                analisis=analisis.get(p.library_id),
                motivos=motivos,
            )
        )
    motivos_ref = [m for m in (listado.motivo, listado.motivo_medios) if m]
    return Referencia(
        producto, oferta_id, page_id, pais, fecha, listado.via, listado.via_medios,
        listado.completo, fichas, motivos_ref,
    )  # fmt: skip


# --- serialización -------------------------------------------------------------------------------


def _a_json(ref: Referencia) -> str:
    def ficha(f: FichaReferencia) -> dict:
        base = {
            k: v
            for k, v in asdict(f).items()
            if k not in ("duracion_s", "medios_hasta", "analisis", "enlace")
        }
        return {
            **base,
            "duracion_s": None if f.duracion_s is None else str(f.duracion_s),
            "enlace": enlace_publico(f.library_id),
            "medios_hasta": None if f.medios_hasta is None else f.medios_hasta.isoformat(),
            "analisis": None if f.analisis is None else asdict(f.analisis),
        }

    d = {
        "version": 1,
        "producto": ref.producto,
        "oferta_id": ref.oferta_id,
        "page_id": ref.page_id,
        "pais": ref.pais,
        "fecha": ref.fecha.isoformat(),
        "via": ref.via,
        "via_medios": ref.via_medios,
        "completo": ref.completo,
        "motivos": ref.motivos,
        "fichas": [ficha(f) for f in ref.fichas],
    }
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


def _ruta_dir(vault: Path, p_id: str) -> Path:
    return Path(vault) / "productos" / p_id / "referencia"


def cargar_referencia(vault: Path, p_id: str) -> Referencia:
    d = json.loads((_ruta_dir(vault, p_id) / "ranking.json").read_text(encoding="utf-8"))
    fichas = []
    for f in d["fichas"]:
        fichas.append(
            FichaReferencia(
                puesto=f["puesto"],
                library_id=f["library_id"],
                estado=f["estado"],
                dias=f["dias"],
                variantes=f["variantes"],
                variantes_cota=f["variantes_cota"],
                puntuacion=f["puntuacion"],
                formato=f["formato"],
                duracion_s=None if f["duracion_s"] is None else Decimal(f["duracion_s"]),
                transcrito=f["transcrito"],
                enlace=f["enlace"],
                medios_hasta=None if f["medios_hasta"] is None else date.fromisoformat(f["medios_hasta"]),
                analisis=None if f["analisis"] is None else Analisis(**f["analisis"]),
                motivos=list(f["motivos"]),
            )
        )
    return Referencia(
        d["producto"], d["oferta_id"], d["page_id"], d["pais"], date.fromisoformat(d["fecha"]),
        d["via"], d["via_medios"], d["completo"], fichas, list(d["motivos"]),
    )  # fmt: skip


# --- presentación --------------------------------------------------------------------------------


def _num(d: Decimal) -> str:
    return f"{d.normalize():f}".replace(".", ",")


def _celda(s: object) -> str:
    return re.sub(r"\s+", " ", str(s)).replace("|", "\\|").strip()


def _dur(f: FichaReferencia) -> str:
    return f"{_num(f.duracion_s)} s" if f.duracion_s is not None else "no medido"


def _formato(f: FichaReferencia) -> str:
    return _NOMBRE_FORMATO[f.formato] if f.formato else "no medido"


def _variantes(f: FichaReferencia) -> str:
    return f"≥{f.variantes}" if f.variantes_cota else str(f.variantes)


def _dias(f: FichaReferencia) -> str:
    return "no medido" if f.dias is None else str(f.dias)


def _ganadores(ref: Referencia) -> list[FichaReferencia]:
    return [f for f in ref.fichas if f.estado == "ganador"]


def _hook(a: Analisis) -> str:
    return f"{a.hook_sujeto} / {a.hook_dolor_o_resultado}"


def _anuncios_md(ref: Referencia) -> str:
    gan = _ganadores(ref)
    en_test = [f for f in ref.fichas if f.estado == "en_test"]
    analizados = sum(1 for f in gan if f.analisis)
    meta = {
        "tipo": "referencia",
        "producto": ref.producto,
        "oferta_id": ref.oferta_id,
        "pais": ref.pais,
        "fecha": ref.fecha.isoformat(),
        "fuente": ref.via,
        "completo": "sí" if ref.completo else "muestra",
        "analizados": analizados,
        "pendientes": len(gan) - analizados,
    }
    lineas = [f"# Referencia {ref.producto} · {ref.pais}", "", "## Ganadores", ""]
    lineas.append(
        "| Puesto | Días | Variantes | Formato | Duración | Transcripción resumida | Hook | Ángulo | CTA | Objeción | Enlace |"
    )
    lineas.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for f in gan:
        a = f.analisis
        c = [a.transcripcion_resumida, _hook(a), a.angulo, a.cta, a.objecion] if a else [PENDIENTE] * 5
        fila = [f.puesto, _dias(f), _variantes(f), _formato(f), _dur(f), *c, enlace_publico(f.library_id)]
        lineas.append("| " + " | ".join(_celda(x) for x in fila) + " |")
    if not gan:
        lineas.append("| — | | | | | | | | | | |")
    lineas += ["", "## En test", "", "| Días | Variantes | Formato | Enlace |", "|---|---|---|---|"]
    for f in en_test:
        fila = [_dias(f), _variantes(f), _formato(f), enlace_publico(f.library_id)]
        lineas.append("| " + " | ".join(_celda(x) for x in fila) + " |")
    if not en_test:
        lineas.append("| — | | | |")
    lineas += ["", "## No medido", ""]
    nm = [f"- {f.library_id}: {m}" for f in ref.fichas for m in f.motivos] + [f"- {m}" for m in ref.motivos]
    lineas += nm or ["- ninguno"]
    return renderizar(meta, "\n".join(lineas) + "\n")


def _pct(n: int, total: int) -> int:
    return int((Decimal(100 * n) / Decimal(total)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _reparto(fichas: list[FichaReferencia]) -> list[str]:
    medidos = [f for f in fichas if f.formato]
    sin = len(fichas) - len(medidos)
    salida: list[str] = []
    if medidos:
        for fmt in ("video", "imagen", "carrusel", "dinamico", "otro"):
            n = sum(1 for f in medidos if f.formato == fmt)
            if n:
                salida.append(f"- {_NOMBRE_FORMATO[fmt]} {_pct(n, len(medidos))} % ({n})")
    else:
        salida.append("- no medido: ningún formato leído")
    salida.append(f"- {sin} no medido")
    return salida


def _mezcla_md(ref: Referencia) -> str:
    top = _ganadores(ref)
    meta = {"tipo": "referencia-mezcla", "producto": ref.producto, "pais": ref.pais, "fecha": ref.fecha.isoformat()}
    lineas = [f"# Mezcla de formatos {ref.producto} · {ref.pais}", "", f"## Top ({len(top)} ganadores)", ""]
    lineas += _reparto(top)
    lineas += ["", f"## Todos los leídos ({len(ref.fichas)})", ""] + _reparto(ref.fichas)
    lineas += ["", "## Duración de los vídeos del top", ""]
    ds = sorted(f.duracion_s for f in top if f.formato == "video" and f.duracion_s is not None)
    if not ds:
        lineas.append("- no medido: ningún vídeo del top con duración")
    else:
        n = len(ds)
        mediana = ds[n // 2] if n % 2 else (ds[n // 2 - 1] + ds[n // 2]) / 2
        lineas.append(f"- mínimo {_num(ds[0])} s · mediana {_num(mediana)} s · máximo {_num(ds[-1])} s")
        tramos = [
            ("≤ 15 s", sum(1 for d in ds if d <= 15)),
            ("16–30 s", sum(1 for d in ds if 15 < d <= 30)),
            ("31–60 s", sum(1 for d in ds if 30 < d <= 60)),
            ("> 60 s", sum(1 for d in ds if d > 60)),
        ]
        lineas += [f"- {t}: {c}" for t, c in tramos]
    sin = sum(1 for f in top if f.formato == "video" and f.duracion_s is None)
    if sin and ds:
        lineas.append(f"- {sin} vídeo sin duración (no medido)")
    return renderizar(meta, "\n".join(lineas) + "\n")


def _galeria_html(ref: Referencia) -> str:
    e = html.escape
    tarjetas = []
    for f in ref.fichas:
        a = f.analisis
        hook = _hook(a) if a else PENDIENTE
        ang = a.angulo if a else PENDIENTE
        puesto = f"#{f.puesto}" if f.puesto else "—"
        medios = f"medios locales hasta {f.medios_hasta.isoformat()}" if f.medios_hasta else "sin medios locales"
        url = e(enlace_publico(f.library_id), quote=True)
        tarjetas.append(
            f"<article><h2>{e(puesto)} · {e(f.estado)}</h2>"
            f"<p>{e(_dias(f))} días · variantes {e(_variantes(f))} · {e(_formato(f))} · {e(_dur(f))}</p>"
            f"<p><b>Hook:</b> {e(hook)}</p><p><b>Ángulo:</b> {e(ang)}</p>"
            f'<p><a href="{url}" rel="noopener noreferrer">Ficha en la Biblioteca de anuncios</a></p>'
            f"<p>{e(medios)}</p></article>"
        )
    return (
        '<!doctype html>\n<html lang="es"><head><meta charset="utf-8">\n'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">\n"
        f"<title>Referencia {e(ref.producto)} {e(ref.pais)}</title>\n"
        "<style>body{font-family:sans-serif;margin:1rem}"
        "article{border:1px solid #ccc;padding:.5rem 1rem;margin:.5rem 0}</style>\n"
        f"</head><body><h1>Referencia {e(ref.producto)} · {e(ref.pais)} · {e(ref.fecha.isoformat())}</h1>\n"
        + "\n".join(tarjetas)
        + "\n</body></html>\n"
    )


def _resumen(ref: Referencia) -> dict:
    gan = _ganadores(ref)
    return {
        "fecha": ref.fecha.isoformat(),
        "pais": ref.pais,
        "via": ref.via,
        "via_medios": ref.via_medios,
        "leidos": len(ref.fichas),
        "ganadores": len(gan),
        "en_test": sum(1 for f in ref.fichas if f.estado == "en_test"),
        "analizados": sum(1 for f in gan if f.analisis),
        "archivo": "referencia/anuncios.md",
    }


def _producto_md(vault: Path, ref: Referencia) -> tuple[Path, str]:
    """Fusiona solo ``referencia`` en el frontmatter; el resto (incluido ``paises``) y el cuerpo se conservan."""
    ruta = Path(vault) / "productos" / ref.producto / "PRODUCTO.md"
    if not ruta.is_file():
        raise FileNotFoundError(
            f"falta {ruta.name} de {ref.producto}: el producto sale de /trovefy:auditar; no se escribe la referencia"
        )
    meta, cuerpo = fm_leer(ruta)
    meta["referencia"] = _resumen(ref)
    linea = f"- Referencia: [[productos/{ref.producto}/referencia/anuncios]]"
    if linea not in cuerpo:
        cuerpo = cuerpo.rstrip("\n") + "\n\n" + linea + "\n"
    return ruta, renderizar(meta, cuerpo)


def escribir_referencia(vault: Path, ref: Referencia, ahora: datetime, *, log: bool = True) -> list[Path]:
    d = _ruta_dir(vault, ref.producto)
    textos = {
        d / "anuncios.md": _anuncios_md(ref),
        d / "mezcla.md": _mezcla_md(ref),
        d / "galeria.html": _galeria_html(ref),
        d / "ranking.json": _a_json(ref),
    }
    ruta_prod, texto_prod = _producto_md(vault, ref)
    textos[ruta_prod] = texto_prod
    for ruta, t in textos.items():
        nombre = buscar_secreto(t)
        if nombre:
            raise ValueError(f"{ruta.name}: aparece un secreto ({nombre}); no se escribe nada")
    for ruta, t in textos.items():
        escribir_atomico(ruta, t)
    if log:
        anadir_log(
            vault, "ver-anuncios", f"referencia {ref.producto} {ref.pais}",
            [f"productos/{ref.producto}/referencia/anuncios.md"], ahora=ahora,
        )  # fmt: skip
    return list(textos)


def referencia_lista(vault: Path, p_id: str) -> tuple[bool, str]:
    if not (_ruta_dir(vault, p_id) / "ranking.json").is_file():
        return False, "falta referencia/"
    faltan = sum(1 for f in _ganadores(cargar_referencia(vault, p_id)) if f.analisis is None)
    if faltan:
        return False, f"faltan {faltan} análisis: /trovefy:ver-anuncios"
    return True, ""
