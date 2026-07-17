# Inspection Commands (read-only)

These commands inspect a generated DSL or bundled schema. They are not part of the primary build workflow (spec -> validate -> apply) but are useful for debugging and verification.

## `dify-cli version`

Prints CLI version and bundled DSL schema versions (same as `--version` flag).

```bash
dify-cli version
```

## `dify-cli schema types`

Lists all node types in the bundled schema (same as `dify-cli node types`).

```bash
dify-cli schema types
```

## `dify-cli node list`

Lists all nodes in a generated DSL file (id, type, title).

```bash
dify-cli node list [--file dsl.yaml]
```

## `dify-cli node show`

Shows one node's full JSON from a generated DSL.

```bash
dify-cli node show <node_id> [--file dsl.yaml]
```

## `dify-cli edge list`

Lists all edges in a generated DSL.

```bash
dify-cli edge list [--file dsl.yaml]
```

## `dify-cli var env list`

Lists environment variables in a generated DSL.

```bash
dify-cli var env list [--file dsl.yaml]
```

## `dify-cli var env get`

Gets one environment variable's value from a generated DSL.

```bash
dify-cli var env get <name> [--file dsl.yaml]
```

## `dify-cli var conversation list`

Lists conversation variables in a generated DSL.

```bash
dify-cli var conversation list [--file dsl.yaml]
```
