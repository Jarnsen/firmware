# JARNSEN service security

The service security layer owns the persistent full-lock state and the temporary service-access policy.

Runtime invariants:

- Service WLAN is temporary and must return the radio to `WIFI_OFF` when stopped or when startup fails.
- Drone Repeater role is not allowed to start Service WLAN.
- Sensitive portal endpoints require an authenticated service session.
- Captive DNS is intentionally short-lived so a connected phone can continue using cellular Internet for external map and release resources.
- Bluetooth service access uses the fixed JARNSEN pairing policy.
- The Tracker button flow retains the existing short-click and 1.2-second service-menu interaction, with full-lock handling layered around it.

This document is intentionally credential-free; credential values live in the common service-security implementation.
