"""``manifest.csv``, cierre de la tanda, aviso por Telegram y rehacer tras un veto (plan 21, Tarea 11).

``manifest.csv`` sustituye al «.txt junto a cada anuncio» de L1 56:40 (mismos campos) y es lo que ``/montar`` (plan
22) consume tal cual. Cerrar exige en ``QA.md``, sobre la huella actual de la tanda: automática sin bloqueos,
``revisor: ok``, ``nativo: ok`` y Whisper ``ok`` en cada vídeo. Al cerrar se fusiona
``paises.<PAIS>.creativos`` en ``PRODUCTO.md`` (nunca el estado: ``listo → montado`` es del 22) y se deposita una
``alerta`` con la hoja de contactos adjunta (el enlace de C1 31:26).
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trovefy.apimart.gasto import gastado_usd, leer_costes
from trovefy.aprobaciones import fuentes
from trovefy.aprobaciones.fuentes import BuzonNoDisponible
from trovefy.creativos import registro
from trovefy.creativos import tanda as tanda_md
from trovefy.creativos.brief import FichaTanda
from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.contexto import Contexto, ruta_tanda
from trovefy.creativos.guion import GuionVideo, cargar_guion
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import actualizar_producto, ruta_producto

SKILL = "/creativos"
NOMBRE = "manifest.csv"
CABECERA = ("id", "nombre", "uso", "orden", "angulo", "angulo_es", "hook", "formato", "tipo", "archivo", "sha256",
            "miniatura", "duracion_s", "voz", "texto", "titulo", "descripcion", "cta", "url", "idioma")


class TandaNoCierra(ValueError):
    def __init__(self, motivos: list[str]) -> None:
        super().__init__("la tanda no cierra:\n" + "\n".join(f"- {m}" for m in motivos))
        self.motivos = motivos


def piezas(ficha: FichaTanda) -> list[tuple[str, str]]:
    return [(e.ad, ficha.brief(e.ad).tipo) for e in ficha.elegidos]


def _proveedor_voz(carpeta: Path, ad: str) -> str:
    from trovefy.creativos.escenas import raiz_fuente
    from trovefy.producto.medios import leer_manifiesto

    e = leer_manifiesto(raiz_fuente(carpeta)).get(f"voz-{ad.lower()}-g") or {}
    return e.get("origen", "") if e.get("origen") in ("apimart", "elevenlabs") else ""


def filas(ctx: Contexto, ficha: FichaTanda, carpeta: Path, cfg: ConfigCreativos, *,
          duraciones: dict[str, float] | None = None) -> list[dict]:
    """Una fila por anuncio, en el orden en que se monta (pura salvo leer los sha256 de disco)."""
    if not ctx.url_anuncio:
        raise TandaNoCierra(["no medido: sin landing en PRODUCTO.md no hay URL del anuncio"])
    rel = Path(carpeta).relative_to(ctx.vault).as_posix()
    salida = []
    for e in ficha.elegidos:
        b = ficha.brief(e.ad)
        archivo = registro.archivo_pieza(carpeta, e.ad, b.tipo)
        sha = registro.sha_archivo(archivo)
        if sha is None:
            raise TandaNoCierra([f"falta {archivo.name}"])
        miniatura = f"{rel}/miniaturas/{e.ad}.jpg" if b.tipo == "video" else f"{rel}/{archivo.name}"
        duracion = ""
        if b.tipo == "video":
            if duraciones and e.ad in duraciones:
                duracion = f"{duraciones[e.ad]:.1f}"
            else:
                g = cargar_guion(carpeta, e.ad, "video", cfg)
                duracion = f"{g.duracion:.1f}" if isinstance(g, GuionVideo) else ""
        salida.append({
            "id": e.ad, "nombre": ficha.nombre(e.ad), "uso": e.uso, "orden": str(e.orden), "angulo": b.angulo,
            "angulo_es": b.angulo_es, "hook": b.hook, "formato": b.formato, "tipo": b.tipo,
            "archivo": f"{rel}/{archivo.name}", "sha256": sha, "miniatura": miniatura, "duracion_s": duracion,
            "voz": _proveedor_voz(carpeta, e.ad) if b.tipo == "video" else "", "texto": b.texto, "titulo": b.titulo,
            "descripcion": b.descripcion, "cta": b.cta, "url": ctx.url_anuncio, "idioma": ctx.idioma})
    return salida


def texto_manifest(filas_: list[dict]) -> str:
    salida = io.StringIO()
    w = csv.DictWriter(salida, fieldnames=CABECERA, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writeheader()
    for f in filas_:
        w.writerow(f)
    return salida.getvalue()


def escribir_manifest(carpeta: Path, filas_: list[dict]) -> tuple[Path, str]:
    texto = texto_manifest(filas_)
    if buscar_secreto(texto):
        raise ValueError("el manifiesto traería algo con forma de secreto; no se escribe")
    ruta = Path(carpeta) / NOMBRE
    escribir_atomico(ruta, texto)
    ruta.chmod(0o640)
    return ruta, hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _reservas_que_entran(vault: Path, ctx: Contexto, carpeta: Path, ficha: FichaTanda, ya: int) -> list[dict]:
    """En una renovación, las piezas de reserva del ángulo ganador (ya revisadas en su tanda) entran tal cual, con
    ``uso: renovacion`` y el grupo de esta tanda en el nombre (Tarea 13)."""
    from trovefy.creativos.renovar import leer_manifiestos

    meta, _, _ = tanda_md.leer(carpeta)
    plan = meta.get("plan_renovacion") if meta.get("tipo") == "renovacion" else None
    ids = plan.get("reservas") if isinstance(plan, dict) else None
    if not ids:
        return []
    propias = {e.ad for e in ficha.elegidos}
    choque = sorted(set(ids) & propias)
    if choque:
        raise TandaNoCierra([f"{', '.join(choque)} ya es una reserva que entra en esta renovación: usa otro ADnn"])
    previas = {f["id"]: f for f in leer_manifiestos(vault, ctx.producto, ctx.pais).values()
               if f.get("uso") == "reserva" and f.get("tanda") != ficha.tanda}
    salida = []
    for n, ad in enumerate(ids, start=ya + 1):
        f = previas.get(ad)
        if f is None:
            raise TandaNoCierra([f"la reserva {ad} no está en el manifiesto de una tanda anterior"])
        fila = {k: f[k] for k in CABECERA}
        nombre = fila["nombre"].split(" ", 2)
        fila.update(uso="renovacion", orden=str(n),
                    nombre=f"{nombre[0]} {ficha.grupo} {nombre[2] if len(nombre) > 2 else ''}".strip())
        salida.append(fila)
    return salida


def _bloque_creativos(vault: Path, producto: str, pais: str) -> dict:
    meta, _ = frontmatter.leer(ruta_producto(vault, producto))
    paises = meta.get("paises") if isinstance(meta, dict) else {}
    bloque = (paises or {}).get(pais) or {}
    c = bloque.get("creativos") if isinstance(bloque, dict) else None
    return c if isinstance(c, dict) else {}


def _rehacer_pendientes(vault: Path, producto: str, pais: str, tanda: str) -> list[dict]:
    t = (_bloque_creativos(vault, producto, pais).get("tandas") or {}).get(tanda) or {}
    return [r for r in (t.get("rehacer") or []) if isinstance(r, dict)]


def cerrar_tanda(vault: Path, ctx: Contexto, ficha: FichaTanda, cfg: ConfigCreativos, ahora: datetime, *,
                 depositar=fuentes.depositar, duraciones: dict[str, float] | None = None) -> tuple[Path, str]:
    """Cierra la tanda. Devuelve (manifiesto, línea del aviso). ``TandaNoCierra`` con lo que falte."""
    vault = Path(vault)
    carpeta = ruta_tanda(vault, ctx.producto, ctx.pais, ficha.tanda)
    lista = piezas(ficha)
    est = registro.estado(carpeta, lista)
    motivos = est.faltan()
    for ad, tipo in lista:
        if tipo == "video" and not (carpeta / "miniaturas" / f"{ad}.jpg").is_file():
            motivos.append(f"falta la miniatura de {ad} (trovefy creativos video)")
    if est.hoja is None or not (carpeta / est.hoja).is_file():
        motivos.append("falta la hoja de contactos que aprobó el revisor")
    previo = carpeta / NOMBRE
    if previo.is_file():
        antes = {f.get("id"): f.get("sha256") for f in csv.DictReader(previo.read_text(encoding="utf-8").splitlines())}
        for r in _rehacer_pendientes(vault, ctx.producto, ctx.pais, ficha.tanda):
            if r.get("resuelto"):
                continue
            for ad in r.get("ads") or []:
                tipo = dict(lista).get(ad, "imagen")
                if antes.get(ad) and antes.get(ad) == registro.sha_archivo(registro.archivo_pieza(carpeta, ad, tipo)):
                    motivos.append(f"{ad} no cambió desde el veto («{r.get('motivo')}»): rehazlo antes de cerrar")
    if motivos:
        raise TandaNoCierra(motivos)
    filas_ = filas(ctx, ficha, carpeta, cfg, duraciones=duraciones)
    filas_ += _reservas_que_entran(vault, ctx, carpeta, ficha, len(filas_))
    ruta, sha = escribir_manifest(carpeta, filas_)
    gasto = gastado_usd(leer_costes(vault, ctx.producto, carpeta))
    meta_t, _, _ = tanda_md.leer(carpeta)
    aprobado = (meta_t.get("aprobacion") or {}).get("total_usd", "—") if isinstance(meta_t.get("aprobacion"),
                                                                                    dict) else "—"
    por_proveedor = {"apimart": Decimal(0), "elevenlabs": Decimal(0)}
    ultimas: dict = {}
    for f in leer_costes(vault, ctx.producto, carpeta):
        ultimas[f.intento] = f
    for f in ultimas.values():
        if f.estado in ("enviando", "enviada", "completada", "fallida", "pendiente"):
            clave = "elevenlabs" if f.modelo.startswith("elevenlabs") else "apimart"
            por_proveedor[clave] += f.coste_real_usd if f.coste_real_usd is not None else (f.coste_estimado_usd or 0)
    rel = carpeta.relative_to(vault).as_posix()
    test = [e.ad for e in ficha.elegidos if e.uso == "test"]
    reserva = [e.ad for e in ficha.elegidos if e.uso == "reserva"]
    videos = [ad for ad, t in lista if t == "video"]
    previos = _rehacer_pendientes(vault, ctx.producto, ctx.pais, ficha.tanda)
    hechos = [{**r, "resuelto": ahora.isoformat(timespec="seconds")} if "resuelto" not in r else r for r in previos]
    datos_tanda = {
        "carpeta": rel, "manifest": f"{rel}/{NOMBRE}", "manifest_sha256": sha, "piezas": len(lista),
        "imagenes": len(lista) - len(videos), "videos": len(videos), "test": test, "reserva": reserva,
        "renovacion": [e.ad for e in ficha.elegidos if e.uso == "renovacion"],
        "qa": {"auto": est.automatica, "revisor": est.revisor, "nativo": est.nativo,
               "whisper": "ok" if all(v == "ok" for v in est.whisper.values()) else "no"},
        "coste_usd": str(gasto), "cerrada": ahora.isoformat(timespec="seconds"), "rehacer": hechos,
        "hoja": f"{rel}/{est.hoja}"}
    actualizar_producto(vault, ctx.producto, {"paises": {ctx.pais: {"creativos": {
        "vigente": ficha.tanda, "tandas": {ficha.tanda: datos_tanda}}}}}, [], SKILL, ahora,
        archivos_log=[f"{rel}/{NOMBRE}"])
    tanda_md.actualizar(carpeta, {"cerrada": ahora.isoformat(timespec="seconds")},
                        f"tanda cerrada; manifest.csv {sha[:12]}", ahora)
    plantillas = ", ".join(sorted({ficha.brief(ad).formato for ad in videos})) or "ninguna"
    texto = (f"{len(lista)} piezas ({len(lista) - len(videos)} imágenes, {len(videos)} vídeos: {plantillas}); "
             + (f"{len(test)} al test, {len(reserva)} de reserva. " if test or reserva else
                f"{len(datos_tanda['renovacion'])} de renovación. ")
             + f"Coste {gasto.quantize(Decimal('0.01'))} USD de {aprobado} aprobados (APIMart "
             f"{por_proveedor['apimart'].quantize(Decimal('0.01'))}, ElevenLabs "
             f"{por_proveedor['elevenlabs'].quantize(Decimal('0.01'))}). Míralos: si algo no te gusta, rechaza "
             "«Activar» y di qué.")
    alerta = {"tipo": "alerta", "origen": SKILL, "nivel": "info",
              "titulo": f"Creativos listos: {ctx.producto} {ctx.pais} {ficha.tanda}", "texto": texto,
              "adjuntos": [f"{rel}/{est.hoja}"]}
    try:
        id_ = depositar(vault, alerta, lambda: ahora)
        aviso = f"aviso enviado: {id_}"
    except BuzonNoDisponible as exc:
        aviso = f"aviso no enviado: {exc}"
    anadir_log(vault, SKILL, f"{ctx.producto} {ctx.pais} {ficha.tanda}: tanda cerrada ({aviso})", [f"{rel}/{NOMBRE}"],
               ahora=ahora)
    return ruta, aviso


def rehacer(vault: Path, producto: str, pais: str, tanda: str, ads: list[str], motivo: str, ahora: datetime) -> Path:
    """Reabre la tanda tras un veto [D-33] con el motivo **literal** del usuario. El resto de piezas no cambia."""
    vault = Path(vault)
    carpeta = ruta_tanda(vault, producto, pais, tanda)
    if not carpeta.is_dir():
        raise FileNotFoundError(f"no existe la tanda {tanda}")
    if not ads or any(not (len(a) == 4 and a.startswith("AD") and a[2:].isdigit()) for a in ads):
        raise ValueError("di qué anuncios rehacer: --ad AD03 (repetible)")
    if not isinstance(motivo, str) or not motivo.strip():
        raise ValueError("hace falta el motivo literal del usuario")
    if buscar_secreto(motivo):
        raise ValueError("el motivo trae algo con forma de secreto; no se guarda")
    entrada = {"ads": list(ads), "motivo": motivo, "fecha": ahora.isoformat(timespec="seconds")}
    previos = _rehacer_pendientes(vault, producto, pais, tanda)
    actualizar_producto(vault, producto, {"paises": {pais: {"creativos": {"tandas": {tanda: {
        "cerrada": None, "rehacer": [*previos, entrada]}}}}}}, [], SKILL, ahora)
    meta, _, _ = tanda_md.leer(carpeta)
    pendientes = [*(meta.get("rehacer") or []), entrada]
    return tanda_md.actualizar(carpeta, {"cerrada": None, "rehacer": pendientes},
                               f"rehacer {', '.join(ads)} — motivo del usuario: «{motivo}»", ahora)
