"""Read weather measurements from UART and forward them to the Weather API."""

from __future__ import annotations

import argparse
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, TextIO

import requests

LOGGER = logging.getLogger("uart_scraper")
REQUIRED_FIELDS = ("t", "h", "p", "r", "ra", "mq", "aht", "bmp")


class SerialPort(Protocol):
    def readline(self) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Settings:
    serial_port: str
    baudrate: int
    api_url: str
    api_key: str
    timeout: float
    retry_delay: float

    @classmethod
    def from_environment(cls) -> "Settings":
        values = {
            "serial_port": os.getenv("UART_PORT", "/dev/serial0"),
            "baudrate": int(os.getenv("UART_BAUDRATE", "9600")),
            "api_url": os.getenv(
                "WEATHER_API_URL",
                "http://localhost:5000/api/v1/measurements/",
            ),
            "api_key": os.getenv("WEATHER_API_KEY", ""),
            "timeout": float(os.getenv("HTTP_TIMEOUT", "10")),
            "retry_delay": float(os.getenv("RETRY_DELAY", "5")),
        }
        if not values["api_key"]:
            raise ValueError("WEATHER_API_KEY is required")
        if values["baudrate"] <= 0 or values["timeout"] <= 0 or values["retry_delay"] < 0:
            raise ValueError("UART_BAUDRATE and HTTP_TIMEOUT must be positive; RETRY_DELAY cannot be negative")
        return cls(**values)


class InvalidMeasurement(ValueError):
    """Raised when a UART line does not contain a valid measurement."""


def _parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise InvalidMeasurement(f"{field} must be a boolean, got {value!r}")


def parse_measurement(line: str) -> dict[str, Any]:
    """Convert a UART line into the API JSON object.

    The sender may prepend its module name, for example
    ``zt01: MW,t=23.41,...``. The module name is transport metadata and is
    intentionally not included in the measurement sent to the API.
    """
    line = line.strip()
    if not line.startswith("MW"):
        sender, separator, payload = line.partition(":")
        if separator and sender.strip() and payload.strip().startswith("MW"):
            line = payload.strip()

    fields = [part.strip() for part in line.strip().split(",")]
    if not fields or fields[0] != "MW":
        raise InvalidMeasurement("line must start with MW")

    values: dict[str, str] = {}
    for field in fields[1:]:
        if "=" not in field:
            raise InvalidMeasurement(f"field has no '=': {field!r}")
        key, value = (part.strip() for part in field.split("=", 1))
        if not key or not value or key in values:
            raise InvalidMeasurement(f"invalid or duplicate field: {field!r}")
        values[key] = value

    missing = [key for key in REQUIRED_FIELDS if key not in values]
    if missing:
        raise InvalidMeasurement(f"missing fields: {', '.join(missing)}")

    try:
        measurement: dict[str, Any] = {
            "t": float(values["t"]),
            "h": float(values["h"]),
            "p": float(values["p"]),
            "r": float(values["r"]),
            "ra": int(values["ra"]),
            "mq": int(values["mq"]),
            "aht": _parse_bool(values["aht"], "aht"),
            "bmp": _parse_bool(values["bmp"], "bmp"),
        }
    except (TypeError, ValueError) as exc:
        raise InvalidMeasurement(f"invalid numeric value: {exc}") from exc

    if measurement["ra"] < 0 or measurement["mq"] < 0:
        raise InvalidMeasurement("ra and mq must be non-negative")
    return measurement


class WeatherApi:
    def __init__(
        self,
        url: str,
        api_key: str,
        timeout: float,
        session: requests.Session | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json", "X-API-Key": api_key}
        )

    def post_measurement(self, measurement: Mapping[str, Any]) -> None:
        response = self.session.post(
            self.url, json=dict(measurement), timeout=self.timeout
        )
        if response.status_code not in {200, 201, 202}:
            response.raise_for_status()


def process_line(
    raw_line: bytes | str,
    api: WeatherApi,
    output: TextIO | None = None,
) -> bool:
    """Parse and send one line. Returns False for malformed input."""
    try:
        line = raw_line.decode("ascii") if isinstance(raw_line, bytes) else raw_line
        measurement = parse_measurement(line)
    except (UnicodeDecodeError, InvalidMeasurement) as exc:
        LOGGER.warning("Ignoring invalid UART line: %s", exc)
        return False

    api.post_measurement(measurement)
    if output is not None:
        output.write("sent\n")
        output.flush()
    LOGGER.info("Measurement sent")
    return True


def run(
    settings: Settings,
    serial_factory: Callable[..., SerialPort],
    *,
    once: bool = False,
) -> None:
    serial_port = serial_factory(settings.serial_port, settings.baudrate, timeout=1)
    api = WeatherApi(settings.api_url, settings.api_key, settings.timeout)
    try:
        while True:
            raw_line = serial_port.readline()
            if not raw_line:
                if once:
                    return
                continue
            try:
                process_line(raw_line, api)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if 400 <= status < 500:
                    LOGGER.error("API rejected measurement with HTTP %s", status)
                else:
                    LOGGER.error("API server error: %s; retrying", exc)
                    time.sleep(settings.retry_delay)
                    continue
            except requests.RequestException as exc:
                LOGGER.error("API request failed: %s; retrying", exc)
                time.sleep(settings.retry_delay)
            if once:
                return
    finally:
        serial_port.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="read one UART line and exit")
    args = parser.parse_args()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = Settings.from_environment()
        import serial

        run(settings, serial.Serial, once=args.once)
    except (ValueError, ImportError) as exc:
        LOGGER.critical("%s", exc)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
