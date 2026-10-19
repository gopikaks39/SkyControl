// Reusable 3D airspace view (three.js). Scene units: 1 unit = 1 NM horizontally;
// altitude is exaggerated (vScale units per 1,000 ft) so vertical separation is visible.
import * as THREE from '../vendor/three.module.min.js';

const COLORS = {
  ground: 0x0a222b, grid: 0x1b3d47, grid2: 0x12313a, coast: 0x3f8d93, ring: 0x1f4b56,
  aircraft: 0xd8f5f0, emergency: 0xff5a5f, warn: 0xf2b245, select: 0x63f1e0, ghost: 0xa48cff, hold: 0xff9d3c, dim: 0x6f8f96,
};

export function altitudeColor(ft) {
  // low = warm, high = cool
  const t = Math.max(0, Math.min(1, ft / 40000));
  const c = new THREE.Color();
  c.setHSL(0.08 + 0.45 * t, 0.75, 0.6);
  return c;
}

function textSprite(text, color = '#9fd7d4', size = 34) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = `600 ${size}px Inter, Segoe UI, Arial`;
  const w = Math.ceil(ctx.measureText(text).width) + 16;
  canvas.width = w; canvas.height = size + 14;
  ctx.font = `600 ${size}px Inter, Segoe UI, Arial`;
  ctx.fillStyle = color;
  ctx.fillText(text, 8, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  sprite.userData.aspect = w / (size + 14);
  return sprite;
}

function planeGeometry() {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.ConeGeometry(0.22, 1.5, 8), null);
  body.rotation.x = Math.PI / 2;            // point along +z (forward)
  const wing = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.05, 0.36), null);
  wing.position.z = -0.05;
  const tail = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.04, 0.2), null);
  tail.position.z = -0.6;
  const fin = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.32, 0.22), null);
  fin.position.set(0, 0.16, -0.6);
  group.add(body, wing, tail, fin);
  return group;
}

export class Airspace3D {
  constructor(container, { extent = 160, vScale = 0.9, aircraftScale = 2.4, grid = 10, rings = [] } = {}) {
    this.container = container;
    this.extent = extent;
    this.vScale = vScale;
    this.aircraftScale = aircraftScale;
    this.aircraft = new Map();
    this.labels = new Map();
    this.paths = new Map();
    this.onSelect = null;
    this.onTick = null;
    this.selected = null;

    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    container.appendChild(this.renderer.domElement);
    this.labelLayer = document.createElement('div');
    this.labelLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden';
    container.appendChild(this.labelLayer);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x061820);
    this.scene.fog = new THREE.Fog(0x061820, extent * 2.2, extent * 5);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, extent * 12);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const sun = new THREE.DirectionalLight(0xffffff, 0.9);
    sun.position.set(extent, extent * 2, extent * 0.5);
    this.scene.add(sun);

    this.world = new THREE.Group();
    this.scene.add(this.world);
    this._ground(grid, rings);

    this.stems = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x4d8c95, transparent: true, opacity: 0.28 }));
    this.trails = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.8 }));
    this.world.add(this.stems, this.trails);

    this.orbit = { theta: -0.55, phi: 0.95, radius: extent * 2.2, target: new THREE.Vector3(0, 6, 0) };
    this._controls();
    this._updateCamera();
    this.raycaster = new THREE.Raycaster();
    this._resize = () => this.resize();
    this.observer = new ResizeObserver(this._resize);
    this.observer.observe(container);
    this.resize();
    this.clock = new THREE.Clock();
    this.running = true;
    const loop = () => {
      if (!this.running) return;
      const dt = this.clock.getDelta();
      if (this.onTick) this.onTick(dt);
      this.renderer.render(this.scene, this.camera);
      this._placeLabels();
      this.frame = requestAnimationFrame(loop);
    };
    loop();
  }

  // ---------- coordinates
  toScene(x, y, ft = 0) { return new THREE.Vector3(x, Math.max(0, ft) / 1000 * this.vScale, -y); }

  // ---------- static layers
  _ground(grid, rings) {
    const e = this.extent;
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(e * 2.4, e * 2.4), new THREE.MeshBasicMaterial({ color: COLORS.ground }));
    plane.rotation.x = -Math.PI / 2;
    plane.position.y = -0.05;
    this.world.add(plane);
    const g = new THREE.GridHelper(e * 2, Math.round(e * 2 / grid), COLORS.grid, COLORS.grid2);
    g.material.transparent = true; g.material.opacity = 0.55;
    this.world.add(g);
    for (const r of rings) this.ring(0, 0, r, COLORS.ring, 0.6);
  }

  ring(x, y, radius, color = COLORS.ring, opacity = 0.6, altitude = 0) {
    const pts = [];
    for (let i = 0; i <= 96; i++) {
      const a = (i / 96) * Math.PI * 2;
      pts.push(this.toScene(x + radius * Math.cos(a), y + radius * Math.sin(a), altitude));
    }
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
    this.world.add(line);
    return line;
  }

  addCoastlines(lines) {
    const mat = new THREE.LineBasicMaterial({ color: COLORS.coast, transparent: true, opacity: 0.85 });
    for (const pts of lines) {
      this.world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts.map(([x, y]) => this.toScene(x, y, 0))), mat));
    }
  }

  addAirports(list) {
    this.airportGroup?.removeFromParent();
    this.airportGroup = new THREE.Group();
    for (const ap of list) {
      const len = Math.max(1.2, (ap.runway_m || 2500) / 1852 * (this.extent > 80 ? 1.4 : 1));
      const rwy = new THREE.Mesh(new THREE.BoxGeometry(len * 0.12, 0.08, len),
        new THREE.MeshBasicMaterial({ color: ap.closed ? 0xc0444a : ap.major === false ? 0x7fa7ad : 0xe8f4f2 }));
      const p = this.toScene(ap.x, ap.y, 0);
      rwy.position.copy(p);
      rwy.rotation.y = -THREE.MathUtils.degToRad(ap.heading || 270);
      this.airportGroup.add(rwy);
      const pad = new THREE.Mesh(new THREE.CircleGeometry(len * 0.75, 24), new THREE.MeshBasicMaterial({ color: ap.closed ? 0x5a1d22 : 0x143b45, transparent: true, opacity: 0.8 }));
      pad.rotation.x = -Math.PI / 2; pad.position.set(p.x, 0.02, p.z);
      this.airportGroup.add(pad);
      const label = textSprite(ap.label || ap.icao || ap.name, ap.closed ? '#ff9a9a' : '#bfe9e5');
      const s = this.extent / 26;
      label.scale.set(s * label.userData.aspect, s, 1);
      label.position.set(p.x, s * 0.9, p.z + len * 0.4);
      this.airportGroup.add(label);
    }
    this.world.add(this.airportGroup);
  }

  addFixes(list) {
    for (const f of list) {
      const p = this.toScene(f.x, f.y, f.altitude || 9000);
      const marker = new THREE.Mesh(new THREE.TorusGeometry(this.extent / 45, 0.12, 6, 32), new THREE.MeshBasicMaterial({ color: 0xffa64d, transparent: true, opacity: 0.55 }));
      marker.rotation.x = Math.PI / 2; marker.position.copy(p);
      this.world.add(marker);
      const label = textSprite(f.name, '#ffc380', 30);
      const s = this.extent / 34;
      label.scale.set(s * label.userData.aspect, s, 1);
      label.position.set(p.x, p.y + s, p.z);
      this.world.add(label);
    }
  }

  setZones(zones) {
    const key = JSON.stringify(zones);
    if (key === this.zoneKey) return;
    this.zoneKey = key;
    this.zoneGroup?.removeFromParent();
    this.zoneGroup = new THREE.Group();
    const colors = { weather: 0xff7043, protected: 0xa48cff, uncertainty: 0xf2c94c, conflict: 0xff5a5f, glide: 0x5ee6a8 };
    for (const z of zones) {
      const color = colors[z.kind] || 0xff5a5f;
      const h = (z.top || 26000) / 1000 * this.vScale;
      const cyl = new THREE.Mesh(new THREE.CylinderGeometry(z.radius, z.radius, h, 48, 1, true),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: z.kind === 'glide' ? 0.06 : 0.13, side: THREE.DoubleSide, depthWrite: false }));
      const p = this.toScene(z.x, z.y, 0);
      cyl.position.set(p.x, h / 2, p.z);
      this.zoneGroup.add(cyl);
      const edge = new THREE.Mesh(new THREE.TorusGeometry(z.radius, 0.08 * this.aircraftScale, 6, 64), new THREE.MeshBasicMaterial({ color }));
      edge.rotation.x = Math.PI / 2; edge.position.set(p.x, 0.05, p.z);
      this.zoneGroup.add(edge);
    }
    this.world.add(this.zoneGroup);
  }

  setMarkers(markers) {
    // markers: [{x, y, ft, kind, label}]; objects are reused between calls and only moved.
    this.markerObjs = this.markerObjs || new Map();
    const kinds = { vehicle: 0xffd166, birds: 0xffffff, preceding: 0xf2b245, radio: 0x7cc7ff, ghost: 0xa48cff };
    const seen = new Set();
    markers.forEach((m, i) => {
      const key = `${m.kind}:${m.label || ''}:${i}`;
      seen.add(key);
      let obj = this.markerObjs.get(key);
      if (!obj) {
        obj = new THREE.Group();
        const color = kinds[m.kind] || 0xffffff;
        const geo = m.kind === 'birds' ? new THREE.IcosahedronGeometry(0.5 * this.aircraftScale, 0)
          : new THREE.BoxGeometry(0.7 * this.aircraftScale, 0.4 * this.aircraftScale, 0.7 * this.aircraftScale);
        const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.4, transparent: m.kind === 'ghost', opacity: 0.6 });
        const count = m.kind === 'birds' ? 10 : 1;
        for (let k = 0; k < count; k++) {
          const mesh = new THREE.Mesh(geo, mat);
          if (k) { mesh.scale.setScalar(0.35); mesh.position.set((Math.random() - 0.5) * 3, Math.random() * 1.5, (Math.random() - 0.5) * 3); }
          obj.add(mesh);
        }
        if (m.label) {
          const sprite = textSprite(m.label, '#ffe6a8', 28);
          const k = this.extent / 40;
          sprite.scale.set(k * sprite.userData.aspect, k, 1);
          sprite.position.set(0, k * 1.4, 0);
          obj.add(sprite);
        }
        this.world.add(obj);
        this.markerObjs.set(key, obj);
      }
      obj.position.copy(this.toScene(m.x, m.y, m.ft || 0));
    });
    for (const [key, obj] of this.markerObjs) {
      if (!seen.has(key)) { obj.removeFromParent(); this.markerObjs.delete(key); }
    }
  }

  // ---------- aircraft
  upsertAircraft(id, { x, y, ft, heading = 0, color = COLORS.aircraft, label = null, labelClass = '', ghost = false }) {
    let a = this.aircraft.get(id);
    if (!a) {
      const mesh = planeGeometry();
      const material = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.25, metalness: 0.1, roughness: 0.6, transparent: ghost, opacity: ghost ? 0.45 : 1 });
      mesh.children.forEach((c) => { c.material = material; c.userData.id = id; });
      mesh.scale.setScalar(this.aircraftScale);
      this.world.add(mesh);
      a = { mesh, material, id };
      this.aircraft.set(id, a);
    }
    a.material.color.set(color);
    a.material.emissive.set(color);
    a.mesh.position.copy(this.toScene(x, y, ft));
    a.mesh.rotation.y = Math.PI - THREE.MathUtils.degToRad(heading);
    a.state = { x, y, ft, heading };
    a.seen = true;
    if (label) this._label(id, label, labelClass); else this._removeLabel(id);
    return a;
  }

  beginFrame() { this.aircraft.forEach((a) => (a.seen = false)); }

  endFrame() {
    for (const [id, a] of this.aircraft) {
      if (!a.seen) {
        a.mesh.removeFromParent();
        this.aircraft.delete(id);
        this._removeLabel(id);
      }
    }
    const pts = [];
    this.aircraft.forEach((a) => {
      if (a.state.ft > 0) {
        pts.push(a.mesh.position.x, a.mesh.position.y, a.mesh.position.z, a.mesh.position.x, 0, a.mesh.position.z);
      }
    });
    this.stems.geometry.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    this.stems.geometry.computeBoundingSphere();
  }

  setTrails(trails) {
    // trails: [{points: [[x, y, ft], ...], color?: THREE.Color | null}]
    const pos = [], col = [];
    for (const tr of trails) {
      for (let i = 1; i < tr.points.length; i++) {
        const a = tr.points[i - 1], b = tr.points[i];
        const pa = this.toScene(a[0], a[1], a[2]), pb = this.toScene(b[0], b[1], b[2]);
        pos.push(pa.x, pa.y, pa.z, pb.x, pb.y, pb.z);
        const ca = tr.color || altitudeColor(a[2]);
        const cb = tr.color || altitudeColor(b[2]);
        const fade = i / tr.points.length;
        col.push(ca.r * fade, ca.g * fade, ca.b * fade, cb.r * fade, cb.g * fade, cb.b * fade);
      }
    }
    this.trails.geometry.dispose();
    this.trails.geometry = new THREE.BufferGeometry();
    this.trails.geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    this.trails.geometry.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  }

  setPath(name, points, { color = 0xffffff, dashed = false, opacity = 0.9 } = {}) {
    this.removePath(name);
    if (!points || points.length < 2) return;
    const geo = new THREE.BufferGeometry().setFromPoints(points.map(([x, y, ft]) => this.toScene(x, y, ft)));
    const mat = dashed
      ? new THREE.LineDashedMaterial({ color, dashSize: this.extent / 40, gapSize: this.extent / 60, transparent: true, opacity })
      : new THREE.LineBasicMaterial({ color, transparent: true, opacity });
    const line = new THREE.Line(geo, mat);
    if (dashed) line.computeLineDistances();
    this.world.add(line);
    this.paths.set(name, line);
  }

  setSegments(name, segments, { color = 0xffffff, opacity = 0.7 } = {}) {
    // segments: [[x1, y1, ft1, x2, y2, ft2], ...] drawn as one batched object
    this.removePath(name);
    if (!segments.length) return;
    const pos = [];
    for (const s of segments) {
      const a = this.toScene(s[0], s[1], s[2]), b = this.toScene(s[3], s[4], s[5]);
      pos.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    const line = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
    this.world.add(line);
    this.paths.set(name, line);
  }

  removePath(name) {
    const p = this.paths.get(name);
    if (p) { p.removeFromParent(); p.geometry.dispose(); this.paths.delete(name); }
  }

  clearPaths(prefix = '') {
    for (const name of [...this.paths.keys()]) if (name.startsWith(prefix)) this.removePath(name);
  }

  // ---------- labels
  _label(id, text, cls) {
    let el = this.labels.get(id);
    if (!el) {
      el = document.createElement('div');
      this.labelLayer.appendChild(el);
      this.labels.set(id, el);
    }
    el.className = 'label3d ' + cls;
    if (el.textContent !== text) el.textContent = text;
  }

  _removeLabel(id) {
    const el = this.labels.get(id);
    if (el) { el.remove(); this.labels.delete(id); }
  }

  _placeLabels() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    const v = new THREE.Vector3();
    for (const [id, el] of this.labels) {
      const a = this.aircraft.get(id);
      if (!a) continue;
      v.copy(a.mesh.position).project(this.camera);
      const visible = v.z < 1 && Math.abs(v.x) < 1.1 && Math.abs(v.y) < 1.1;
      el.style.display = visible ? '' : 'none';
      if (visible) el.style.transform = `translate(${(v.x + 1) / 2 * w}px, ${(1 - v.y) / 2 * h}px) translate(-50%, -135%)`;
    }
  }

  // ---------- camera and interaction
  _controls() {
    const el = this.renderer.domElement;
    let drag = null;
    el.addEventListener('contextmenu', (e) => e.preventDefault());
    el.addEventListener('pointerdown', (e) => {
      drag = { x: e.clientX, y: e.clientY, button: e.button, shift: e.shiftKey, moved: 0 };
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY; drag.moved += Math.abs(dx) + Math.abs(dy);
      if (drag.button === 2 || drag.shift) {
        const k = this.orbit.radius / 900;
        const right = new THREE.Vector3(Math.cos(this.orbit.theta), 0, -Math.sin(this.orbit.theta));
        const fwd = new THREE.Vector3(Math.sin(this.orbit.theta), 0, Math.cos(this.orbit.theta));
        this.orbit.target.addScaledVector(right, -dx * k).addScaledVector(fwd, -dy * k);
      } else {
        this.orbit.theta -= dx * 0.006;
        this.orbit.phi = Math.max(0.12, Math.min(1.5, this.orbit.phi - dy * 0.005));
      }
      this._updateCamera();
    });
    el.addEventListener('pointerup', (e) => {
      if (drag && drag.moved < 5) this._pick(e);
      drag = null;
    });
    el.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.orbit.radius = Math.max(this.extent * 0.15, Math.min(this.extent * 5, this.orbit.radius * (1 + Math.sign(e.deltaY) * 0.1)));
      this._updateCamera();
    }, { passive: false });
  }

  _updateCamera() {
    const { theta, phi, radius, target } = this.orbit;
    this.camera.position.set(target.x + radius * Math.sin(phi) * Math.sin(theta), target.y + radius * Math.cos(phi), target.z + radius * Math.sin(phi) * Math.cos(theta));
    this.camera.lookAt(target);
  }

  view(name) {
    if (name === 'top') Object.assign(this.orbit, { phi: 0.13, theta: 0 });
    if (name === 'perspective') Object.assign(this.orbit, { phi: 0.95, theta: -0.55 });
    if (name === 'side') Object.assign(this.orbit, { phi: 1.42, theta: 0 });
    this._updateCamera();
  }

  focus(x, y, ft = 0, radius = null) {
    this.orbit.target.copy(this.toScene(x, y, ft));
    if (radius) this.orbit.radius = radius;
    this._updateCamera();
  }

  _pick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(mouse, this.camera);
    const meshes = [];
    this.aircraft.forEach((a) => meshes.push(...a.mesh.children));
    const hit = this.raycaster.intersectObjects(meshes, false)[0];
    let id = hit ? hit.object.userData.id : null;
    if (!id) {
      // generous screen-space pick for small aircraft
      let best = 18;
      const v = new THREE.Vector3();
      this.aircraft.forEach((a) => {
        v.copy(a.mesh.position).project(this.camera);
        const px = (v.x + 1) / 2 * rect.width, py = (1 - v.y) / 2 * rect.height;
        const d = Math.hypot(px - (e.clientX - rect.left), py - (e.clientY - rect.top));
        if (d < best) { best = d; id = a.id; }
      });
    }
    if (id && this.onSelect) this.onSelect(id);
  }

  resize() {
    const w = this.container.clientWidth || 800, h = this.container.clientHeight || 500;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  snapshot() { return this.renderer.domElement.toDataURL('image/png'); }

  dispose() {
    this.running = false;
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labelLayer.remove();
  }
}

export const PALETTE = COLORS;
