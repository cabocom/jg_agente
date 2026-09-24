#!/usr/bin/env python3
"""Script de compilación nativa Cython para jg_agente.

Convierte los módulos de lógica de negocio (.py) en bibliotecas dinámicas C nativas (.so)
y elimina los archivos de código fuente originales para proteger la propiedad intelectual.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from setuptools import setup
from Cython.Build import cythonize


def compile_modules(target_dirs: list[Path]) -> None:
    py_files: list[str] = []

    for base in target_dirs:
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            # Preservar __init__.py como archivos Python para garantizar el descubrimiento de paquetes
            if p.name == "__init__.py":
                continue
            py_files.append(str(p))

    if not py_files:
        print("ℹ️  No se encontraron archivos .py elegibles para compilación Cython.")
        return

    print(f"🔒 Compilando {len(py_files)} módulos Python con Cython a código máquina C (.so)...")

    # Compilar en el mismo lugar (--inplace)
    ext_modules = cythonize(
        py_files,
        compiler_directives={
            "language_level": "3",
            "always_allow_keywords": True,
        },
        nthreads=os.cpu_count() or 2,
        quiet=True,
    )

    setup(
        ext_modules=ext_modules,
        script_args=["build_ext", "--inplace"],
    )

    # Eliminar código fuente .py y archivos temporales .c
    compiled_count = 0
    for f in py_files:
        py_path = Path(f)
        c_path = py_path.with_suffix(".c")
        if c_path.exists():
            c_path.unlink()

        so_matches = list(py_path.parent.glob(f"{py_path.stem}.*.so")) + list(
            py_path.parent.glob(f"{py_path.stem}.so")
        )
        if so_matches:
            py_path.unlink()
            compiled_count += 1
            print(f"  ✓ Binario nativo generado: {py_path.name} -> {so_matches[0].name}")
        else:
            print(f"  ⚠️  Advertencia: No se generó .so para {py_path.name}, conservando .py")

    print(f"\n✅ Compilación Cython completada: {compiled_count} módulos convertidos a binarios .so.")


if __name__ == "__main__":
    dirs = [Path(arg) for arg in sys.argv[1:] if Path(arg).exists()]
    if not dirs:
        dirs = [Path("app"), Path("plugins")]
    compile_modules(dirs)
