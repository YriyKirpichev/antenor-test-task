/** Leaflet map: device markers, geozone circles, viewport reporting. */

import * as L from "leaflet";
import "leaflet/dist/leaflet.css";

import type { BBox, DevicePoint, Geozone } from "./types.ts";

/** Canvas copes with thousands of markers, but not with ten thousand per
 *  second. Past this the snapshot is truncated and the UI says so; the real
 *  answer is a viewport filter, which the server already supports. */
export const MAX_RENDERED_DEVICES = 3000;

const DEVICE_STYLE: L.CircleMarkerOptions = {
  radius: 3,
  weight: 0,
  fillColor: "#2563eb",
  fillOpacity: 0.85,
};

const ZONE_STYLE: L.CircleMarkerOptions = {
  color: "#0f766e",
  weight: 2,
  fillColor: "#14b8a6",
  fillOpacity: 0.12,
};

/** Pixel-sized, so it does not vanish when the metre circle is sub-pixel. */
const ZONE_CENTER_STYLE: L.CircleMarkerOptions = {
  radius: 5,
  weight: 2,
  color: "#0f766e",
  fillColor: "#2dd4bf",
  fillOpacity: 0.9,
};

const ZONE_ALERT_STYLE: L.CircleMarkerOptions = {
  color: "#dc2626",
  weight: 3,
  fillColor: "#ef4444",
  fillOpacity: 0.3,
};

export class LiveMap {
  readonly map: L.Map;
  private readonly renderer: L.Canvas;
  private readonly deviceLayer: L.LayerGroup;
  private readonly zoneLayer: L.LayerGroup;
  private readonly markers = new Map<number, L.CircleMarker>();
  private readonly zoneShapes = new Map<number, L.Circle>();
  private readonly zoneCenters = new Map<number, L.CircleMarker>();

  constructor(container: HTMLElement) {
    this.map = L.map(container, { center: [50.4501, 30.5234], zoom: 11 });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(this.map);

    this.renderer = L.canvas({ padding: 0.3 });
    this.deviceLayer = L.layerGroup().addTo(this.map);
    this.zoneLayer = L.layerGroup().addTo(this.map);
  }

  bbox(): BBox {
    const bounds = this.map.getBounds();
    return {
      min_lat: bounds.getSouth(),
      min_lon: bounds.getWest(),
      max_lat: bounds.getNorth(),
      max_lon: bounds.getEast(),
    };
  }

  /** Markers are reused by device id: moving a marker is far cheaper than
   *  rebuilding the layer every second. Returns how many were drawn. */
  renderDevices(points: DevicePoint[]): number {
    const shown =
      points.length > MAX_RENDERED_DEVICES
        ? points.slice(0, MAX_RENDERED_DEVICES)
        : points;

    const seen = new Set<number>();
    for (const [deviceId, lat, lon] of shown) {
      seen.add(deviceId);
      const existing = this.markers.get(deviceId);
      if (existing) {
        existing.setLatLng([lat, lon]);
      } else {
        const marker = L.circleMarker([lat, lon], {
          ...DEVICE_STYLE,
          renderer: this.renderer,
        });
        marker.bindTooltip(`device ${deviceId}`, { direction: "top" });
        marker.addTo(this.deviceLayer);
        this.markers.set(deviceId, marker);
      }
    }

    for (const [deviceId, marker] of this.markers) {
      if (!seen.has(deviceId)) {
        this.deviceLayer.removeLayer(marker);
        this.markers.delete(deviceId);
      }
    }
    return shown.length;
  }

  renderZones(zones: Geozone[], onDelete: (zoneId: number) => void): void {
    this.zoneLayer.clearLayers();
    this.zoneShapes.clear();
    this.zoneCenters.clear();

    for (const zone of zones) {
      const shape = L.circle([zone.lat, zone.lon], {
        ...ZONE_STYLE,
        radius: zone.radius_m,
      });
      const popup = document.createElement("div");
      popup.innerHTML =
        `<strong>${escapeHtml(zone.name)}</strong><br>` +
        `#${zone.id} &middot; r = ${Math.round(zone.radius_m)} m<br>` +
        `${zone.lat.toFixed(5)}, ${zone.lon.toFixed(5)}<br>`;
      const button = document.createElement("button");
      button.textContent = "Delete";
      button.className = "danger";
      button.onclick = () => onDelete(zone.id);
      popup.append(button);

      shape.bindPopup(popup);
      shape.addTo(this.zoneLayer);
      this.zoneShapes.set(zone.id, shape);

      // A 2 km circle is 0.08 px wide at world zoom; the dot keeps the zone on
      // screen at any scale, and carries the same popup.
      const center = L.circleMarker([zone.lat, zone.lon], ZONE_CENTER_STYLE);
      center.bindPopup(popup);
      center.addTo(this.zoneLayer);
      this.zoneCenters.set(zone.id, center);
    }
  }

  /** Metres per pixel at the current centre and zoom. */
  metersPerPixel(): number {
    const center = this.map.getCenter();
    return (
      (156543.03392 * Math.cos((center.lat * Math.PI) / 180)) /
      2 ** this.map.getZoom()
    );
  }

  fitZones(): void {
    const bounds = L.latLngBounds([]);
    for (const shape of this.zoneShapes.values()) bounds.extend(shape.getBounds());
    if (bounds.isValid()) this.map.fitBounds(bounds.pad(0.2));
  }

  /** Zoom to one zone so its circle actually fills part of the screen. */
  focusZone(zoneId: number): void {
    const shape = this.zoneShapes.get(zoneId);
    if (shape) this.map.fitBounds(shape.getBounds().pad(1.5));
  }

  /** Radius in metres of the smallest zone, for the "zoom in" hint. */
  smallestZoneRadius(): number | null {
    let smallest: number | null = null;
    for (const shape of this.zoneShapes.values()) {
      const radius = shape.getRadius();
      if (smallest === null || radius < smallest) smallest = radius;
    }
    return smallest;
  }

  /** Make an alert visible on the map for a moment. */
  flashZone(zoneId: number): void {
    const shape = this.zoneShapes.get(zoneId);
    if (!shape) return;
    shape.setStyle(ZONE_ALERT_STYLE);
    window.setTimeout(() => shape.setStyle(ZONE_STYLE), 1500);
  }

  fitDevices(): void {
    if (this.markers.size === 0) return;
    const bounds = L.latLngBounds([]);
    for (const marker of this.markers.values()) bounds.extend(marker.getLatLng());
    this.map.fitBounds(bounds.pad(0.1));
  }

  onViewportChange(handler: () => void): void {
    this.map.on("moveend", handler);
    this.map.on("zoomend", handler);
  }

  onClick(handler: (lat: number, lon: number) => void): void {
    this.map.on("click", (event: L.LeafletMouseEvent) => {
      handler(event.latlng.lat, event.latlng.lng);
    });
  }
}

function escapeHtml(value: string): string {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}
