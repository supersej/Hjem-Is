import logging
import aiohttp
import async_timeout
from datetime import timedelta, datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

DOMAIN = "hjem-is"

async def async_setup_entry(hass, entry, async_add_entities):
    lat = entry.data["latitude"]
    lng = entry.data["longitude"]
    selected_id = entry.data.get("selected_stop_id")
    
    # Opret og start coordinatoren
    coordinator = HjemIsCoordinator(hass, lat, lng)
    await coordinator.async_config_entry_first_refresh()

    entities = []
    
    if selected_id == "all":
        # "Hent alle" logik
        if coordinator.data:
            for stop in coordinator.data:
                raw_address = stop.get("address", "Ukendt")
                clean_address = raw_address.split(',')[0]
                entities.append(
                    HjemIsSensor(coordinator, stop["id"], clean_address)
                )
    else:
        # Enkelt stop logik
        address_name = entry.data.get("stop_address", f"Stop {selected_id}")
        entities.append(
            HjemIsSensor(coordinator, int(selected_id), address_name)
        )

    async_add_entities(entities)

class HjemIsCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, lat, lng):
        super().__init__(
            hass,
            _LOGGER,
            name="Hjem-IS API",
            # Vi starter konservativt med 6 timer. Dette ændres dynamisk efter første kald.
            update_interval=timedelta(hours=6),
        )
        self.lat = lat
        self.lng = lng

    async def _async_update_data(self):
        url = f"https://sms.hjem-is.dk/?coordinates[lat]={self.lat}&coordinates[lng]={self.lng}&format=json"
        async with async_timeout.timeout(10):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise UpdateFailed(f"Fejl ved hentning: {response.status}")
                    
                    data = await response.json()
                    
                    # --- DYNAMISK INTERVAL LOGIK ---
                    self._adjust_interval(data)
                    
                    return data

    def _adjust_interval(self, data):
        """Justerer opdateringshastigheden baseret på om bilen kommer i dag."""
        if not data or len(data) == 0:
            return

        # Vi tager datoen fra det første stop i listen (antager hele ruten køres samme dag)
        # JSON format: "arrival_date": "2026-01-26"
        next_visit_str = data[0].get("arrival_date")
        
        if next_visit_str:
            today_str = datetime.now().date().isoformat()
            
            if next_visit_str == today_str:
                # DET ER I DAG! Turbo mode aktiveret 🚀
                # Vi opdaterer hvert 15. minut for at fange forsinkelser/ankomster live
                if self.update_interval != timedelta(minutes=15):
                    _LOGGER.info("Hjem-IS kommer i dag! Opdateringsinterval sat op til 15 minutter.")
                    self.update_interval = timedelta(minutes=15)
            else:
                # Det er ikke i dag. Vi slapper af. 💤
                if self.update_interval != timedelta(hours=6):
                    _LOGGER.info("Hjem-IS kommer ikke i dag. Opdateringsinterval sat ned til 6 timer.")
                    self.update_interval = timedelta(hours=6)

class HjemIsSensor(SensorEntity):
    _attr_icon = "mdi:ice-cream-truck"
    _attr_has_entity_name = False

    def __init__(self, coordinator, my_stop_id, address_name):
        self.coordinator = coordinator
        self.my_stop_id = my_stop_id
        self._attr_unique_id = f"hjem_is_stop_{my_stop_id}"
        self._attr_name = f"Hjem-IS {address_name}"

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def _get_my_stop_data(self):
        data = self.coordinator.data
        if not data: return None
        for stop in data:
            if stop.get("id") == self.my_stop_id:
                return stop
        return None

    @property
    def state(self):
        stop = self._get_my_stop_data
        if stop:
            events = stop.get("upcoming_plan_events_dates", [])
            if events:
                return events[0].get("date")
        return "Ukendt"

    @property
    def extra_state_attributes(self):
        stop = self._get_my_stop_data
        if stop:
            return stop
        return {}

    async def async_update(self):
        await self.coordinator.async_request_refresh()