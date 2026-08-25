from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Station
from ..security import get_current_user
from ..services import registry

router = APIRouter(prefix="/stations", tags=["stations"])


def _wire(station: Station, snapshot=None) -> dict:
    # The live registry is keyed by station_code (ST-001) — what the hardware
    # publishes; the DB row id is a separate stable key.
    live = snapshot or registry.get(station.station_code) or registry.get(station.id)
    base = {
        "id": station.id,
        "station_code": station.station_code,
        "name": station.name,
        "status": live.status if live else station.status,
        # Ecolamp station metadata: the CARRIAGE sorting mechanism.
        "mechanism": getattr(station, "mechanism", None) or "carriage",
    }
    if live is not None:
        base["carriage_position"] = live.carriage_position
        base["state"] = live.state
        base["weight_grams"] = round(live.weight_grams, 2)
        base["beam_broken"] = live.beam_broken
        base["door_state"] = live.door_state
        base["compartment_status"] = live.compartment_readiness()
        base["operation_id"] = live.operation_id
        base["last_seen"] = live.last_seen
    return base


@router.get("")
def list_stations(
    _user=Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    stations = list(db.execute(select(Station).order_by(Station.station_code)).scalars())
    return {"items": [_wire(s, registry.get(s.station_code)) for s in stations]}


@router.get("/{station_id}")
def get_station(
    station_id: str,
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status_code=404, detail="This station could not be found.")
    return _wire(station, registry.get(station.station_code))


@router.get("/{station_id}/status")
def station_status(
    station_id: str,
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status_code=404, detail="This station could not be found.")
    snapshot = registry.get(station.station_code)
    if snapshot is None:
        return {
            "station_id": station.id,
            "station_code": station.station_code,
            "status": station.status,
            "state": "UNKNOWN",
            "carriage_position": 0,
            "last_seen": None,
        }
    return snapshot.to_dict()