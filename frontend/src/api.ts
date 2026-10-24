/** REST client. Identity is the mock `X-User-Id` header the backend expects. */

import type { Geozone, NewGeozone, Notification } from "./types.ts";

const BASE = "/api/v1";

async function request<T>(
  userId: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "X-User-Id": userId,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}

export function listZones(userId: string): Promise<Geozone[]> {
  return request<Geozone[]>(userId, "/geozones");
}

export function createZone(userId: string, zone: NewGeozone): Promise<Geozone> {
  return request<Geozone>(userId, "/geozones", {
    method: "POST",
    body: JSON.stringify(zone),
  });
}

export function deleteZone(userId: string, zoneId: number): Promise<void> {
  return request<void>(userId, `/geozones/${zoneId}`, { method: "DELETE" });
}

/** Alerts that Pub/Sub could not deliver while this client was away. */
export function listNotifications(
  userId: string,
  sinceId?: number,
): Promise<Notification[]> {
  const query = sinceId === undefined ? "" : `?since_id=${sinceId}`;
  return request<Notification[]>(userId, `/notifications${query}`);
}
