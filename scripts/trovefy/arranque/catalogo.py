"""Catálogo de pasos de /arranque (tabla de §4.2): (id, nombre, fase, opcional)."""

PASOS: list[tuple[str, str, int | None, bool]] = [
    ("00", "Entorno", 0, False),
    ("01", "Cerebro", 0, False),
    ("02", "Caza sin cuentas", 0, False),
    ("03", "Perfil de Facebook", 0, False),
    ("04", "Portfolio comercial (Business Manager)", 0, False),
    ("05", "Página de Facebook", 0, False),
    ("06", "Cuenta publicitaria", 0, False),
    ("07", "Dominio", 0, False),
    ("08", "Verificar el dominio en Meta", 0, False),
    ("09", "Impultienda", 0, False),
    ("10", "Cobro: Whop", 0, False),
    ("10b", "Respaldo: Hotmart", 0, False),
    ("11", "Dataset/píxel", 2, False),
    ("12", "Bot de Telegram", 1, False),
    ("13", "App de Meta + system user", 1, False),
    ("14", "MCP oficial de Meta", 1, False),
    ("15", "(Opcional) API de la Biblioteca", None, True),
    ("16", "APIMart", 0, False),
    ("17", "(Opcional) UTMify Free", None, True),
    ("18", "Ensayo general", 1, False),
]
