# fw-framework-check

## Rol

Actúas como `orchestrator` en modo `fw-framework-check`.

## Objetivo

Generar un reporte read-only que compare el repo consumidor contra el contrato canónico del Framework V2 sin modificar ningún archivo.

## Contexto obligatorio

Lee `.framework/context.md` si existe, `.framework/project-config.yml`, `.framework/framework-reference.md`, la versión local del framework y la documentación versionada relevante.

La versión local debe resolverse en este orden:

1. `.framework/framework-version`
2. `.framework/version.txt`

La versión canónica debe resolverse desde el repo central del Framework en este orden:

1. `.framework/version.txt`
2. `.framework/framework-version`

No adivines versiones faltantes.

## Alcance del check

- Detectar la versión local del framework.
- Comparar contra la versión canónica del Framework.
- Identificar archivos framework-owned propagables.
- Detectar drift en archivos propagables.
- Respetar `artifact_policy: local-only`, `hybrid` y `versioned`.
- Proteger `project-config.yml`, `context.md`, ORQ history, local tooling y secretos.
- Reportar conflictos que requieran revisión.
- No aplicar propagación ni marcar repos consumidores como alineados con el Framework central.

## No debes

- Modificar archivos.
- Stagear cambios.
- Ejecutar sincronización.
- Marcar repos consumidores como sincronizados.
- Inferir que el check actualiza el repo consumidor o el repo central.

## Pasos

1. Resolver `artifact_policy` del repo consumidor si existe.
2. Resolver la versión local del framework con el orden de prioridad definido arriba.
3. Resolver la versión canónica del framework.
4. Determinar el conjunto mínimo de archivos framework-owned propagables a verificar.
5. Separar archivos chequedos, protegidos, omitidos y con drift.
6. Reportar conflictos como entradas ligeras con al menos `path` y `reason`.
7. Limitar `sync_status` de Phase 1 a `Aligned`, `Drifted` o `Needs Review`.
8. Emitir un reporte read-only en Markdown.

## Output esperado

Un reporte con estas secciones, como mínimo:

- `framework_version_local`
- `framework_version_canonical`
- `sync_status`
- `drift_detected`
- `files_checked`
- `files_skipped_protected`
- `conflicts_requiring_review`
- `suggested_next_action`

## Regla

Si la versión local no puede resolverse, o si el contrato local es ambiguo, devolver `Needs Review` en lugar de inferir.
