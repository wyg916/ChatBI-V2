from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ColumnMetadata:
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: bool = False
    default: str | None = None
    comment: str | None = None
    sample_values: list = field(default_factory=list)


@dataclass
class TableMetadata:
    schema: str
    name: str
    comment: str | None = None
    columns: list[ColumnMetadata] = field(default_factory=list)


@dataclass
class RelationMetadata:
    source_schema: str
    source_table: str
    source_columns: list[str]
    target_schema: str | None
    target_table: str
    target_columns: list[str]


@dataclass
class ConnectorMetadata:
    schemas: list[str] = field(default_factory=list)
    tables: list[TableMetadata] = field(default_factory=list)
    relations: list[RelationMetadata] = field(default_factory=list)


class DataSourceConnector(ABC):
    @abstractmethod
    def test_connection(self) -> None:
        """Raise an exception when the connection is not usable."""

    @abstractmethod
    def sync_metadata(self) -> ConnectorMetadata:
        """Read catalog metadata without scanning business rows."""
