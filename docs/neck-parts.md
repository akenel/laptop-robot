# Neck block — parts list

Drafted 25 Nov 2026 after a conversation with Grace. **Not bought, not tested yet.**

## What to buy

| Part | Why | Price seen | Link |
| --- | --- | --- | --- |
| Raspberry Pi Pico 2 **H** (RP2350, pre-soldered headers) | The neck's small brain. "H" = headers already on, so no soldering. | ~CHF 6 (DigiKey CH, ex VAT); EUR 5.95 (Pimoroni) | [digitec](https://www.digitec.ch/en/s1/product/raspberry-pi-pico-2h-development-boards-kits-58582559) · [Pimoroni](https://shop.pimoroni.com/en-eu/products/raspberry-pi-pico-2) |
| MG90S micro servo (metal gear, 180°) | Turns the webcam left/right. | EUR 5.00, 200+ in stock (Tinytronics) | [Tinytronics](https://www.tinytronics.nl/en/mechanics-and-actuators/motors/servomotors/mg90s-mini-servo) · [AZ-Delivery](https://az-delivery.de/en/products/mg90s-micro-servomotor) |
| Micro-USB **data** cable | Laptop to Pico: power + commands. Many cheap cables are charge-only and will not work. | a few CHF | any shop; you may already own one |
| Jumper wires, female-to-female (Dupont) | Servo plug to the Pico header pins. | a few CHF per pack | any shop |

Total: roughly **CHF 15–20**.

## Wiring (three wires)

| Servo wire | Pico pin |
| --- | --- |
| Brown / black (ground) | GND, pin 38 |
| Red (power) | VBUS (5 V from USB), pin 40 |
| Orange / yellow (signal) | GP15, pin 20 |

## Software (two halves)

1. **On the Pico, once:** flash MicroPython (drag the `.uf2` file onto the Pico), then save a
   short `main.py` that reads an angle over USB serial and moves the servo. It runs by itself
   on every power-up. Memory is no issue: 4 MB flash, 520 KB RAM on the Pico 2.
2. **On the laptop:** a driver in `drivers/` that sends "turn to 90" over USB serial, plus
   `devices/neck.yaml`. The MCP server picks it up from the registry.

## What I could not verify (honest gaps)

- **Prices on digitec.ch:** the pages timed out when fetched. The digitec links come from a
  search and exist, but price and stock were not read. Check before ordering.
- **Digitec MG90S / jumper wires:** not confirmed that they stock them. Tinytronics (NL) and
  AZ-Delivery (DE) do; postage to Switzerland is not checked.
- **Power:** an MG90S can draw several hundred mA when it stalls; a USB port gives ~500 mA.
  For a light webcam and slow moves this should be fine. If the Pico resets when the servo
  moves, add a separate 5 V supply (shared ground). Measure, don't assume.
- **Correction:** during the chat Grace said "the original Pico has 2 MB / 264 KB". True for the
  Pico 1; the recommended Pico 2 has 4 MB / 520 KB.

## Sources

- [digitec — Pico 2H](https://www.digitec.ch/en/s1/product/raspberry-pi-pico-2h-development-boards-kits-58582559)
- [DigiKey CH — Pico 2](https://www.digikey.ch/en/products/detail/dfrobot/DFR1190/26460598)
- [Pimoroni — Pico 2](https://shop.pimoroni.com/en-eu/products/raspberry-pi-pico-2)
- [SparkFun — Pico 2 with headers](https://www.sparkfun.com/raspberry-pi-pico-2-with-headers.html)
- [Tinytronics — MG90S](https://www.tinytronics.nl/en/mechanics-and-actuators/motors/servomotors/mg90s-mini-servo)
- [AZ-Delivery — MG90S](https://az-delivery.de/en/products/mg90s-micro-servomotor)
