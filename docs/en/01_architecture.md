# 01. Cognitive Runtime Architecture (`jg_agente`)

[← Back to README](../README.md) | [02. Cognitive Graph →](02_cognitive_graph.md) | [07. Operational Modes](07_operational_modes.md)

---

## 1. System Overview

`jg_agente` is the autonomous execution plane (**Execution Plane**) of the jG ecosystem. It is engineered as a private, asynchronous, decoupled microservice built upon [FastAPI](https://fastapi.tiangolo.com/) and [LangGraph](https://github.com/langchain-ai/langgraph), designed to run within isolated networks (air-gapped environments, private VPCs, or Zero-Trust enclaves) without public Internet exposure.

The engine ingests normalized stimuli via the `AgentInput` contract and delivers audited, structured outputs via `AgentOutput`.

```text
┌────────────────────────────────────────────────────────────────────────┐
│               EXTERNAL INVOCATORS / CONTROL PLANE / GATEWAYS           │
│        Telegram Bots · WhatsApp Webhooks · API Gateways · Dashboards   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HMAC-SHA256 Signatures (Private Net)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      EXECUTION PLANE (jg_agente)                       │
│                                                                        │
│  ┌─────────────────────────┐            ┌───────────────────────────┐  │
│  │   FastAPI Private Core  │            │    CapabilityRegistry     │  │
│  │  /trigger  /health  HITL│            │ (Tools, Engines, Schemas) │  │
│  └────────────┬────────────┘            └─────────────▲─────────────┘  │
│               │ Invocation                            │ Registers     │
│               ▼                                       │ Capabilities  │
│  ┌─────────────────────────┐            ┌─────────────┴─────────────┐  │
│  │    LangGraph Engine     │            │      Ecosystem Plugins    │  │
│  │  (observe -> plan ->    │            │     (Packaged via SDK)    │  │
│  │   execute -> evaluate)  │            └───────────────────────────┘  │
│  └────────────┬────────────┘                                           │
│               │                                                        │
│               ▼                                                        │
│  ┌─────────────────────────┐            ┌───────────────────────────┐  │
│  │      SecurityGuard      │◄──────────►│    DualPostgresSaver      │  │
│  │ (SSRF, RBAC, Timeouts)  │            │   (PostgreSQL Core Views) │  │
│  └─────────────────────────┘            └───────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

## 2. Core Components

1. **FastAPI Private Core (`app/main.py`, `app/api/`):**
   - Exposes private REST endpoints (`/executions/trigger`, `/executions/{thread_id}`, `/executions/{thread_id}/approve`, `/executions/{thread_id}/reject`, `/health`, `/metrics`, `/capabilities`).
   - Validates caller identity and cryptographic HMAC-SHA256 request signatures via `verify_control_plane_auth`.

2. **CapabilityRegistry (`app/core/registry.py`):**
   - In-memory registry indexing tools (`AgentTool`), engines (`ObserverEngine`, `PlannerEngine`, `VerifierEngine`), and plugin schemas.
   - Enforces strict collision prevention (`BootConflictError`) at boot time.

3. **LangGraph StateGraph (`app/core/graph.py`):**
   - Dynamic orchestrator of the reasoning and execution cycle.
   - Compiles graph topology dynamically based on registered capabilities.

4. **SecurityGuard (`app/security/guard.py`):**
   - Preventive security interceptor executing prior to any tool invocation.
   - Sanitizes arguments against shell injection, directory traversal, and enforces TCP-level SSRF / DNS pinning.
   - Enforces Human-in-the-Loop (HITL) authorization for `HIGH` or `CRITICAL` risk operations.

5. **Prompt Subsystem & i18n (`app/prompts/`):**
   - Externalized text templates under `app/prompts/templates/{es,en,fr,de,it}/`.
   - `PromptManager` provides dynamic language resolution:
     $$\text{Effective Locale} = \text{request.locale} \;\lor\; \text{plugin.default\_locale} \;\lor\; \text{settings.DEFAULT\_LOCALE} \;\lor\; \text{"es"}$$
