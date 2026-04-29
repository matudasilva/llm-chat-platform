# Framework Reference

## Framework

- Name: AI Together Framework V2
- Canonical repository: /home/matias/Cursor/Framework/ai-together-framework
- Canonical version: AI Together Framework V2

## Project Policy

- Repository visibility: unset
- Framework artifact policy: unset
- Operational memory location: unset
- ORQ language: es
- Local tools enabled: yes

## Versioned Contract

List only the framework artifacts that this repo intentionally versions.

- `.framework/context.md`
- `.framework/framework-reference.md`
- `.framework/project-config.yml`
- `.framework/framework-version`

## Public Boundary

Document the boundary between product source and documentation and the internal framework orchestration artifacts.

## Notes

- Repository visibility does not define Framework artifact policy.
- An external context source can hold human context, roadmap, and governed reporting, but it does not replace local executable tools or imply ORQ creation there by default.
- ORQ language is configured per project or operator and must be resolved through `orq_language` when available.
- `learning_sync` and `dashboard_sync` are separate contracts.
- `fw-close` performs local closure; `fw-governance-sync` performs the actual governance update when applicable and only explicitly.
