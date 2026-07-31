import json
from typing import Any

from sqlalchemy.types import Text, TypeDecorator, UserDefinedType


class _CockroachVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"VECTOR({self.dimensions})"


class Vector(TypeDecorator):
    """CockroachDB VECTOR in production and JSON text in local SQLite."""

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int):
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_CockroachVector(self.dimensions))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect) -> str | None:
        if value is None:
            return None
        return json.dumps(value, separators=(",", ":"))

    def process_result_value(self, value: Any, dialect) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return [float(item) for item in json.loads(value)]
        return [float(item) for item in value]
