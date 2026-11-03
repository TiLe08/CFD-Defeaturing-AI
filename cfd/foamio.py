"""Minimal reader for ASCII OpenFOAM meshes and fields.

Only what the post-processing needs: patch face centres, owner cells, cell
centres (approximate) and internal/boundary values of volFields. The file
formats are stable across OpenFOAM versions, unlike the output layout of the
sampling function objects.
"""
from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path

import numpy as np

_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _strip(text: str) -> str:
    text = _COMMENTS.sub("", text)
    # drop the FoamFile header
    m = re.search(r"FoamFile\s*\{.*?\}", text, re.S)
    return text[m.end():] if m else text


def _list_body(text: str, start: int = 0) -> tuple[int, str, int]:
    """Find 'N ( ... )' from start; return N, body and end index."""
    m = re.compile(r"(\d+)\s*\(").search(text, start)
    if not m:
        raise ValueError("no list found")
    i, depth = m.end(), 1
    while depth:
        c = text[i]
        depth += c == "("
        depth -= c == ")"
        i += 1
    return int(m.group(1)), text[m.end():i - 1], i


def read_points(f: Path) -> np.ndarray:
    n, body, _ = _list_body(_strip(Path(f).read_text()))
    a = np.array(body.replace("(", " ").replace(")", " ").split(), dtype=float)
    return a.reshape(n, 3)


def read_faces(f: Path) -> list[np.ndarray]:
    _, body, _ = _list_body(_strip(Path(f).read_text()))
    return [np.array(x.split(), dtype=int)
            for x in re.findall(r"\d+\s*\(([^)]*)\)", body)]


def read_labels(f: Path) -> np.ndarray:
    _, body, _ = _list_body(_strip(Path(f).read_text()))
    return np.array(body.split(), dtype=int)


def read_boundary(f: Path) -> dict[str, dict]:
    _, body, _ = _list_body(_strip(Path(f).read_text()))
    out = {}
    for name, block in re.findall(r"(\w+)\s*\{([^}]*)\}", body):
        d = dict(re.findall(r"(\w+)\s+([^;]+);", block))
        out[name] = {"type": d["type"], "nFaces": int(d["nFaces"]),
                     "startFace": int(d["startFace"])}
    return out


def _values(token: str, ncomp: int) -> np.ndarray:
    """Parse 'uniform x' / 'uniform (x y z)' / 'nonuniform List<..> N(...)'."""
    token = token.strip()
    if token.startswith("uniform"):
        v = token[len("uniform"):].replace("(", " ").replace(")", " ").split()
        return np.array(v, dtype=float).reshape(1, ncomp)
    n, body, _ = _list_body(token)
    a = np.array(body.replace("(", " ").replace(")", " ").split(), dtype=float)
    return a.reshape(n, ncomp)


def _ncomp(text: str) -> int:
    cls = re.search(r"class\s+(\w+);", text).group(1)
    return {"volScalarField": 1, "volVectorField": 3}[cls]


def read_field(f: Path) -> tuple[np.ndarray, dict[str, np.ndarray | None]]:
    """Internal values and per-patch 'value' entries (None if not written)."""
    raw = Path(f).read_text()
    ncomp = _ncomp(raw)
    text = _strip(raw)
    m = re.search(r"internalField\s+(.*?);\s*\n\s*boundaryField", text, re.S)
    internal = _values(m.group(1), ncomp)
    bstart = text.index("boundaryField")
    bf = text[text.index("{", bstart) + 1:]
    patches = {}
    i = 0
    pat = re.compile(r"(\"[^\"]+\"|\w+)\s*\{")
    while True:
        m = pat.search(bf, i)
        if not m:
            break
        j, depth = m.end(), 1
        while depth:
            depth += bf[j] == "{"
            depth -= bf[j] == "}"
            j += 1
        block = bf[m.end():j - 1]
        v = re.search(r"\bvalue\s+(.*?);", block, re.S)
        patches[m.group(1).strip('"')] = _values(v.group(1), ncomp) if v else None
        i = j
    return internal, patches


class Mesh:
    def __init__(self, case: Path):
        self.dir = Path(case) / "constant" / "polyMesh"

    @cached_property
    def points(self):
        return read_points(self.dir / "points")

    @cached_property
    def faces(self):
        return read_faces(self.dir / "faces")

    @cached_property
    def owner(self):
        return read_labels(self.dir / "owner")

    @cached_property
    def boundary(self):
        return read_boundary(self.dir / "boundary")

    @cached_property
    def n_cells(self) -> int:
        return int(self.owner.max()) + 1

    def patch_faces(self, name: str) -> range:
        b = self.boundary[name]
        return range(b["startFace"], b["startFace"] + b["nFaces"])

    def face_centres(self, idx) -> np.ndarray:
        return np.array([self.points[self.faces[i]].mean(axis=0) for i in idx])

    def face_areas(self, idx) -> np.ndarray:
        """Area vectors (exact for planar quads/triangles)."""
        out = []
        for i in idx:
            p = self.points[self.faces[i]]
            c = p.mean(axis=0)
            a = sum(np.cross(p[k] - c, p[(k + 1) % len(p)] - c)
                    for k in range(len(p)))
            out.append(0.5 * a)
        return np.array(out)

    @cached_property
    def cell_centres(self) -> np.ndarray:
        """Approximate cell centres (mean of face centres of owned faces).

        Good enough for locating cells and for profiles; not for gradients.
        """
        nei = read_labels(self.dir / "neighbour")
        fc = self.face_centres(range(len(self.faces)))
        acc = np.zeros((self.n_cells, 3))
        cnt = np.zeros(self.n_cells)
        np.add.at(acc, self.owner, fc)
        np.add.at(cnt, self.owner, 1)
        np.add.at(acc, nei, fc[:len(nei)])
        np.add.at(cnt, nei, 1)
        return acc / cnt[:, None]
