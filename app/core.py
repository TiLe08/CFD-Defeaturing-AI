"""Tool logic behind the UI, independent of the web server (testable).

A Session holds one loaded STL: the mesh (in m), the detected features,
the suggestions and finally the export with a protocol of every decision.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import io as _io
import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from models.baselines import KEEP, REMOVE, UNSURE, b0_suggest
from stl import defeature, detect, envelope
from stl import io as stlio

TOOL_VERSION = "0.1.0"
SCHEMA = "fad-defeaturing/1"


def _git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1], timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def default_radius(mesh) -> float:
    """3 % of the bounding-box diagonal: a starting point, the user adjusts it."""
    return float(0.03 * np.linalg.norm(mesh.extents))


@dataclass
class Session:
    name: str
    unit: str
    mesh: object
    source_sha256: str
    params: dict = field(default_factory=dict)
    detection: object = None
    suggestions: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_bytes(cls, data: bytes, name: str, unit: str = "mm") -> "Session":
        mesh = stlio.load_mesh(_io.BytesIO(data), unit=unit)
        return cls(name=Path(name).stem or "bauteil", unit=unit, mesh=mesh,
                   source_sha256=hashlib.sha256(data).hexdigest())

    @property
    def scale(self) -> float:
        """Factor m -> display unit."""
        return 1.0 / stlio.UNIT_SCALE[self.unit]

    @property
    def l_ref(self) -> float:
        return float(np.linalg.norm(self.mesh.extents))

    # -------------------------------------------------------------- detection
    def analyse(self, r_max: float | None = None, r_convex: float | None = None,
                s0: float = 0.02, max_voxels: int = envelope.DEFAULT_MAX_VOXELS,
                l_ref: float | None = None) -> None:
        """Envelope + detection + B0 suggestion. Radii and l_ref in m."""
        r_max = r_max or default_radius(self.mesh)
        r_convex = r_convex or r_max
        t0 = time.perf_counter()
        env = envelope.build_envelope(self.mesh, r_max, max_voxels=max_voxels, r_convex=r_convex)
        t1 = time.perf_counter()
        self.detection = detect.detect_features(self.mesh, env)
        t2 = time.perf_counter()
        self.params = {"r_max": r_max, "r_convex": r_convex, "s0": s0,
                       "l_ref": l_ref or self.l_ref, "pitch": env.pitch,
                       "eps": self.detection.eps, "max_voxels": max_voxels,
                       "grid": list(map(int, env.shape))}
        self.timings = {"envelope_s": round(t1 - t0, 2), "detect_s": round(t2 - t1, 2)}
        self.suggest(s0, self.params["l_ref"])

    def suggest(self, s0: float, l_ref: float | None = None) -> None:
        self.params["s0"] = s0
        if l_ref:
            self.params["l_ref"] = l_ref
        self.suggestions = b0_suggest(self.detection.features, self.params["l_ref"], s0)
        span = float(self.mesh.extents.max())
        for f, sug in zip(self.detection.features, self.suggestions):
            if f.length > 0.5 * span:
                sug["decision"] = KEEP
                sug["reason"] = ("erstreckt sich über mehr als die halbe Bauteillänge, vermutlich "
                                 "eine dünne Bauteilkante (z. B. Hinterkante) und kein Feature")
                sug["model"] = "B0+Kantenregel"

    # ------------------------------------------------------------- UI payload
    def mesh_payload(self) -> dict:
        v = (self.mesh.vertices * self.scale).astype(np.float32)
        f = self.mesh.faces.astype(np.uint32)
        return {
            "vertices": base64.b64encode(v.tobytes()).decode(),
            "faces": base64.b64encode(f.tobytes()).decode(),
            "n_vertices": int(len(v)), "n_faces": int(len(f)),
        }

    def features_payload(self) -> dict:
        s = self.scale
        feats = []
        for f, sug in zip(self.detection.features, self.suggestions):
            d = f.to_dict()
            for k in ("h", "w", "length"):
                d[k] = d[k] * s
            d["area"] *= s * s
            d["footprint"] *= s * s
            d["centroid"] = [x * s for x in d["centroid"]]
            d["suggestion"] = sug
            feats.append(d)
        ff = self.detection.face_feature.astype(np.int32)
        p = {k: (v * s if k in ("r_max", "r_convex", "l_ref", "pitch", "eps") else v)
             for k, v in self.params.items()}
        return {
            "session": self.id, "name": self.name, "unit": self.unit,
            "params": p, "timings": self.timings,
            "warnings": self.detection.warnings, "rejected": self.detection.rejected,
            "features": feats,
            "face_feature": base64.b64encode(ff.tobytes()).decode(),
            "bbox": (self.mesh.bounds * s).tolist(),
        }

    # ----------------------------------------------------------------- export
    def export(self, decisions: dict, out_unit: str = "m", decided_by: dict | None = None):
        """decisions: {feature id: "remove"|"keep"}. Returns (stl bytes, protocol dict)."""
        decided_by = decided_by or {}
        remove = [int(k) for k, v in decisions.items() if v == REMOVE]
        t0 = time.perf_counter()
        res = defeature.remove_features(self.mesh, self.detection, remove)
        t_def = time.perf_counter() - t0
        buf = _io.BytesIO()
        out = res.mesh.copy()
        out.apply_scale(1.0 / stlio.UNIT_SCALE[out_unit])
        buf.write(__import__("trimesh").exchange.stl.export_stl(out))
        s_out = 1.0 / stlio.UNIT_SCALE[out_unit]
        feats = []
        for f, sug in zip(self.detection.features, self.suggestions):
            fid = f.id
            final = decisions.get(fid, decisions.get(str(fid), KEEP))
            if fid in res.failed:
                status = "nicht entfernt (Fehler)"
            elif fid in res.removed:
                status = "entfernt"
            else:
                status = "behalten"
            feats.append({
                "id": fid, "kind": f.kind, "kind_label": detect.KIND_LABEL[f.kind],
                "h": f.h * s_out, "w": f.w * s_out, "length": f.length * s_out,
                "area": f.area * s_out ** 2, "area_fraction": f.area_fraction,
                "centroid": [x * s_out for x in f.centroid], "normal": f.normal,
                "suggestion": sug["decision"], "suggestion_reason": sug["reason"],
                "suggestion_model": sug["model"],
                "decision": final,
                "decided_by": decided_by.get(fid, decided_by.get(str(fid),
                                             "modell" if final == sug["decision"] else "mensch")),
                "status": status,
                "error": res.failed.get(fid),
                "cap_deviation": res.cap_deviation.get(fid, 0.0) * s_out,
            })
        p = self.params
        protocol = {
            "schema": SCHEMA,
            "tool_version": TOOL_VERSION,
            "code_revision": _git_rev(),
            "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": {"name": self.name, "unit": self.unit, "sha256": self.source_sha256,
                       "faces": int(len(self.mesh.faces))},
            "output": {"file": f"{self.name}_defeatured.stl", "unit": out_unit,
                       "faces": int(len(res.mesh.faces)), "watertight": res.watertight,
                       "volume": float(res.mesh.volume) * s_out ** 3,
                       "volume_original": float(self.mesh.volume) * s_out ** 3},
            "parameters": {"unit": out_unit,
                           "r_max": p["r_max"] * s_out, "r_convex": p["r_convex"] * s_out,
                           "voxel_pitch": p["pitch"] * s_out, "eps": p["eps"] * s_out,
                           "l_ref": p["l_ref"] * s_out, "b0_threshold_h_over_L": p["s0"]},
            "counts": {"detected": len(feats), "removed": len(res.removed),
                       "kept": len(feats) - len(res.removed) - len(res.failed),
                       "failed": len(res.failed),
                       "overridden_by_human": sum(1 for x in feats if x["decided_by"] == "mensch")},
            "timings_s": {**self.timings, "defeature_s": round(t_def, 2)},
            "features": feats,
            "notes": "Vorschlag nach Größenregel B0 (h/L_ref). Strömungsbewusste Empfehlung folgt in Stufe 3.",
        }
        return buf.getvalue(), protocol


def protocol_json(protocol: dict) -> str:
    return json.dumps(protocol, ensure_ascii=False, indent=2)
