"""Ordered drawable mark regions and reject-only boundary geometry checks.

The manifest schema owns the data shape. These checks supply the geometric
constraints JSON Schema cannot express; they never repair or reorder input.
Coordinates are face UV; comparisons use a 1e-12 arithmetic tolerance.
"""
from __future__ import annotations

import math


_EPS = 1e-12


def drawable_mark_parts(mark: dict) -> list[dict]:
    """Return the base region followed by the optional ordered overlays.

    Pairing metadata belongs to the mark, not to these drawable regions. The
    returned geometry is borrowed read-only; consumers must not mutate it.
    """
    return [{key: mark[key] for key in ("outline", "holes", "fill")},
            *mark.get("parts", [])]


def _cross(a, b, c):
    return ((b[0] - a[0]) * (c[1] - a[1])
            - (b[1] - a[1]) * (c[0] - a[0]))


def _on_segment(p, a, b):
    return (abs(_cross(a, b, p)) <= _EPS
            and min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS)


def _edges(ring):
    return zip(ring, ring[1:] + ring[:1])


def _intersects(a, b, c, d):
    ab_c, ab_d = _cross(a, b, c), _cross(a, b, d)
    cd_a, cd_b = _cross(c, d, a), _cross(c, d, b)
    if (((ab_c > _EPS and ab_d < -_EPS) or (ab_c < -_EPS and ab_d > _EPS))
            and ((cd_a > _EPS and cd_b < -_EPS) or (cd_a < -_EPS and cd_b > _EPS))):
        return True
    return (abs(ab_c) <= _EPS and _on_segment(c, a, b)
            or abs(ab_d) <= _EPS and _on_segment(d, a, b)
            or abs(cd_a) <= _EPS and _on_segment(a, c, d)
            or abs(cd_b) <= _EPS and _on_segment(b, c, d))


def _location(p, ring):
    """-1 outside, 0 on the boundary, 1 strictly inside a simple ring."""
    inside = False
    for a, b in _edges(ring):
        if _on_segment(p, a, b):
            return 0
        if ((a[1] > p[1]) != (b[1] > p[1])
                and p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])):
            inside = not inside
    return 1 if inside else -1


def _validate_ring(ring, path):
    for point in ring:
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in point):
            raise ValueError(f"{path}: ring coordinates must be finite face UV in [0, 1]")
    edges = list(_edges(ring))
    for i, (a, b) in enumerate(edges):
        if a == b:
            raise ValueError(f"{path}: repeated vertex creates a zero-length edge")
        c = ring[(i + 2) % len(ring)]
        if (abs(_cross(a, b, c)) <= _EPS
                and (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) < -_EPS):
            raise ValueError(f"{path}: adjacent edges overlap by backtracking")
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if _intersects(a, b, *edges[j]):
                raise ValueError(f"{path}: ring crosses or touches itself at edges {i}, {j}")
    twice_area = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)
    if abs(twice_area) <= _EPS:
        raise ValueError(f"{path}: ring has zero area")


def _rings_touch(first, second):
    return any(_intersects(a, b, c, d)
               for a, b in _edges(first) for c, d in _edges(second))


def _validate_region(region, path):
    outline, holes = region["outline"], region["holes"]
    _validate_ring(outline, f"{path}.outline")
    for i, hole in enumerate(holes):
        hole_path = f"{path}.holes[{i}]"
        _validate_ring(hole, hole_path)
        if _rings_touch(hole, outline) or any(_location(p, outline) != 1 for p in hole):
            raise ValueError(f"{hole_path}: hole must be strictly inside its outline without boundary contact")
        for earlier in holes[:i]:
            if (_rings_touch(hole, earlier) or _location(hole[0], earlier) >= 0
                    or _location(earlier[0], hole) >= 0):
                raise ValueError(f"{hole_path}: holes must be disjoint, without nesting or contact")


def _edge_breaks(a, b, envelope):
    """Split an edge at every envelope intersection, including vertex contacts.

    Checking vertices alone misses an edge cutting across a concave notch.
    Checking only proper crossings also misses a notch entered via its vertex.
    Each open interval between intersections has constant inside/outside state.
    """
    ts = [0.0, 1.0]
    rx, ry = b[0] - a[0], b[1] - a[1]
    length2 = rx * rx + ry * ry
    for c, d in _edges(envelope):
        sx, sy = d[0] - c[0], d[1] - c[1]
        qx, qy = c[0] - a[0], c[1] - a[1]
        denominator = rx * sy - ry * sx
        if abs(denominator) > _EPS:
            t = (qx * sy - qy * sx) / denominator
            u = (qx * ry - qy * rx) / denominator
            if -_EPS <= t <= 1 + _EPS and -_EPS <= u <= 1 + _EPS:
                ts.append(max(0.0, min(1.0, t)))
        elif abs(qx * ry - qy * rx) <= _EPS:
            for p in (c, d):
                t = ((p[0] - a[0]) * rx + (p[1] - a[1]) * ry) / length2
                if 0 <= t <= 1:
                    ts.append(t)
    return sorted(set(ts))


def _inside_envelope(ring, envelope):
    if any(_location(p, envelope) < 0 for p in ring):
        return False
    for a, b in _edges(ring):
        ts = _edge_breaks(a, b, envelope)
        for lo, hi in zip(ts, ts[1:]):
            t = (lo + hi) / 2
            midpoint = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]
            if _location(midpoint, envelope) < 0:
                return False
    return True


def validate_mark_geometry(mark: dict, path: str = "mark") -> None:
    """Reject invalid mark regions after the canonical schema checks their shape.

    The outer outline is the pairing envelope even if the base has holes. An
    overlay may paint a base void; its own holes reveal the layers underneath.
    """
    _validate_region(mark, path)
    for i, part in enumerate(mark.get("parts", [])):
        part_path = f"{path}.parts[{i}]"
        _validate_region(part, part_path)
        if not _inside_envelope(part["outline"], mark["outline"]):
            raise ValueError(f"{part_path}: part must lie wholly inside the mark envelope")
