# Workflow Spec Authoring Guide

This document describes how to author `spec.json` for the two-phase workflow: **design stage** writes the spec (structure + IO contracts + dependencies), **implementation stage** fills each node's internal config (impl files).

## Two-phase model

- **Design stage**: author `spec.json` with node structure, IO declarations, dependencies (variable selectors), and `implementation_hint` for nodes that need internal config. Impl files don't exist yet. Run `dify-cli spec validate` to check structure.
- **Implementation stage**: for each node that needs internal config, a sub-agent generates the impl file. Run `dify-cli node check <id> --spec spec.json` to verify each node (impl path is derived by convention, no need to specify).
- **Apply**: `dify-cli apply` merges hoisted spec fields + impl file content, full-validates, generates DSL.

## Impl file convention

Impl files (node internal config) live at a convention-based path derived from the spec file:

```
<spec_dir>/<spec_basename>_impl/<node_id>.json
```

Examples:
- `spec.json` -> `impl/code.json`, `impl/llm.json`, ...
- `mitr_spec.json` -> `mitr_impl/code.json`, `mitr_impl/llm.json`, ...

**Node ids must match `[a-z0-9_-]+`** (lowercase alphanumerics, underscore, hyphen) - they're used directly as impl filenames. `spec validate` rejects invalid ids.

**Which nodes need impl files?** Most node types (code, llm, http-request, answer, tool, ...). These don't: `start`, `end`, `iteration`, `loop`, `document-extractor`, `if-else` - their required fields are all hoisted or have frontend defaults, so the spec layer is complete at design stage.

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
      "variables": [{"variable": "q", "label": "Query", "type": "text-input", "required": true}]
    },
    {
      "id": "code", "type": "code", "title": "Parse",
      "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
      "outputs": {"items": {"type": "array[string]"}},
      "_output_schema": {"items": {"element": "string"}},
      "implementation_hint": "把查询拆成关键词数组"
    },
    {
      "id": "iter", "type": "iteration", "title": "Loop",
      "iterator_selector": ["code", "items"],
      "output_selector": ["inner", "upper"],
      "children": ["inner"]
    },
    {
      "id": "inner", "type": "code", "title": "Upper",
      "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
      "outputs": {"upper": {"type": "string"}},
      "implementation_hint": "对每个 item 做大写转换"
    },
    },
    {
      "id": "end", "type": "end", "title": "End",
      "outputs": [{"variable": "r", "value_selector": ["iter", "output"]}]
    }
  ],
  "edges": [
    {"source": "start", "target": "code"},
    {"source": "code", "target": "iter"},
    {"source": "iter", "target": "end"}
  ]
}
```

Note: `start`/`end`/`iter` don't have `implementation_hint` (they don't need impl files). `code`/`inner` have `implementation_hint` to guide the implementation sub-agent.

### Top-level fields

- `mode` (required): `workflow` | `advanced-chat`
- `name` (required): app name
- `dsl_version` (optional, default latest bundled)
- `description` (optional)
- `environment_variables` (optional): list of `{name, value, value_type}` - `value_type` must be a SegmentType (`string`/`secret`/`number`/...), NOT `text`
- `conversation_variables` (optional): list of `{name, value_type, description, value}`
- `nodes` (required): list of node objects
- `edges` (required): list of edge objects

### Node object

- `id` (required): stable string id matching `[a-z0-9_-]+`. Used as impl filename. Re-apply keeps ids stable.
- `type` (required): node type string (`dify-cli node types` to list)
- `title` (required)
- **Hoisted IO/dependency fields** (per node type, see table below) - contain variable selectors or IO declarations, visible to `spec validate`
- `_output_schema` (optional): IO contract schema with field structure (apply ignores; for future test generation)
- `implementation_hint` (optional): natural-language description of what the node should do. Only for nodes that need impl files (code/llm/http/etc). apply ignores it; the implementation sub-agent reads it.
- `children` (iteration/loop only): list of child node **ids** (strings). Child nodes are defined at the same level as other nodes in `spec.nodes`, not nested.

### Hoisted fields per node type

Fields containing variable selectors or IO declarations are hoisted to the spec node top-level (NOT in impl files):

| Node type | Hoisted fields | Needs impl file? |
|---|---|---|
| start | `variables` | no |
| end | `outputs` | no |
| if-else | `cases` | no |
| iteration | `iterator_selector`, `output_selector` | no |
| loop | `loop_variables`, `break_conditions` | no |
| document-extractor | `variable_selector` | no |
| code | `variables`, `outputs` | yes |
| llm | `context` | yes |
| template-transform | `variables` | yes |
| variable-aggregator | `variables` | yes |
| knowledge-retrieval | `query_variable_selector` | yes |
| question-classifier | `query_variable_selector` | yes |
| parameter-extractor | `parameters`, `query` | yes |
| http-request, answer, tool, agent, ... | (none) | yes |

### Edge object

- `source` / `target` (required): spec node ids
- `src_handle` (optional): for if-else branches, `"true"` / `"false"`. Default `"source"`.

### Edge wiring rules for iteration/loop containers

`spec validate` enforces these rules:

1. **Container must NOT directly connect to its own child.** The iteration-start/loop-start node (auto-created by apply) handles subgraph entry - it auto-connects to child nodes with no incoming edges. Do NOT write `container -> child` edges.
   ```
   WRONG:  {"source": "iter", "target": "inner"}      # container -> own child
   RIGHT:  (omit - start node auto-connects to entry children)
   ```

2. **Child inside a container must NOT connect to an external node.** The container node's `output` is what external nodes reference. Use `container -> external` instead.
   ```
   WRONG:  {"source": "inner", "target": "end"}        # child -> external
   RIGHT:  {"source": "iter", "target": "end"}          # container -> external
   ```

3. **Edges between siblings (same container) are fine.**
   ```
   OK:     {"source": "inner_a", "target": "inner_b"}  # sibling -> sibling
   ```

### Key properties

- **Idempotent**: same spec + same impl files -> byte-identical DSL (deterministic ids, edge ids `<source>-<target>`, condition ids `<node>-cond-<index>`).
- **Design stage validates without impl files**: `spec validate` only checks hoisted fields (structure), not impl content.

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

## Impl file content (internal config)

The impl file holds internal node config - everything NOT hoisted. Examples:

- **code**: `{code_language, code}` (the actual Python/JS code)
- **llm**: `{model, prompt_template, vision, ...}` (model params + prompts)
- **http-request**: `{url, method, headers, body, ...}`
- **answer**: `{answer}` (template string, may contain `{{#node.var#}}`)
- **template-transform**: `{template}` (the template string; `variables` is hoisted)

Use the `write_file` tool to create impl files in the implementation stage. Template variable refs (`{{#node.var#}}`) inside impl files are checked by `node check` against the spec. If an impl file accidentally includes a hoisted field, it's silently dropped (spec wins).

## Node field gotchas

When unsure about a field's shape, run `dify-cli schema node <type>` (hoisted fields are excluded from the output - you see only what goes in the impl file).

**start `variables[]`** items require `variable`, `label`, `type`. `type`: `text-input`/`paragraph`/`number`/`select`/`file`/`file-list`/`json_object`. For `select`, add `options`. (hoisted)

**if-else `cases[].conditions[]`** uses `variable_selector` (NOT `variable`). `value` accepts string/array[string]/boolean/null - **not number**. (hoisted)

**http-request `headers`/`params`** are **strings** (one `key: value` per line), not objects. (impl)

**http-request `body`** is `{type, data}` where type is `none`/`form-data`/`x-www-form-urlencoded`/`raw-text`/`json`/`binary`. (impl)

**end `outputs[]`** items: `{variable, value_selector}`. (hoisted)

**variable-aggregator `variables`** is array of arrays (each inner array is a selector). (hoisted)

**code `variables[]`** items: `{variable, value_selector}`. (hoisted; `variable` is the Python param name)

**code `outputs`** is `{name: {type: SegmentType}}`. SegmentType: `string`/`number`/`object`/`array[string]`/`array[object]`/`array[number]`/`boolean`/`file`/`array[file]`/`secret`/`none`. (hoisted)

**code `code_language`** accepts only `python3` or `javascript` (NOT `python`; auto-corrected). (impl)

**iteration** requires `iterator_selector` + `output_selector` (hoisted). iteration-start child auto-created by apply - do NOT list it. `children` is a list of child node ids; child nodes are defined at the same level in `spec.nodes`. Inner nodes reference `[<iter_id>, "item"]`.

**loop** exposes `loop_variables[].label` (hoisted). `break_conditions` reference the loop's own variables, NOT child outputs.

**Comparison operators**: `contains`/`is`/`empty`/`not empty`/`=`/`≠`/`>`/`<`/`≥`/`≤`. Run `dify-cli schema enum if-else comparison_operator` for full list.

**LLM `prompt_template`** is a JSON array of `{role, text}`. (impl)

## Examples

### Minimal LLM workflow

Design spec (impl files don't exist yet):
```json
{
  "mode": "workflow", "name": "My App",
  "nodes": [
    {"id": "start", "type": "start", "title": "Start"},
    {"id": "llm", "type": "llm", "title": "Call GPT",
     "implementation_hint": "调用GPT生成回答"},
    {"id": "end", "type": "end", "title": "End",
     "outputs": [{"variable": "result", "value_selector": ["llm", "text"]}]}
  ],
  "edges": [
    {"source": "start", "target": "llm"},
    {"source": "llm", "target": "end"}
  ]
}
```

```bash
dify-cli spec validate --spec spec.json   # design stage: structure OK

# implementation stage: sub-agent generates impl/llm.json
# (impl path derived from spec name: spec.json -> impl/llm.json)
dify-cli node check llm --spec spec.json  # verifies impl/llm.json

dify-cli apply --spec spec.json -f app.yaml --force
dify-cli validate app.yaml
```

### Changing the workflow

Edit `spec.json` (structure/IO) and/or impl files (internal config), re-run `spec validate` + `apply`. Never hand-edit the generated DSL.
