# Rope ESP32 TCP Protocol

## Connection
- **Port:** 3333
- **Delimiter:** `\n` (newline)
- **Encoding:** ASCII / plain text
- **TCP_NODELAY:** enabled (no Nagle buffering)

## Commands (Client → ESP32)

### Immediate Movement
| Command | Description              | Response        |
|---------|--------------------------|-----------------|
| `F`     | Forward at current speed | `OK:F`          |
| `B`     | Backward at current speed| `OK:B`          |
| `L`     | Spin left (counter-clock)| `OK:L`          |
| `R`     | Spin right (clockwise)   | `OK:R`          |
| `S`     | Stop motors immediately  | `STOPPED`       |

### Timed Movement
| Command    | Description                       | Response           |
|------------|-----------------------------------|--------------------|
| `F<ms>`    | Forward for `<ms>` milliseconds   | `OK:F<ms>`         |
| `B<ms>`    | Backward for `<ms>` milliseconds  | `OK:B<ms>`         |
| `L<ms>`    | Spin left for `<ms>` milliseconds | `OK:L<ms>`         |
| `R<ms>`    | Spin right for `<ms>` milliseconds| `OK:R<ms>`         |

When the timer expires the motors stop automatically and the ESP32 sends `STOPPED`.

### Servo Control
| Command          | Description                        | Response              |
|------------------|------------------------------------|-----------------------|
| `HEAD:<angle>`   | Set head servo (0–180°)            | `OK:HEAD:<angle>`     |
| `ARM_R:<angle>`  | Set right arm servo (0–180°)       | `OK:ARM_R:<angle>`    |
| `ARM_L:<angle>`  | Set left arm servo (0–180°)        | `OK:ARM_L:<angle>`    |
| `CENTER`         | Reset all servos to 90°            | `OK:CENTER`           |

Values are clamped to [0, 180].

### Speed
| Command        | Description                   | Response             |
|----------------|-------------------------------|----------------------|
| `SPD:<value>`  | Set motor speed (0–255)       | `OK:SPD:<value>`     |

Default speed: **180**. Values outside [0, 255] are clamped.

### Animation
| Command  | Description                               | Response      |
|----------|-------------------------------------------|---------------|
| `HAPPY`  | Non-blocking arm wave (3-phase, ~1s)      | `OK:HAPPY`    |

The animation runs in the background; `OK:HAPPY` is sent when it finishes.

### Unknown
Any unrecognised command produces:
```
ERR:unknown
```

## Unsolicited Messages (ESP32 → Client)

### Battery
Every 2 seconds the ESP32 sends the battery voltage over **TCP only** (not USB Serial):
```
BAT:<voltage>
```
Example: `BAT:11.82`

Voltage is the average of 10 ADC samples. Expected range for a 3S LiPo: 9.0–12.6 V.

### Timed Stop
When a timed movement expires:
```
STOPPED
```

## Error Responses
| Response           | Meaning                               |
|--------------------|---------------------------------------|
| `ERR:unknown`      | Command not recognised               |

## Notes
- All responses are terminated with `\n`.
- USB Serial mirrors all command responses for debugging; battery reports are TCP-only.
- The ESP32 accepts one TCP client at a time; new clients replace the old one.
- WiFi: STA mode, SSID `3mar`, no password.
