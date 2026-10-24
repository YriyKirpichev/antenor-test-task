/** Wire formats, mirroring app/schemas/events.py and the geozone REST schemas. */

/** [device_id, lat, lon, ts] -- positional to keep snapshots small. */
export type DevicePoint = [number, number, number, number];

export interface MapSnapshot {
  type: "snapshot";
  ts: number;
  count: number;
  devices: DevicePoint[];
}

export interface AlertMessage {
  type: "alert";
  event: "ENTER" | "INSIDE";
  geozone_id: number;
  device_id: number;
  lat: number;
  lon: number;
  ts: number;
  notification_id?: number;
}

export interface ServerError {
  type: "error";
  detail: string;
}

export type ServerMessage = MapSnapshot | AlertMessage | ServerError;

export interface BBox {
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
}

export interface Geozone {
  id: number;
  name: string;
  lat: number;
  lon: number;
  radius_m: number;
  created_at: string;
  updated_at: string;
}

export interface NewGeozone {
  name: string;
  lat: number;
  lon: number;
  radius_m: number;
}

export interface Notification {
  id: number;
  geozone_id: number;
  device_id: number;
  event: string;
  lat: number;
  lon: number;
  occurred_at: string;
  created_at: string;
}
