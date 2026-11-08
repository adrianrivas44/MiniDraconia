"""Carga el runtime de C++ del sistema antes que Qt (voz Emma / Kokoro).

PySide6 6.5 trae msvcp140.dll 14.29 (2019) en su carpeta. Si Qt se carga primero,
onnxruntime 1.31 enlaza contra esa copia vieja y hace segfault en la primera síntesis
(visto 2026-10-13: exit 139). Cargar aquí la de System32 (14.5x) y onnxruntime deja
el proceso con el runtime correcto. Importar este módulo antes que cualquier PySide6.
"""
import os
import sys

if sys.platform == "win32":
    import ctypes

    _sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for _dll in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
        try:
            ctypes.WinDLL(os.path.join(_sys32, _dll))
        except OSError:
            pass
    # v1: the former onnxruntime/Kokoro import was removed; scripted mode ships
    # no inference stack and nothing here may import one.
