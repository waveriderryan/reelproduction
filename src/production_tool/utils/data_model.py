from typing import List
from pydantic import BaseModel, Field


class Event(BaseModel):
    event_id: str = Field(description="ID of event")
    starting_timestamp: str = Field(description="Timestamp of the event with format hh:mm:ss")
    ending_timestamp: str = Field(description="Timestamp of the event with format hh:mm:ss")
    starting_frame: int = Field(description="Start frame of the event")
    ending_frame: int = Field(description="End frame of the event")
    description: str = Field(description="Description of the event")


class Events(BaseModel):
    events: List[Event] = Field(default_factory=list, description="List of events")
