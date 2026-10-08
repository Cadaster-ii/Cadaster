"use client";
/**
 * web/src/components/MapDrawer.tsx
 *
 * Leaflet map with leaflet-draw for polygon drawing.
 * Loaded dynamically (ssr: false) because Leaflet uses browser globals.
 *
 * Emits the drawn GeoJSON polygon via onPolygonChange.
 */

import { useEffect, useRef } from "react";
import type { GeoJSONPolygon } from "@/lib/agentApi";

interface Props {
  onPolygonChange: (polygon: GeoJSONPolygon | null) => void;
}

export default function MapDrawer({ onPolygonChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<ReturnType<typeof import("leaflet")["map"]> | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !containerRef.current || mapRef.current) return;

    // Dynamically import Leaflet so Next.js doesn't SSR it
    Promise.all([
      import("leaflet"),
      import("leaflet-draw"),
      import("leaflet/dist/leaflet.css"),
      // @ts-ignore — no types for this CSS import
      import("leaflet-draw/dist/leaflet.draw.css"),
    ]).then(([L]) => {
      if (!containerRef.current || mapRef.current) return;

      // Fix Leaflet default icon paths broken by Webpack
      delete (L.Icon.Default.prototype as Record<string, unknown>)["_getIconUrl"];
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl:       "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl:     "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      const map = L.map(containerRef.current!).setView([20, 0], 2);
      mapRef.current = map;

      // OpenStreetMap base layer
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(map);

      // Draw control
      const drawnItems = new L.FeatureGroup();
      map.addLayer(drawnItems);

      const drawControl = new (L as unknown as Record<string, unknown>).Control.Draw({
        draw: {
          polygon: {
            allowIntersection: false,
            showArea: true,
            shapeOptions: {
              color: "var(--color-polygon-stroke, #0d6e6e)",
              fillColor: "var(--color-polygon-stroke, #0d6e6e)",
              fillOpacity: 0.18,
              weight: 2,
            },
          },
          // Disable all other draw tools
          rectangle: false,
          circle: false,
          marker: false,
          circlemarker: false,
          polyline: false,
        },
        edit: { featureGroup: drawnItems },
      });
      map.addControl(drawControl as unknown as L.Control);

      // Handle draw events
      map.on((L as unknown as Record<string, unknown>).Draw.Event.CREATED as string, (e: unknown) => {
        const event = e as { layer: L.Layer };
        drawnItems.clearLayers();
        drawnItems.addLayer(event.layer);

        // Extract GeoJSON polygon
        const feature = (event.layer as L.Polygon).toGeoJSON();
        const geom = feature.geometry;
        if (geom.type === "Polygon") {
          onPolygonChange({
            type: "Polygon",
            coordinates: geom.coordinates as [number, number][][],
          });
        }
      });

      map.on((L as unknown as Record<string, unknown>).Draw.Event.DELETED as string, () => {
        onPolygonChange(null);
      });

      map.on((L as unknown as Record<string, unknown>).Draw.Event.EDITED as string, (e: unknown) => {
        const event = e as { layers: L.FeatureGroup };
        event.layers.eachLayer((layer) => {
          const feature = (layer as L.Polygon).toGeoJSON();
          const geom = feature.geometry;
          if (geom.type === "Polygon") {
            onPolygonChange({
              type: "Polygon",
              coordinates: geom.coordinates as [number, number][][],
            });
          }
        });
      });
    });

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={containerRef}
      style={{ height: "400px", width: "100%", borderRadius: "8px" }}
      aria-label="Map — draw a polygon to define your land claim"
      role="application"
    />
  );
}
