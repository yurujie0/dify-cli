---
name: dify-cli
description: Build and edit Dify DSL (workflow / chatflow) YAML files from the command line. Use when the user wants to author, scaffold, or programmatically generate Dify app definitions — init a workflow/chatflow skeleton, add/edit/remove nodes and edges, manage environment/conversation variables, and validate against the Dify schema before importing into a Dify instance. Schema-driven: works across DSL versions without code changes.
---

# dify-cli

`dify-cli` is a command-line tool for authoring Dify DSL YAML files. It lets you build workflows and chatflows as code — init a scaffold, add nodes and edges, set variables, validate, then import the result into a Dify instance.

The CLI is **schema-driven**: node field definitions are loaded from pre-generated JSON Schema bundles keyed by DSL version (`dify_cli/schemas/v<ver>.json` + `defaults-v<ver>.json`). When Dify upgrades the DSL, only a new schema bundle needs to be regenerated — the CLI code itself does not change.

## When to use

Use this skill when the user asks to:

- **Scaffold a Dify app as code** — "create a workflow DSL file", "generate a chatflow YAML"
- **Build workflows programmatically** — "add an LLM node", "connect start to llm", "set up environment variables"
- **Edit existing DSL files** — "add a node to this dsl.yaml", "change the model on the LLM node"
- **Validate a DSL before importing** — "check this DSL file is valid"
- **Author complex workflows via script/CICD** — generating DSL from templates, parameterizing deployments

Do NOT use for:

- Running or executing workflows (use the Dify API directly)
- Importing DSLs into Dify (that's the Dify web UI's job — this tool only generates/edits the file)
- Managing Dify instances, datasets, or plugins

## Quick probe (for agents)

Before scaffolding, an agent can probe the environment with these commands. Both work without any DSL file:

```bash
dify-cli --version        # prints "dify-cli <version>" (or: dify-cli version)
dify-cli node types       # lists all node types in the latest bundled schema (28 types)
dify-cli node types -v 0.5.0   # list types for a specific DSL version
```

`dify-cli node types` does NOT require a DSL file — it reads from the bundled schema. Use it to discover what node types are available before `dify-cli init`.

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

### `dify-cli init` — scaffold a new DSL file

```bash
dify-cli init --mode <mode> --name <name> [--output dsl.yaml] [--dsl-version 0.5.0] [--description "..."] [--force]
```

- `--mode`: one of `workflow`, `advanced-chat`, `chat`, `completion`, `agent-chat`
- `--name`: app name
- `--output` / `-o`: output file path (default `dsl.yaml`)
- `--dsl-version`: must match a bundled schema version (default `0.5.0`)
- `--force`: overwrite existing file

Produces a minimal DSL skeleton with empty `workflow.graph` (for workflow/advanced-chat) or empty `model_config` (for chat/completion).

### `dify-cli node` — node CRUD

```bash
# Add a node — most common command
dify-cli node add <node_type> [--title T] [--parent <iter-or-loop-id>] [--field key=value]... [--file dsl.yaml]

# List all nodes
dify-cli node list [--file dsl.yaml]

# Show one node's full JSON
dify-cli node show <node_id> [--file dsl.yaml]

# Edit fields on an existing node (deep-merged over existing data)
dify-cli node edit <node_id> --field key=value [--field ...] [--file dsl.yaml]

# Remove a node and its connected edges
dify-cli node remove <node_id> [--file dsl.yaml]

# List node types known to the bundled schema
dify-cli node types [--file dsl.yaml]
```

**`--field` syntax** (critical):

- Format: `key=value`. Key supports **dotted paths** for nested assignment: `model.name=gpt-4o` sets `data.model.name`.
- Value parsing (in order):
  1. **`@filename`** → reads value from a file (use for multi-line content like code blocks): `--field code=@mycode.py`
  2. **`@-`** → reads value from stdin (use with heredoc): `--field code=@- <<'PY' ... PY`
  3. Starts with `{` or `[` → parsed as JSON: `--field 'context={"enabled": false}'`, `--field 'prompt_template=[{"role":"user","text":"hi"}]'`
  4. Otherwise → plain string: `--field model.provider=openai`
- Repeat `--field` for multiple fields.

**Passing multi-line code** (common pitfall): do NOT use `--field code="line1\nline2"` — `\n` stays as two literal characters. Either write the code to a file first and use `@file`, or pipe via stdin:

```bash
# Recommended: write code to a file, reference it
cat > mycode.py <<'PY'
import json
result = {"answer": "hello " + arg1}
PY
dify-cli node add code --title "Run Code" \
  --field code=@mycode.py \
  --field 'variables=[{"variable":"arg1","value_selector":["<start-node-id>","input"]}]' \
  --field 'outputs={"answer":{"type":"string"}}'
```

Replace `<start-node-id>` with the actual id from `dify-cli node list`.

Node IDs are auto-generated as millisecond timestamps (e.g. `1783395438602`), matching the Dify frontend's `Date.now()` algorithm. Adding an `iteration` or `loop` node also auto-creates its start child node with id `<parent_id>start` and links the parent's `start_node_id`. To reference node ids (e.g. for edges or `value_selector`), run `dify-cli node list` after adding.

**Placing nodes inside iteration/loop containers**: use `--parent <iter-or-loop-id>` when adding a node that should live inside a container. This sets `parentId`, `extent: "parent"`, `zIndex: 1002`, and `data.isInIteration`/`iteration_id` (or `isInLoop`/`loop_id`) so ReactFlow renders the node inside the container:

```bash
dify-cli node add iteration --title "Loop" -f app.yaml
ITER_ID=$(dify-cli node list -f app.yaml | awk '$2=="iteration"{print $1; exit}')
dify-cli node add code --title "Inner" --parent "$ITER_ID" -f app.yaml \
  --field "variables=[{\"variable\":\"item\",\"value_selector\":[\"$ITER_ID\",\"item\"]}]"
```

**Iteration variable references**: inside an iteration, the current element is exposed as `<iteration_id>.item` and the index as `<iteration_id>.index` — NOT `<iter-start-id>.output`. The iteration-start node is just a subgraph entry marker; the iteration node itself injects `item`/`index` into the variable pool each loop. Connect `iter-start → <first-inner-node>` as the subgraph entry edge, and the iteration node's `output_selector` points to the inner node's output that gets collected into the iteration's `output` array.

**Iteration edges**: the inner subgraph nodes should NOT connect directly to external nodes (e.g. End). The iteration node's `output_selector` aggregates inner outputs, and the iteration node itself connects to the next external node. Typical edge pattern:
- `<prev> → <iteration>` (enter iteration)
- `<iter-start> → <first-inner>` (subgraph entry)
- `<inner> → <inner>` (subgraph internal)
- `<iteration> → <next>` (exit iteration, carrying aggregated `output`)

### `dify-cli edge` — edge CRUD

```bash
# Add an edge between two nodes
dify-cli edge add <source_node_id> <target_node_id> [--src-handle H] [--dst-handle H] [--id ID] [--file dsl.yaml]

# List edges
dify-cli edge list [--file dsl.yaml]

# Remove an edge by id
dify-cli edge remove <edge_id> [--file dsl.yaml]
```

Edges auto-populate `sourceHandle: "source"`, `targetHandle: "target"`, `type: "custom"`, `zIndex: 0`, and `data: {sourceType, targetType, isInIteration: false, isInLoop: false}` (resolved from the source/target nodes). Override handles only for branch nodes (if-else, question-classifier) where edges connect to specific case outputs.

### `dify-cli var` — variable management

```bash
# Environment variables (string values, plaintext)
dify-cli var env set <name> <value> [--file dsl.yaml]
dify-cli var env get <name> [--file dsl.yaml]
dify-cli var env list [--file dsl.yaml]
dify-cli var env remove <name> [--file dsl.yaml]

# Conversation variables (typed, for advanced-chat/workflow)
dify-cli var conversation set <name> [--type string|number|object|array[string]...] [--description "..."] [--file dsl.yaml]
dify-cli var conversation list [--file dsl.yaml]
dify-cli var conversation remove <name> [--file dsl.yaml]
```

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

## Node field gotchas

These fields have shapes that are easy to get wrong. When a node fails validation, run `dify-cli node show <id>` to inspect, or check the schema directly:

```bash
python -c "import json; print(json.dumps(json.load(open('dify_cli/schemas/v0.5.0.json'))['node_types']['<type>'], indent=2))"
```

**if-else `cases[].conditions[]`** uses `variable_selector` (array of node-id path segments), NOT `variable`. The `value` field accepts only string / array[string] / boolean / null — **not number**. To compare against a number, convert to string or use an operator like `not empty`:

```bash
# CORRECT: string value
--field 'cases=[{"case_id":"true","logical_operator":"and","conditions":[{"variable_selector":["start-1","input"],"comparison_operator":"contains","value":"hello"}]}]'
# CORRECT: empty check (no value needed)
--field 'cases=[{"case_id":"true","logical_operator":"and","conditions":[{"variable_selector":["code-1","keywords"],"comparison_operator":"not empty","value":null}]}]'
# WRONG (will fail validation): variable instead of variable_selector
# WRONG: numeric value (value: 0) — use a string operator instead
```

**http-request `headers` / `params`** are **strings** (one `key: value` per line), not objects or arrays:

```bash
# CORRECT
--field 'headers=Content-Type: application/json
Authorization: Bearer xxx'
# WRONG (will fail validation): object or array
--field 'headers={"Content-Type":"application/json"}'
```

**http-request `body`** is an object with `type` (`none`/`form-data`/`x-www-form-urlencoded`/`raw-text`/`json`/`binary`) and `data`:

```bash
--field 'body={"type":"json","data":[{"key":"","type":"text","value":"{\"key\":\"val\"}"}]}'
```

**end `outputs[]`** items use `variable` (the output name) + `value_selector` (array path to the upstream node's output):

```bash
--field 'outputs=[{"variable":"result","value_selector":["llm-1","text"]}]'
```

**variable-aggregator `variables`** is an array of arrays (each inner array is a value selector):

```bash
--field 'variables=[["node-1","output"],["node-2","output"]]'
```

**Comparison operators** for if-else/code conditions include string forms like `contains`, `is`, `empty`, `not empty`, plus symbol forms `=`, `≠`, `>`, `<`. Check the schema enum for the full list.

**code node `variables[]`** items are `{variable: <name>, value_selector: [<node-id>, <output>]}` — the `variable` is the Python function parameter name, `value_selector` is the path to the upstream output:

```bash
--field 'variables=[{"variable":"name","value_selector":["start-1","name"]},{"variable":"count","value_selector":["start-1","count"]}]'
```

**code node `outputs`** is an object mapping output name → `{type: <SegmentType>}`. SegmentType values include `string`, `number`, `object`, `array[string]`, `array[object]`, `array[number]`, `boolean`, `file`, `array[file]`, `secret`, `none`:

```bash
--field 'outputs={"items":{"type":"array[object]"},"summary":{"type":"object"},"count":{"type":"number"}}'
```

**iteration node** requires `iterator_selector` (the array to loop over), `output_selector` (path to the output collected from each iteration), and `start_node_id` (the iteration-start node id). The iteration-start node is a separate node of type `iteration-start` that lives inside the iteration subgraph:

```bash
dify-cli node add iteration --title "Loop" --id iter-1 \
  --field 'iterator_selector=["code-1","items"]' \
  --field 'output_selector=["code-2","result"]' \
  --field 'start_node_id=iter-start-1'
dify-cli node add iteration-start --title "Iter Start" --id iter-start-1
```



### Minimal LLM workflow

```bash
dify-cli init --mode workflow --name "My App" -o app.yaml --force
dify-cli node add start --title "Start" -f app.yaml
START_ID=$(dify-cli node list -f app.yaml | awk '$2=="start"{print $1; exit}')
dify-cli node add llm --title "Call GPT" \
  --field model.provider=openai \
  --field model.name=gpt-4o \
  -f app.yaml
LLM_ID=$(dify-cli node list -f app.yaml | awk '$2=="llm"{print $1; exit}')
dify-cli node add end --title "End" \
  --field "outputs=[{\"variable\":\"result\",\"value_selector\":[\"$LLM_ID\",\"text\"]}]" \
  -f app.yaml
END_ID=$(dify-cli node list -f app.yaml | awk '$2=="end"{print $1; exit}')
dify-cli edge add "$START_ID" "$LLM_ID" -f app.yaml
dify-cli edge add "$LLM_ID" "$END_ID" -f app.yaml
dify-cli validate app.yaml
```

Note: the LLM node only needs `model.provider` and `model.name` — `mode`, `completion_params.temperature`, `prompt_template`, `context`, `vision` all come from the frontend defaults template. Node ids are millisecond timestamps (matching the Dify frontend); use `node list` to look them up for edges and `value_selector`.

### Editing an existing node

```bash
# Look up the node id from `node list`
LLM_ID=$(dify-cli node list -f app.yaml | awk '$2=="llm"{print $1; exit}')

# Change the model on the LLM node
dify-cli node edit "$LLM_ID" --field model.name=gpt-4o-mini -f app.yaml

# Add a system prompt
dify-cli node edit "$LLM_ID" \
  --field 'prompt_template=[{"role":"system","text":"You are helpful."},{"role":"user","text":"{{#sys.query#}}"}]' \
  -f app.yaml
```

### Advanced-chat with conversation memory

```bash
dify-cli init --mode advanced-chat --name "Chatbot" -o chat.yaml --force
dify-cli var conversation set user_name --type string --description "Remembered name" -f chat.yaml
dify-cli var env set SYSTEM_PROMPT "You are a helpful assistant." -f chat.yaml
dify-cli node add start --title "Start" -f chat.yaml
START_ID=$(dify-cli node list -f chat.yaml | awk '$2=="start"{print $1; exit}')
dify-cli node add llm --title "Reply" \
  --field model.provider=openai --field model.name=gpt-4o \
  --field 'prompt_template=[{"role":"system","text":"{{#env.SYSTEM_PROMPT#}}"},{"role":"user","text":"{{#sys.query#}}"}]' \
  -f chat.yaml
LLM_ID=$(dify-cli node list -f chat.yaml | awk '$2=="llm"{print $1; exit}')
dify-cli node add answer --title "Answer" \
  --field "answer={{#$LLM_ID.text#}}" \
  -f chat.yaml
ANSWER_ID=$(dify-cli node list -f chat.yaml | awk '$2=="answer"{print $1; exit}')
dify-cli edge add "$START_ID" "$LLM_ID" -f chat.yaml
dify-cli edge add "$LLM_ID" "$ANSWER_ID" -f chat.yaml
dify-cli validate chat.yaml
```

Note: `var env set` takes `NAME VALUE` as positional args (not `--value`). `var conversation set` takes `NAME` positional plus `--type`/`--description` options.

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
