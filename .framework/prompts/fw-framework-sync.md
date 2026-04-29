# fw-framework-sync

## Rol

Actúas como `orchestrator`.

## Objetivo

Sincronizar cambios del repo central `ai-together-framework` hacia repos consumidores de manera plan-first y protegida por defecto.
Este prompt local comienza como un workflow de nivel prompt. Puede promoverse más adelante a un comando o script cuando el propagation manifest y la semántica de apply estén estables entre múltiples repos consumidores.

## Uso

Usa este prompt leyendo `cat .framework/prompts/fw-framework-sync.md`.

## Modo por defecto

- `plan`
- `read-only`

## Modo explicitado

- `check`: detectar drift entre el contrato canónico del framework y el repo consumidor.
- `plan`: proponer cambios sin escribir.
- `apply`: aplicar solo archivos propagables aprobados.

`apply` requiere instrucción explícita del operador y no debe inferirse desde `check` ni desde `plan`.

## Contexto obligatorio

Lee el contrato canónico del Framework, el estado local del repo consumidor y cualquier documentación versionada relevante antes de decidir.

## Alcance

- comparar versión local y versión canónica del framework
- detectar drift en archivos propagables
- proponer un plan de sync protegido por defecto
- aplicar solo archivos propagables aprobados cuando exista instrucción explícita

## No debes

- tocar archivos protegidos
- inferir permisos de escritura
- sobrescribir historia de ORQs
- marcar `Governance Sync`, `Learning Sync` o `Dashboard Sync` como `Synced` sin evidencia externa real
- modificar `.framework/project-config.yml`
- modificar `.framework/context.md`
- modificar `.framework/orqs/**`
- modificar secretos
- modificar runtime o archivos de producto

## Archivos protegidos

Tratar como protegidos, omitidos o solo de revisión:

- `.framework/project-config.yml`
- `.framework/context.md`
- `.framework/orqs/**`
- secretos
- archivos runtime
- archivos de producto
- historial de ORQs

## Pasos

1. Resolver `framework_version_local`.
2. Resolver `framework_version_canonical`.
3. Identificar el conjunto mínimo de archivos framework-owned propagables.
4. Clasificar archivos en:
   - `checked`
   - `protected`
   - `skipped`
   - `to_update`
   - `conflicts`
5. Si el modo es `check`, emitir solo detección de drift.
6. Si el modo es `plan`, emitir un plan de sync sin escribir.
7. Si el modo es `apply`, actualizar solo los archivos propagables aprobados y mantener intactos los protegidos.
8. Registrar evidencia de lo revisado y, si corresponde, de lo aplicado.

## Evidencia a registrar

- `framework_version_local`
- `framework_version_canonical`
- `checked_files`
- `files_to_update`
- `protected_skipped_files`
- `conflicts_requiring_review`
- `applied_files`

## Regla de idempotencia

Si un archivo ya coincide con el contrato canónico, no debe reescribirse.
Si existe conflicto entre el contrato canónico y una modificación local protegida, detenerse y pedir revisión en lugar de sobrescribir.

## Relación con governance sync

Este prompt sincroniza contrato y documentación del framework entre repos.
No reemplaza `fw-governance-sync`, que sigue siendo el mecanismo para syncs de learning, dashboard y reporting gobernado con evidencia real.

## Output esperado

Un sync plan o reporte con:

- estado del drift
- archivos revisados
- archivos protegidos u omitidos
- archivos a actualizar
- conflictos que requieren revisión
- archivos aplicados, si aplica
- próximo paso sugerido
