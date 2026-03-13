from abc import ABC, abstractmethod
from typing import Callable
from pawguard.models import LocationEvent


class BaseConnector(ABC):
    """
    Each connector normalizes tracker-specific data into a LocationEvent
    and calls on_location_received. Zero analysis happens here.
    """
    def __init__(self, pet_id: str, on_location_received: Callable[[LocationEvent], None]):
        self.pet_id = pet_id
        self.on_location_received = on_location_received
        self._running = False

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @property
    def is_running(self) -> bool:
        return self._running
