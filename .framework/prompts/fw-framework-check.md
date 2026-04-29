# fw-framework-check

## Role

You act as `orchestrator` in `fw-framework-check` mode.

## Objective

Generate a read-only drift report that compares the consumer repo against the canonical Framework V2 contract without modifying any file.

## Mandatory context

Read `.framework/context.md` if it exists, `.framework/project-config.yml`, `.framework/framework-reference.md`, the local framework version, and any versioned project documentation relevant to the check.

Resolve the local framework version in this order:

1. `.framework/framework-version`
2. `.framework/version.txt`

Resolve the canonical framework version from the central Framework repo in this order:

1. `.framework/version.txt`
2. `.framework/framework-version`

Do not guess missing versions.

## Scope

- Detect the local framework version.
- Compare it against the canonical framework version.
- Identify framework-owned propagable files.
- Detect drift in propagable files.
- Respect `artifact_policy: local-only`, `hybrid`, and `versioned`.
- Protect `project-config.yml`, `context.md`, ORQ history, local tooling, and secrets.
- Report conflicts that require review.
- Do not apply propagation or mark the consumer repo as aligned.

## Do not

- Modify files.
- Stage changes.
- Run synchronization.
- Mark repos as synced.
- Infer that the check updates the consumer repo or the central repo.

## Steps

1. Resolve `artifact_policy` for the consumer repo if it exists.
2. Resolve the local framework version using the priority order above.
3. Resolve the canonical framework version.
4. Determine the minimum set of framework-owned propagable files to verify.
5. Separate checked, protected, omitted, and drifted files.
6. Report conflicts as lightweight entries with at least `path` and `reason`.
7. Limit `sync_status` to `Aligned`, `Drifted`, or `Needs Review`.
8. Emit a Markdown report.

## Output expected

Include at least these sections:

- `framework_version_local`
- `framework_version_canonical`
- `sync_status`
- `drift_detected`
- `files_checked`
- `files_skipped_protected`
- `conflicts_requiring_review`
- `suggested_next_action`

## Rule

If the local version cannot be resolved, or if the local contract is ambiguous, return `Needs Review` instead of guessing.
