import json
import math

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import StatementError

from app.vector import Vector


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()], ids=["sqlite", "postgresql"])
def test_vector_preserves_valid_values_and_null(dialect) -> None:
    vector = Vector(4)
    values = [1.0, -0.5, 0.0, 2.0]

    encoded = vector.process_bind_param(values, dialect)

    assert json.loads(encoded) == values
    assert vector.process_result_value(encoded, dialect) == values
    assert vector.process_result_value(values, dialect) == values
    assert vector.process_bind_param(None, dialect) is None
    assert vector.process_result_value(None, dialect) is None
    assert vector.process_result_value(vector.process_bind_param([0.0] * 4, dialect), dialect) == [0.0] * 4


@pytest.mark.parametrize(
    "values",
    [
        [],
        [1.0] * 3,
        [1.0] * 5,
        [1.0, 2.0, 3.0, math.nan],
        [1.0, 2.0, 3.0, math.inf],
        [1.0, 2.0, 3.0, -math.inf],
        [1.0, 2.0, 3.0, True],
        [1.0, 2.0, 3.0, "4.0"],
        [1.0, 2.0, 3.0, [4.0]],
    ],
    ids=["empty", "too-short", "too-long", "nan", "infinity", "negative-infinity", "boolean", "numeric-string", "nested"],
)
@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()], ids=["sqlite", "postgresql"])
def test_vector_rejects_invalid_values_on_write_and_read(values, dialect) -> None:
    vector = Vector(4)

    with pytest.raises(ValueError):
        vector.process_bind_param(values, dialect)
    with pytest.raises(ValueError):
        vector.process_result_value(json.dumps(values), dialect)
    with pytest.raises(ValueError):
        vector.process_result_value(values, dialect)


def test_sqlite_storage_rolls_back_invalid_vector() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    memories = Table("memories", metadata, Column("id", Integer, primary_key=True), Column("embedding", Vector(4)))
    metadata.create_all(engine)

    with pytest.raises(StatementError, match="exactly 4"):
        with engine.begin() as connection:
            connection.execute(memories.insert(), {"id": 1, "embedding": [1.0] * 4})
            connection.execute(memories.insert(), {"id": 2, "embedding": [1.0] * 3})

    with engine.connect() as connection:
        assert connection.execute(select(memories.c.id)).all() == []
    engine.dispose()


def test_sqlite_rejects_malformed_legacy_vector_when_read() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    memories = Table("memories", metadata, Column("id", Integer, primary_key=True), Column("embedding", Vector(4)))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO memories VALUES (1, '[1.0, 2.0]')"))

    with engine.connect() as connection:
        with pytest.raises(ValueError, match="exactly 4"):
            connection.execute(select(memories.c.embedding)).scalar_one()
    engine.dispose()
