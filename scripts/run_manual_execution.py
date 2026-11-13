#!/usr/bin/env python3
# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Script interactivo de ejecución manual del ciclo cognitivo de jg_agente.

Permite observar en tiempo real el paso del agente por todos los nodos del grafo:
OBSERVE -> REASON -> PLAN -> RISK_ASSESS -> HUMAN_APPROVAL [HITL] -> EXECUTE -> VERIFY -> ROLLBACK -> CONCLUDE

Soporta ejecución simulada (MockChatModel sin API keys) o con LLMs reales (Groq, Gemini, OpenAI).
"""

import asyncio
import os
import sys
from datetime import datetime

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.core.config import Settings
from app.core.graph import GraphBuilder
from app.core.llm import get_chat_model
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    StepStatus,
)
from app.models.tools import AgentTool, RiskLevel

try:
    from scripts.demo_fixtures import (
        C_BOLD,
        C_CYAN,
        C_DIM,
        C_GREEN,
        C_RED,
        C_RESET,
        C_YELLOW,
        DemoObserver,
        DemoPlanner,
        DemoVerifier,
        func_consultar_metricas,
        func_reiniciar_nodo,
        print_banner,
        rollback_reiniciar_nodo,
    )
except ImportError:
    from demo_fixtures import (  # type: ignore[no-redef]
        C_BOLD,
        C_CYAN,
        C_DIM,
        C_GREEN,
        C_RED,
        C_RESET,
        C_YELLOW,
        DemoObserver,
        DemoPlanner,
        DemoVerifier,
        func_consultar_metricas,
        func_reiniciar_nodo,
        print_banner,
        rollback_reiniciar_nodo,
    )


# ==========================================================
# Lógica Principal del Runner Manual
# ==========================================================


async def main() -> None:
    print_banner()

    # 1. Configuración del Proveedor LLM
    print(f"{C_BOLD}1. Selección de Proveedor LLM:{C_RESET}")
    print("   [1] Mock LLM (Simulado - No requiere API Key, determinista y rápido)")
    print("   [2] Groq (llama-3.3-70b-versatile - Ultrarrápido)")
    print("   [3] Google Gemini (gemini-2.0-flash / gemini-1.5-flash)")
    print("   [4] OpenAI / Custom OpenAI-compatible")

    choice = input(f"\n{C_CYAN}Selecciona opción [1-4] (default: 1): {C_RESET}").strip() or "1"

    provider = "mock"
    model_name = "mock-agent-model"
    api_key: str | None = None

    if choice == "2":
        provider = "groq"
        model_name = "llama-3.3-70b-versatile"
        api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            api_key = input(f"{C_YELLOW}Introduce tu GROQ_API_KEY: {C_RESET}").strip()
    elif choice == "3":
        provider = "gemini"
        model_name = "gemini-2.0-flash"
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            api_key = input(f"{C_YELLOW}Introduce tu GEMINI_API_KEY: {C_RESET}").strip()
    elif choice == "4":
        provider = "openai"
        model_name = input("Nombre del modelo (ej: gpt-4o): ").strip() or "gpt-4o"
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            api_key = input(f"{C_YELLOW}Introduce tu OPENAI_API_KEY: {C_RESET}").strip()

    # 2. Configurar simulación de fallo en verificación (para probar Rollback)
    print(f"\n{C_BOLD}2. Escenario de Verificación Post-Ejecución:{C_RESET}")
    print("   [1] Verificación Exitosa (Flujo normal -> Conclude con éxito)")
    print("   [2] Simular Fallo de Verificación (Activa el nodo ROLLBACK automático)")
    verify_choice = (
        input(f"\n{C_CYAN}Selecciona escenario [1-2] (default: 1): {C_RESET}").strip() or "1"
    )
    simulate_failure = verify_choice == "2"

    # 3. Construir CapabilityRegistry con motores y herramientas
    registry = CapabilityRegistry()
    registry.register_engine(DemoObserver())
    registry.register_engine(DemoPlanner())
    registry.register_engine(DemoVerifier(simulate_failure=simulate_failure))

    t1 = AgentTool(
        name="consultar_metricas_nodo",
        description="Lee métricas y salud del nodo de infraestructura",
        category="infra",
        func=func_consultar_metricas,
        risk_level=RiskLevel.LOW,
        reversible=False,
    )
    t2 = AgentTool(
        name="reiniciar_nodo_produccion",
        description="Reinicia un worker node de k8s en producción",
        category="infra",
        func=func_reiniciar_nodo,
        rollback_func=rollback_reiniciar_nodo,
        risk_level=RiskLevel.HIGH,
        reversible=True,
    )
    registry.register_tool(t1)
    registry.register_tool(t2)

    # 4. Inicializar LLM y GraphBuilder
    custom_settings = Settings(
        LLM_PROVIDER=provider,
        LLM_MODEL=model_name,
        LLM_API_KEY=api_key,
    )
    llm = get_chat_model(app_settings=custom_settings)

    builder = GraphBuilder(registry=registry, llm=llm)
    checkpointer = MemorySaver()
    graph = builder.build(checkpointer=checkpointer)

    topo = builder.get_topology()
    print(f"\n{C_GREEN}✔ Grafo compilado exitosamente con topología:{C_RESET}")
    print(f"   Nodos: {C_BOLD}{' ➔ '.join(topo.nodes)}{C_RESET}\n")

    # 5. Iniciar ejecución
    thread_id = f"manual-exec-{int(datetime.now().timestamp())}"
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    prompt = "Optimizar clúster y reiniciar nodo worker-03 que presenta alta carga"
    initial_state: AgentState = {
        "request": AgentInput(
            execution_id=f"exec-{thread_id}",
            thread_id=thread_id,
            prompt=prompt,
        ),
        "messages": [HumanMessage(content=prompt)],
        "status": AgentExecutionStatus.IDLE,
        "audit_trail": [],
    }

    print(f"{C_BOLD}🚀 Disparando ejecución en hilo '{thread_id}'...{C_RESET}")
    print(f'   Prompt: "{prompt}"\n')

    # 6. Primera fase: ejecutar hasta encontrar posible interrupción HITL
    result = await graph.ainvoke(initial_state, config=config)

    # Verificar si el grafo pausó por HITL
    if "__interrupt__" in result:
        interrupts = result["__interrupt__"]
        payload = interrupts[0].value if interrupts else {}

        print(f"\n{C_YELLOW}{C_BOLD}{'!' * 60}{C_RESET}")
        print(
            f"{C_YELLOW}{C_BOLD} 🛑 [HUMAN-IN-THE-LOOP] INTERRUPCIÓN DE SEGURIDAD DETECTADA{C_RESET}"
        )
        print(f"{C_YELLOW}{C_BOLD}{'!' * 60}{C_RESET}")
        print(f"   Acción requerida: {C_BOLD}{payload.get('action')}{C_RESET}")
        print(f"   Mensaje: {payload.get('message')}")

        plan = payload.get("plan") or {}
        steps = plan.get("steps") if isinstance(plan, dict) else getattr(plan, "steps", [])
        if steps:
            print(f"\n   {C_BOLD}Pasos formulados para autorización:{C_RESET}")
            for s in steps:
                s_name = s.get("tool_name") if isinstance(s, dict) else getattr(s, "tool_name", "")
                s_risk = (
                    s.get("risk_level") if isinstance(s, dict) else getattr(s, "risk_level", "")
                )
                print(f"     • [{s_risk}] {s_name}")

        print(
            f"\n   {C_DIM}El grafo está actualmente pausado y persistido en el checkpointer.{C_RESET}"
        )
        dec = (
            input(
                f"\n{C_BOLD}¿Autorizas la ejecución de la acción de alto riesgo? ([S]í / [N]o): {C_RESET}"
            )
            .strip()
            .lower()
        )

        is_approved = dec in ("s", "si", "y", "yes")
        approver = os.environ.get("USER", "operador_humano")

        resume_payload = {
            "approved": is_approved,
            "approver": approver,
            "notes": "Autorizado en terminal interactiva"
            if is_approved
            else "Rechazado por operador",
        }

        print(
            f"\n{C_CYAN}🔄 Enviando comando de reanudación: Command(resume={resume_payload})...{C_RESET}\n"
        )
        result = await graph.ainvoke(Command(resume=resume_payload), config=config)

    # 7. Resumen de Ejecución Final
    print(f"\n{C_GREEN}{C_BOLD}{'=' * 70}{C_RESET}")
    print(f"{C_GREEN}{C_BOLD}   🏁 RESULTADO FINAL DE LA EJECUCIÓN{C_RESET}")
    print(f"{C_GREEN}{C_BOLD}{'=' * 70}{C_RESET}\n")

    final_status = result.get("status")
    status_color = C_GREEN if final_status == AgentExecutionStatus.RESOLVED else C_RED
    print(f"• {C_BOLD}Estado Final:{C_RESET} {status_color}{final_status}{C_RESET}")

    exec_records = result.get("execution_records", [])
    print(f"• {C_BOLD}Herramientas Ejecutadas ({len(exec_records)}):{C_RESET}")
    for r in exec_records:
        r_name = getattr(r, "tool_name", "")
        r_st = getattr(r, "status", "")
        st_color = C_GREEN if r_st == StepStatus.COMPLETED else C_RED
        print(f"   - {r_name} ➔ {st_color}{r_st}{C_RESET}")

    v_results = result.get("verification_results", [])
    if v_results:
        v_st = v_results[0].get("status")
        v_col = C_GREEN if v_st == "pass" else C_RED
        print(f"• {C_BOLD}Verificación Post-Ejecución:{C_RESET} {v_col}{v_st.upper()}{C_RESET}")
        print(f"   Detalles: {v_results[0].get('details')}")

    rollbacks = result.get("rollback_records", [])
    if rollbacks:
        print(
            f"\n• {C_YELLOW}{C_BOLD}Compensaciones de Rollback Ejecutadas ({len(rollbacks)}):{C_RESET}"
        )
        for rb in rollbacks:
            rb_name = rb.get("tool_name")
            rb_ok = rb.get("success")
            rb_col = C_GREEN if rb_ok else C_RED
            print(
                f"   - {rb_name} ➔ {rb_col}{'ÉXITO' if rb_ok else 'FALLO'}{C_RESET} ({rb.get('output')})"
            )

    output = result.get("output")
    if output:
        print(f"\n• {C_BOLD}Respuesta Final para el Usuario:{C_RESET}")
        print(f'   "{output.response}"')

    audits = result.get("audit_trail", [])
    print(
        f"\n• {C_BOLD}Trazas de Auditoría Inmutables:{C_RESET} {len(audits)} eventos registrados."
    )
    for a in audits:
        print(f"   [{a.event_type}] por {a.actor}")

    print(f"\n{C_CYAN}{'=' * 70}{C_RESET}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{C_RED}Ejecución interrumpida por el usuario.{C_RESET}")
        sys.exit(0)
