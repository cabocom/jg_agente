# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

# ==============================================================================
# TEST DE DERIVA DE CONTRATOS (Contract Drift Test)
# ==============================================================================
# Este test verifica la paridad estructural estricta entre el Core (jg_agente)
# y el kit canónico público (jg_agente_sdk).
#
# Si jg_sdk está instalado (vía PyPI Package Registry o clonado en CI/local),
# ejecuta las aserciones de paridad sobre todos los modelos y enums.
# Si no está disponible en el entorno mínimo, se omite de forma segura.
# ==============================================================================

from __future__ import annotations

import pytest

try:
    from jg_sdk.contracts import (
        AgentTool as SDKAgentTool,
    )
    from jg_sdk.contracts import (
        ExecutionStatus as SDKExecutionStatus,
    )
    from jg_sdk.contracts import (
        RiskLevel as SDKRiskLevel,
    )
    from jg_sdk.contracts import (
        ToolResult as SDKToolResult,
    )
    from jg_sdk.contracts import (
        ToolType as SDKToolType,
    )
    from jg_sdk.models import (
        AgentInput as SDKAgentInput,
    )
    from jg_sdk.models import (
        AgentOutput as SDKAgentOutput,
    )
    from jg_sdk.models import (
        UserContext as SDKUserContext,
    )

    HAS_JG_SDK = True
except ImportError:
    HAS_JG_SDK = False

from app.models.io import (
    AgentInput as CoreAgentInput,
)
from app.models.io import (
    AgentOutput as CoreAgentOutput,
)
from app.models.io import (
    ExecutionStatus as CoreExecutionStatus,
)
from app.models.io import (
    UserContext as CoreUserContext,
)
from app.models.tools import (
    AgentTool as CoreAgentTool,
)
from app.models.tools import (
    RiskLevel as CoreRiskLevel,
)
from app.models.tools import (
    ToolResult as CoreToolResult,
)
from app.models.tools import (
    ToolType as CoreToolType,
)


@pytest.mark.skipif(
    not HAS_JG_SDK,
    reason="jg_agente_sdk no está instalado en este entorno. Instalar jg-agente-sdk desde el registry para validar la paridad de contratos.",
)
class TestContractDrift:
    """Verificación de paridad estricta entre modelos del Core y del SDK."""

    def test_risk_level_enum_parity(self) -> None:
        """Verifica que todos los niveles de riesgo coincidan exactamente."""
        core_values = {e.value for e in CoreRiskLevel}
        sdk_values = {e.value for e in SDKRiskLevel}
        diff = core_values ^ sdk_values
        assert not diff, f"Divergencia en valores de RiskLevel entre Core y SDK: {diff}"

    def test_tool_type_enum_parity(self) -> None:
        """Verifica que todas las tipologías de herramienta coincidan exactamente."""
        core_values = {e.value for e in CoreToolType}
        sdk_values = {e.value for e in SDKToolType}
        diff = core_values ^ sdk_values
        assert not diff, f"Divergencia en valores de ToolType entre Core y SDK: {diff}"

    def test_execution_status_enum_parity(self) -> None:
        """Verifica que los estados de ejecución de AgentOutput coincidan."""
        core_values = {e.value for e in CoreExecutionStatus}
        sdk_values = {e.value for e in SDKExecutionStatus}
        diff = core_values ^ sdk_values
        assert not diff, f"Divergencia en valores de ExecutionStatus entre Core y SDK: {diff}"

    def test_agent_tool_fields_parity(self) -> None:
        """Verifica que la especificación de AgentTool contenga los mismos campos requeridos."""
        core_fields = set(CoreAgentTool.model_fields.keys())
        sdk_fields = set(SDKAgentTool.model_fields.keys())
        diff = core_fields ^ sdk_fields
        assert not diff, f"Divergencia en campos de AgentTool entre Core y SDK: {diff}"

    def test_tool_result_fields_parity(self) -> None:
        """Verifica que el resultado de herramienta ToolResult tenga idéntica estructura."""
        core_fields = set(CoreToolResult.model_fields.keys())
        sdk_fields = set(SDKToolResult.model_fields.keys())
        diff = core_fields ^ sdk_fields
        assert not diff, f"Divergencia en campos de ToolResult entre Core y SDK: {diff}"

    def test_agent_input_fields_parity(self) -> None:
        """Verifica que el estímulo canónico AgentInput tenga idénticos campos."""
        core_fields = set(CoreAgentInput.model_fields.keys())
        sdk_fields = set(SDKAgentInput.model_fields.keys())
        diff = core_fields ^ sdk_fields
        assert not diff, f"Divergencia en campos de AgentInput entre Core y SDK: {diff}"

    def test_agent_output_fields_parity(self) -> None:
        """Verifica que la salida canónica AgentOutput tenga idénticos campos."""
        core_fields = set(CoreAgentOutput.model_fields.keys())
        sdk_fields = set(SDKAgentOutput.model_fields.keys())
        diff = core_fields ^ sdk_fields
        assert not diff, f"Divergencia en campos de AgentOutput entre Core y SDK: {diff}"

    def test_user_context_fields_parity(self) -> None:
        """Verifica que el contexto de usuario UserContext tenga idénticos campos."""
        core_fields = set(CoreUserContext.model_fields.keys())
        sdk_fields = set(SDKUserContext.model_fields.keys())
        diff = core_fields ^ sdk_fields
        assert not diff, f"Divergencia en campos de UserContext entre Core y SDK: {diff}"
