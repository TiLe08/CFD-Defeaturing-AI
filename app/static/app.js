import * as THREE from "three";
import { OrbitControls } from "/static/vendor/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const COL = {
  base: new THREE.Color(0xb9bcc2), remove: new THREE.Color(0x2e9d5b),
  keep: new THREE.Color(0xd0583c), sel: new THREE.Color(0x2f6fdb),
};
const st = {
  sid: null, unit: "mm", faces: null, verts: null, faceFeature: null,
  features: [], decisions: {}, suggested: {}, selected: -1, preview: false,
};

// ------------------------------------------------------------------ 3D view
const canvas = $("c");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(window.devicePixelRatio);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf6f6f4);
const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 1e6);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
camera.add(sun); sun.position.set(0.5, 1, 0.8);
scene.add(camera);
let meshObj = null, edgeObj = null;

function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / Math.max(r.height, 1);
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();
(function loop() { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); })();

function b64(buf, Type) {
  const bin = atob(buf); const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Type(u8.buffer);
}

function showMesh(verts, faces, colored) {
  if (meshObj) { scene.remove(meshObj); meshObj.geometry.dispose(); }
  if (edgeObj) { scene.remove(edgeObj); edgeObj.geometry.dispose(); }
  const n = faces.length / 3;
  const pos = new Float32Array(n * 9);
  for (let f = 0; f < n; f++) for (let k = 0; k < 3; k++) {
    const v = faces[3 * f + k];
    pos.set([verts[3 * v], verts[3 * v + 1], verts[3 * v + 2]], 9 * f + 3 * k);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 9), 3));
  g.computeVertexNormals();
  meshObj = new THREE.Mesh(g, new THREE.MeshStandardMaterial({
    vertexColors: true, flatShading: true, roughness: 0.75, metalness: 0.0, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  }));
  scene.add(meshObj);
  edgeObj = new THREE.LineSegments(new THREE.EdgesGeometry(g, 25),
    new THREE.LineBasicMaterial({ color: 0x5d6168, transparent: true, opacity: 0.55 }));
  scene.add(edgeObj);
  colored ? recolor() : paintAll(COL.base);
}

function paintAll(c) {
  const a = meshObj.geometry.attributes.color.array;
  for (let i = 0; i < a.length; i += 3) { a[i] = c.r; a[i + 1] = c.g; a[i + 2] = c.b; }
  meshObj.geometry.attributes.color.needsUpdate = true;
}

function recolor() {
  if (!meshObj || st.preview) return;
  const a = meshObj.geometry.attributes.color.array;
  const ff = st.faceFeature;
  for (let f = 0; f < ff.length; f++) {
    const id = ff[f];
    const c = id < 0 ? COL.base : id === st.selected ? COL.sel : COL[st.decisions[id]];
    for (let k = 0; k < 3; k++) { const o = 9 * f + 3 * k; a[o] = c.r; a[o + 1] = c.g; a[o + 2] = c.b; }
  }
  meshObj.geometry.attributes.color.needsUpdate = true;
}

function fitView(bbox) {
  const lo = new THREE.Vector3(...bbox[0]), hi = new THREE.Vector3(...bbox[1]);
  const c = lo.clone().add(hi).multiplyScalar(0.5);
  const r = hi.clone().sub(lo).length() / 2;
  controls.target.copy(c);
  camera.near = r / 100; camera.far = r * 100;
  camera.position.copy(c.clone().add(new THREE.Vector3(0.9, -1.4, 1.1).normalize().multiplyScalar(r * 3.0)));
  camera.up.set(0, 0, 1);
  camera.updateProjectionMatrix();
}

// ------------------------------------------------------------------ picking
const ray = new THREE.Raycaster();
function pick(ev) {
  if (!meshObj || st.preview || !st.faceFeature) return -1;
  const r = canvas.getBoundingClientRect();
  const p = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(p, camera);
  const hit = ray.intersectObject(meshObj)[0];
  return hit ? st.faceFeature[hit.faceIndex] : -1;
}
let down = null;
canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
canvas.addEventListener("pointerup", (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  const id = pick(e);
  if (id >= 0) { toggle(id); select(id, false); }
});
canvas.addEventListener("pointermove", (e) => {
  const tip = $("tip");
  if (e.buttons) { tip.style.display = "none"; return; }
  const id = pick(e);
  if (id < 0) { tip.style.display = "none"; canvas.style.cursor = ""; return; }
  const f = st.features[id];
  canvas.style.cursor = "pointer";
  tip.textContent = `#${id + 1} ${f.kind_label}, h = ${fmt(f.h)} ${st.unit}: ${st.decisions[id] === "remove" ? "entfernen" : "behalten"} (Klick schaltet um)`;
  const r = canvas.getBoundingClientRect();
  tip.style.left = `${e.clientX - r.left + 14}px`; tip.style.top = `${e.clientY - r.top + 14}px`;
  tip.style.display = "block";
});

// ------------------------------------------------------------------ helpers
function fmt(x) {
  const a = Math.abs(x);
  return a >= 100 ? x.toFixed(0) : a >= 10 ? x.toFixed(1) : a >= 1 ? x.toFixed(2) : x.toPrecision(2);
}
function busy(on, text = "Rechne…") { $("busy").hidden = !on; $("busytext").textContent = text; }
function toast(msg, ms = 4000) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), ms); }
async function api(path, body, isForm = false) {
  const res = await fetch(path, isForm ? { method: "POST", body } :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res;
}
function enable(id, on = true) { $(id).classList.toggle("disabled", !on); }
function initialDecision(s) { return s.decision === "remove" ? "remove" : "keep"; }

// ------------------------------------------------------------------ loading
async function loaded(res) {
  const d = await res.json();
  st.sid = d.session; st.unit = d.unit;
  st.verts = b64(d.mesh.vertices, Float32Array); st.faces = b64(d.mesh.faces, Uint32Array);
  st.faceFeature = null; st.features = []; st.decisions = {}; st.selected = -1;
  $("preview").checked = false; st.preview = false;
  showMesh(st.verts, st.faces, false);
  fitView(d.bbox);
  $("empty").style.display = "none";
  document.querySelectorAll(".u").forEach((e) => (e.textContent = d.unit));
  const r = +fmt(d.default_r);
  $("rmax").value = r; $("rcvx").value = r;
  const ext = d.bbox[1].map((v, i) => v - d.bbox[0][i]);
  $("loadinfo").textContent = `${d.name}: ${d.mesh.n_faces.toLocaleString("de-DE")} Dreiecke, ${ext.map(fmt).join(" × ")} ${d.unit}`;
  $("loadinfo").className = "info";
  enable("step-detect"); enable("step-review", false); enable("step-export", false);
  $("flist").innerHTML = ""; $("counts").textContent = ""; $("detectinfo").textContent = "";
}

async function loadFile(file) {
  if (!file) return;
  const fd = new FormData(); fd.append("file", file); fd.append("unit", $("unit").value);
  busy(true, "Lade STL…");
  try { await loaded(await api("/api/load", fd, true)); }
  catch (e) { $("loadinfo").textContent = e.message; $("loadinfo").className = "info err"; }
  finally { busy(false); }
}
$("file").addEventListener("change", (e) => loadFile(e.target.files[0]));
const drop = $("drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => loadFile(e.dataTransfer.files[0]));
document.body.addEventListener("dragover", (e) => e.preventDefault());
document.body.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); });
$("demo").addEventListener("click", async () => {
  busy(true, "Lade Beispiel…");
  try {
    $("unit").value = "mm";
    await loaded(await api("/api/demo"));
    $("rmax").value = 4; $("rcvx").value = 3.5;
    toast("Beispielplatte: Bohrung, Tasche, Zapfen, Gravur, Rippe. Radien passend vorbelegt.");
  } catch (e) { toast(e.message); } finally { busy(false); }
});

// ---------------------------------------------------------------- analysing
function applyFeatures(d, keepDecisions = false) {
  st.faceFeature = b64(d.face_feature, Int32Array);
  st.features = d.features;
  st.suggested = {};
  for (const f of d.features) {
    st.suggested[f.id] = initialDecision(f.suggestion);
    if (!keepDecisions || !(f.id in st.decisions)) st.decisions[f.id] = st.suggested[f.id];
  }
  renderList(); recolor();
}

$("analyse").addEventListener("click", async () => {
  busy(true, "Suche Features… (je nach Größe einige Sekunden)");
  try {
    const d = await (await api("/api/analyse", {
      session: st.sid, r_max: +$("rmax").value || null, r_convex: +$("rcvx").value || null,
      s0: (+$("s0").value || 0) / 100, max_voxels: +$("quality").value,
    })).json();
    st.decisions = {}; st.selected = -1;
    if ($("preview").checked) { $("preview").checked = false; setPreview(false); }
    applyFeatures(d);
    const p = d.params;
    let txt = `${d.features.length} Features gefunden in ${(d.timings.envelope_s + d.timings.detect_s).toFixed(1)} s ` +
      `(Voxel ${fmt(p.pitch)} ${d.unit}, Gitter ${p.grid.join("×")}).`;
    $("detectinfo").textContent = txt + (d.warnings.length ? "\n" + d.warnings.join("\n") : "");
    $("detectinfo").className = d.warnings.length ? "info warn" : "info";
    enable("step-review"); enable("step-export");
  } catch (e) { $("detectinfo").textContent = e.message; $("detectinfo").className = "info err"; }
  finally { busy(false); }
});

$("s0").addEventListener("change", async () => {
  if (!st.sid || !st.features.length) return;
  const d = await (await api("/api/suggest", { session: st.sid, s0: (+$("s0").value || 0) / 100 })).json();
  applyFeatures(d, false);
  toast("Vorschlag neu berechnet. Eigene Änderungen wurden zurückgesetzt.");
});

// ----------------------------------------------------------------- deciding
function toggle(id) {
  st.decisions[id] = st.decisions[id] === "remove" ? "keep" : "remove";
  renderList(); recolor();
  if (st.preview) setPreview(true);
}
function setAll(fn) {
  for (const f of st.features) st.decisions[f.id] = fn(f);
  renderList(); recolor();
  if (st.preview) setPreview(true);
}
$("all-suggest").addEventListener("click", () => setAll((f) => st.suggested[f.id]));
$("all-remove").addEventListener("click", () => setAll(() => "remove"));
$("all-keep").addEventListener("click", () => setAll(() => "keep"));

function select(id, focus = true) {
  st.selected = st.selected === id && focus ? -1 : id;
  renderList(); recolor();
  if (focus && st.selected >= 0) {
    const f = st.features[id];
    const c = new THREE.Vector3(...f.centroid);
    // look onto the opening of the feature, slightly tilted for depth
    const cur = camera.position.clone().sub(controls.target).normalize();
    const dir = new THREE.Vector3(...f.normal).normalize().multiplyScalar(0.8).add(cur.multiplyScalar(0.35)).normalize();
    const want = Math.max(f.length, f.h, 1e-9) * 3.5;
    controls.target.copy(c); camera.position.copy(c.clone().add(dir.multiplyScalar(want)));
  }
  const li = document.querySelector(`#flist li[data-id="${id}"]`);
  if (li) li.scrollIntoView({ block: "nearest" });
}

function renderList() {
  const ul = $("flist");
  ul.innerHTML = "";
  let nr = 0;
  for (const f of st.features) {
    const dec = st.decisions[f.id];
    if (dec === "remove") nr++;
    const human = dec !== st.suggested[f.id];
    const li = document.createElement("li");
    li.dataset.id = f.id;
    li.className = `${dec}${f.id === st.selected ? " sel" : ""}`;
    const tags = [];
    if (f.suggestion.decision === "unsure") tags.push('<span class="tag unsure">unsicher</span>');
    if (human) tags.push('<span class="tag human">von dir geändert</span>');
    li.innerHTML = `<span class="dot" title="Klick: umschalten"></span>
      <span><span class="t">#${f.id + 1} ${f.kind_label}</span>
      <span class="m">h ${fmt(f.h)} · b ${fmt(f.w)} · l ${fmt(f.length)} ${st.unit}</span><br>
      <span class="m" title="${f.suggestion.reason}">Vorschlag ${f.suggestion.decision === "remove" ? "entfernen" : f.suggestion.decision === "keep" ? "behalten" : "unsicher"}: ${f.suggestion.reason}</span></span>
      <span>${tags.join(" ")}</span>`;
    li.querySelector(".dot").addEventListener("click", (e) => { e.stopPropagation(); toggle(f.id); });
    li.addEventListener("click", () => select(f.id));
    li.addEventListener("dblclick", () => toggle(f.id));
    ul.appendChild(li);
  }
  $("counts").innerHTML = st.features.length
    ? `<b class="c-remove">${nr} entfernen</b> · <b class="c-keep">${st.features.length - nr} behalten</b> · Punkt anklicken zum Umschalten`
    : "Keine Features gefunden. Radien größer wählen?";
}

// ----------------------------------------------------------------- preview
function decidedBy() {
  const o = {};
  for (const f of st.features) o[f.id] = st.decisions[f.id] === st.suggested[f.id] ? "modell" : "mensch";
  return o;
}
async function setPreview(on) {
  st.preview = on;
  if (!on) { showMesh(st.verts, st.faces, true); return; }
  busy(true, "Erzeuge Vorschau…");
  try {
    const d = await (await api("/api/preview", { session: st.sid, decisions: st.decisions })).json();
    showMesh(b64(d.mesh.vertices, Float32Array), b64(d.mesh.faces, Uint32Array), false);
    const nf = Object.keys(d.failed).length;
    toast(nf ? `${nf} Feature(s) konnten nicht sauber entfernt werden und bleiben erhalten.` : "Vorschau: so sieht die exportierte STL aus.");
  } catch (e) { toast(e.message); } finally { busy(false); }
}
$("preview").addEventListener("change", (e) => setPreview(e.target.checked));

// ------------------------------------------------------------------ export
$("export").addEventListener("click", async () => {
  busy(true, "Exportiere…");
  try {
    const res = await api("/api/export", {
      session: st.sid, decisions: st.decisions, decided_by: decidedBy(), out_unit: $("outunit").value,
    });
    const blob = await res.blob();
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || "defeaturing.zip";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    const [nr, nk, nf] = (res.headers.get("X-Counts") || "0,0,0").split(",");
    const saved = res.headers.get("X-Saved-To");
    $("exportinfo").textContent = `Fertig: ${nr} entfernt, ${nk} behalten` + (+nf ? `, ${nf} konnten nicht entfernt werden (siehe Protokoll)` : "") +
      `.\nDownload: ${name}` + (saved ? `\nAußerdem gespeichert in: ${decodeURIComponent(saved)}` : "");
    $("exportinfo").className = +nf ? "info warn" : "info";
  } catch (e) { $("exportinfo").textContent = e.message; $("exportinfo").className = "info err"; }
  finally { busy(false); }
});

window.__fad = st; // for automated UI tests
