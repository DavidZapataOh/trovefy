"""APIMart falso para los tests de la CLI y del flujo: nunca hay red (Global Constraints del plan 17)."""

import json
import os
import pathlib

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "apimart"
CLAVE = "sk-prueba-" + "y" * 24


def fixture(nombre: str):
    ruta = FIXTURES / nombre
    if nombre.endswith(".json"):
        return json.loads(ruta.read_text(encoding="utf-8"))
    return ruta.read_bytes()


def escribir_env(carpeta: pathlib.Path, clave: str = CLAVE) -> pathlib.Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "claude.env"
    ruta.write_text(f"APIMART_API_KEY={clave}\n", encoding="utf-8")
    os.chmod(ruta, 0o600)
    return ruta


class _Resp:
    def __init__(self, cuerpo: bytes, codigo: int = 200):
        self.status, self._c = codigo, cuerpo

    def read(self, *_a):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (60, 90), (31, 78, 95)).save(buf, format="PNG")
    return buf.getvalue()


class APIMartFalso:
    """Precio (``/api/pricing/model``), generación → ``task_id``, tarea completada. ``precio=False``: sin
    precio medible (404)."""

    def __init__(self, precio: bool = True, coste: float = 0.0085):
        self.precio, self.coste = precio, coste
        self.rutas: list[str] = []
        self.autorizaciones: list[str] = []
        self.n = 0

    def __call__(self, req, timeout=None):
        ruta = req.full_url.removeprefix("https://api.apimart.ai")
        self.rutas.append(f"{req.get_method()} {ruta}")
        self.autorizaciones.append(req.headers.get("Authorization", ""))
        if ruta.startswith("/api/pricing/model"):
            if not self.precio:
                return _Resp(b'{"success": false}', 200)
            return _Resp(json.dumps(fixture("pricing-gpt-image-2.json")).encode())
        if ruta == "/v1/images/generations":
            self.n += 1
            return _Resp(json.dumps({"code": 200, "data": [{"status": "submitted",
                                                            "task_id": f"task_abcdef{self.n:06d}"}]}).encode())
        if ruta.startswith("/v1/tasks/"):
            tid = ruta.rsplit("/", 1)[1].split("?")[0]
            datos = fixture("tarea-completada.json")
            datos["data"].update(id=tid, cost=self.coste, credits_cost=0.085)
            datos["data"]["result"]["images"][0]["url"] = [f"https://upload.apimart.ai/f/image/{tid}.png"]
            return _Resp(json.dumps(datos).encode())
        raise AssertionError(f"ruta inesperada {ruta}")


def publico(req, timeout=None):
    assert "Authorization" not in req.headers
    return _Resp(_png())
