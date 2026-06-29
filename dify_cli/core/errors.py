class DifyCliError(Exception):
    pass


class SchemaNotFoundError(DifyCliError):
    def __init__(self, dsl_version: str, available: list[str]):
        super().__init__(
            f"No schema bundle for DSL version {dsl_version!r}. "
            f"Available: {', '.join(available) or 'none'}."
        )
        self.dsl_version = dsl_version
        self.available = available


class NodeValidationError(DifyCliError):
    def __init__(self, node_type: str, message: str, path: str | None = None):
        loc = f" at {path}" if path else ""
        super().__init__(f"Validation failed for node type {node_type!r}{loc}: {message}")
        self.node_type = node_type
        self.path = path


class GraphValidationError(DifyCliError):
    pass


class DslLoadError(DifyCliError):
    pass
