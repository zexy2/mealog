# Running Mealog locally

Mealog can be run three ways, from cheapest to most complete. Start with the
keyless demo; only move to the live provider when you specifically need to test
integration.

Requirements: Node.js 22.x. Python 3.11 is needed only for offline evaluation.
iOS runtime needs macOS, Xcode, and a bootable Simulator; Android runtime needs
Android Studio/emulator or a connected device.

```sh
git clone https://github.com/zexy2/mealog.git
cd mealog
node --version       # 22.x
python3.11 --version # only for offline evaluation
```

## 1. Keyless mobile demo

Fastest product path. Deterministic local scenarios; no Node service, network,
or API key required.

```sh
cd apps/mobile
npm ci
npm run typecheck
npm test
EXPO_PUBLIC_DEMO_MODE=true npm run ios
```

The Capture screen exposes six demo states: auto-accept, review, abstention,
degraded, provider error, and empty day. Start with **Review** to inspect the
p10–p90 band and “Nasıl bulundu?” audit, then use **Abstention** to see the
closed-set safety boundary. Use `npm run android` instead of `npm run ios` for
an available Android emulator/device.

These commands attempt a runtime launch. Bundle export is a separate build
check and is not device proof.

## 2. Keyless Node API smoke

Works on a clean clone: `en_US` and `ja_JP` ship in full.

Terminal 1:

```sh
cd server
npm ci
npm run build
VISION_PROVIDER=fixture PORT=3000 npm start
```

Terminal 2:

```sh
curl --fail --silent http://localhost:3000/health

curl --fail --silent \
  -H 'Content-Type: application/json' \
  -d '{
    "idempotency_key": "readme-quickstart-1",
    "sample_id": "n5k_0002",
    "locale": "en_US",
    "config": "V3"
  }' \
  http://localhost:3000/v1/meals
```

Expected: HTTP 200, `action: "review"`, resolved `us.eggs_scrambled`, a
65–145 g portion band, and `portion_provenance` naming the catalogue default.
This works on a clean clone because `en_US` ships in full. If port 3000 is
occupied, use another `PORT` and the same port in both URLs.

**Turkish variant.** `locale: "tr"` with `sample_id: "tr_0001"` resolves
`tr.kuru_fasulye` instead, but only after the licence-restricted catalogue is
installed once from a source you are entitled to use (see
[docs/licensing.md](licensing.md)). Without it that request answers `503` with
the locale and reason, while `en_US` and `ja_JP` keep working:

```sh
make pack   # TR_PACK_SOURCE=<directory|zip|url> make pack
```

## 3. Optional live Gemini integration

Live mode requires a server-side key; never place it in the mobile bundle.

```sh
# Terminal 1: server/
VISION_PROVIDER=gemini GEMINI_API_KEY='your-key' PORT=3000 npm start

# Terminal 2: apps/mobile/
EXPO_PUBLIC_DEMO_MODE=false \
EXPO_PUBLIC_API_URL=http://localhost:3000 \
npm run ios
```

For a physical phone, replace `localhost` with a service address reachable from
that phone. A successful request proves integration, not provider accuracy.

## 4. Full verification

```sh
# Node service
cd server
npm ci
npm run build
npm run typecheck
npm run lint
npm test

# Mobile client
cd ../apps/mobile
npm ci
npm run typecheck
npm test
npx expo export --platform ios
npx expo export --platform android

# Offline Python/reference gates, from repository root
cd ../..
MEALOG_VENV="$(mktemp -d)/venv"
python3.11 -m venv "$MEALOG_VENV"
. "$MEALOG_VENV/bin/activate"
python -m pip install -e "server[dev]"
make check
```

`make check` is the offline Python/reference gate; it does not replace Node or
mobile checks.
