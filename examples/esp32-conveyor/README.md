# ESP32 conveyor IR-count example

This firmware publishes only real IR pulse counts from the configured GPIO.
It does not derive speed, current, voltage, or RPM. Those fields must be omitted
until corresponding physical sensors and an approved calibration exist.
**Nameplate RPM is never emitted as telemetry.**

## Wiring and build

- Use an ESP32 development board and an IR sensor with a digital output.
- Connect sensor VCC/GND to the module's supported supply and common ground.
- Connect digital output to GPIO 27. Confirm the sensor output voltage is safe
  for the ESP32 input before wiring; use level shifting when required.
- Install PlatformIO Core and copy `src/secrets.h.example` to `src/secrets.h`.
- Replace every placeholder with the Wi-Fi network, HTTPS API URL, trusted API
  root certificate, registered sensor ID, and a scoped device credential.
- Never commit `src/secrets.h`; it is excluded by the repository ignore rule.
- Build and flash with `pio run -e esp32dev -t upload`.

The backend sensor must be registered with a count-compatible quantity/unit.
The firmware uses NTP to produce UTC event times and does not enqueue a sample
when it cannot establish a synchronized clock.

## Calibration and credential provisioning

Provision a credential from the selected sensor in `/app`. Copy the
one-time `key_id.secret` value into the ignored `secrets.h`; rotate/revoke it
from the UI if it is exposed. Use a unique registered sensor for each physical
measurement. This example has no speed/current/voltage calibration and therefore
does not transmit those quantities.

## Buffering and replay

Readings are appended to LittleFS before network delivery. A monotonically
increasing sequence and stable source event ID are stored with each sample.
The local JSONL outbox is bounded to 512 KiB; when full, the firmware reports
that a sample could not be stored instead of silently exceeding the limit.
The firmware retries the queued readings after Wi-Fi/API recovery; REST event
keys make a response-lost replay idempotent. Samples remain in LittleFS when
the server rejects a batch so they can be inspected rather than silently
dropped. Protect physical access to the board because the filesystem and
credential are not encrypted by this example.

This is an illustrative, read-only ingestion publisher, not a PLC controller.
It sends no command or actuation request.

## Verification status

The backend protocol tests run without hardware. PlatformIO and an ESP32 board
were not available in the implementation environment, so firmware compilation,
electrical safety, NTP, TLS trust, and on-device LittleFS behavior must be
validated on the target board before use.
