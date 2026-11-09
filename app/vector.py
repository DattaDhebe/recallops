import json
import math
from numbers import Real
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
        return json.dumps(self._validated_values(value), separators=(",", ":"), allow_nan=False)

    def process_result_value(self, value: Any, dialect) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = json.loads(value)
        return self._validated_values(value)

    def _validated_values(self, value: Any) -> list[float]:
        if not isinstance(value, (list, tuple)) or len(value) != self.dimensions:
            raise ValueError(f"embedding must contain exactly {self.dimensions} numeric values")
        values = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, Real):
                raise ValueError("embedding values must be real numbers")
            try:
                number = float(item)
            except OverflowError as exc:
                raise ValueError("embedding values must be finite") from exc
            if not math.isfinite(number):
                raise ValueError("embedding values must be finite")
            values.append(number)
        return values
