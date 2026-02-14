from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import ZendureSmartFlowCoordinator

_LOGGER = logging.getLogger(__name__)

OLD_DOMAIN = "zendure_smartflow_ai"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Handle migration from old domain."""
    old_entries = hass.config_entries.async_entries(OLD_DOMAIN)

    if old_entries:
        _LOGGER.info("Migrating Zendure SmartFlow AI entries to Battery SmartFlow AI")

    for old_entry in old_entries:
        hass.async_create_task(_migrate_entry(hass, old_entry))

    return True


async def _migrate_entry(hass: HomeAssistant, old_entry: ConfigEntry) -> None:
    """Migrate old config entry to new domain."""
    _LOGGER.info("Migrating config entry %s to new domain %s", old_entry.entry_id, DOMAIN)

    data = dict(old_entry.data)
    options = dict(old_entry.options)

    new_entry = hass.config_entries.async_create_entry(
        title=old_entry.title,
        data=data,
        options=options,
        domain=DOMAIN,
    )

    await hass.config_entries.async_remove(old_entry.entry_id)

    if new_entry:
        await hass.config_entries.async_reload(new_entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    coordinator = ZendureSmartFlowCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator:
            await coordinator.async_shutdown()
    return unload_ok
