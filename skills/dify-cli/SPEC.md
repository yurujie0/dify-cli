# Workflow Spec Authoring Guide

This document describes how to author `spec.json` for the two-phase workflow: **design stage** writes the spec (structure + IO contracts + dependencies), **implementation stage** fills each node's internal config (`@file`). See [SKILL.md](SKILL.md) for CLI commands.

## Two-phase model

- **Design stage**: author `spec.json` with node structure, IO declarations, dependencies (variable selectors), and `@file` references for internal config (files don't exist yet). Run `dify-cli spec validate` to check structure.
- **Implementation stage**: for each node, a sub-agent generates the `@file` (internal config: code, prompt_template, model params). Run `dify-cli node check <id> --spec spec.json --fields <file>` to verify each node.
- **Apply**: `dify-cli apply` merges hoisted spec fields + `@file` content, full-validates, generates DSL.

## Spec format

```json
{
  "mode": "workflow",
  "name": "My App",
  "dsl_version": "0.5.0",
  "description": "",
  "environment_variables": [
    {"name": "API_KEY", "value": "sk-xxx"}
  ],
  "conversation_variables": [
    {"name": "memory", "value_type": "string", "description": "user memory"}
  ],
  "nodes": [
    {
      "id": "start", "type": "start", "title": "Start",
      "variables": [{"variable": "q", "label": "Query", "type": "text-input", "required": true}],
      "implementation_hint": "用户输入查询字符串",
      "fields": "@/tmp/impl/start.json"
    },
    {
      "id": "code", "type": "code", "title": "Parse",
      "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
      "outputs": {"items": {"type": "array[string]"}},
      "_output_schema": {"items": {"element": "string"}},
      "implementation_hint": "把查询拆成关键词数组",
      "fields": "@/tmp/impl/code.json"
    },
    {
      "id": "iter", "type": "iteration", "title": "Loop",
      "iterator_selector": ["code", "items"],
      "output_selector": ["inner", "upper"],
      "fields": "@/tmp/impl/iter.json",
      "children": [
        {"id": "inner", "type": "code", "title": "Upper",
         "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
         "outputs": {"upper": {"type": "string"}},
         "fields": "@/tmp/impl/inner.json"}
      ]
    },
    {
      "id": "end", "type": "end", "title": "End",
      "outputs": [{"variable": "r", "value_selector": ["iter", "output"]}],
      "fields": "@/tmp/impl/end.json"
    }
  ],
  "edges": [
    {"source": "start", "target": "code"},
    {"source": "code", "target": "iter"},
    {"source": "iter", "target": "end"}
  ]
}
```

### Top-level fields

- `mode` (required): `workflow` | `advanced-chat`
- `name` (required): app name
- `dsl_version` (optional, default latest bundled)
- `description` (optional)
- `environment_variables` (optional): list of `{name, value, value_type}`
- `conversation_variables` (optional): list of `{name, value_type, description, value}`
- `nodes` (required): list of node objects
- `edges` (required): list of edge objects

### Node object - field layering

Each node has two layers:

**Spec layer** (design stage, visible to `spec validate`):
- `id` (required): stable string id (NOT a timestamp). Re-apply keeps ids stable.
- `type` (required): node type string (`dify-cli node types` to list)
- `title` (required)
- **Hoisted IO/dependency fields** (per node type, see table below) - contain variable selectors or IO declarations
- `_output_schema` (optional): IO contract schema with field structure (apply ignores; for future test generation)
- `implementation_hint` (optional): natural-language description of what the node should do (apply ignores; passed to the implementation sub-agent)
- `fields`: `@file` reference (string) or inline dict - the node's internal config

**@file layer** (implementation stage, the `fields` content):
- Internal config only (code, prompt_template, model params, url, headers, etc.)
- Must NOT contain hoisted fields (they live at spec layer)
- No cross-node variable selectors (those are hoisted); template refs `{{#node.var#}}` are OK (checked by `node check`)

### Hoisted fields per node type

Fields containing variable selectors or IO declarations are hoisted to spec layer (not in `@file`):

| Node type | Hoisted fields | Why |
|---|---|---|
| start | `variables` | input declaration (what the node exposes) |
| code | `variables`, `outputs` | input deps + output declaration |
| end | `outputs` | workflow outputs (contain value_selector) |
| llm | `context` | contains variable_selector |
| if-else | `cases` | conditions contain variable_selector |
| iteration | `iterator_selector`, `output_selector` | deps |
| loop | `loop_variables`, `break_conditions` | state declaration + condition deps |
| template-transform | `variables` | contains value_selector |
| variable-aggregator | `variables` | selector array |
| knowledge-retrieval | `query_variable_selector` | dep |
| question-classifier | `query_variable_selector` | dep |
| parameter-extractor | `parameters`, `query` | output declaration + dep |
| http-request, answer, tool, agent, ... | (none) | all internal config, goes in @file |

### Edge object

- `source` / `target` (required): spec node ids
- `src_handle` (optional): for if-else branches, `"true"` / `"false"`. Default `"source"`.

### Key properties

- **Idempotent**: same spec + same @files -> byte-identical DSL (deterministic ids, edge ids `<source>-<target>`, condition ids `<node>-cond-<index>`).
- **Design stage can validate without @file**: `spec validate` only checks hoisted fields (structure), not @file content.

## Variable model (what each node exposes)

`spec validate` and `node check` check every `value_selector`/`variable_selector` against this model.

| Node type | Exposes | Scope note |
|---|---|---|
| start | `variables[].variable` | visible to all downstream |
| code | `outputs` keys | visible to all downstream |
| llm | `text` | visible to all downstream |
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

**Scope rule**: a node is visible to the referencing node if the target is top-level, or both are in the same container. You **cannot reference a node inside an iteration/loop from outside it** - reference the container node instead.

**Exception**: `iteration.output_selector` legitimately points at an inner node.

## @file content (internal config)

The `@file` (fields) holds internal node config. Examples of what goes in @file (NOT hoisted):

- **code**: `{code_language, code}` (the actual Python/JS code)
- **llm**: `{model, prompt_template, vision, ...}` (model params + prompts)
- **http-request**: `{url, method, headers, body, ...}`
- **answer**: `{answer}` (template string, may contain `{{#node.var#}}`)
- **template-transform**: `{template}` (the template string; `variables` is hoisted)

Use the `write_file` tool to create these files in the implementation stage. Template variable refs (`{{#node.var#}}`) inside @file are checked by `node check` against the spec.

## Node field gotchas

When unsure about a field's shape, run `dify-cli schema node <type>`.

**start `variables[]`** items require `variable`, `label`, `type`. `type`: `text-input`/`paragraph`/`number`/`select`/`file`/`file-list`/`json_object`. For `select`, add `options`. (hoisted)

**if-else `cases[].conditions[]`** uses `variable_selector` (NOT `variable`). `value` accepts string/array[string]/boolean/null - **not number**. (hoisted)

**http-request `headers`/`params`** are **strings** (one `key: value` per line), not objects. (@file)

**http-request `body`** is `{type, data}` where type is `none`/`form-data`/`x-www-form-urlencoded`/`raw-text`/`json`/`binary`. (@file)

**end `outputs[]`** items: `{variable, value_selector}`. (hoisted)

**variable-aggregator `variables`** is array of arrays (each inner array is a selector). (hoisted)

**code `variables[]`** items: `{variable, value_selector}`. (hoisted; `variable` is the Python param name)

**code `outputs`** is `{name: {type: SegmentType}}`. SegmentType: `string`/`number`/`object`/`array[string]`/`array[object]`/`array[number]`/`boolean`/`file`/`array[file]`/`secret`/`none`. (hoisted)

**code `code_language`** accepts only `python3` or `javascript` (NOT `python`; auto-corrected). (@file)

**iteration** requires `iterator_selector` + `output_selector` (hoisted). iteration-start child auto-created by apply - do NOT list it. Inner nodes in `children` reference `[<iter_id>, "item"]`.

**loop** exposes `loop_variables[].label` (hoisted). `break_conditions` reference the loop's own variables, NOT child outputs.

**Comparison operators**: `contains`/`is`/`empty`/`not empty`/`=`/`≠`/`>`/`<`/`≥`/`≤`. Run `dify-cli schema enum if-else comparison_operator` for full list.

**LLM `prompt_template`** is a JSON array of `{role, text}`. (@file) For long prompts, `@file` the whole fields file.

## Examples

### Minimal LLM workflow

Design spec:
```json
{
  "mode": "workflow", "name": "My App",
  "nodes": [
    {"id": "start", "type": "start", "title": "Start", "fields": "@/tmp/impl/start.json"},
    {"id": "llm", "type": "llm", "title": "Call GPT",
     "fields": "@/tmp/impl/llm.json"},
    {"id": "end", "type": "end", "title": "End",
     "outputs": [{"variable": "result", "value_selector": ["llm", "text"]}],
     "fields": "@/tmp/impl/end.json"}
  ],
  "edges": [
    {"source": "start", "target": "llm"},
    {"source": "llm", "target": "end"}
  ]
}
```

```bash
dify-cli spec validate --spec spec.json   # design stage: structure OK

# implementation stage: sub-agents generate @files
# /tmp/impl/llm.json: {"model": {"provider":"openai","name":"gpt-4o"}, "prompt_template":[...]}
dify-cli node check llm --spec spec.json --fields /tmp/impl/llm.json

dify-cli apply --spec spec.json -f app.yaml --force
dify-cli validate app.yaml
```

### Changing the workflow

Edit `spec.json` (structure/IO) and/or the `@file` (internal config), re-run `spec validate` + `apply`. Never hand-edit the generated DSL.
