---
name: dify-cli
description: Build Dify DSL (workflow / chatflow) YAML files declaratively. Use when the user wants to author or programmatically generate Dify app definitions - write a spec, validate it, apply it to generate DSL, and validate before importing into Dify. Schema-driven: works across DSL versions without code changes.
---

# dify-cli

`dify-cli` is a command-line tool for authoring Dify DSL YAML files **declaratively**: you write a spec (the single source of truth), validate it, and `apply` generates the DSL. Edits go back through the spec + re-apply, not by mutating the DSL directly.

The CLI is **schema-driven**: node field definitions are loaded from pre-generated JSON Schema bundles keyed by DSL version (`dify_cli/schemas/v<ver>.json` + `defaults-v<ver>.json`). When Dify upgrades the DSL, only a new schema bundle needs to be regenerated - the CLI code itself does not change.

## Primary workflow

```
1. author spec.json        (nodes, edges, env/conversation variables)
2. dify-cli spec validate  (semantic check: variable refs + scope)
3. dify-cli apply          (generate DSL, idempotent)
4. dify-cli validate       (final DSL topology/schema check)
   -> to change anything: edit spec.json, re-run from step 2
```

The spec is the single source of truth. Never hand-edit the generated DSL - change the spec and re-apply. Structural imperative commands (`init`, `node add/remove`, `edge add/remove`, `node edit`, `var ... set/remove`) are deprecated in favor of declaring everything in the spec. Read-only commands (`node list/show`, `edge list`, `validate`, `schema`, `spec validate`) remain for inspection.

## When to use

Use this skill when the user asks to:

- **Build a workflow/chatflow as code** - "create a workflow", "generate a chatflow"
- **Generate Dify DSL programmatically** - from a design doc or template
- **Validate a DSL before importing** - "check this DSL file is valid"
- **Author complex workflows via CI/CD** - declarative spec, idempotent apply

## Quick probe (for agents)

Before scaffolding, an agent can probe the environment with these commands. Both work without any DSL file:

```bash
dify-cli --version        # prints "dify-cli <version>" (or: dify-cli version)
dify-cli node types       # lists all node types in the latest bundled schema (28 types)
dify-cli node types -v 0.5.0   # list types for a specific DSL version
```

`dify-cli node types` does NOT require a DSL file — it reads from the bundled schema. Use it to discover what node types are available before writing a spec.

## Installation

The CLI lives at `cli/` in the dify repo. For development use:

```bash
cd cli
pip install -e ".[dev]"
```

Requires Python >= 3.11. Dependencies: `typer`, `pyyaml`, `jsonschema`, `rich`.

Verify installation:

```bash
dify-cli version
# dify-cli 0.1.0
# Bundled DSL schemas: 0.5.0
```

If `dify-cli` is not on PATH, run via module:

```bash
python -m dify_cli.main version
```

## Architecture (important for understanding behavior)

Each node built by this CLI is constructed in **three layers**, from bottom to top:

1. **Frontend `defaultValue` template** (`dify_cli/schemas/defaults-v<ver>.json`) — the exact `data` object the Dify web UI seeds when a user clicks "add node". This guarantees the resulting DSL imports cleanly (the frontend has no null guards on many optional fields, so they must be present). Example: an LLM node always gets `model.completion_params.temperature: 0.7`, `prompt_template: [{role: 'system', text: ''}]`, `context.enabled: false`, `vision.enabled: false`.

2. **User `--field` overrides** — dotted key=value pairs that deep-merge over the template. Example: `--field model.name=gpt-4o` only overrides `name`, preserving other defaults.

3. **Backend JSON Schema validation** (`dify_cli/schemas/v<ver>.json`) — reflected from Dify's Pydantic `*NodeData` models. The CLI validates the final node data against this before writing, catching invalid enum values, missing required fields, etc.

Node graph structure (top-level `type`, `positionAbsolute`, `width`, `height`, `sourcePosition`, `targetPosition`, edge `data.{sourceType,targetType,isInIteration,isInLoop}`, `zIndex`) matches what the frontend expects on import — this is non-negotiable for avoiding "client-side exception" errors.

## Command reference

### `dify-cli apply` - generate a complete DSL from a spec (declarative)

```bash
dify-cli apply --spec spec.json [--file dsl.yaml] [--force]
```

Generates the ENTIRE workflow from one spec file - nodes, edges, and per-node field overrides in a single command. Re-running `apply` with an edited spec regenerates the DSL deterministically (same spec -> byte-identical output). **For complex workflows or when the design may change, prefer `apply` over issuing many `node add`/`edge add` commands** - it's one turn per revision instead of N, and there's no drift because the spec is the single source of truth.

**Spec format** (JSON):
```json
{
  "mode": "workflow", "name": "My App", "dsl_version": "0.5.0",
  "environment_variables": [
    {"name": "API_KEY", "value": "sk-xxx"},
    {"name": "BASE_URL", "value": "@/tmp/url.txt"}
  ],
  "conversation_variables": [
    {"name": "memory", "value_type": "string", "description": "user memory"}
  ],
  "nodes": [
    {"id": "start", "type": "start", "title": "Start", "fields": {"variables": [...]}},
    {"id": "code", "type": "code", "title": "Parse", "fields": {
      "code_language": "python3",
      "code": "@/tmp/parse.py",
      "variables": [{"variable":"q","value_selector":["start","q"]}],
      "outputs": {"items": {"type": "array[object]"}}
    }},
    {"id": "iter", "type": "iteration", "title": "Loop", "fields": {
      "iterator_selector": ["code","items"],
      "output_selector": ["inner","upper"]
    }, "children": [
      {"id": "inner", "type": "code", "title": "Upper", "fields": {"code": "@/tmp/upper.py", "...": "..."}}
    ]},
    {"id": "end", "type": "end", "title": "End", "fields": {
      "outputs": [{"variable":"r","value_selector":["iter","output"]}]
    }}
  ],
  "edges": [
    {"source": "start", "target": "code"},
    {"source": "code", "target": "iter"},
    {"source": "iter", "target": "end"}
  ]
}
```

Key points:
- **Stable ids**: the `id` in the spec becomes the node's id in the DSL (NOT a timestamp). Re-applying keeps ids stable so edges and `value_selector` references never break.
- **`fields` is a dict**: values support `@file` (read from file - use for multi-line code, prompt_template, URLs), dict/list (used as-is), and scalars. Same semantics as `--fields-file`.
- **`children`**: only for `iteration`/`loop` nodes. The iteration-start/loop-start child is auto-created and linked to `start_node_id` - do NOT list it in the spec. Children auto-get `parentId`/`isInIteration`.
- **`edges`**: `source`/`target` reference spec ids; `src_handle` optional (for if-else branches: `"true"`/`"false"`).
- **Idempotent**: same spec -> identical DSL every time (deterministic node ids, edge ids `<source>-<target>`, condition ids `<node>-cond-<index>`). Safe to re-apply after editing the spec.
- **All nodes need `title`** (the schema requires it).

**Three-layer separation**: the spec (`spec.json`) describes structure; `@file` files hold multi-line content (code/prompts/URLs); the generated `dsl.yaml` is derived and never hand-edited. Change the spec -> re-apply; change code -> re-apply (the `@file` is re-read).

**Spec covers everything**: nodes, edges, AND environment/conversation variables. Do not use `var env set` / `var conversation set` / `node add` / `edge add` / `node edit` - declare them in the spec and re-apply. The spec is the single source of truth; the generated DSL is derived and never hand-edited.

**Environment/conversation variables** in the spec: `environment_variables` is a list of `{name, value, value_type}` (value supports `@file` for URLs); `conversation_variables` is a list of `{name, value_type, description, value}`. See the spec format above.

### `dify-cli spec validate` - check a spec before applying (design stage)

```bash
dify-cli spec validate --spec spec.json
```

Validates a spec's **variable references and scope** - the semantic rules the JSON schema can't express: every `value_selector`/`variable_selector` must point to a variable the target node actually exposes, and you can't reference a node inside an iteration/loop container from outside it. Run this in the design stage and fix errors BEFORE `apply` (apply also checks defensively, but iterating on `spec validate` is the intended feedback loop).

**Design-stage workflow**:
1. Analyze the requirement -> author `spec.json`
2. `dify-cli spec validate --spec spec.json` -> read the errors
3. Fix the spec -> re-validate until `OK spec is valid`
4. `dify-cli apply --spec spec.json -f dsl.yaml --force` -> generate the DSL

The validator is the single source of truth for variable semantics - it knows what each node type exposes (start exposes its `variables`, code exposes `outputs` keys, iteration exposes `item`/`index` inside and `output` outside, loop exposes its `loop_variables`, etc.). Common errors it catches:

```
FAIL end.fields.outputs[0].value_selector: node 'loop' (loop) does not expose variable 'counter'. Exposes: (none).
     -> define loop_variables on the loop, or reference an existing variable.
FAIL end.fields.outputs[0].value_selector: cannot reference 'loopbody' from here - it is inside container 'loop'. Reference the container node instead.
     -> you can't reach into a container; reference the container node (loop/iteration) which exposes its output.
```

When the validator says a node "does not expose" a variable, check what it actually exposes - for start/code/parameter-extractor that's their declared variables/outputs/parameters; for containers use the container's special vars (`item`/`index`/`output`/`loop_variables`).

### `dify-cli node` - inspect nodes (read-only)

```bash
# List all nodes (id, type, title)
dify-cli node list [--file dsl.yaml]

# Show one node's full JSON
dify-cli node show <node_id> [--file dsl.yaml]

# List node types known to the bundled schema
dify-cli node types [--file dsl.yaml]
```

`node add`/`node remove`/`node edit` are removed - declare nodes in the spec and use `dify-cli apply`.

## Spec field values and @file

Spec field values can be inline strings, numbers, booleans, arrays, or objects. For multi-line content (code, prompt_template) or sensitive values (URLs), use `@file` - a string starting with `@` is replaced with the file's contents:

```json
{"id": "code", "type": "code", "fields": {
  "code": "@/tmp/parse.py",
  "prompt_template": "@/tmp/prompt.json"
}}
```

This keeps the spec clean and lets you edit code/prompts independently. Use the `write_file` tool to create these files.

## Agent-framework URL blocking (mostly N/A in declarative workflow)

Agent frameworks (nanobot) block commands whose arguments contain `https://` or `http://`. In the declarative workflow this is rarely an issue: URLs live inside the spec file (written via `write_file`), and `dify-cli apply --spec spec.json` only puts the file path on the command line - no URL in the args. So **just put URLs directly in the spec** (or in an `@file` referenced by the spec); do not pass them as command arguments.

The only remaining guardrail: never inline a URL in a command argument (e.g. `dify-cli var env get 'https://...'` - there's no reason to do this). If you ever need a URL on the command line, write it to a file first with `write_file` and reference the file.

### `dify-cli edge` - inspect edges (read-only)

```bash
dify-cli edge list [--file dsl.yaml]
```

`edge add`/`edge remove` are removed - declare edges in the spec and use `dify-cli apply`.

### `dify-cli var` - inspect variables (read-only)

```bash
dify-cli var env list [--file dsl.yaml]
dify-cli var env get <name> [--file dsl.yaml]
dify-cli var conversation list [--file dsl.yaml]
```

`var ... set/remove` are removed - declare environment/conversation variables in the spec and use `dify-cli apply`.

### `dify-cli validate` — full validation

```bash
dify-cli validate [file]  # default dsl.yaml
```

Checks:
1. Top-level DSL structure (`version`, `kind`, `app`, `workflow` or `model_config`)
2. Every node's `data` against the backend JSON Schema (catches invalid enums, missing required fields)
3. Graph topology (unique node IDs, edges reference existing nodes, exactly one start node)

Exits non-zero with `✗`-prefixed error list on failure. Run this before importing into Dify.

### `dify-cli version`

Prints CLI version and bundled DSL schema versions.

### `dify-cli schema` - inspect node schemas

```bash
dify-cli schema types                          # list all node types
dify-cli schema node <type>                    # full JSON Schema for a node's data
dify-cli schema node <type> --required-only    # just the required field names
dify-cli schema enum <type> <field>            # allowed values for an enum field
```

Use this to discover which fields a node requires and what enum values are accepted - works on any installed dify-cli, no source access needed.

## Common node types

These are the most-used node types (full list via `dify-cli node types`):

| Type | DSL string | Required user fields (beyond defaults) |
|---|---|---|
| Start | `start` | none (variables default to `[]`) |
| End | `end` | `outputs` (array of output variable selectors) |
| LLM | `llm` | `model.provider`, `model.name` (mode defaults to `chat`) |
| HTTP Request | `http-request` | `url` (method defaults to `get`) |
| Code | `code` | `code_language`, `code`, `variables`, `outputs` |
| Knowledge Retrieval | `knowledge-retrieval` | `dataset_ids` |
| If-Else | `if-else` | `cases` (branch conditions) |
| Template Transform | `template-transform` | `template`, `variables` |
| Question Classifier | `question-classifier` | `model`, `query_variable_selector`, `classes` |
| Tool | `tool` | `provider_id`, `tool_name`, `tool_parameters` |
| Variable Aggregator | `variable-aggregator` | `variables` |
| Iteration | `iteration` | `iterator_selector`, `start_node_id` |
| Agent | `agent` | `model`, `strategy`, `tools` |
| Answer | `answer` | `answer` (template string) |

### LLM prompt_template in the spec

The LLM node's `prompt_template` is a JSON array of message objects, often containing multi-line prompts, embedded quotes, and `{{#node-id.var#}}` template variables. In the spec it's just a normal JSON value - no shell quoting issues. Put it directly in the spec:

```json
{"id": "llm", "type": "llm", "title": "GPT", "fields": {
  "model": {"provider": "openai", "name": "gpt-4o"},
  "prompt_template": [
    {"role": "system", "text": "You are a helpful assistant. Follow these rules:\n1. Be concise\n2. Use {{#start.input#}} as context"},
    {"role": "user", "text": "Summarize the above."}
  ]
}}
```

For very long prompts, write the prompt text to a file and reference it with `@file`:
```json
{"role": "system", "text": "@/tmp/system_prompt.txt"}
```

## How to look up node field requirements

The CLI bundles the full Dify node schema and exposes it via `dify-cli schema` subcommands. When unsure which fields a node type requires (or what values an enum accepts), query it instead of guessing:

```bash
# List required field names for a node type:
dify-cli schema node start --required-only

# Dump the full JSON Schema for a node type (incl. nested $defs, enums):
dify-cli schema node start

# List all node types in the schema:
dify-cli schema types

# Look up an enum field's allowed values:
dify-cli schema enum code code_language
```

These commands work on any installed dify-cli (no source access needed). The gotchas below cover the fields agents get wrong most often.

## Node field gotchas

These field shapes are easy to get wrong. All examples show the spec `fields` value for the node. When a node fails validation, run `dify-cli node show <id>` on the generated DSL, or `dify-cli schema node <type>` for the authoritative shape.

**start `variables[]`** items require `variable`, `label`, and `type`. `type` is one of: `text-input`, `paragraph`, `number`, `select`, `file`, `file-list`, `json_object`. For `select`, add `options`:
```json
"fields": {"variables": [
  {"variable": "name", "label": "Name", "type": "text-input", "required": true},
  {"variable": "role", "label": "Role", "type": "select", "options": ["admin","user"], "required": true}
]}
```

**if-else `cases[].conditions[]`** uses `variable_selector` (NOT `variable`). `value` accepts only string / array[string] / boolean / null - **not number** (use a string operator like `not empty` for numeric checks):
```json
"fields": {"cases": [{"case_id": "true", "logical_operator": "and", "conditions": [
  {"variable_selector": ["start", "input"], "comparison_operator": "contains", "value": "hello"}
]}]}
```

**http-request `headers` / `params`** are **strings** (one `key: value` per line), not objects:
```json
"fields": {"headers": "Content-Type: application/json\nAuthorization: Bearer xxx"}
```

**http-request `body`** is an object with `type` (`none`/`form-data`/`x-www-form-urlencoded`/`raw-text`/`json`/`binary`) and `data`:
```json
"fields": {"body": {"type": "json", "data": [{"key": "", "type": "text", "value": "{\"k\":\"v\"}"}]}}
```

**end `outputs[]`** items use `variable` (output name) + `value_selector` (path to upstream output):
```json
"fields": {"outputs": [{"variable": "result", "value_selector": ["llm", "text"]}]}
```

**variable-aggregator `variables`** is an array of arrays (each inner array is a value selector):
```json
"fields": {"variables": [["node1", "output"], ["node2", "output"]], "output_type": "string"}
```

**code `variables[]`** items are `{variable, value_selector}` - `variable` is the Python parameter name, `value_selector` is the path to the upstream output:
```json
"fields": {"variables": [{"variable": "name", "value_selector": ["start", "name"]}]}
```

**code `outputs`** is an object mapping output name -> `{type: <SegmentType>}`. SegmentType: `string`, `number`, `object`, `array[string]`, `array[object]`, `array[number]`, `boolean`, `file`, `array[file]`, `secret`, `none`:
```json
"fields": {"outputs": {"items": {"type": "array[object]"}, "count": {"type": "number"}}}
```

**code `code_language`** accepts only `python3` or `javascript` (NOT `python`; the CLI auto-corrects `python`->`python3`).

**iteration** requires `iterator_selector` (array to loop over) and `output_selector` (path to the inner node's output to collect). The iteration-start child is auto-created by `apply` - do NOT list it in the spec. Inner nodes go in `children` and reference `[<iteration_id>, "item"]`:
```json
{"id": "iter", "type": "iteration", "fields": {
  "iterator_selector": ["code", "items"],
  "output_selector": ["inner", "result"]
}, "children": [
  {"id": "inner", "type": "code", "fields": {
    "variables": [{"variable": "item", "value_selector": ["iter", "item"]}]
  }}
]}
```

**loop** exposes its `loop_variables` (by `label`) to both inner children and outside nodes. break_conditions reference the loop's own variables, NOT child outputs:
```json
{"id": "loop", "type": "loop", "fields": {
  "loop_variables": [{"label": "counter", "var_type": "number", "value": "0", "value_type": "constant"}],
  "break_conditions": [{"variable_selector": ["loop", "counter"], "comparison_operator": "\u2265", "value": "5"}]
}}
```

**Comparison operators**: `contains`, `is`, `empty`, `not empty`, `=`, `\u2260` (\u2260), `>`, `<`, `\u2265`, `\u2264`. Check `dify-cli schema enum if-else comparison_operator` for the full list.

### Minimal LLM workflow (spec + apply)

Write a spec, validate, apply:

```json
// spec.json
{
  "mode": "workflow", "name": "My App",
  "nodes": [
    {"id": "start", "type": "start", "title": "Start"},
    {"id": "llm", "type": "llm", "title": "Call GPT", "fields": {
      "model": {"provider": "openai", "name": "gpt-4o"}
    }},
    {"id": "end", "type": "end", "title": "End", "fields": {
      "outputs": [{"variable": "result", "value_selector": ["llm", "text"]}]
    }}
  ],
  "edges": [
    {"source": "start", "target": "llm"},
    {"source": "llm", "target": "end"}
  ]
}
```

```bash
dify-cli spec validate --spec spec.json
dify-cli apply --spec spec.json -f app.yaml --force
dify-cli validate app.yaml
```

The LLM node only needs `model.provider` and `model.name` - `mode`, `completion_params.temperature`, `prompt_template`, `context`, `vision` come from the frontend defaults. Stable ids (`start`/`llm`/`end`) let edges and `value_selector` reference nodes by name.

### Changing the workflow

Edit `spec.json` (add/remove nodes, change fields, update edges) and re-run `spec validate` + `apply`. The spec is the single source of truth - never hand-edit `app.yaml`. Example: change the model and add a system prompt by editing the llm node in the spec:

```json
{"id": "llm", "type": "llm", "title": "Call GPT", "fields": {
  "model": {"provider": "openai", "name": "gpt-4o-mini"},
  "prompt_template": [{"role": "system", "text": "You are helpful."}, {"role": "user", "text": "{{#sys.query#}}"}]
}}
```

Then `dify-cli apply --spec spec.json -f app.yaml --force` regenerates the DSL.

### Advanced-chat with conversation memory

Declare conversation/environment variables and nodes in the spec:

```json
{
  "mode": "advanced-chat", "name": "Chatbot",
  "environment_variables": [{"name": "SYSTEM_PROMPT", "value": "You are a helpful assistant."}],
  "conversation_variables": [{"name": "user_name", "value_type": "string", "description": "Remembered name"}],
  "nodes": [
    {"id": "start", "type": "start", "title": "Start"},
    {"id": "llm", "type": "llm", "title": "Reply", "fields": {
      "model": {"provider": "openai", "name": "gpt-4o"},
      "prompt_template": [{"role": "system", "text": "{{#env.SYSTEM_PROMPT#}}"}, {"role": "user", "text": "{{#sys.query#}}"}]
    }},
    {"id": "answer", "type": "answer", "title": "Answer", "fields": {"answer": "{{#llm.text#}}"}}
  ],
  "edges": [
    {"source": "start", "target": "llm"},
    {"source": "llm", "target": "answer"}
  ]
}
```

```bash
dify-cli spec validate --spec spec.json && dify-cli apply --spec spec.json -f chat.yaml --force && dify-cli validate chat.yaml
```

## Importing into Dify

The CLI only writes the YAML file. To import:

1. Open Dify web UI → Create app → Import DSL
2. Upload the generated `dsl.yaml`
3. The DSL version must be <= the Dify instance's `CURRENT_DSL_VERSION` (check via `dify-cli version`)

If import fails with "client-side exception", the node structure is incomplete — run `dify-cli validate` first, and ensure you're on the latest bundled defaults (regenerate via the extract script if needed).

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

The defaults extractor statically parses each `web/app/components/workflow/nodes/<type>/default.ts` with the TypeScript compiler API and evaluates the `defaultValue` object literal — no runtime imports of the web codebase.

After regeneration, the CLI automatically picks up the new version via `dify-cli/schemas/` filename — no code changes needed.

## Troubleshooting

**"No schema bundle for DSL version X"** — the `v<ver>.json` file is missing in `dify_cli/schemas/`. Run the extractors (above) or fall back to a supported version.

**"Validation failed for node type 'llm' at model.mode: 'bogus' is not one of ['chat', 'completion']"** — the backend schema rejected a value. Fix the `--field` value.

**Import fails with "client-side exception"** — a node is missing a field the frontend expects without null-guarding. Confirm `dify-cli validate` passes, ensure the frontend defaults bundle (`defaults-v<ver>.json`) is present and was regenerated against the same Dify version.

**`node add` succeeds but Dify can't find a field** — the frontend defaults template may be stale. Regenerate `defaults-v<ver>.json` from the matching Dify commit.

**Edges disappear after `node remove`** — this is intended: removing a node also removes its connected edges to avoid dangling references.

## Key files

- `cli/dify_cli/main.py` — Typer app, command registration
- `cli/dify_cli/core/node_builder.py` — three-layer node construction (frontend defaults + user fields + schema validation)
- `cli/dify_cli/core/dsl.py` — DSL load/save/init_skeleton
- `cli/dify_cli/core/graph.py` — node/edge CRUD + topology validation
- `cli/dify_cli/core/schema_store.py` — loads `v<ver>.json` and `defaults-v<ver>.json` by DSL version
- `cli/dify_cli/schemas/` — bundled JSON Schema + frontend defaults per DSL version
- `cli/scripts/extract_schemas.py` — backend Pydantic reflection (run in api env)
- `cli/scripts/extract_defaults.mjs` — frontend AST extraction (run with node + typescript)
