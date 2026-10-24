/** Wires the sidebar, the REST calls and the live socket onto the map. */

import "./style.css";

import * as api from "./api.ts";
import { LiveMap, MAX_RENDERED_DEVICES } from "./map.ts";
import { LiveSocket } from "./socket.ts";
import type { AlertMessage, Geozone, Notification, ServerMessage } from "./types.ts";

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (node === null) throw new Error(`Missing element #${id}`);
  return node as T;
}

const ui = {
  userId: el<HTMLInputElement>("user-id"),
  connect: el<HTMLButtonElement>("connect"),
  status: el<HTMLParagraphElement>("status"),
  count: el<HTMLElement>("stat-count"),
  drawn: el<HTMLElement>("stat-drawn"),
  age: el<HTMLElement>("stat-age"),
  scale: el<HTMLElement>("stat-scale"),
  viewportFilter: el<HTMLInputElement>("viewport-filter"),
  fit: el<HTMLButtonElement>("fit"),
  truncated: el<HTMLParagraphElement>("truncated"),
  zoneName: el<HTMLInputElement>("zone-name"),
  zoneRadius: el<HTMLInputElement>("zone-radius"),
  pick: el<HTMLButtonElement>("pick"),
  picked: el<HTMLParagraphElement>("picked"),
  create: el<HTMLButtonElement>("create"),
  zones: el<HTMLUListElement>("zones"),
  zoneCount: el<HTMLElement>("zone-count"),
  fitZones: el<HTMLButtonElement>("fit-zones"),
  zoneHint: el<HTMLParagraphElement>("zone-hint"),
  alerts: el<HTMLUListElement>("alerts"),
  alertCount: el<HTMLElement>("alert-count"),
  error: el<HTMLParagraphElement>("error"),
};

const liveMap = new LiveMap(el<HTMLElement>("map"));

let socket: LiveSocket | null = null;
let center: { lat: number; lon: number } | null = null;
let picking = false;
let alerts = 0;
/** Highest notification id seen, so a reconnect only backfills what we missed. */
let lastNotificationId: number | undefined;

function currentUser(): string {
  return ui.userId.value.trim();
}

function showError(error: unknown): void {
  ui.error.textContent = error instanceof Error ? error.message : String(error);
  ui.error.classList.remove("hidden");
}

function clearError(): void {
  ui.error.classList.add("hidden");
}

/** Shows the scale, and why a zone or a 23 m step can be invisible at it. */
function refreshScale(): void {
  const metersPerPixel = liveMap.metersPerPixel();
  ui.scale.textContent =
    metersPerPixel >= 1000
      ? `${(metersPerPixel / 1000).toFixed(1)} km/px`
      : `${Math.round(metersPerPixel)} m/px`;

  const smallest = liveMap.smallestZoneRadius();
  if (smallest !== null && smallest / metersPerPixel < 3) {
    ui.zoneHint.textContent =
      `At ${Math.round(metersPerPixel)} m/px the smallest zone is ` +
      `${(smallest / metersPerPixel).toFixed(1)} px wide: only its centre dot ` +
      `is visible. Zoom in or use "Fit map to zones".`;
    ui.zoneHint.classList.remove("hidden");
  } else {
    ui.zoneHint.classList.add("hidden");
  }
}

function setStatus(status: "connecting" | "open" | "closed"): void {
  ui.status.textContent = status === "open" ? "connected" : status;
  ui.status.className = `status ${status}`;
  ui.connect.textContent = status === "closed" ? "Connect" : "Disconnect";
}

// --- live data ---------------------------------------------------------------

function onMessage(message: ServerMessage): void {
  switch (message.type) {
    case "snapshot": {
      const drawn = liveMap.renderDevices(message.devices);
      ui.count.textContent = String(message.count);
      ui.drawn.textContent = String(drawn);
      ui.age.textContent = new Date(message.ts * 1000).toLocaleTimeString();
      if (message.count > MAX_RENDERED_DEVICES) {
        ui.truncated.textContent =
          `Drawing ${MAX_RENDERED_DEVICES} of ${message.count}. ` +
          `Turn on the viewport filter to see a real subset.`;
        ui.truncated.classList.remove("hidden");
      } else {
        ui.truncated.classList.add("hidden");
      }
      break;
    }
    case "alert":
      addAlert(message);
      liveMap.flashZone(message.geozone_id);
      if (message.notification_id !== undefined) {
        lastNotificationId = Math.max(
          lastNotificationId ?? 0,
          message.notification_id,
        );
      }
      break;
    case "error":
      showError(new Error(`server: ${message.detail}`));
      break;
  }
}

function addAlert(alert: AlertMessage | Notification, backfilled = false): void {
  const item = document.createElement("li");
  const text = document.createElement("div");
  const when = "ts" in alert ? new Date(alert.ts * 1000) : new Date(alert.occurred_at);
  text.innerHTML =
    `<strong>${alert.event}</strong> device ${alert.device_id}` +
    `<div class="meta">zone #${alert.geozone_id} &middot; ` +
    `${when.toLocaleTimeString()}${backfilled ? " &middot; missed" : ""}</div>`;
  item.append(text);

  const locate = document.createElement("button");
  locate.textContent = "Show";
  locate.onclick = () => liveMap.map.setView([alert.lat, alert.lon], 14);
  item.append(locate);

  ui.alerts.prepend(item);
  while (ui.alerts.children.length > 50) ui.alerts.lastElementChild?.remove();
  alerts += 1;
  ui.alertCount.textContent = String(alerts);
}

// --- geozones ----------------------------------------------------------------

async function refreshZones(): Promise<void> {
  const user = currentUser();
  if (!user) return;
  const zones = await api.listZones(user);
  ui.zoneCount.textContent = String(zones.length);
  liveMap.renderZones(zones, (zoneId) => void removeZone(zoneId));
  renderZoneList(zones);
  refreshScale();
}

function renderZoneList(zones: Geozone[]): void {
  ui.zones.replaceChildren();
  for (const zone of zones) {
    const item = document.createElement("li");

    const label = document.createElement("div");
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = zone.name;
    name.onclick = () => liveMap.map.setView([zone.lat, zone.lon], 13);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `#${zone.id} · r = ${Math.round(zone.radius_m)} m`;
    label.append(name, meta);

    const remove = document.createElement("button");
    remove.className = "danger";
    remove.textContent = "Delete";
    remove.onclick = () => void removeZone(zone.id);

    item.append(label, remove);
    ui.zones.append(item);
  }
}

async function removeZone(zoneId: number): Promise<void> {
  try {
    await api.deleteZone(currentUser(), zoneId);
    liveMap.map.closePopup();
    await refreshZones();
    clearError();
  } catch (error) {
    showError(error);
  }
}

async function createZone(): Promise<void> {
  if (center === null) return;
  try {
    const created = await api.createZone(currentUser(), {
      name: ui.zoneName.value.trim() || "Zone",
      lat: center.lat,
      lon: center.lon,
      radius_m: Number(ui.zoneRadius.value),
    });
    center = null;
    ui.create.disabled = true;
    ui.picked.textContent = "No center picked yet.";
    await refreshZones();
    liveMap.focusZone(created.id);
    clearError();
  } catch (error) {
    showError(error);
  }
}

// --- connection --------------------------------------------------------------

async function connect(): Promise<void> {
  const user = currentUser();
  if (!user) {
    showError(new Error("Enter a user id first"));
    return;
  }
  localStorage.setItem("user_id", user);

  socket = new LiveSocket(user, { onMessage, onStatus: setStatus });
  socket.connect();
  socket.sendBBox(ui.viewportFilter.checked ? liveMap.bbox() : null);

  try {
    await refreshZones();
    // Pub/Sub keeps nothing, so catch up on what was missed while away
    const missed = await api.listNotifications(user, lastNotificationId);
    for (const notification of missed.reverse()) {
      addAlert(notification, true);
      lastNotificationId = Math.max(lastNotificationId ?? 0, notification.id);
    }
    clearError();
  } catch (error) {
    showError(error);
  }
}

function disconnect(): void {
  socket?.close();
  socket = null;
  setStatus("closed");
}

// --- events ------------------------------------------------------------------

ui.connect.onclick = () => {
  if (socket === null) void connect();
  else disconnect();
};

ui.viewportFilter.onchange = () => {
  socket?.sendBBox(ui.viewportFilter.checked ? liveMap.bbox() : null);
};

ui.fit.onclick = () => liveMap.fitDevices();

ui.fitZones.onclick = () => liveMap.fitZones();

ui.pick.onclick = () => {
  picking = !picking;
  ui.pick.classList.toggle("armed", picking);
  ui.pick.textContent = picking ? "Click the map…" : "Pick center on map";
};

ui.create.onclick = () => void createZone();

liveMap.onClick((lat, lon) => {
  if (!picking) return;
  picking = false;
  ui.pick.classList.remove("armed");
  ui.pick.textContent = "Pick center on map";
  center = { lat, lon };
  ui.picked.textContent = `Center: ${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  ui.create.disabled = false;
});

liveMap.onViewportChange(() => {
  refreshScale();
  if (ui.viewportFilter.checked) socket?.sendBBox(liveMap.bbox());
});

refreshScale();

const remembered = localStorage.getItem("user_id");
if (remembered !== null) ui.userId.value = remembered;
void connect();
