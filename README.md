# dify-cli

Command-line tool for authoring Dify DSL (workflow / chatflow) YAML files declaratively.

The CLI is **schema-driven**: node field definitions are loaded from pre-generated
JSON Schema bundles keyed by DSL version (`dify_cli/schemas/v<ver>.json`). When
Dify upgrades the DSL, only a new schema bundle needs to be regenerated and
shipped - the CLI code itself does not need to change.

## Install (dev)

```bash
cd cli
pip install -e ".[dev]"
```

## Importing DSL into Dify

The CLI only writes the YAML file. To import into a Dify instance:

1. Open Dify web UI -> Create app -> Import DSL
2. Upload the generated `dsl.yaml`
3. The DSL version must be <= the Dify instance's `CURRENT_DSL_VERSION` (check via `dify-cli --version`)

If import fails with "client-side exception", run `dify-cli validate` first, and ensure the frontend defaults bundle matches the Dify version (see [Regenerating schemas](#regenerating-schemas) below).

## Regenerating schemas

When Dify bumps `CURRENT_DSL_VERSION` (in `api/services/app_dsl_service.py`), regenerate both bundles so the CLI picks up new node fields and defaults.

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

## Project structure

| Path | Purpose |
|---|---|
| `cli/dify_cli/main.py` | Typer app, command registration |
| `cli/dify_cli/commands/apply.py` | Declarative spec -> DSL generation |
| `cli/dify_cli/commands/spec.py` | `spec validate` command |
| `cli/dify_cli/commands/node.py` | `node check` + read-only inspection commands |
| `cli/dify_cli/core/spec_validator.py` | Variable reference + scope validation |
| `cli/dify_cli/core/spec_format.py` | Hoisted fields mapping (IO/dependency vs internal config) |
| `cli/dify_cli/core/node_builder.py` | Three-layer node construction (frontend defaults + fields + schema validation) |
| `cli/dify_cli/core/dsl.py` | DSL load/save/skeleton |
| `cli/dify_cli/core/graph.py` | Node/edge construction + topology validation |
| `cli/dify_cli/core/schema_store.py` | Loads `v<ver>.json` and `defaults-v<ver>.json` by DSL version |
| `cli/dify_cli/schemas/` | Bundled JSON Schema + frontend defaults per DSL version |
| `cli/scripts/extract_schemas.py` | Backend Pydantic reflection (run in api env) |
| `cli/scripts/extract_defaults.mjs` | Frontend AST extraction (run with node + typescript) |
| `skills/dify-cli/SKILL.md` | Agent-facing skill brief (commands + workflow) |
| `skills/dify-cli/references/spec-author-guide.md` | Spec authoring guide |
| `skills/dify-cli/references/inspection-commands.md` | Read-only inspection commands reference |
