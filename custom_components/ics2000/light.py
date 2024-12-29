"""Platform for light integration."""
from __future__ import annotations

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
        """Turn the light on with a possible brightness adjustment."""
        _LOGGER.info(f'Function turn_on called in thread {threading.current_thread().name}')

        # Ensure we are not firing actions too fast
        if self.is_on is None or not self.is_on:
            self._brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
            self._state = True  # Update state to ON
            # Perform the actions sequentially with a 0.5 second gap
            self._hub.turn_on(self._id)  # Turn on the device
            
            if self._brightness < 255:  # If not full brightness, adjust
                level = math.ceil(self._brightness / 17)  # Scale brightness to the device's expected range
                self._hub.dim(self._id, level)  # Dim the device to the appropriate level
                

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        _LOGGER.info(f'Function turn_off called in thread {threading.current_thread().name}')

        # Ensure we are not firing actions too fast
        self._state = False  # Update state to OFF
        self._hub.turn_off(self._id)  # Turn off the device
        

    def update(self) -> None:
        """Update the state of the device."""
        pass
