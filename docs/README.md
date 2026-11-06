# Documentación Técnica — `jg_agente`

Execution Plane (Motor Autónomo de Ejecución Cognitiva) del ecosistema `javiergalvez-ia`.

---

## 🌐 Estructura Multilingüe

La documentación técnica del runtime está organizada por directorios de idioma (ISO 639-1):

- 🇪🇸 **[Español (Fuente Canónica / SSOT)](es/)**:
  - [01. Arquitectura del Runtime](es/01_architecture.md) — Topología de red, componentes core y aislamiento.
  - [02. Grafo Cognitivo y Máquina de Estados](es/02_cognitive_graph.md) — Flujo reflexivo de 10 nodos y guardarraíles.
  - [03. Seguridad, Aislamiento de Red y Sandboxing](es/03_security_sandboxing.md) — SecurityGuard, anti-SSRF y DNS Pinning.
  - [04. Persistencia, Estado y Checkpointing](es/04_persistence_state.md) — DualPostgresSaver, esquema relacional y modo degradado.
  - [05. Ciclo de Vida y Ecosistema de Plugins](es/05_plugin_lifecycle.md) — Descubrimiento dinámico y gestión de dependencias.
  - [06. Referencia de API REST Privada](es/06_api_reference.md) — Especificación de endpoints, esquemas I/O y códigos HTTP.
  - [07. Modos de Funcionamiento, Topologías y Registro](es/07_operational_modes.md) — Standalone (Telegram/WhatsApp), Clúster con Dashboard y registro Zero-Trust.

- 🇬🇧 **[English (International Reference)](en/)**:
  - [01. Runtime Architecture](en/01_architecture.md) — Network topology, core components, and isolation.
  - *Chapters 02 to 07 are compiled with canonical fallback to Spanish.*

---

## Compilación Unificada

Para compilar la documentación consolidada de `jg_agente` para IAs externas y desarrolladores:
```bash
# Compilar versión canónica (español)
./workspace.sh docs jg_agente --locale=es

# Compilar versión en inglés
./workspace.sh docs jg_agente --locale=en

# Compilar todos los idiomas
./workspace.sh docs jg_agente --locale=all
```
