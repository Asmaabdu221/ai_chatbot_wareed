# Wareed Chat - Mobile App (MVP)

React Native + TypeScript mobile application for the Wareed AI medical chatbot. Works on **Android** and **iOS**.

## Overview

| Item | Details |
|------|---------|
| **Framework** | React Native (Expo) |
| **Language** | TypeScript |
| **Backend** | Existing FastAPI (same as web) |
| **Auth** | JWT Bearer token |

## Quick Start

### 1. Backend

```bash
# From project root
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Use `--host 0.0.0.0` when testing on a physical device.

### 2. Mobile App

```bash
cd mobile-app
npm install
npm start
```

### 3. Configure API URL

Create `mobile-app/.env`:

```
# Physical device (use your computer's IP)
EXPO_PUBLIC_API_URL=http://192.168.1.112:8000

# Android emulator
# EXPO_PUBLIC_API_URL=http://10.0.2.2:8000

# iOS simulator
# EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
```

### 4. Run

- **Android:** Press `a` in the terminal or run `npm run android`
- **iOS:** Press `i` (macOS only) or run `npm run ios`
- **Physical device:** Install Expo Go, scan QR code

## Features (MVP)

- [x] Login / Register
- [x] Chat screen with AI messages
- [x] RTL layout
- [x] Bearer token auth
- [x] Error handling (Network, API errors)

## Future (TTS/STT)

- **TTS:** `expo-speech` or `react-native-tts`
- **STT:** `expo-speech` Speech.recognize or `@react-native-voice/voice`

## Full Documentation

See [mobile-app/README.md](mobile-app/README.md) for detailed setup and troubleshooting.
