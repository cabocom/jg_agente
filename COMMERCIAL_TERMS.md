# Términos Comerciales y Modelo de Doble Licenciamiento (Dual Licensing)
## jg_agente (Execution Plane - Core)

**Repositorio oficial:** [https://gitlab.com/javiergalvez-ia/jg_agente](https://gitlab.com/javiergalvez-ia/jg_agente)  
**Titular de los derechos de autor:** Copyright (C) 2026 Javier Gálvez.

---

## 1. Resumen Ejecutivo

El motor cognitivo y plano de ejecución **`jg_agente`** se distribuye bajo un esquema de **Doble Licenciamiento (Dual Licensing)**, permitiendo a individuos y organizaciones elegir el modelo legal que mejor se adapte a su entorno operativo y comercial:

1. **Licencia de Código Abierto (AGPLv3):** Ideal para la comunidad de software libre, investigación, uso académico y organizaciones dispuestas a compartir sus adaptaciones bajo la misma licencia recíproca fuerte ([LICENSE](LICENSE)).
2. **Licencia Comercial Enterprise (200 € / mes cada 3 agentes):** Diseñada para empresas, proveedores de servicios SaaS e integradores que necesitan desplegar, modificar, embeber o prestar servicios con el agente **sin la obligación de revelar su código fuente** ni sus plugins propietarios.

---

## 2. La Licencia de Código Abierto: GNU AGPLv3

Por defecto, el código de `jg_agente` se distribuye bajo los términos de la **GNU Affero General Public License, Version 3.0 (AGPL-3.0)** tal como la publica la Free Software Foundation ([LICENSE](LICENSE)).

### La Cláusula de Interacción por Red (Sección 13 de AGPLv3)
La licencia AGPLv3 incluye una cláusula vinculante de copyleft de red (*Remote Network Interaction*):

> *Si modificas el Programa, tu versión modificada debe ofrecer de manera prominente a todos los usuarios que interactúen con él de forma remota a través de una red informática (...) una oportunidad para recibir el Código Fuente Correspondiente de tu versión.*

#### Implicaciones directas para empresas:
- Si ejecutas `jg_agente` en servidores o infraestructura cloud y proporcionas acceso a empleados, clientes o terceros a través de una red (APIs REST, webhooks, bots de mensajería, telefonía), **estás legalmente obligado a entregar el código fuente completo de tus modificaciones y extensiones a cualquier usuario que interactúe con el servicio**.
- Si desarrollas plugins o motores con lógica de negocio confidencial que se vinculen al runtime del agente, la naturaleza copyleft de AGPLv3 puede exigir su liberación como software libre si se opera en red.

---

## 3. Licencia Comercial Enterprise

Para organizaciones que no pueden o no desean someterse a las obligaciones copyleft de la AGPLv3, ofrecemos una **Licencia Comercial Empresarial directa del autor original**.

### 3.1 Esquema de Tarifas
- **Cuota de Suscripción Base:** **200 € / mes** (+ IVA aplicable) **por cada bloque de hasta 3 agentes**.
- **Sin rappel por volumen:** La tarificación es estrictamente lineal y acumulativa por número de agentes aprovisionados:
  - De 1 a 3 agentes: **200 € / mes**
  - De 4 a 6 agentes: **400 € / mes**
  - De 7 a 9 agentes: **600 € / mes**
  - *(Sin descuentos por tramos ni rappel).*
- **Periodicidad:** Facturación mensual o anual recurrente.
- **Despliegues de Gran Volumen:** Si tu organización requiere un volumen superior de agentes o una licencia corporativa global (*unlimited instances* / OEM), contacta directamente a través de **[https://javiergalvez.com](https://javiergalvez.com)**.

### 3.2 Derechos y Ventajas Otorgados
Al suscribir la Licencia Comercial Enterprise, tu organización adquiere:

1. **Exención Total de AGPLv3:** Exención completa y explícita de los requisitos de la Sección 13 de AGPLv3. No estás obligado a publicar ni compartir tu código fuente, configuraciones ni adaptaciones.
2. **Protección de Propiedad Intelectual en Plugins:** Puedes crear, utilizar y distribuir plugins y herramientas propietarias cerradas sin temor a contaminación copyleft.
3. **Explotación Comercial y SaaS:** Derecho a comercializar servicios basados en `jg_agente` o sublicenciar soluciones a clientes finales como parte de tu catálogo de productos.
4. **Marca Blanca y Personalización:** Permiso para eliminar o personalizar los avisos de atribución pública y adaptar el agente a la identidad corporativa.
5. **Garantía y Ausencia de Conflicto de Licencias:** Garantía formal de indemnidad sobre la titularidad del software y el cese de responsabilidades derivadas de la licencia GPL.
6. **Soporte Prioritario:** Acceso a parches de seguridad prioritarios, soporte técnico N2/N3 y canal directo de consultoría de arquitectura.

---

## 4. Matriz Comparativa: AGPLv3 vs. Comercial Enterprise

| Característica / Obligación | Licencia Comunitaria (AGPLv3) | Licencia Comercial Enterprise |
| :--- | :---: | :---: |
| **Coste de Licencia** | Gratuito (0 €) | **200 € / mes (cada 3 agentes)** |
| **Escalado de tarifa** | N/A | **Lineal (sin rappel)** |
| **Acceso al código fuente completo** | Sí | Sí |
| **Uso para pruebas / investigación local** | Sí | Sí |
| **Obligación de liberar código fuente al operar en red (SaaS/API)** | **SÍ (Obligatorio por Sec. 13)** | **NO (Exento)** |
| **Permite plugins y motores con código cerrado/secreto industrial** | No (Contaminación copyleft) | **SÍ (100% Propietarios)** |
| **Uso en producción comercial sin compartir código** | No permitido | **Permitido** |
| **Marca blanca (White-labeling)** | No permitido | **Permitido** |
| **SLA y Soporte Técnico de Plataforma** | Vía comunidad / Best effort | **Soporte Prioritario N2/N3** |
| **Certificado de titularidad y compliance legal** | No | **Sí (Acuerdo Legal Firmado)** |

---

## 5. Preguntas Frecuentes (FAQ)

#### ¿Puedo usar jg_agente internamente en mi empresa sin pagar?
Si tu empresa utiliza el software de forma estrictamente privada y nadie fuera de la entidad jurídica interactúa con él, la ejecución interna es libre. Sin embargo, en el momento en que clientes, contratistas o usuarios externos interactúen con el agente por red (APIs, webhooks, bots), se activa la obligación de la Sección 13 de AGPLv3. Por seguridad jurídica, los departamentos de *Compliance* corporativo requieren la Licencia Comercial.

#### ¿Cómo se calcula la cuota si tengo 4 agentes?
Cada bloque cubre hasta 3 agentes sin rappel. Para 4 agentes se requieren 2 bloques (hasta 6 agentes), resultando en una tarifa de 400 € / mes.

#### ¿Cómo se cancela la suscripción comercial?
La suscripción mensual puede cancelarse en cualquier momento con un preaviso de 30 días. Tras la cancelación, la empresa deberá cesar la explotación comercial privada o acogerse estrictamente a los términos de la AGPLv3 compartiendo el código de sus versiones modificadas.

---

## 6. Contacto y Contratación

Para formalizar el contrato de **Licencia Comercial Enterprise**, solicitar facturación proforma o consultar esquemas de mayor volumen:

- **Sitio Web Oficial:** **[https://javiergalvez.com](https://javiergalvez.com)**

