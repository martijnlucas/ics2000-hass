"""Platform for light integration."""
from __future__ import annotations

import queue
import time
import math
import logging
import time
import threading
import voluptuous as vol

from typing import Any
from ics2000.Core import Hub
from ics2000.Devices import Device, Dimmer
from enum import Enum

# Import the device class from the component that you want to support
import homeassistant.helpers.config_validation as cv
from homeassistant.components.light import ATTR_BRIGHTNESS, PLATFORM_SCHEMA, LightEntity, ColorMode
from homeassistant.const import CONF_PASSWORD, CONF_MAC, CONF_EMAIL,CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

_LOGGER = logging.getLogger(__name__)


def repeat(tries: int, sleep: int, callable_function, **kwargs):
    _LOGGER.info(f'Function repeat called in thread {threading.current_thread().name}')
    qualname = getattr(callable_function, '__qualname__')
    for i in range(0, tries):
        _LOGGER.info(f'Try {i + 1} of {tries} on {qualname}')
        callable_function(**kwargs)
        time.sleep(sleep if i != tries - 1 else 0)


# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MAC): cv.string,
    vol.Required(CONF_EMAIL): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional('tries'): cv.positive_int,
    vol.Optional('sleep'): cv.positive_int,
    vol.Optional(CONF_IP_ADDRESS): cv.matches_regex(r'[1-9][0-9]{0,2}(\.(0|[1-9][0-9]{0,2})){2}\.[1-9][0-9]{0,2}'),
    vol.Optional('aes'): cv.matches_regex(r'[a-zA-Z0-9]{32}')
})


def setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the ICS2000 Light platform."""
    # Assign configuration variables.
    # The configuration check takes care they are present.
    # Setup connection with devices/cloud
    hub = Hub(
        config[CONF_MAC],
        config[CONF_EMAIL],
        config[CONF_PASSWORD]
    )

    # Verify that passed in configuration works
    if not hub.connected:
        _LOGGER.error("Could not connect to ICS2000 hub")
        return

    # Add devices
    add_entities(KlikAanKlikUitDevice(
        device=device,
        tries=int(config.get('tries', 1)),
        sleep=int(config.get('sleep', 3))
    ) for device in hub.devices)


class KlikAanKlikUitAction(Enum):
    TURN_ON = 'on'
    TURN_OFF = 'off'
    DIM = 'dim'


class KlikAanKlikUitThread(threading.Thread):
    def __init__(self):
        super().__init__(name="KlikAanKlikUitWorker")
        self.task_queue = queue.Queue()
        self.stop_event = threading.Event()
    
    def run(self):
        while not self.stop_event.is_set():
            try:
                # Wait for a task with a timeout
                task = self.task_queue.get(timeout=1)
                self.process_task(task)
                self.task_queue.task_done()
            except queue.Empty:
                # No task to process, loop continues
                continue
    
    def process_task(self, task):
        device_id = task.get("device_id")
        action = task.get("action")
        params = task.get("params", {})
        print(f"Processing action '{action}' for device '{device_id}' with params: {params}")
        # Simulate action processing
        time.sleep(0.5)  # Simulate some delay

    def has_running_threads(self, device_id) -> bool:
        # Check if any pending tasks in the queue are for the given device_id
        with self.task_queue.mutex:
            return any(task.get("device_id") == device_id for task in self.task_queue.queue)

    def add_task(self, device_id, action, params=None):
        if not self.has_running_threads(device_id):
            task = {"device_id": device_id, "action": action, "params": params or {}}
            self.task_queue.put(task)
    
    def stop(self):
        self.stop_event.set()


class KlikAanKlikUitDevice(LightEntity):
    """Representation of a KlikAanKlikUit device"""

    def __init__(self, device: Device, tries: int, sleep: int) -> None:
        """Initialize a KlikAanKlikUitDevice"""
        self.tries = tries
        self.sleep = sleep
        self._name = device.name
        self._id = device.id
        self._hub = device.hub
        self._state = None
        self._brightness = None
        if Dimmer == type(device):
            _LOGGER.info(f'Adding dimmer with name {device.name}')
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        else:
            _LOGGER.info(f'Adding device with name {device.name}')
            self._attr_color_mode = ColorMode.ONOFF
            self._attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def name(self) -> str:
        """Return the display name of this light."""
        return self._name

    @property
    def brightness(self):
        """Return the brightness of the light.

        This method is optional. Removing it indicates to Home Assistant
        that brightness is not supported for this light.
        """
        return self._brightness

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self._state

    def turn_on(self, **kwargs: Any) -> None:
        _LOGGER.info(f'Function turn_on called in thread {threading.current_thread().name}')
    
        # Check if the centralized thread is running
        if not hasattr(self, 'worker_thread') or not self.worker_thread.is_alive():
            _LOGGER.error("Worker thread is not running. Please start the KlikAanKlikUitThread.")
            return

        # Avoid adding tasks if tasks are already in progress for this device
        if KlikAanKlikUitThread.has_running_threads(self._id):
            return

        self._brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
    
        if self.is_on is None or not self.is_on:
            # Add TURN_ON task to the centralized worker thread
            self.worker_thread.add_task(
                device_id=self._id,
                action=KlikAanKlikUitAction.TURN_ON,
                params={
                    'tries': self.tries,
                    'sleep': self.sleep,
                    'callable_function': self._hub.turn_on,
                    'entity': self._id
                }
            )
        else:
            # KlikAanKlikUit brightness goes from 1 to 15 so divide by 17
            self.worker_thread.add_task(
                device_id=self._id,
                action=KlikAanKlikUitAction.DIM,
                params={
                    'tries': self.tries,
                    'sleep': self.sleep,
                    'callable_function': self._hub.dim,
                    'entity': self._id,
                    'level': math.ceil(self.brightness / 17)
                }
            )
    
        self._state = True


    def turn_off(self, **kwargs: Any) -> None:
        _LOGGER.info(f'Function turn_off called in thread {threading.current_thread().name}')
    
        # Check if the centralized thread is running
        if not hasattr(self, 'worker_thread') or not self.worker_thread.is_alive():
            _LOGGER.error("Worker thread is not running. Please start the KlikAanKlikUitThread.")
            return

        # Avoid adding tasks if tasks are already in progress for this device
        if KlikAanKlikUitThread.has_running_threads(self._id):
            return

        # Add TURN_OFF task to the centralized worker thread
        self.worker_thread.add_task(
            device_id=self._id,
            action=KlikAanKlikUitAction.TURN_OFF,
            params={
                'tries': self.tries,
                'sleep': self.sleep,
                'callable_function': self._hub.turn_off,
                'entity': self._id
            }
        )
        self._state = False

    def update(self) -> None:
        pass
