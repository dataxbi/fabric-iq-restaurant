# Data Agent — Restaurante Autogestionado

Este agente proporciona inteligencia operacional en tiempo real sobre el restaurante a partir de los eventos almacenados en el Eventhouse de Microsoft Fabric. Actúa como capa de consulta sobre el historial de eventos procesados y el estado operativo derivado.

## Capacidades

- **Estado de pedidos activos**: identifica qué pedidos están en curso, cuáles superan umbrales de demora y cuáles presentan riesgo de incumplir su SLA, filtrado por canal, estación o severidad.

- **Presión de estaciones de cocina**: reporta el estado actual de cada estación (grill, fryer, sauces, assembly), incluyendo tamaño de cola, capacidad, porcentaje de carga y tiempo estimado de drenaje.

- **Inventario crítico**: detecta ingredientes por debajo de su umbral de stock definido.

- **Trazabilidad de decisiones**: recorre la cadena completa recomendación del agente de operaciones → aprobación humana → acción ejecutada, permitiendo auditar qué se decidió, quién aprobó y qué pasó.

- **Recomendaciones pendientes**: lista las recomendaciones del agente de operaciones que todavía no han recibido aprobación ni rechazo.

- **Throughput de cocina**: cuántas órdenes se completaron en un periodo dado, desglosadas por estación y ventana temporal.

## Fuentes de datos

Base de datos KQL `restaurant_rti` en el Eventhouse de Microsoft Fabric. Tablas disponibles:

| Tabla | Contenido |
|---|---|
| `order_events` | Eventos de pedido: creación, retraso, finalización de pago |
| `kitchen_events` | Estado de estaciones de cocina: cola, capacidad, saturación |
| `inventory_events` | Niveles de stock de ingredientes |
| `agent_events` | Recomendaciones emitidas por el agente de operaciones |
| `approval_events` | Aprobaciones o rechazos de recomendaciones |
| `action_events` | Acciones ejecutadas tras aprobación |
| `stations` | Tabla de referencia de estaciones (id, nombre, especialización, capacidad) |

## Limitaciones

- Solo accede a datos ya ingeridos en el Eventhouse; no consulta fuentes externas.
- No puede ejecutar acciones, enviar aprobaciones ni modificar el estado operativo del restaurante.
- La ventana temporal de los datos depende de la política de retención configurada en cada tabla.
