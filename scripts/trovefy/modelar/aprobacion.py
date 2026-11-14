"""Aprobación de la oferta [D-14], rechazo, excepción de R16 y paso ``aprobado → modelado``.

``OFERTA.md`` es la fuente de verdad de la aprobación (Ruling R-T7b): aquí se escribe primero y
``PRODUCTO.md`` solo lleva una copia (``oferta.aprobacion``, ``aprobacion_fecha``, ``aprobacion_cita``)
vía ``actualizar_producto``. El país elegido pasa a ``modelado`` solo con la oferta ``aprobada`` o
``aprobada_tacita`` y la tercera señal (``se_puede_mejorar``) en ``true`` o una excepción vigente en
``decisiones/*-excepcion-r16.md`` (resolución 8). ``cerrar`` es la aprobación tácita: idempotente,
la llaman ``/cerrar`` y el paso 0 de ``/producto`` (resolución 9).

Las citas del usuario se guardan tal cual, después de pasar por ``buscar_secreto``.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from trovefy.modelar.salida import cargar_oferta
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
from trovefy.vault.producto import (
    ESTADOS_FASE2,
    actualizar_producto,
    avanzar_estado,
    estado_pais,
    pais_elegido,
    ruta_producto,
)

APROBACIONES = ("presentada", "aprobada", "aprobada_tacita", "rechazada")
APROBADAS = ("aprobada", "aprobada_tacita")
_ETIQUETA = {"presentada": "presentada", "aprobada": "aprobada", "aprobada_tacita": "aprobada tácitamente",
             "rechazada": "rechazada"}
MOTIVO_RECHAZADA = "la oferta está rechazada: vuelve a /modelar"
MOTIVO_YA_APROBADA = "la oferta ya quedó aprobada; para cambiarla, rehaz /modelar"
_SKILL = "modelar"


# --- utilidades ------------------------------------------------------------------------------------


def _con_zona(ahora: datetime) -> datetime:
    if not isinstance(ahora, datetime) or ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError(f"ahora sin zona horaria: {ahora!r} (usa un datetime con tzinfo)")
    return ahora.astimezone(ZONA_NEGOCIO)


def _cita(cita: str) -> str:
    if not isinstance(cita, str) or not cita.strip():
        raise ValueError("hace falta la cita literal del usuario (--cita)")
    return cita


def _fecha(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor.strip()[:10])
        except ValueError:
            return None
    return None


def _sin_secretos(textos: dict[str, str]) -> None:
    for nombre, texto in textos.items():
        patron = buscar_secreto(texto)  # RevisionSecretosNoDisponible: no se escribe nada
        if patron:
            raise ValueError(f"{nombre}: aparece un secreto ({patron}); no se escribe nada")


def _cita_md(cita: str) -> str:
    return "\n".join(f"> {x}" if x else ">" for x in cita.split("\n"))


def _carpeta(vault: Path, p_id: str) -> Path:
    return ruta_producto(vault, p_id).parent


def _leer_oferta(vault: Path, p_id: str) -> tuple[Path, dict, str]:
    cargar_oferta(vault, p_id)  # FileNotFoundError("falta OFERTA.md: /modelar")
    ruta = _carpeta(vault, p_id) / "OFERTA.md"
    meta, cuerpo = frontmatter.leer(ruta)
    meta = dict(meta or {})
    aprobacion = meta.get("aprobacion")
    if aprobacion not in APROBACIONES:
        raise ValueError(f"OFERTA.md trae una aprobación desconocida: {aprobacion!r} "
                         f"(va una de {', '.join(APROBACIONES)})")
    return ruta, meta, cuerpo


def _ruta_decision(dir_: Path, hoy: date, sufijo: str) -> Path:
    """``AAAA-MM-DD-<sufijo>.md`` es siempre la última del día; una anterior del mismo día pasa a
    ``AAAA-MM-DD-N-<sufijo>.md`` (mismo criterio que la elección de país de ``/auditar``)."""
    ruta = dir_ / f"{hoy.isoformat()}-{sufijo}.md"
    if ruta.exists():
        n = 1
        while (dir_ / f"{hoy.isoformat()}-{n}-{sufijo}.md").exists():
            n += 1
        ruta.rename(dir_ / f"{hoy.isoformat()}-{n}-{sufijo}.md")
    return ruta


def _nueva_oferta(meta: dict, cuerpo: str, nueva: str, ahora: datetime, cita: str | None) -> tuple[dict, str]:
    anterior = meta["aprobacion"]
    meta = {**meta, "aprobacion": nueva, "aprobacion_fecha": ahora.isoformat(timespec="seconds"),
            "aprobacion_cita": cita}
    cuerpo = cuerpo.replace(f"Aprobación: {_ETIQUETA[anterior]}.", f"Aprobación: {_ETIQUETA[nueva]}.", 1)
    return meta, cuerpo


def _guardar_oferta(vault: Path, p_id: str, ruta: Path, texto: str, meta: dict, otros: list[Path],
                    que: str, ahora: datetime) -> None:
    escribir_atomico(ruta, texto)
    archivos = [r.relative_to(vault).as_posix() for r in [ruta, *otros]]
    anadir_log(vault, _SKILL, que, archivos, ahora=ahora)
    actualizar_producto(vault, p_id, {"oferta": {"aprobacion": meta["aprobacion"],
                                                 "aprobacion_fecha": meta["aprobacion_fecha"],
                                                 "aprobacion_cita": meta["aprobacion_cita"]}},
                        [], _SKILL, ahora)


# --- reglas ----------------------------------------------------------------------------------------


def puede_avanzar(meta_oferta: dict, excepcion: Path | None) -> tuple[bool, str]:
    """Oferta ``aprobada``/``aprobada_tacita`` y tercera señal en ``true`` o excepción que existe."""
    aprobacion = meta_oferta.get("aprobacion")
    if aprobacion == "rechazada":
        return False, MOTIVO_RECHAZADA
    if aprobacion not in APROBADAS:
        return False, (f"la oferta está {aprobacion or 'sin aprobación'}: falta aprobarla "
                       "(o cerrar la sesión sin rechazarla)")
    senal = meta_oferta.get("se_puede_mejorar")
    if senal is True:
        return True, "oferta aprobada con las tres señales"
    if excepcion is not None and Path(excepcion).is_file():
        return True, f"oferta aprobada con la excepción de R16 ({Path(excepcion).name})"
    valor = "no" if senal is False else "no medida"
    return False, (f"falta la tercera señal (se puede mejorar: {valor}); sin las tres señales no se produce: "
                   "o mejoras la oferta o registras la excepción con las palabras del usuario")


def excepcion_vigente(vault: Path, p_id: str) -> Path | None:
    """La ``decisiones/*-excepcion-r16.md`` más reciente del país de ``OFERTA.md`` con fecha igual o
    posterior a la de ``OFERTA.md``; None si no hay (o si aún no hay ``OFERTA.md``)."""
    vault = Path(vault)
    try:
        oferta = cargar_oferta(vault, p_id)
    except FileNotFoundError:
        return None
    desde = _fecha(oferta.get("fecha"))
    if desde is None:
        return None
    candidatas = []
    for ruta in (_carpeta(vault, p_id) / "decisiones").glob("*-excepcion-r16.md"):
        meta, _ = frontmatter.leer(ruta)
        if not isinstance(meta, dict) or meta.get("regla") != "R16" or meta.get("tipo") != "decision":
            continue
        if meta.get("producto") != p_id or meta.get("pais") != oferta.get("pais"):
            continue
        fecha = _fecha(meta.get("fecha"))
        if fecha is None or fecha < desde:
            continue
        candidatas.append(((fecha, str(meta.get("registrada") or ""), ruta.name), ruta))
    return max(candidatas)[1] if candidatas else None


def _avanzar(vault: Path, p_id: str, ahora: datetime) -> str:
    """Pasa el país elegido de ``aprobado`` a ``modelado`` si ``puede_avanzar``; devuelve qué pasó."""
    pais, _, _ = pais_elegido(vault, p_id)
    meta = cargar_oferta(vault, p_id)
    if meta.get("producto") != p_id or meta.get("pais") != pais:
        return (f"OFERTA.md es de {meta.get('producto')} · {meta.get('pais')} y el país elegido es {pais}: "
                "rehaz /modelar")
    estado = estado_pais(vault, p_id, pais)
    if estado in ESTADOS_FASE2[1:]:
        return f"{pais} ya está en {estado}"
    if estado != "aprobado":
        return f"{pais} está en {estado or 'sin estado'}: no pasa a modelado"
    ok, motivo = puede_avanzar(meta, excepcion_vigente(vault, p_id))
    if not ok:
        return f"{pais} sigue en aprobado: {motivo}"
    avanzar_estado(vault, p_id, pais, "aprobado", "modelado", evidencia=f"productos/{p_id}/OFERTA.md",
                   skill=_SKILL, ahora=ahora)
    return f"{pais} pasa a modelado"


def _linea(p_id: str, aprobacion: str, resultado: str) -> str:
    return f"Oferta de {p_id}: {_ETIQUETA[aprobacion]}; {resultado}"


# --- transiciones ----------------------------------------------------------------------------------


def aprobar(vault: Path, p_id: str, cita: str, ahora: datetime) -> str:
    """``presentada → aprobada`` con la cita literal; después intenta avanzar a ``modelado``.

    Una oferta ya aprobada (explícita o tácitamente) no cambia; una rechazada da ``ValueError``."""
    vault, ahora, cita = Path(vault), _con_zona(ahora), _cita(cita)
    ruta, meta, cuerpo = _leer_oferta(vault, p_id)
    if meta["aprobacion"] == "rechazada":
        raise ValueError(MOTIVO_RECHAZADA)
    if meta["aprobacion"] == "presentada":
        meta, cuerpo = _nueva_oferta(meta, cuerpo, "aprobada", ahora, cita)
        texto = frontmatter.renderizar(meta, cuerpo)
        _sin_secretos({"OFERTA.md": texto})
        _guardar_oferta(vault, p_id, ruta, texto, meta, [], f"{p_id}: oferta aprobada por el usuario", ahora)
    return _linea(p_id, meta["aprobacion"], _avanzar(vault, p_id, ahora))


def rechazar(vault: Path, p_id: str, cita: str, ahora: datetime) -> Path:
    """``presentada → rechazada``; escribe ``decisiones/AAAA-MM-DD-oferta-rechazada.md`` con la cita literal."""
    vault, ahora, cita = Path(vault), _con_zona(ahora), _cita(cita)
    ruta, meta, cuerpo = _leer_oferta(vault, p_id)
    if meta["aprobacion"] in APROBADAS:
        raise ValueError(MOTIVO_YA_APROBADA)
    if meta["aprobacion"] == "rechazada":
        raise ValueError("la oferta ya está rechazada: vuelve a /modelar")
    hoy = ahora.date()
    pais = meta.get("pais")
    meta, cuerpo = _nueva_oferta(meta, cuerpo, "rechazada", ahora, cita)
    texto_oferta = frontmatter.renderizar(meta, cuerpo)
    decision = {"tipo": "decision", "fecha": hoy.isoformat(), "registrada": ahora.isoformat(timespec="seconds"),
                "fuente": "usuario", "producto": p_id, "pais": pais, "decision": "oferta_rechazada",
                "oferta": f"productos/{p_id}/OFERTA.md", "cita": cita}
    lineas = [f"# Oferta rechazada · {p_id} · {pais} ({hoy.isoformat()})", "",
              "Palabras del usuario (cita literal):", "", _cita_md(cita), "",
              "La oferta no pasa a producción: hay que rehacer /modelar.", "",
              f"Oferta: [[productos/{p_id}/OFERTA]]", ""]
    texto_decision = frontmatter.renderizar(decision, "\n".join(lineas))
    _sin_secretos({"OFERTA.md": texto_oferta, "decisión de rechazo": texto_decision})
    dir_ = _carpeta(vault, p_id) / "decisiones"
    dir_.mkdir(parents=True, exist_ok=True)
    destino = _ruta_decision(dir_, hoy, "oferta-rechazada")
    escribir_atomico(destino, texto_decision)
    _guardar_oferta(vault, p_id, ruta, texto_oferta, meta, [destino], f"{p_id}: oferta rechazada por el usuario",
                    ahora)
    return destino


def cerrar(vault: Path, p_id: str, ahora: datetime) -> str:
    """La aprobación tácita [D-14], idempotente: ``presentada → aprobada_tacita``; aprobada o rechazada
    no cambian. Después intenta avanzar a ``modelado``. Devuelve una línea para el usuario."""
    vault, ahora = Path(vault), _con_zona(ahora)
    ruta, meta, cuerpo = _leer_oferta(vault, p_id)
    if meta["aprobacion"] == "presentada":
        meta, cuerpo = _nueva_oferta(meta, cuerpo, "aprobada_tacita", ahora, None)
        texto = frontmatter.renderizar(meta, cuerpo)
        _sin_secretos({"OFERTA.md": texto})
        _guardar_oferta(vault, p_id, ruta, texto, meta, [], f"{p_id}: oferta aprobada tácitamente", ahora)
    return _linea(p_id, meta["aprobacion"], _avanzar(vault, p_id, ahora))


def registrar_excepcion(vault: Path, p_id: str, pais: str, cita: str, ahora: datetime) -> Path:
    """Escribe ``decisiones/AAAA-MM-DD-excepcion-r16.md`` (producir sin la tercera señal, con las palabras
    del usuario) y después intenta avanzar a ``modelado``."""
    vault, ahora, cita = Path(vault), _con_zona(ahora), _cita(cita)
    pais = pais.strip().upper() if isinstance(pais, str) else ""
    elegido, _, _ = pais_elegido(vault, p_id)
    if pais != elegido:
        raise ValueError(f"la excepción es para el país elegido ({elegido}), no para {pais or 'ninguno'}")
    _, oferta, _ = _leer_oferta(vault, p_id)
    if oferta.get("pais") != elegido:
        raise ValueError(f"OFERTA.md es de {oferta.get('pais')} y el país elegido es {elegido}: rehaz /modelar")
    valor = oferta.get("se_puede_mejorar")
    if valor is True:
        raise ValueError("la tercera señal ya está (se puede mejorar: sí): no hace falta excepción")
    motivo = oferta.get("se_puede_mejorar_motivo")
    hoy = ahora.date()
    meta = {"tipo": "decision", "fecha": hoy.isoformat(), "registrada": ahora.isoformat(timespec="seconds"),
            "fuente": "usuario", "producto": p_id, "pais": pais, "regla": "R16", "senal": "se_puede_mejorar",
            "valor": valor, "motivo": motivo, "oferta": f"productos/{p_id}/OFERTA.md",
            "oferta_fecha": str(oferta.get("fecha")), "cita": cita}
    lineas = [f"# Excepción de R16 · {p_id} · {pais} ({hoy.isoformat()})", "",
              (f"Tercera señal (se puede mejorar): {'no' if valor is False else 'no medida'}"
              f" — {motivo or 'sin motivo'}."), "",
              "El usuario decide producir igual. Palabras del usuario (cita literal):", "",
              _cita_md(cita), "",
              f"Oferta: [[productos/{p_id}/OFERTA]] ({oferta.get('fecha')})", ""]
    texto = frontmatter.renderizar(meta, "\n".join(lineas))
    _sin_secretos({"excepción de R16": texto})
    dir_ = _carpeta(vault, p_id) / "decisiones"
    dir_.mkdir(parents=True, exist_ok=True)
    destino = _ruta_decision(dir_, hoy, "excepcion-r16")
    escribir_atomico(destino, texto)
    anadir_log(vault, _SKILL, f"{p_id} {pais}: excepción de R16 (se puede mejorar) con las palabras del usuario",
               [destino.relative_to(vault).as_posix()], ahora=ahora)
    _avanzar(vault, p_id, ahora)
    return destino
