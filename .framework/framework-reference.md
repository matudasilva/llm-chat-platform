# Referencia del Framework

## Framework

- Nombre: AI Together Framework V2
- Repositorio del framework:
- Versión del framework:

## Política del proyecto

- Visibilidad del repositorio:
- Política de artefactos del framework:
- Ubicación de memoria operativa:
- Idioma narrativo de la ORQ (`orq_language`):
- Herramientas locales habilitadas:

## Contrato versionado

Listar solo los artefactos del framework que este proyecto versiona de forma intencional.

- `.framework/context.md`
- `.framework/framework-reference.md`
- `.framework/project-config.yml`
- `.framework/framework-version`

## Límite de fuente pública

Documentar el límite entre el código y la documentación del producto, y los artefactos internos de orquestación del framework.

## Notas

La visibilidad del repositorio no define la política de artefactos del framework.

Una fuente externa de contexto puede alojar contexto humano, roadmap y reporting gobernado, pero no reemplaza las herramientas locales ejecutables ni implica creación de ORQs en esa fuente por defecto.
La narrativa de la ORQ es configurable por proyecto u operador y debe resolverse al crear la ORQ a través de `orq_language` cuando esté disponible.
`learning_sync` y `dashboard_sync` son contratos distintos: uno registra aprendizaje reusable y el otro registra observabilidad operativa del ORQ Dashboard.
`fw-close` realiza `Local Closure`; `fw-governance-sync` ejecuta el update real de governance cuando corresponde y solo de manera explícita.
Si el sync externo ya está confirmado, `fw-governance-sync` debe limitarse a la alineación local del cierre, preservar la evidencia original y no repetir discovery ni escrituras externas salvo solicitud explícita de un nuevo sync.
`fw-framework-sync` starts as a prompt-level workflow. It may later be promoted to a command/script once the propagation manifest and apply semantics are stable across multiple consumer repositories.
