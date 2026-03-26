from __future__ import annotations

from datetime import datetime
from typing import Any

from ..base import (
    PluginContext,
    PluginField,
    PluginFieldOption,
    PluginManifest,
    PluginRefreshResult,
    ScreenPlugin,
)

OPEN_METEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
OPEN_METEO_GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'

WEATHER_CODE_LABELS = {
    0: 'CLEAR',
    1: 'MAINLYCLEAR',
    2: 'PARTLYCLOUDY',
    3: 'OVERCAST',
    45: 'FOG',
    48: 'RIMEFOG',
    51: 'LIGHTDRIZZLE',
    53: 'DRIZZLE',
    55: 'HEAVYDRIZZLE',
    56: 'FREEZEDRIZZLE',
    57: 'DENSEFRZDRIZ',
    61: 'LIGHTRAIN',
    63: 'RAIN',
    65: 'HEAVYRAIN',
    66: 'FREEZERAIN',
    67: 'HEAVYFRZRAIN',
    71: 'LIGHTSNOW',
    73: 'SNOW',
    75: 'HEAVYSNOW',
    77: 'SNOWGRAINS',
    80: 'RAINSHOWERS',
    81: 'HVRYSHOWERS',
    82: 'VIOLENTRAIN',
    85: 'SNOWSHOWERS',
    86: 'HVYSNWSHOWR',
    95: 'TSTORM',
    96: 'TSTRMHAIL',
    99: 'HVYHAIL',
}


class OpenMeteoForecastPlugin(ScreenPlugin):
    manifest = PluginManifest(
        plugin_id='weatherbit_forecast',
        name='Open-Meteo 3 Day Forecast',
        description='Fetch a three day weather forecast from Open-Meteo and render it as a screen.',
        default_refresh_interval_seconds=3600,
        settings_schema=(
            PluginField(
                name='city',
                label='City',
                field_type='text',
                required=True,
                placeholder='London',
            ),
            PluginField(
                name='country',
                label='Country Code',
                field_type='text',
                required=True,
                placeholder='GB',
                help_text='Use a 2 letter country code.',
            ),
            PluginField(
                name='units',
                label='Units',
                field_type='select',
                default='M',
                options=(
                    PluginFieldOption(label='Metric (C)', value='M'),
                    PluginFieldOption(label='Imperial (F)', value='I'),
                ),
            ),
        ),
        design_schema=(
            PluginField(
                name='title',
                label='Title Override',
                field_type='text',
                default='',
                placeholder='3 DAY LONDON',
            ),
            PluginField(
                name='showConditions',
                label='Show Conditions',
                field_type='checkbox',
                default=True,
            ),
        ),
    )

    async def refresh(
        self,
        *,
        settings: dict[str, Any],
        design: dict[str, Any],
        context: PluginContext,
        http_session,
        previous_state=None,
        common_settings=None,
    ) -> PluginRefreshResult:
        city = str(settings.get('city', '')).strip()
        country = str(settings.get('country', '')).strip().upper()
        units = str(settings.get('units', 'M')).strip().upper() or 'M'

        if not city:
            raise ValueError('Open-Meteo city is required.')

        if not country:
            raise ValueError('Open-Meteo country code is required.')

        async with http_session.get(
            OPEN_METEO_GEOCODING_URL,
            params={
                'name': city,
                'count': 1,
                'language': 'en',
                'countryCode': country,
            },
        ) as geocoding_response:
            geocoding_payload = await geocoding_response.json(content_type=None)
            if not geocoding_response.ok:
                error = geocoding_payload.get('reason') if isinstance(geocoding_payload, dict) else None
                raise ValueError(error or 'Open-Meteo geocoding request failed.')

        results = geocoding_payload.get('results') if isinstance(geocoding_payload, dict) else None
        if not isinstance(results, list) or len(results) == 0:
            raise ValueError('Open-Meteo could not find that city/country combination.')

        location = results[0]
        temperature_unit = 'fahrenheit' if units == 'I' else 'celsius'

        async with http_session.get(
            OPEN_METEO_FORECAST_URL,
            params={
                'latitude': location.get('latitude'),
                'longitude': location.get('longitude'),
                'daily': 'weather_code,temperature_2m_max,temperature_2m_min',
                'forecast_days': 3,
                'temperature_unit': temperature_unit,
                'timezone': location.get('timezone') or 'auto',
            },
        ) as response:
            payload = await response.json(content_type=None)
            if not response.ok:
                error = payload.get('reason') if isinstance(payload, dict) else None
                raise ValueError(error or 'Open-Meteo forecast request failed.')

        daily = payload.get('daily') if isinstance(payload, dict) else None
        if not isinstance(daily, dict):
            raise ValueError('Open-Meteo did not return daily forecast data.')

        dates = daily.get('time')
        max_temps = daily.get('temperature_2m_max')
        min_temps = daily.get('temperature_2m_min')
        weather_codes = daily.get('weather_code')
        if not all(isinstance(series, list) and len(series) >= 3 for series in (dates, max_temps, min_temps, weather_codes)):
            raise ValueError('Open-Meteo did not return a complete three day forecast.')

        show_conditions = bool(design.get('showConditions', True))
        unit_symbol = 'F' if units == 'I' else 'C'

        lines: list[str] = []
        for index in range(3):
            lines.append(
                self._build_day_line(
                    {
                        'valid_date': dates[index],
                        'min_temp': min_temps[index],
                        'max_temp': max_temps[index],
                        'weather_code': weather_codes[index],
                    },
                    context.cols,
                    unit_symbol,
                    show_conditions,
                )
            )
        lines = self.with_optional_title(lines, design=design, context=context)

        return PluginRefreshResult(
            lines=lines[: context.rows],
            meta={
                'city': location.get('name') or city,
                'country': location.get('country_code') or country,
            },
        )

    def placeholder_lines(
        self,
        *,
        settings: dict[str, Any],
        design: dict[str, Any],
        context: PluginContext,
        error: str | None = None,
    ) -> list[str]:
        detail = (error or 'WAITING FOR DATA').upper()
        return self.with_optional_title([
            self._fit(detail, context.cols),
        ], design=design, context=context)[: context.rows]

    def _build_day_line(
        self,
        day: dict[str, Any],
        cols: int,
        unit_symbol: str,
        show_conditions: bool,
    ) -> str:
        valid_date = str(day.get('valid_date') or '').strip()
        weekday = self._weekday_label(valid_date)

        min_temp = self._format_temperature(day.get('min_temp'))
        max_temp = self._format_temperature(day.get('max_temp'))
        base = f'{weekday} {min_temp}/{max_temp}{unit_symbol}'

        if not show_conditions:
            return self._fit(base, cols)

        description = WEATHER_CODE_LABELS.get(day.get('weather_code'), '')
        remaining = cols - len(base) - 1

        if remaining <= 0 or not description:
            return self._fit(base, cols)

        return self._fit(f'{base} {description[:remaining]}', cols)

    def _weekday_label(self, valid_date: str) -> str:
        try:
            return datetime.strptime(valid_date, '%Y-%m-%d').strftime('%a').upper()
        except ValueError:
            return valid_date[:3].upper() or 'DAY'

    def _format_temperature(self, value: Any) -> str:
        try:
            return str(int(round(float(value))))
        except (TypeError, ValueError):
            return '--'

    def _fit(self, value: str, cols: int) -> str:
        return value[:cols]


PLUGIN = OpenMeteoForecastPlugin()
