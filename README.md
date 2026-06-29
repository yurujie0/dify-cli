# dify-cli

Command-line tool for authoring [Dify](https://github.com/langgenius/dify) DSL (workflow / chatflow) YAML files. Build and edit workflows as code — init a scaffold, add/edit/remove nodes and edges, manage variables, then validate before importing into Dify.

The CLI is **schema-driven**: node field definitions are loaded from pre-generated JSON Schema bundles keyed by DSL version (`dify_cli/schemas/v<ver>.json`). When Dify upgrades the DSL, only a new schema bundle needs to be regenerated and shipped — the CLI code itself does not need to change.

> **Note:** This is an independent project and is not affiliated with the Dify team. "Dify" is a trademark of its respective owners.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python >= 3.11.

## Usage

```bash
dify-cli init --mode workflow --name my-app -o dsl.yaml
dify-cli node add start --title "Start" --id start-1
dify-cli node add llm --title "Call GPT" \
  --field model.provider=openai \
  --field model.name=gpt-4o \
  --field model.mode=chat \
  --field 'context={"enabled": false}' \
  --field 'prompt_template=[{"role":"user","text":"hi"}]'
dify-cli node add end --title "End" --field 'outputs=[]'
dify-cli edge add start-1 <llm-id>
dify-cli var env set API_KEY sk-xxx
dify-cli validate
dify-cli version
```

### Commands

| Command | Description |
|---|---|
| `init` | Scaffold a new DSL file (modes: workflow, advanced-chat, chat, completion, agent-chat) |
| `node add/list/show/edit/remove/types` | Node CRUD; `--field key=value` supports dotted keys and JSON values |
| `edge add/list/remove` | Edge management |
| `var env/conversation set/get/list/remove` | Environment & conversation variables |
| `validate` | Validate top-level shape, every node's schema, and graph topology |
| `version` | Print CLI version and bundled DSL schema versions |

## How schemas work

Each DSL version has a bundle at `dify_cli/schemas/v<ver>.json` containing:
- `dsl_version` — the version string
- `top_schema` — JSON Schema for the DSL top-level structure
- `node_types` — `{node_type: json_schema}` for every node type

The CLI loads the bundle matching the DSL file's `version:` field. To support a new Dify DSL version, drop in a new `v<ver>.json` — no code changes needed.

## Regenerating schemas (contributors)

Schemas are extracted from the Dify backend's Pydantic node-data models. Run against a working `dify-api` environment from the Dify repo root:

```bash
uv run --project api python /path/to/dify-cli/scripts/extract_schemas.py --out dify_cli/schemas/v0.5.0.json
```

The current bundled `v0.5.0.json` is a hand-authored fallback covering common node types with loose validation (`additionalProperties: true`). Running the extract script against a real Dify environment produces a fully exhaustive, field-accurate schema.

## License

Apache-2.0
