#!/usr/bin/env python3
# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Script de compilación nativa Cython para jg_agente.

Convierte los módulos de lógica de negocio (.py) en bibliotecas dinámicas C nativas (.so)
y elimina los archivos de código fuente originales para proteger la propiedad intelectual.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from Cython.Build import cythonize
from setuptools import setup


def compile_package(pkg_dir: Path, base_dir: Path) -> int:
    py_files = [
        str(p.relative_to(base_dir))
        for p in pkg_dir.rglob("*.py")
        if p.name != "__init__.py" and "tests" not in p.parts and not p.name.startswith("test_")
    ]
    if not py_files:
        return 0

    print(f"🔒 Compilando {len(py_files)} módulos en {pkg_dir.name} (base: {base_dir})...")

    cur_dir = os.getcwd()
    os.chdir(base_dir)
    compiled_count = 0
    try:
        exts = cythonize(
            py_files,
            compiler_directives={"language_level": "3", "always_allow_keywords": True},
            nthreads=os.cpu_count() or 2,
            quiet=True,
        )
        setup(ext_modules=exts, script_args=["build_ext", "--inplace"])

        for rel_f in py_files:
            p = base_dir / rel_f
            c_p = p.with_suffix(".c")
            if c_p.exists():
                c_p.unlink()
            sos = list(p.parent.glob(f"{p.stem}.*.so")) + list(p.parent.glob(f"{p.stem}.so"))
            if sos:
                p.unlink()
                compiled_count += 1
                print(f"  ✓ {p.name} -> {sos[0].name}")
            else:
                print(f"  ⚠️  Advertencia: No se generó .so para {p.name}")
    finally:
        os.chdir(cur_dir)

    return compiled_count


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    app_dir = root / "app"
    plugins_dir = root / "plugins"

    total = 0
    # 1. Compilar app troncal (base_dir es root)
    if app_dir.exists():
        total += compile_package(app_dir, root)

    # 2. Compilar cada plugin individualmente (base_dir es plugins_dir)
    if plugins_dir.exists():
        for plg in plugins_dir.iterdir():
            if plg.is_dir() and (plg / "__init__.py").exists():
                total += compile_package(plg, plugins_dir)

    print(f"\n✅ Compilación Cython completada exitosamente: {total} módulos protegidos en .so.")


if __name__ == "__main__":
    main()
