# Análisis Técnico: ISSUE-F04-T03 — Implementación de PluginManager con autodiscovery

> **Issue ID:** ISSUE-F04-T03  
> **Fase:** FASE 04 (CapabilityRegistry y Sistema de Plugins Core)  
> **Prioridad:** High  
> **Complejidad:** M  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

Para que `jg_agente` sea extensible en entornos locales de desarrollo y en producción contenerizada sin acoplamientos rígidos, se requiere un orquestador que descubra automáticamente los plugins disponibles y coordine su ciclo de vida respetando dependencias.

El objetivo de este issue es:
1. Desarrollar `PluginManager` en `app/core/plugin_manager.py`.
2. Implementar descubrimiento distribuido mediante `importlib.metadata.entry_points(group="jg_agente.plugins")`.
3. Implementar descubrimiento local mediante `pkgutil.iter_modules()` reconociendo la convención `PLUGIN_CLASS` o subclases directas de `BasePlugin`.
4. Validar las dependencias declaradas en `PluginMetadata.dependencies`, detectando dependencias ausentes (`PluginDependencyError`) y previniendo dependencias circulares mediante ordenamiento topológico (algoritmo de Kahn).
5. Integrar el registro automático en `CapabilityRegistry`.
6. Gestionar el ciclo de vida asíncrono ordenado: `startup()` en orden de dependencias y `shutdown()` en orden inverso.
7. Proveer agregación de salud en `health_check()`.

---

## 2. Reutilización y Adaptación (Código Origen)

- En `jg-ai-gateway/app/core/plugin_manager.py`, se utilizaba `pkgutil.iter_modules()` acoplado a subcarpetas fijas `interfaces/` y `tools/`, sin soporte de entry points ni ordenamiento por dependencias.
- En `jg_agente`, se unificó la arquitectura con:
  - Soporte dual (modo local + paquetes distribuidos vía entry points estándar de Python).
  - Verificación tipada de herencia de `BasePlugin`.
  - Resolución topológica formal de dependencias.
  - Integración directa con `CapabilityRegistry`.

---

## 3. Decisiones de Diseño

1. **Resolución Topológica y Ciclos:**
   - Si el plugin B depende de A, A se inicializa antes que B.
   - En caso de grafo cíclico o dependencias no instaladas, se lanza `PluginDependencyError` de manera preventiva en tiempo de carga antes de cualquier invocación a `startup()`.
2. **Apagado en Orden Inverso:**
   - Durante `shutdown()`, los plugins consumidores se apagan antes que los servicios de los que dependen (e.g. B se apaga antes que A), evitando errores de conexión durante el cese del servicio.
3. **Aislamiento en Descubrimiento Local:**
   - El escaneo local inyecta dinámicamente el directorio objetivo en `sys.path` para permitir resoluciones de importación limpias y reproducibles en tests y producción.

---

## 4. Criterios de Aceptación Verificados

- [x] `PluginManager` localiza e inicializa plugins presentes en el entorno registrando sus capacidades en `CapabilityRegistry`.
- [x] Autodescubrimiento probado tanto vía `entry_points` como en directorios locales.
- [x] Detección estricta de dependencias ausentes y circulares.
- [x] Orden de ejecución garantizado en `startup()` y `shutdown()`.
- [x] 116 tests pasando con éxito (100% verde en Ruff, MyPy estricto y Pytest).
