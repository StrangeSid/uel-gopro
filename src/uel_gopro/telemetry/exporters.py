from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Union

from uel_gopro.core.models import TelemetryTrack


def export_gpx(track: TelemetryTrack, output_path: Union[Path, str]) -> Path:
    """Export a TelemetryTrack to GPX 1.1 XML.

    Contains ``<trkpt lat="..." lon="...">`` with ``<ele>``, ``<time>``, and
    ``<speed>`` when available.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    ns = "http://www.topografix.com/GPX/1/1"
    ET.register_namespace("", ns)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

    gpx = ET.Element(
        f"{{{ns}}}gpx",
        {
            "version": "1.1",
            "creator": "uel-gopro",
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": (
                "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd"
            ),
        },
    )

    metadata = ET.SubElement(gpx, f"{{{ns}}}metadata")
    meta_name = ET.SubElement(metadata, f"{{{ns}}}name")
    meta_name.text = f"{track.device_name} Telemetry"

    trk = ET.SubElement(gpx, f"{{{ns}}}trk")
    trk_name = ET.SubElement(trk, f"{{{ns}}}name")
    trk_name.text = f"{track.device_name} Track"

    trkseg = ET.SubElement(trk, f"{{{ns}}}trkseg")
    for pt in track.gps_points:
        trkpt = ET.SubElement(
            trkseg,
            f"{{{ns}}}trkpt",
            {"lat": f"{pt.lat:.7f}", "lon": f"{pt.lon:.7f}"},
        )
        ele = ET.SubElement(trkpt, f"{{{ns}}}ele")
        ele.text = f"{pt.alt:.3f}"
        if pt.timestamp_utc:
            time_el = ET.SubElement(trkpt, f"{{{ns}}}time")
            time_el.text = pt.timestamp_utc
        speed_val = pt.speed_2d if pt.speed_2d is not None else pt.speed_3d
        if speed_val is not None:
            spd_el = ET.SubElement(trkpt, f"{{{ns}}}speed")
            spd_el.text = f"{speed_val:.3f}"

    ET.indent(gpx, space="  ")
    out.write_bytes(ET.tostring(gpx, encoding="utf-8", xml_declaration=True))
    return out


def export_kml(track: TelemetryTrack, output_path: Union[Path, str]) -> Path:
    """Export a TelemetryTrack to KML for Google Earth."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    ns = "http://www.opengis.net/kml/2.2"
    ET.register_namespace("", ns)

    kml = ET.Element(f"{{{ns}}}kml")
    doc = ET.SubElement(kml, f"{{{ns}}}Document")
    doc_name = ET.SubElement(doc, f"{{{ns}}}name")
    doc_name.text = f"{track.device_name} Track"

    placemark = ET.SubElement(doc, f"{{{ns}}}Placemark")
    pm_name = ET.SubElement(placemark, f"{{{ns}}}name")
    pm_name.text = f"{track.device_name} Path"

    line_string = ET.SubElement(placemark, f"{{{ns}}}LineString")
    tessellate = ET.SubElement(line_string, f"{{{ns}}}tessellate")
    tessellate.text = "1"
    alt_mode = ET.SubElement(line_string, f"{{{ns}}}altitudeMode")
    alt_mode.text = "absolute"

    coord_lines = [f"{pt.lon:.7f},{pt.lat:.7f},{pt.alt:.3f}" for pt in track.gps_points]
    coords_el = ET.SubElement(line_string, f"{{{ns}}}coordinates")
    coords_el.text = "\n" + "\n".join(coord_lines) + "\n"

    ET.indent(kml, space="  ")
    out.write_bytes(ET.tostring(kml, encoding="utf-8", xml_declaration=True))
    return out


def export_geojson(track: TelemetryTrack, output_path: Union[Path, str]) -> Path:
    """Export a TelemetryTrack to a GeoJSON FeatureCollection.

    Uses a ``LineString`` for two or more points, a ``Point`` for exactly one
    point, and ``null`` geometry for an empty track.  A ``bbox`` is included
    when coordinates exist.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    coordinates = [[pt.lon, pt.lat, pt.alt] for pt in track.gps_points]

    if len(coordinates) >= 2:
        geometry = {"type": "LineString", "coordinates": coordinates}
    elif len(coordinates) == 1:
        geometry = {"type": "Point", "coordinates": coordinates[0]}
    else:
        geometry = None

    bbox = None
    if coordinates:
        lons = [c[0] for c in coordinates]
        lats = [c[1] for c in coordinates]
        alts = [c[2] for c in coordinates]
        bbox = [min(lons), min(lats), min(alts), max(lons), max(lats), max(alts)]

    properties = {
        "device_name": track.device_name,
        "has_gyro": track.has_gyro,
        "has_accel": track.has_accel,
        "point_count": len(track.gps_points),
    }

    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": properties,
                "geometry": geometry,
            }
        ],
    }
    if bbox is not None:
        data["bbox"] = bbox

    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out


def export_csv(track: TelemetryTrack, output_path: Union[Path, str]) -> Path:
    """Export a TelemetryTrack to a CSV table."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "lat", "lon", "alt", "speed_2d", "speed_3d"])
        for pt in track.gps_points:
            writer.writerow(
                [
                    pt.timestamp_utc or "",
                    pt.lat,
                    pt.lon,
                    pt.alt,
                    pt.speed_2d if pt.speed_2d is not None else "",
                    pt.speed_3d if pt.speed_3d is not None else "",
                ]
            )

    return out
