"""Local web server for the defeaturing tool.

    python -m app.server            # http://localhost:8765
    python -m app.server --open     # also opens the browser

Everything runs on this computer; no data is sent anywhere.
"""
from __future__ import annotations

import argparse
import io as _io
import os
import threading
import webbrowser
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from stl import io as stlio
from stl.samples import demo_plate

from .core import TOOL_VERSION, Session, default_radius, protocol_json

STATIC = Path(__file__).resolve().parent / "static"
MAX_SESSIONS = 5

app = FastAPI(title="Flow-Aware Defeaturing", version=TOOL_VERSION)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_sessions: dict[str, Session] = {}


def _store(s: Session) -> Session:
    while len(_sessions) >= MAX_SESSIONS:
        _sessions.pop(next(iter(_sessions)))
    _sessions[s.id] = s
    return s


def _get(sid: str) -> Session:
    if sid not in _sessions:
        raise HTTPException(404, "Sitzung abgelaufen, bitte die STL neu laden.")
    return _sessions[sid]


def _loaded(s: Session) -> dict:
    return {"session": s.id, "name": s.name, "unit": s.unit,
            "default_r": default_radius(s.mesh) * s.scale, "l_ref": s.l_ref * s.scale,
            "bbox": (s.mesh.bounds * s.scale).tolist(), "mesh": s.mesh_payload(),
            "watertight": bool(s.mesh.is_watertight)}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/version")
def version():
    return {"version": TOOL_VERSION}


@app.post("/api/load")
async def load(file: UploadFile = File(...), unit: str = Form("mm")):
    data = await file.read()
    try:
        s = Session.from_bytes(data, file.filename or "bauteil.stl", unit)
    except (stlio.MeshError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return _loaded(_store(s))


@app.post("/api/demo")
def demo():
    mesh, _ = demo_plate()
    buf = _io.BytesIO()
    mesh.export(buf, file_type="stl")
    s = Session.from_bytes(buf.getvalue(), "beispielplatte.stl", "mm")
    return _loaded(_store(s))


class AnalyseReq(BaseModel):
    session: str
    r_max: float | None = None  # display unit
    r_convex: float | None = None
    s0: float = 0.02
    l_ref: float | None = None
    max_voxels: int = 8_000_000


@app.post("/api/analyse")
def analyse(req: AnalyseReq):
    s = _get(req.session)
    k = 1.0 / s.scale
    s.analyse(r_max=req.r_max and req.r_max * k, r_convex=req.r_convex and req.r_convex * k,
              s0=req.s0, max_voxels=min(max(req.max_voxels, 100_000), 60_000_000),
              l_ref=req.l_ref and req.l_ref * k)
    return s.features_payload()


class SuggestReq(BaseModel):
    session: str
    s0: float
    l_ref: float | None = None


@app.post("/api/suggest")
def suggest(req: SuggestReq):
    s = _get(req.session)
    if s.detection is None:
        raise HTTPException(400, "Erst analysieren.")
    s.suggest(req.s0, req.l_ref and req.l_ref / s.scale)
    return s.features_payload()


class DecisionReq(BaseModel):
    session: str
    decisions: dict[str, str]
    decided_by: dict[str, str] = {}
    out_unit: str = "m"


@app.post("/api/preview")
def preview(req: DecisionReq):
    s = _get(req.session)
    from stl import defeature
    remove = [int(k) for k, v in req.decisions.items() if v == "remove"]
    res = defeature.remove_features(s.mesh, s.detection, remove)
    tmp = Session(name=s.name, unit=s.unit, mesh=res.mesh, source_sha256="")
    return {"mesh": tmp.mesh_payload(), "failed": {str(k): v for k, v in res.failed.items()},
            "watertight": res.watertight}


@app.post("/api/export")
def export(req: DecisionReq):
    s = _get(req.session)
    if req.out_unit not in stlio.UNIT_SCALE:
        raise HTTPException(400, "unbekannte Einheit")
    stl_bytes, protocol = s.export({int(k): v for k, v in req.decisions.items()},
                                   req.out_unit, {int(k): v for k, v in req.decided_by.items()})
    stl_name = f"{s.name}_defeatured.stl"
    json_name = f"{s.name}_defeaturing.json"
    pj = protocol_json(protocol)
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(stl_name, stl_bytes)
        z.writestr(json_name, pj)
    headers = {"Content-Disposition": f'attachment; filename="{s.name}_defeaturing.zip"'}
    out_dir = os.environ.get("FAD_OUTPUT_DIR")
    if out_dir:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / stl_name).write_bytes(stl_bytes)
        (d / json_name).write_text(pj, encoding="utf-8")
        headers["X-Saved-To"] = quote(os.environ.get("FAD_OUTPUT_DIR_DISPLAY", str(d)))
    c = protocol["counts"]
    headers["X-Counts"] = f'{c["removed"]},{c["kept"]},{c["failed"]}'
    headers["Access-Control-Expose-Headers"] = "X-Saved-To, X-Counts"
    return Response(buf.getvalue(), media_type="application/zip", headers=headers)


@app.exception_handler(Exception)
async def _unexpected(request, exc):  # pragma: no cover
    return JSONResponse({"detail": f"Interner Fehler: {exc}"}, status_code=500)


def main(argv=None):
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="Browser öffnen")
    a = ap.parse_args(argv)
    url = f"http://localhost:{a.port}"
    print(f"Defeaturing-Tool läuft: {url}  (Beenden: Fenster schließen oder Strg+C)")
    if a.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
