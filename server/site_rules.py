"""Owner-editable site rules: watch-room limits and defaults for new guests.

Stored sealed in the task store settings table under one key. Every reader
gets a complete, validated value: unknown or missing fields fall back to the
defaults below, which are the limits MediaVault enforced before rules existed.
"""
from pydantic import BaseModel, ConfigDict, Field

KEY = 'site-rules'


class RoomRules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    limit: int = Field(default=16, ge=1, le=64)
    perOwner: int = Field(default=2, ge=1, le=8)
    members: int = Field(default=8, ge=1, le=16)
    hours: int = Field(default=6, ge=1, le=48)
    guestsMayHost: bool = True


class GuestRules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    days: int = Field(default=30, ge=0, le=3650)
    watch: bool = True
    read: bool = True


class Rules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rooms: RoomRules = Field(default_factory=RoomRules)
    guests: GuestRules = Field(default_factory=GuestRules)


DEFAULTS = Rules().model_dump()


def current(store):
    """The stored rules merged over defaults; a damaged record never blocks the site."""
    value = store.setting(KEY) if store is not None else None
    if not isinstance(value, dict):
        return Rules().model_dump()
    merged = {section: {**DEFAULTS[section], **(value.get(section) or {})} for section in DEFAULTS}
    try:
        return Rules.model_validate(merged).model_dump()
    except ValueError:
        return Rules().model_dump()


def save(store, rules: Rules):
    value = rules.model_dump()
    store.setting(KEY, value)
    return value
