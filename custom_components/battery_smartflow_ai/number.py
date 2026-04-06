from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    INTEGRATION_NAME,
    INTEGRATION_MANUFACTURER,
    INTEGRATION_MODEL,
    INTEGRATION_VERSION,
    # settings keys
    SETTING_BATTERY_PACKS,
    SETTING_SOC_MIN,
    SETTING_SOC_MAX,
    SETTING_MAX_CHARGE,
    SETTING_MAX_DISCHARGE,
    SETTING_PRICE_THRESHOLD,
    SETTING_VERY_EXPENSIVE_THRESHOLD,
    SETTING_EMERGENCY_SOC,
    SETTING_EMERGENCY_CHARGE,
    SETTING_PROFIT_MARGIN_PCT,
    SETTING_PEAK_FACTOR,
    SETTING_VALLEY_FACTOR,
    SETTING_VERY_CHEAP_PRICE,
    SETTING_PV_CHARGE_START_EXPORT_W,
    # defaults
    DEFAULT_BATTERY_PACKS,
    DEFAULT_SOC_MIN,
    DEFAULT_SOC_MAX,
    DEFAULT_MAX_CHARGE,
    DEFAULT_MAX_DISCHARGE,
    DEFAULT_PRICE_THRESHOLD,
    DEFAULT_VERY_EXPENSIVE_THRESHOLD,
    DEFAULT_EMERGENCY_SOC,
    DEFAULT_EMERGENCY_CHARGE,
    DEFAULT_PROFIT_MARGIN_PCT,
    DEFAULT_PEAK_FACTOR,
    DEFAULT_VALLEY_FACTOR,
    DEFAULT_VERY_CHEAP_PRICE,
    DEFAULT_PV_CHARGE_START_EXPORT_W,
)


@dataclass(frozen=True, kw_only=True)
class ZendureNumberEntityDescription(NumberEntityDescription):
    option_key: str
    default_value: float | int | None


NUMBERS: tuple[ZendureNumberEntityDescription, ...] = (
    ZendureNumberEntityDescription(
        key=SETTING_BATTERY_PACKS,
        translation_key=SETTING_BATTERY_PACKS,
        option_key=SETTING_BATTERY_PACKS,
        default_value=DEFAULT_BATTERY_PACKS,
        native_min_value=1,
        native_max_value=6,
        native_step=1,
        mode=NumberMode.BOX,
        icon="mdi:battery-multiple",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_SOC_MIN,
        translation_key=SETTING_SOC_MIN,
        option_key=SETTING_SOC_MIN,
        default_value=DEFAULT_SOC_MIN,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        mode=NumberMode.BOX,
        icon="mdi:battery-low",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_SOC_MAX,
        translation_key=SETTING_SOC_MAX,
        option_key=SETTING_SOC_MAX,
        default_value=DEFAULT_SOC_MAX,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        mode=NumberMode.BOX,
        icon="mdi:battery-high",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_MAX_CHARGE,
        translation_key=SETTING_MAX_CHARGE,
        option_key=SETTING_MAX_CHARGE,
        default_value=DEFAULT_MAX_CHARGE,
        native_min_value=0,
        native_max_value=3000,
        native_step=10,
        native_unit_of_measurement="W",
        mode=NumberMode.BOX,
        icon="mdi:battery-arrow-up",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_MAX_DISCHARGE,
        translation_key=SETTING_MAX_DISCHARGE,
        option_key=SETTING_MAX_DISCHARGE,
        default_value=DEFAULT_MAX_DISCHARGE,
        native_min_value=0,
        native_max_value=3000,
        native_step=10,
        native_unit_of_measurement="W",
        mode=NumberMode.BOX,
        icon="mdi:battery-arrow-down",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_PRICE_THRESHOLD,
        translation_key=SETTING_PRICE_THRESHOLD,
        option_key=SETTING_PRICE_THRESHOLD,
        default_value=DEFAULT_PRICE_THRESHOLD,
        native_min_value=0.00,
        native_max_value=2.00,
        native_step=0.01,
        native_unit_of_measurement="€/kWh",
        mode=NumberMode.BOX,
        icon="mdi:currency-eur",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_VERY_EXPENSIVE_THRESHOLD,
        translation_key=SETTING_VERY_EXPENSIVE_THRESHOLD,
        option_key=SETTING_VERY_EXPENSIVE_THRESHOLD,
        default_value=DEFAULT_VERY_EXPENSIVE_THRESHOLD,
        native_min_value=0.00,
        native_max_value=2.00,
        native_step=0.01,
        native_unit_of_measurement="€/kWh",
        mode=NumberMode.BOX,
        icon="mdi:currency-eur-off",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_EMERGENCY_SOC,
        translation_key=SETTING_EMERGENCY_SOC,
        option_key=SETTING_EMERGENCY_SOC,
        default_value=DEFAULT_EMERGENCY_SOC,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        mode=NumberMode.BOX,
        icon="mdi:alert",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_EMERGENCY_CHARGE,
        translation_key=SETTING_EMERGENCY_CHARGE,
        option_key=SETTING_EMERGENCY_CHARGE,
        default_value=DEFAULT_EMERGENCY_CHARGE,
        native_min_value=0,
        native_max_value=3000,
        native_step=10,
        native_unit_of_measurement="W",
        mode=NumberMode.BOX,
        icon="mdi:battery-alert",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_PROFIT_MARGIN_PCT,
        translation_key=SETTING_PROFIT_MARGIN_PCT,
        option_key=SETTING_PROFIT_MARGIN_PCT,
        default_value=DEFAULT_PROFIT_MARGIN_PCT,
        native_min_value=0,
        native_max_value=200,
        native_step=1,
        native_unit_of_measurement="%",
        mode=NumberMode.BOX,
        icon="mdi:percent",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_PEAK_FACTOR,
        translation_key=SETTING_PEAK_FACTOR,
        option_key=SETTING_PEAK_FACTOR,
        default_value=DEFAULT_PEAK_FACTOR,
        native_min_value=1.00,
        native_max_value=3.00,
        native_step=0.01,
        mode=NumberMode.BOX,
        icon="mdi:chart-line",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_VALLEY_FACTOR,
        translation_key=SETTING_VALLEY_FACTOR,
        option_key=SETTING_VALLEY_FACTOR,
        default_value=DEFAULT_VALLEY_FACTOR,
        native_min_value=0.10,
        native_max_value=1.50,
        native_step=0.01,
        mode=NumberMode.BOX,
        icon="mdi:chart-bell-curve-cumulative",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_VERY_CHEAP_PRICE,
        translation_key=SETTING_VERY_CHEAP_PRICE,
        option_key=SETTING_VERY_CHEAP_PRICE,
        default_value=DEFAULT_VERY_CHEAP_PRICE,
        native_min_value=-1.00,
        native_max_value=1.00,
        native_step=0.01,
        native_unit_of_measurement="€/kWh",
        mode=NumberMode.BOX,
        icon="mdi:cash-minus",
    ),
    ZendureNumberEntityDescription(
        key=SETTING_PV_CHARGE_START_EXPORT_W,
        translation_key=SETTING_PV_CHARGE_START_EXPORT_W,
        option_key=SETTING_PV_CHARGE_START_EXPORT_W,
        default_value=DEFAULT_PV_CHARGE_START_EXPORT_W,
        native_min_value=0,
        native_max_value=1000,
        native_step=10,
        native_unit_of_measurement="W",
        mode=NumberMode.BOX,
        icon="mdi:solar-power-variant",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities(
        ZendureSmartFlowNumber(entry, coordinator, description)
        for description in NUMBERS
    )


class ZendureSmartFlowNumber(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator,
        description: ZendureNumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry

        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{description.key}"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": INTEGRATION_NAME,
            "manufacturer": INTEGRATION_MANUFACTURER,
            "model": INTEGRATION_MODEL,
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | None:
        value = self._entry.options.get(
            self.entity_description.option_key,
            self.entity_description.default_value,
        )
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        new_options = dict(self._entry.options)
        new_options[self.entity_description.option_key] = float(value)

        self.hass.config_entries.async_update_entry(
            self._entry,
            options=new_options,
        )

        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
