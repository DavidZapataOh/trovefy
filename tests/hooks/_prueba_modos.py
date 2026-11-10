"""Hook de prueba: el comportamiento de decidir() lo elige tool_name."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "hooks"))

from _comun import ejecutar_guardia


def decidir(entrada):
    modo = entrada["tool_name"]
    if modo == "salir0":
        sys.exit(0)
    if modo == "salir1":
        sys.exit(1)
    if modo == "interrupcion":
        raise KeyboardInterrupt
    if modo == "decision_invalida":
        return ("quizas", "x")
    if modo == "motivo_no_str":
        return ("deny", pathlib.Path("/tmp"))
    if modo == "allow":
        return ("allow", "")
    if modo == "deny":
        return ("deny", "no permitido")
    if modo == "stdout_cerrado":
        sys.stdout.close()
        return ("deny", "no permitido")
    raise AssertionError(modo)


if __name__ == "__main__":
    ejecutar_guardia(decidir)
