from typing import List, Literal
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


class HighFive(BaseModel):
    found_high_five: bool = Field(description="Whether person doing high five is found")
    starting_timestamp: str = Field(description="Timestamp of the starting of high five action with format hh:mm:ss")
    starting_frame: int = Field(description="Frame of the starting of high five action")
    highlight_timestamp: str = Field(description="Timestamp of the highlighted action")
    highlight_frame: int = Field(description="Frame of the highlighted action")
    ending_timestamp: str = Field(description="Timestamp of the ending of high five action with format hh:mm:ss")
    ending_frame: int = Field(description="Frame of the ending of high five action")
    hand: Literal["right", "left"] = Field(description="Hand used for high five action")
