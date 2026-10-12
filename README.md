# UART Weather Scraper

Program odczytuje linie z UART Raspberry Pi i przesyła każdy poprawny pomiar do
Weather API opisanego w [instrukcji API](../Desktop/weatherapi/README.md).

## Instalacja na Raspberry Pi

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Ustaw w `.env` adres API i klucz stacji (`WEATHER_API_KEY`). Domyślny port
`/dev/serial0` oraz prędkość `9600` można zmienić przez `UART_PORT` i
`UART_BAUDRATE`.

## Uruchomienie

Zmienne z `.env` należy załadować przed uruchomieniem, np.:

```bash
set -a
. ./.env
set +a
python uart_scraper.py
```

Test pojedynczego odczytu:

```bash
python uart_scraper.py --once
```

Oczekiwany format linii to:

```text
MW,t=23.41,h=48.20,p=1012.55,r=12,ra=901,mq=387,aht=1,bmp=1
```

`aht` i `bmp` są wysyłane jako wartości JSON `true`/`false`. Uszkodzone
linie są pomijane i logowane. Błędy HTTP są logowane, a proces czeka
`RETRY_DELAY` sekund przed dalszym odczytem.

## Testy

```bash
python -m unittest -v
```
