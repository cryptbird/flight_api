"""Pydantic schemas for validated flight ticket extraction output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FlightTicketData(BaseModel):
    """Structured flight ticket fields; all keys are required strings (may be empty)."""

    passenger_name: str = Field(..., description="Passenger full name as on ticket")
    pnr: str = Field(..., description="Booking reference / PNR")
    airline: str = Field(..., description="Airline name or code")
    flight_number: str = Field(..., description="Flight number, e.g. AI101")
    departure_airport: str = Field(..., description="Departure airport code or name")
    arrival_airport: str = Field(..., description="Arrival airport code or name")
    departure_time: str = Field(..., description="Scheduled departure time")
    arrival_time: str = Field(..., description="Scheduled arrival time")
    date: str = Field(..., description="Flight date")
    seat: str = Field(..., description="Seat assignment if present")
    gate: str = Field(..., description="Departure gate if present")
    price: str = Field(..., description="Fare or total price if present")

    model_config = {
        "extra": "forbid",
    }
