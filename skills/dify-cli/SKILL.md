---
name: dify-cli
description: Build Dify DSL (workflow / chatflow) YAML files declaratively. Use when the user wants to author or programmatically generate Dify app definitions - write a spec, validate it, apply it to generate DSL, and validate before importing into Dify. Schema-driven: works across DSL versions without code changes.
---

# dify-cli

`dify-cli` is a command-line tool for authoring Dify DSL YAML files **declaratively**: you write a spec (the single source of truth), validate it, and `apply` generates the DSL. Edits go back through the spec + re-apply, not by mutating the DSL directly.

The CLI is **schema-driven**: node field definitions are loaded from pre-generated JSON Schema bundles keyed by DSL version. When Dify upgrades the DSL, only a new schema bundle needs to be regenerated - the CLI code itself does not change.

**dify-cli is pre-installed.** If `dify-cli` is not on PATH, run via module: `python -m dify_cli.main version`.

**For how to write `spec.json` (format, node fields, variable model, examples), see [SPEC.md](SPEC.md).** This file covers the CLI commands and workflow.

## Primary workflow (two-phase)

**Design stage** (structure + IO contracts):
```
1. author spec.json        (nodes, hoisted IO/dependencies, @file refs; see SPEC.md)
2. dify-cli spec validate  (structure check: node types, variable refs, scope, edges)
```

**Implementation stage** (fill node internal config, parallelizable per node):
```
3. for each node: generate its @file (code/prompts/model params)
   dify-cli node check <id> --spec spec.json --fields <file>  (schema + template refs)
```

**Apply**:
```
4. dify-cli apply --spec spec.json -f dsl.yaml --force  (merge hoisted + @file, full validate)
5. dify-cli validate dsl.yaml                           (final topology check)
   -> to change: edit spec (@file refs/IO) or @file (internal config), re-run
```

The spec is the single source of truth. Never hand-edit the generated DSL.

## When to use

- **Build a workflow/chatflow as code** - "create a workflow", "generate a chatflow"
- **Generate Dify DSL programmatically** - from a design doc or template
- **Validate a DSL before importing** - "check this DSL file is valid"
- **Author complex workflows via CI/CD** - declarative spec, idempotent apply

## Quick probe (for agents)

```bash
dify-cli --version        # CLI version
dify-cli node types       # list all node types in the bundled schema (no DSL file needed)
```

## Architecture (important for understanding behavior)

Each node built by this CLI is constructed in **three layers**, from bottom to top:

1. **Frontend `defaultValue` template** (`dify_cli/schemas/defaults-v<ver>.json`) - the exact `data` object the Dify web UI seeds when a user clicks "add node". This guarantees the resulting DSL imports cleanly (the frontend has no null guards on many optional fields, so they must be present).

2. **Spec field overrides** - the `fields` dict in the spec, deep-merged over the template. Example: `{"model": {"name": "gpt-4o"}}` only overrides `name`, preserving other defaults.

3. **Backend JSON Schema validation** (`dify_cli/schemas/v<ver>.json`) - reflected from Dify's Pydantic `*NodeData` models. The CLI validates the final node data against this before writing.

Node graph structure (top-level `type`, `positionAbsolute`, `width`, `height`, `sourcePosition`, `targetPosition`, edge `data.{sourceType,targetType,isInIteration,isInLoop}`, `zIndex`) matches what the frontend expects on import - this is non-negotiable for avoiding "client-side exception" errors.

## Command reference (core workflow)

### `dify-cli apply` - generate a complete DSL from a spec

```bash
dify-cli apply --spec spec.json [--file dsl.yaml] [--force]
```

Generates the ENTIRE workflow from one spec file - nodes, edges, env/conversation variables - in a single command. Re-running `apply` with an edited spec regenerates the DSL deterministically (same spec -> byte-identical output). Defensively runs `spec validate` first; on invalid references it reports errors and exits without generating.

**Spec format**: see [SPEC.md](SPEC.md).

### `dify-cli spec validate` - check a spec before applying (design stage)

```bash
dify-cli spec validate --spec spec.json
```

Validates a spec's **variable references and scope** - the semantic rules the JSON schema can't express: every `value_selector`/`variable_selector` must point to a variable the target node actually exposes, and you can't reference a node inside an iteration/loop container from outside it. Run this in the design stage and fix errors BEFORE `apply`.

**Design-stage workflow**:
1. Analyze the requirement -> author `spec.json` (see [SPEC.md](SPEC.md))
2. `dify-cli spec validate --spec spec.json` -> read the errors
3. Fix the spec -> re-validate until `OK spec is valid`
4. `dify-cli apply --spec spec.json -f dsl.yaml --force` -> generate the DSL

The validator is the single source of truth for variable semantics - see the "Variable model" section in [SPEC.md](SPEC.md).

### `dify-cli node check` - check a single node's internal config (implementation stage)

```bash
dify-cli node check <node_id> --spec spec.json --fields <file>
```

Used in the implementation stage: a sub-agent fills a node's `@file` (internal config), then runs this to verify the merged node data (hoisted IO from spec + internal config) passes backend schema validation, and that template variable references (`{{#node.var#}}`) in the config point to valid in-scope nodes. See [SPEC.md](SPEC.md).

### `dify-cli validate` - full DSL validation

```bash
dify-cli validate [file]  # default dsl.yaml
```

Checks:
1. Top-level DSL structure (`version`, `kind`, `app`, `workflow` or `model_config`)
2. Every node's `data` against the backend JSON Schema (catches invalid enums, missing required fields)
3. Graph topology (unique node IDs, edges reference existing nodes, exactly one start node)

Run this after `apply` as a final check before importing into Dify.

### `dify-cli schema` - inspect node schemas

```bash
dify-cli schema node <type>                    # full JSON Schema for a node's data
dify-cli schema node <type> --required-only    # just the required field names
dify-cli schema enum <type> <field>            # allowed values for an enum field
```

Use this to discover which fields a node requires and what enum values are accepted - works on any installed dify-cli, no source access needed.

### `dify-cli node types`

```bash
dify-cli node types   # list all node types in the bundled schema (no DSL file needed)
```

### `dify-cli --version`

```bash
dify-cli --version   # CLI version
```

## Inspection commands (read-only, less common)

For commands to inspect a generated DSL (`node list`, `node show`, `edge list`, `var env list`, etc.), see [references/inspection-commands.md](references/inspection-commands.md).

## Agent-framework URL blocking (mostly N/A)

Agent frameworks (nanobot) block commands whose arguments contain `https://` or `http://`. In the declarative workflow this is rarely an issue: URLs live inside the spec file (written via `write_file`), and `dify-cli apply --spec spec.json` only puts the file path on the command line - no URL in the args. So **just put URLs directly in the spec** (or in an `@file` referenced by the spec); do not pass them as command arguments.

## Importing into Dify

The CLI only writes the YAML file. To import:

1. Open Dify web UI -> Create app -> Import DSL
2. Upload the generated `dsl.yaml`
3. The DSL version must be <= the Dify instance's `CURRENT_DSL_VERSION` (check via `dify-cli --version`)

If import fails with "client-side exception", run `dify-cli validate` first, and ensure the frontend defaults bundle matches the Dify version (regenerate via the extract script if needed).

## Regenerating schemas after a Dify upgrade

When Dify bumps `CURRENT_DSL_VERSION` (in `api/services/app_dsl_service.py`), regenerate both bundles:

### Backend schema (Pydantic reflection)

Requires a working `dify-api` environment:

```bash
cd api
PYTHONPATH=$PWD uv run --project api python \
  ../cli/scripts/extract_schemas.py \
  --out ../cli/dify_cli/schemas/v<NEW_VER>.json
```

### Frontend defaults (AST extraction)

Requires `typescript` and `esbuild` (zero other web deps):

```bash
cd cli
npm install --no-save typescript esbuild
node scripts/extract_defaults.mjs dify_cli/schemas/defaults-v<NEW_VER>.json <NEW_VER>
```

After regeneration, the CLI automatically picks up the new version via `dify_cli/schemas/` filename - no code changes needed.

## Troubleshooting

**"No schema bundle for DSL version X"** - the `v<ver>.json` file is missing in `dify_cli/schemas/`. Run the extractors above or fall back to a supported version.

**"Validation failed for node type 'llm' at model.mode: ..."** - the backend schema rejected a value. Fix the spec field. Run `dify-cli schema node <type>` to see the allowed values.

**spec validate reports invalid variable references** - see the "Variable model" section in [SPEC.md](SPEC.md). Common fixes: define `loop_variables` on loop nodes, reference container `output` (not inner nodes) from outside, use `variable_selector` (not `variable`) in if-else conditions.

**Import fails with "client-side exception"** - a node is missing a field the frontend expects without null-guarding. Confirm `dify-cli validate` passes, ensure the frontend defaults bundle (`defaults-v<ver>.json`) is present and was regenerated against the same Dify version.

## Key files

- `cli/dify_cli/main.py` - Typer app, command registration
- `cli/dify_cli/commands/apply.py` - declarative spec -> DSL generation
- `cli/dify_cli/commands/spec.py` - `spec validate` command
- `cli/dify_cli/core/spec_validator.py` - variable reference + scope validation
- `cli/dify_cli/core/spec_format.py` - hoisted fields mapping
- `cli/dify_cli/core/node_builder.py` - three-layer node construction
- `cli/dify_cli/schemas/` - bundled JSON Schema + frontend defaults per DSL version
- `skills/dify-cli/SPEC.md` - spec authoring guide (format, node fields, variable model, examples)
- `skills/dify-cli/references/inspection-commands.md` - read-only inspection commands
- `cli/scripts/extract_schemas.py` - backend Pydantic reflection (run in api env)
- `cli/scripts/extract_defaults.mjs` - frontend AST extraction (run with node + typescript)
