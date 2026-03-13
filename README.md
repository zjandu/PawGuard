# 🐾 PawGuard

> A blogger I followed had a cat he loved dearly. One day the cat wandered off
> while playing outside. His GPS tracker couldn't update fast enough.
> By the time he found him, it was too late.
>
> He and thousands of his followers were devastated. I was too.
>
> This happens more than it should. PawGuard is my attempt to make it
> happen less — even if just a little.

**AI-powered pet safety monitoring. Turns any GPS tracker into a proactive guardian.**

> *Built because a beautiful cat was lost to poisoning while its tracker silently reported coordinates no one was watching. PawGuard watches — so you don't have to stare at an app.*

---

## What PawGuard does

Standard pet trackers answer one question: *where is my pet?*

PawGuard answers the question that actually matters: **is my pet safe right now?**

| Standard tracker | PawGuard |
|---|---|
| Shows GPS coordinates | Detects if pet is motionless in an unfamiliar area |
| Sends geofence exit alert | Distinguishes between "exploring" and "not moving and in danger" |
| Battery drains fast | Behavior model reduces unnecessary GPS polling |
| One-size alert | 4-level alert system with deduplication — no cry-wolf effect |
| No learning | Builds a personal activity model per pet over time |

### Core detection logic

PawGuard's most important rule (V1):

> **If your pet has been motionless for N minutes in a location it has never visited before → alert.**

This covers: poisoning, injury, entrapment, getting stuck. It is the scenario standard trackers completely miss.

---

## Quick start (Docker — recommended)

**Step 1: Clone**
```bash
git clone https://github.com/your-username/pawguard.git
cd pawguard
```

**Step 2: Create your config**
```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your pet name, home coordinates, and tracker details
```

**Step 3: Start**
```bash
docker compose up -d
```

**Step 4: Verify**
```bash
# Check logs
docker compose logs -f pawguard

# Test the API
curl http://localhost:8000/api/pets

# Open dashboard
open http://localhost:8000/dashboard
```

You will receive a Telegram message confirming PawGuard is running.

---

## Setup guide

### 1. Find your home coordinates

Go to [latlong.net](https://www.latlong.net/), click your home on the map, copy the lat/lon.

### 2. Create a Telegram bot (takes 2 minutes)

1. Open Telegram → search for `@BotFather`
2. Send `/newbot`, follow prompts, copy the **bot token**
3. Start a chat with your new bot
4. Get your **chat ID**: open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in browser after sending any message to the bot

### 3. Choose your tracker

#### Option A: Tractive GPS collar
```yaml
tracker:
  type: "tractive"
  tractive:
    email: "your@email.com"
    password: "yourpassword"
    tracker_id: "ABCDEF"        # From Tractive app → Tracker Settings → About
    poll_interval_seconds: 60
```
> ⚠️ Uses the unofficial Tractive API (same endpoints as the Home Assistant integration, stable since 2019). Free plan updates every ~2 min. Premium updates every ~3 sec.

#### Option B: Webhook (IFTTT / OwnTracks / GPSLogger)
```yaml
tracker:
  type: "webhook"
  webhook:
    secret: "a_random_string"    # Set this, then add header X-PawGuard-Secret to your webhook
```

Your webhook URL: `http://YOUR_SERVER_IP:8000/webhook/location/cat_01`

**With GPSLogger for Android:**
- URL: `http://YOUR_IP:8000/webhook/location/cat_01`
- HTTP Method: POST
- Body: `{"lat": %LAT, "lon": %LON, "accuracy": %ACC, "battery": %BATT, "ts": %TIMESTAMP}`
- Content Type: `application/json`

**With OwnTracks:**
- PawGuard natively understands the OwnTracks JSON format. Just point OwnTracks HTTP mode at the webhook URL.

#### Option C: MQTT (DIY hardware)
```yaml
tracker:
  type: "mqtt"
  mqtt:
    host: "192.168.1.100"
    port: 1883
    topic: "pawguard/location"
```

Publish JSON to the topic:
```json
{"lat": 39.9042, "lon": 116.4074, "accuracy": 10, "battery": 78, "speed": 0.5}
```

**Example ESP32 + SIM7000 sketch:** see `docs/esp32-example/`

---

## Alert levels

| Level | Meaning | Example |
|---|---|---|
| 🟢 SAFE | All clear | Pet is home, moving normally |
| 🔵 NOTICE | Worth knowing | Pet crossed the geofence boundary |
| 🟠 WARNING | Investigate soon | Pet still in unfamiliar area for 20+ min |
| 🔴 CRITICAL | Act now | Pet motionless in unfamiliar area for 45+ min |

**Sample CRITICAL alert:**
```
🔴 PawGuard Alert — 小橘
Level: CRITICAL | Confidence: HIGH

📍 Location: 39.91234, 116.41234 → [Open Map]
🏠 Distance from home: 387m
⏱ Motionless for: 48 min
📡 GPS fix age: 2min ago
🪫 Battery: 18%

Why this alert:
• IMMOBILE in unfamiliar location for 48 minutes (threshold: 45 min)
• Outside geofence by 87m
• Low battery: 18%

What to do: GO NOW — pet has been motionless in an unfamiliar location
for 48 minutes. This could indicate injury, illness, or poisoning.
Head to the last known location immediately.
```

---

## How the behavior model works

PawGuard builds an **activity grid** for your pet: a record of every location visited, organized by time of week (Monday 3pm, Tuesday 9am, etc.).

After 3 days of data:
- PawGuard knows which locations are "familiar" (visited before at this time of week)
- Stillness alerts only trigger in **unfamiliar** locations
- This eliminates false alarms for known resting spots (garden, neighbor's porch)

The model is completely local, private, and stored in a SQLite file in `./data/`.

---

## API reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/pets` | List all pets and current status |
| `GET` | `/api/pets/{id}/location` | Recent location history (`?limit=50`) |
| `GET` | `/api/pets/{id}/alerts` | Alert history |
| `POST` | `/api/pets/{id}/alerts/{alert_id}/ack` | Acknowledge an alert |
| `POST` | `/webhook/location/{pet_id}` | Receive location (webhook mode) |
| `GET` | `/api/status` | System health check |
| `GET` | `/dashboard` | Web dashboard |

---

## Roadmap

**V1.0 (this release)**
- [x] Tractive, MQTT, Webhook connectors
- [x] Stillness detection in unfamiliar areas
- [x] Geofence alerts
- [x] Activity grid behavior model (3+ days)
- [x] 4-level alert system with deduplication
- [x] Telegram notifications
- [x] Web dashboard
- [x] Docker deployment

**V2.0 (planned)**
- [ ] Gaussian Process location prediction (fill GPS gaps)
- [ ] Heart rate / temperature sensor support
- [ ] Community danger zone map (anonymous reporting)
- [ ] Adaptive power scheduling commands (Tractive Premium)
- [ ] Email / SMS alert channels
- [ ] Multiple pets with per-pet thresholds

**V3.0 (future)**
- [ ] Home camera integration (RTSP/NVR)
- [ ] BLE crowdsource network
- [ ] iOS / Android native app

---

## Contributing

The most valuable contributions right now:

1. **New connectors** — Does your tracker have an API? Write a connector in `pawguard/connectors/`. Subclass `BaseConnector`, implement `start()` and `stop()`. Submit a PR.

2. **Hardware guides** — ESP32 + GPS module setup, Raspberry Pi gateway, etc. Add to `docs/`.

3. **Real-world testing** — Deploy it, use it, open issues. This is V1. It needs field data.

4. **Translations** — Alert messages should be in the user's language. Help localize.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## FAQ

**Q: Will this work if my pet's tracker only updates every 2 minutes?**  
A: Yes. PawGuard's stillness detection uses the history of all received locations. Even at 2-minute intervals, a 20-45 minute stillness window (10-22 data points) is enough to detect the pattern reliably.

**Q: What about false alarms when my cat is just napping outside?**  
A: After 3 days of data, PawGuard learns your cat's regular outdoor resting spots. A nap in the familiar garden won't trigger an alert. A nap in an alley three streets away will.

**Q: Does it run on a Raspberry Pi?**  
A: Yes. A Pi 3B+ or newer is sufficient. The behavior model uses SQLite and runs entirely in Python with no GPU required.

**Q: Is my data sent to any cloud service?**  
A: No. All data is stored locally in `./data/pawguard.db`. The only outbound connections are to your tracker's API (Tractive) and Telegram for alert delivery.

**Q: Why not use Apple AirTag?**  
A: AirTag has no API. It's designed to be found by the Find My network, which is closed. PawGuard is built around trackable APIs. If you use AirTag, combine it with a secondary Bluetooth scanner setup.

---

## License

MIT License. Free to use, modify, and distribute. See [LICENSE](LICENSE).

---

*For the cats and dogs who can't tell us when they're in trouble.*
