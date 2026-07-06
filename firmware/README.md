# ESP32-CAM NFC Scanner Firmware

Reads Mifare Classic 1K stickers with a PN532 and sends the tag UID to the
self-checkout API (`POST /scan`), which pushes the product to the kiosk UI.

## Hardware

| Part | Detail |
|---|---|
| MCU | ESP32-CAM (Freenove dev board, AI Thinker compatible) |
| NFC | PN532 V3 in **I2C mode** — DIP switch 1 ON, switch 2 OFF |
| Tags | Mifare Classic 1K (ISO14443A, 13.56 MHz) |

### Wiring

| PN532 | ESP32-CAM |
|---|---|
| GND | GND |
| VCC | 5V |
| SDA | GPIO 14 |
| SCL | GPIO 15 |

VCC on 5V is correct — the PN532 V3 board has its own regulator and its I2C
lines are 3.3 V logic, safe for the ESP32. IRQ/RSTO stay unconnected; the
firmware polls over I2C.

## Flashing (Arduino IDE)

1. **Boards Manager** → install "esp32 by Espressif Systems"
   (add URL in Preferences if missing:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`)
2. **Library Manager** → install **Adafruit PN532** (pulls in Adafruit BusIO)
3. Board: **AI Thinker ESP32-CAM** · Port: the Freenove USB port
4. Open `self_checkout_scanner/self_checkout_scanner.ino`, edit the CONFIG
   block: Wi-Fi SSID/password, `API_BASE` (your computer's LAN IP), `API_KEY`
   (must match the API's `.env`)
5. Upload. If it fails with "Failed to connect", hold the IO0/BOOT button while
   the upload starts, then release.

Or with arduino-cli:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32cam firmware/self_checkout_scanner
arduino-cli upload  --fqbn esp32:esp32:esp32cam -p /dev/cu.usbserial-XXXX firmware/self_checkout_scanner
```

## Running the API for the ESP32

The ESP32 reaches the API over the LAN, so bind to all interfaces:

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8123
```

Find your computer's LAN IP with `ipconfig getifaddr en0` (macOS) and put it in
`API_BASE`. If scans time out, allow incoming connections for Python in
macOS System Settings → Firewall. ESP32 and computer must be on the same
Wi-Fi network (2.4 GHz — the ESP32 can't see 5 GHz networks).

## "Loading IDs onto tags" — how it actually works

You don't write anything to the stickers. Every Mifare tag ships with a
**factory-burned, read-only UID** (4 or 7 bytes). The firmware reads that UID
and formats it like `1A:2B:3C:4D`. "Registering" a tag means mapping its UID to
a product **in the database**, not writing to the tag:

1. Flash the firmware, open Serial Monitor at **115200 baud**
2. Hold a sticker on the PN532 — it flashes 3 short blinks (unknown tag) and
   the serial output prints the UID plus a ready-made `curl` command:
   ```
   POST /scan tag=1A:2B:3C:4D -> 404
   >> Unregistered tag. Register it with:
   >> curl -X POST http://192.168.1.146:8123/products ...
   ```
3. Run that curl with real name/price/stock (or use Swagger at `/docs`)
4. Scan again → one long flash → product appears on the kiosk UI

To reuse the two seed products with your real stickers, point them at the real
UIDs instead:

```bash
curl -X PATCH http://192.168.1.146:8123/products/1 \
  -H 'Content-Type: application/json' -d '{"nfc_tag_id":"<real-uid-here>"}'
```

## LED feedback

| Signal | Meaning |
|---|---|
| 2 short white flashes on boot | PN532 found, ready |
| 1 long white flash | Product found — pushed to kiosk |
| 3 short white flashes | Unknown tag (register it — UID in serial) |
| 2 red blinks | API key rejected |
| 5 fast red blinks | API unreachable (check `--host 0.0.0.0`, firewall, IP) |
| Slow red blink forever | PN532 not detected — check wiring/DIP switches |

## Behavior notes

- Same tag held on the reader re-sends only after a 2 s cooldown
  (`SCAN_COOLDOWN_MS`) — scan the same product twice by tapping twice.
- Wi-Fi drops auto-reconnect in the main loop.
- The white flash LED (GPIO 4) is bright — swap `flashBlink` for a buzzer or
  external LED later if it's annoying.
