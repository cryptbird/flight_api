"""Pydantic schemas for validated flight ticket extraction output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Passenger(BaseModel):
    passengerId: int = Field(..., description="1-based passenger index")
    firstName: str = Field(..., description="Passenger first name")
    lastName: str = Field(..., description="Passenger last name")
    type: str = Field(..., description="Passenger type like ADT/CHD/INF if present, else empty string")
    ticketNumber: str = Field(..., description="Ticket / e-ticket number if present, else empty string")
    seatNumber: str = Field(..., description="Seat number if present, else empty string")

    model_config = {"extra": "forbid"}


class AirportStop(BaseModel):
    airportCode: str = Field(..., description="IATA airport code (or empty string)")
    city: str = Field(..., description="City name if present, else empty string")
    terminal: str = Field(..., description="Terminal if present, else empty string")
    dateTime: str = Field(
        ...,
        description="ISO-8601 local date-time like 2026-01-11T18:15:00; empty string if unknown",
    )

    model_config = {"extra": "forbid"}


class FlightSegment(BaseModel):
    segmentId: int = Field(..., description="1-based segment index")
    airlineName: str = Field(..., description="Airline name if present, else empty string")
    airlineCode: str = Field(..., description="Airline code like SG if present, else empty string")
    flightNumber: str = Field(..., description="Flight number like SG651 if present, else empty string")
    departure: AirportStop
    arrival: AirportStop
    travelClass: str = Field(..., description="Travel cabin/class like Economy if present, else empty string")
    bookingClass: str = Field(..., description="Booking class if present, else empty string")
    status: str = Field(..., description="Status like Confirmed if present, else empty string")

    model_config = {"extra": "forbid"}


class FlightTicketData(BaseModel):
    """
    Extracted ticket data in the format expected by the client.

    All string fields must be present in the JSON (use "" when unknown).
    """

    pnr: str = Field(..., description="Booking reference / PNR")
    bookingDate: str = Field(
        ...,
        description="ISO-8601 date like 2026-11-12T00:00:00; empty string if unknown",
    )
    passengers: list[Passenger] = Field(..., description="All passengers listed on the ticket")
    flightDetails: list[FlightSegment] = Field(..., description="One entry per flight segment")

    model_config = {"extra": "forbid"}
