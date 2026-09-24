# ==============================================================================
# TEST DE DERIVA DE CONTRATOS (Contract Drift Test) [DESACTIVADO TEMPORALMENTE]
# ==============================================================================
# Este test verifica la paridad estructural entre jg_agente y jg_agente_sdk.
# Se mantiene comentado para evitar dependencias directas de rutas entre repositorios
# en los pipelines de CI/CD aislados.
#
# Para reactivarlo en el futuro cuando ambos proyectos compartan un pipeline conjunto
# o se consuma el SDK publicado como paquete/submódulo, descomentar este bloque.
# Ver Issue: "Activar test de deriva de contratos (Contract Drift Test)"
# ==============================================================================
#
# from __future__ import annotations
#
# from jg_sdk.contracts import (
#     AgentTool as SDKAgentTool,
#     RiskLevel as SDKRiskLevel,
#     ToolResult as SDKToolResult,
#     ToolType as SDKToolType,
# )
# from jg_sdk.models import (
#     AgentInput as SDKAgentInput,
#     AgentOutput as SDKAgentOutput,
#     ExecutionStatus as SDKExecutionStatus,
#     UserContext as SDKUserContext,
# )
#
# from app.models.io import (
#     AgentInput as CoreAgentInput,
#     AgentOutput as CoreAgentOutput,
#     ExecutionStatus as CoreExecutionStatus,
#     UserContext as CoreUserContext,
# )
# from app.models.tools import (
#     AgentTool as CoreAgentTool,
#     RiskLevel as CoreRiskLevel,
#     ToolResult as CoreToolResult,
#     ToolType as CoreToolType,
# )
#
#
# class TestContractDrift:
#     """Verificación de paridad estricta entre modelos del Core y del SDK."""
#
#     def test_risk_level_enum_parity(self) -> None:
#         """Verifica que todos los niveles de riesgo coincidan exactamente."""
#         core_values = {e.value for e in CoreRiskLevel}
#         sdk_values = {e.value for e in SDKRiskLevel}
#         diff = core_values ^ sdk_values
#         assert not diff, f"Divergencia en valores de RiskLevel entre Core y SDK: {diff}"
#
#     def test_tool_type_enum_parity(self) -> None:
#         """Verifica que todas las tipologías de herramienta coincidan exactamente."""
#         core_values = {e.value for e in CoreToolType}
#         sdk_values = {e.value for e in SDKToolType}
#         diff = core_values ^ sdk_values
#         assert not diff, f"Divergencia en valores de ToolType entre Core y SDK: {diff}"
#
#     def test_execution_status_enum_parity(self) -> None:
#         """Verifica que los estados de ejecución de AgentOutput coincidan."""
#         core_values = {e.value for e in CoreExecutionStatus}
#         sdk_values = {e.value for e in SDKExecutionStatus}
#         diff = core_values ^ sdk_values
#         assert not diff, f"Divergencia en valores de ExecutionStatus entre Core y SDK: {diff}"
#
#     def test_agent_tool_fields_parity(self) -> None:
#         """Verifica que la especificación de AgentTool contenga los mismos campos requeridos."""
#         core_fields = set(CoreAgentTool.model_fields.keys())
#         sdk_fields = set(SDKAgentTool.model_fields.keys())
#         diff = core_fields ^ sdk_fields
#         assert not diff, f"Divergencia en campos de AgentTool entre Core y SDK: {diff}"
#
#     def test_tool_result_fields_parity(self) -> None:
#         """Verifica que el resultado de herramienta ToolResult tenga idéntica estructura."""
#         core_fields = set(CoreToolResult.model_fields.keys())
#         sdk_fields = set(SDKToolResult.model_fields.keys())
#         diff = core_fields ^ sdk_fields
#         assert not diff, f"Divergencia en campos de ToolResult entre Core y SDK: {diff}"
#
#     def test_agent_input_fields_parity(self) -> None:
#         """Verifica que el estímulo canónico AgentInput tenga idénticos campos."""
#         core_fields = set(CoreAgentInput.model_fields.keys())
#         sdk_fields = set(SDKAgentInput.model_fields.keys())
#         diff = core_fields ^ sdk_fields
#         assert not diff, f"Divergencia en campos de AgentInput entre Core y SDK: {diff}"
#
#     def test_agent_output_fields_parity(self) -> None:
#         """Verifica que la salida canónica AgentOutput tenga idénticos campos."""
#         core_fields = set(CoreAgentOutput.model_fields.keys())
#         sdk_fields = set(SDKAgentOutput.model_fields.keys())
#         diff = core_fields ^ sdk_fields
#         assert not diff, f"Divergencia en campos de AgentOutput entre Core y SDK: {diff}"
#
#     def test_user_context_fields_parity(self) -> None:
#         """Verifica que el contexto de usuario UserContext tenga idénticos campos."""
#         core_fields = set(CoreUserContext.model_fields.keys())
#         sdk_fields = set(SDKUserContext.model_fields.keys())
#         diff = core_fields ^ sdk_fields
#         assert not diff, f"Divergencia en campos de UserContext entre Core y SDK: {diff}"
