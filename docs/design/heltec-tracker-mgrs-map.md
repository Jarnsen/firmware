# Heltec Wireless Tracker: MGRS map and target navigation

Target hardware: **Heltec Wireless Tracker V1.1** (`heltec-wireless-tracker`).

## Required behaviour

- Always display **10-digit MGRS** coordinates (1 m grid precision).
- Show both:
  - own GPS position,
  - selected remote Meshtastic node position.
- Show the age of the remote position.
- Show distance and bearing to the selected node.
- Bearing display uses NATO 6400 mil:
  - North 0000,
  - East 1600,
  - South 3200,
  - West 4800.
- Show left/right correction in mil relative to available own heading.
- Own heading source:
  - GPS course while moving,
  - optional external magnetometer while stationary,
  - otherwise heading is marked unavailable.
- Provide an offline map view with own position, selected node, other known nodes, north indicator, target line and zoom levels.
- Support saved waypoints and MGRS target entry.

## Display pages

1. **Map**
   - own marker,
   - selected-node marker,
   - line to target,
   - 10-digit own and target MGRS,
   - distance and bearing,
   - position age.
2. **Target navigation**
   - large direction indication,
   - bearing in 6400 mil,
   - distance,
   - left/right correction,
   - target MGRS.
3. **Position**
   - own 10-digit MGRS,
   - GPS status, accuracy, altitude, speed and course.
4. **Node details**
   - node name/ID,
   - target 10-digit MGRS,
   - RSSI/SNR when available,
   - battery and position age.
5. **Waypoints**
   - browse saved targets,
   - enter a 10-digit MGRS target.

## One-button interaction

- Short press: next node or item.
- Double press: previous node or item.
- Long press: next page.
- Map interaction: cycle zoom level without removing the existing very-long-press shutdown action.

## Map storage constraints

The board has limited flash and no SD card. The first implementation should therefore use a compact vector/line map format rather than full raster OSM tiles. It should support a configured geographic area and at least three zoom levels. Road, path, railway, water and selected place-name layers are sufficient for the first version.

## Implementation stages

1. Add coordinate service for fixed 10-digit MGRS formatting and parsing.
2. Add distance, true bearing and 6400-mil conversion helpers.
3. Add selected-node state and position-age handling.
4. Add position and target-navigation display pages.
5. Add compact offline-map renderer and map data format.
6. Add waypoint storage and MGRS entry.
7. Add optional external magnetometer integration.
8. Build and test for `heltec-wireless-tracker`.
