# Workflow Spec Authoring Guide

This document describes how to author `spec.json` for `dify-cli apply`. The spec is the single source of truth for a workflow - `apply` generates the DSL from it deterministically.

For the CLI commands themselves, see [SKILL.md](SKILL.md).

## Spec format

```json
{
  "mode": "workflow",
  "name": "My App",
  "dsl_version": "0.5.0",
  "description": "",
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
      "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
      "outputs": {"items": {"type": "array[object]"}}
    }},
    {"id": "iter", "type": "iteration", "title": "Loop", "fields": {
      "iterator_selector": ["code", "items"],
      "output_selector": ["inner", "upper"]
    }, "children": [
      {"id": "inner", "type": "code", "title": "Upper", "fields": {"code": "@/tmp/upper.py"}}
    ]},
    {"id": "end", "type": "end", "title": "End", "fields": {
      "outputs": [{"variable": "r", "value_selector": ["iter", "output"]}]
    }}
  ],
  "edges": [
    {"source": "start", "target": "code"},
    {"source": "code", "target": "iter"},
    {"source": "iter", "target": "end"}
  ]
}
```

### Top-level fields

- `mode` (required): `workflow` | `advanced-chat` (apply only supports graph-based modes)
- `name` (required): app name
- `dsl_version` (optional, default latest bundled): must match a bundled schema version
- `description` (optional): app description
- `environment_variables` (optional): list of `{name, value, value_type}` - `value` supports `@file`
- `conversation_variables` (optional): list of `{name, value_type, description, value}`
- `nodes` (required): list of node objects
- `edges` (required): list of edge objects

### Node object

- `id` (required): **stable string id** - becomes the node's id in the DSL (NOT a timestamp). Re-applying keeps ids stable so edges and `value_selector` references never break. Choose readable ids (`start`, `llm`, `end`).
- `type` (required): node type string (e.g. `start`, `llm`, `code`). List via `dify-cli node types`.
- `title` (required): the schema requires it.
- `fields` (optional): dict of field overrides - values support `@file`, dict/list, scalars.
- `children` (optional, iteration/loop only): nodes inside the container. The iteration-start/loop-start child is auto-created - do NOT list it. Children auto-get `parentId`/`isInIteration`.

### Edge object

- `source` / `target` (required): reference spec node ids
- `src_handle` (optional): for if-else branches, `"true"` / `"false"`. Default `"source"`.

### Key properties

- **Idempotent**: same spec -> byte-identical DSL every time (deterministic node ids, edge ids `<source>-<target>`, condition ids `<node>-cond-<index>`). Safe to re-apply after editing.
- **Three-layer separation**: spec (`spec.json`) describes structure; `@file` files hold multi-line content (code/prompts/URLs); the generated `dsl.yaml` is derived and never hand-edited.

## Spec field values and @file

Field values can be inline strings, numbers, booleans, arrays, or objects. For multi-line content (code, prompt_template) or sensitive values (URLs), use `@file` - a string value starting with `@` is replaced with the file's contents:

```json
{"id": "code", "type": "code", "fields": {
  "code": "@/tmp/parse.py",
  "prompt_template": "@/tmp/prompt.json"
}}
```

This keeps the spec clean and lets you edit code/prompts independently. Use the `write_file` tool to create these files. `@-` reads from stdin.

## Common node types

Full list via `dify-cli node types` (28 types). Most-used:

| Type | DSL string | Required fields (beyond defaults) |
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
| Iteration | `iteration` | `iterator_selector`, `output_selector` |
| Loop | `loop` | `loop_variables`, `break_conditions` |
| Agent | `agent` | `model`, `strategy`, `tools` |
| Answer | `answer` | `answer` (template string) |

## Variable model (what each node exposes)

`dify-cli spec validate` checks every `value_selector`/`variable_selector` against this model. A reference `["node_id", "var"]` is valid only if `node_id` exists, is in scope, and exposes `var`.

| Node type | Exposes | Scope note |
|---|---|---|
| start | `variables[].variable` | visible to all downstream |
| code | `outputs` keys | visible to all downstream |
| llm | `text` (+ structured_output keys) | visible to all downstream |
| http-request | `body`, `headers`, `status_code`, `files` | visible to all downstream |
| template-transform | `output` | visible to all downstream |
| variable-aggregator | `output` | visible to all downstream |
| knowledge-retrieval | `result` | visible to all downstream |
| question-classifier | `class_name` | visible to all downstream |
| parameter-extractor | `parameters[].name` | visible to all downstream |
| iteration | `item`, `index` (inside) / `output` (outside) | children reference item/index; external nodes reference output |
| loop | `loop_variables[].label` (inside AND outside) | children and external nodes reference loop_variables |
| end / answer | (none, sink) | - |
| tool / agent | (loose - not statically checked) | depends on runtime config |

**Scope rule**: a node is visible to the referencing node if the target is top-level, or both are in the same container. You **cannot reference a node inside an iteration/loop from outside it** - reference the container node instead (iteration exposes `output`, loop exposes its `loop_variables`).

**Exception**: `iteration.output_selector` legitimately points at an inner node (it names which inner output to collect) - this is the only field that can reach into a container.

## Node field gotchas

These field shapes are easy to get wrong. All examples show the spec `fields` value. When unsure, run `dify-cli schema node <type>` for the authoritative shape.

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

**iteration** requires `iterator_selector` (array to loop over) and `output_selector` (path to the inner node's output to collect). The iteration-start child is auto-created by `apply` - do NOT list it. Inner nodes go in `children` and reference `[<iteration_id>, "item"]`:
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

**loop** exposes its `loop_variables` (by `label`) to both inner children and outside nodes. `break_conditions` reference the loop's own variables, NOT child outputs:
```json
{"id": "loop", "type": "loop", "fields": {
  "loop_variables": [{"label": "counter", "var_type": "number", "value": "0", "value_type": "constant"}],
  "break_conditions": [{"variable_selector": ["loop", "counter"], "comparison_operator": "≥", "value": "5"}]
}}
```

**Comparison operators**: `contains`, `is`, `empty`, `not empty`, `=`, `≠`, `>`, `<`, `≥`, `≤`. Run `dify-cli schema enum if-else comparison_operator` for the full list.

**LLM `prompt_template`** is a JSON array of message objects. In the spec it's just a normal JSON value - no shell quoting issues:
```json
"fields": {
  "model": {"provider": "openai", "name": "gpt-4o"},
  "prompt_template": [
    {"role": "system", "text": "You are helpful. Use {{#start.input#}} as context."},
    {"role": "user", "text": "Summarize."}
  ]
}
```
For very long prompts, write the text to a file and reference with `@file`: `{"role": "system", "text": "@/tmp/system_prompt.txt"}`.

## Examples

### Minimal LLM workflow

```json
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

The LLM node only needs `model.provider` and `model.name` - `mode`, `completion_params.temperature`, `prompt_template`, `context`, `vision` come from the frontend defaults.

### Advanced-chat with conversation memory

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

### Changing the workflow

Edit `spec.json` (add/remove nodes, change fields, update edges) and re-run `spec validate` + `apply`. Never hand-edit the generated DSL. Example: change the model and add a system prompt by editing the llm node in the spec, then `dify-cli apply --spec spec.json -f app.yaml --force`.
