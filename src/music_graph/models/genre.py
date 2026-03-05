"""Genre/Tag model."""

from sqlmodel import Field, SQLModel

from music_graph.models.base import SourcePlatform


class Genre(SQLModel, table=True):
    """Genre or tag entity."""

    __tablename__ = "genre"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    source: SourcePlatform
