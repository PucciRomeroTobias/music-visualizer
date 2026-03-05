"""Match candidate model for cross-platform entity resolution."""

import enum

from sqlmodel import Field, SQLModel


class MatchMethod(str, enum.Enum):
    """Method used to determine a match."""

    ISRC = "isrc"
    MUSICBRAINZ = "musicbrainz"
    FUZZY = "fuzzy"
    EXACT = "exact"


class MatchStatus(str, enum.Enum):
    """Status of a match candidate."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class MatchCandidate(SQLModel, table=True):
    """Candidate match between two source records."""

    __tablename__ = "match_candidate"

    id: int | None = Field(default=None, primary_key=True)
    entity_type: str  # "track" or "artist"
    source_a_id: int = Field(index=True)
    source_b_id: int = Field(index=True)
    method: MatchMethod
    confidence: float
    status: MatchStatus = Field(default=MatchStatus.PENDING)
    resolved_entity_id: str | None = None
