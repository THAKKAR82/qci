// Illustrative Bloch sphere. Character changes are visual, not measured probabilities.
const canvas = document.querySelector("#bloch-sphere");

if (canvas) {
  const context = canvas.getContext("2d");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const bodyGlyphs = ["·", ":", "0", "1", "ψ", "φ", "θ", "ℏ", "σ", "⊗"];
  const contourGlyphs = ["0", "1", "ψ", "σ", "⊗"];
  const activeGlyphs = ["Ψ", "Φ", "Θ", "Σ", "Ω", "⊗", "ℏ", "1", "0"];
  const guidePaths = [];
  const tilt = 0.1222;

  for (const z of [-0.68, 0, 0.68]) {
    const radius = Math.sqrt(1 - z * z);
    guidePaths.push(Array.from({ length: 81 }, (_, index) => {
      const angle = (index / 80) * Math.PI * 2;
      return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, z };
    }));
  }
  for (let meridian = 0; meridian < 6; meridian += 1) {
    const angle = (meridian / 6) * Math.PI * 2;
    guidePaths.push(Array.from({ length: 49 }, (_, index) => {
      const polar = (index / 48) * Math.PI;
      return { x: Math.cos(angle) * Math.sin(polar), y: Math.sin(angle) * Math.sin(polar), z: Math.cos(polar) };
    }));
  }

  let width = 0;
  let height = 0;
  let rotation = Math.PI / 4;
  let pointer = null;
  const mouseVector = { x: 0, y: 0, opacity: 0 };
  let waves = [];
  let lastWaveTime = 0;
  let lastFrame = 0;
  let frame = 0;
  let visible = false;

  function project(point, size, cx, cy) {
    const tiltedY = point.y * Math.cos(tilt) - point.z * Math.sin(tilt);
    const tiltedZ = point.y * Math.sin(tilt) + point.z * Math.cos(tilt);
    const turnedX = point.x * Math.cos(rotation) - tiltedY * Math.sin(rotation);
    const turnedY = point.x * Math.sin(rotation) + tiltedY * Math.cos(rotation);
    return {
      x: cx + turnedX * size,
      y: cy - tiltedZ * size * 0.91 + turnedY * size * 0.32,
      depth: turnedY * 0.91 + tiltedZ * 0.32,
    };
  }

  function waveStrength(x, y, now) {
    let strength = 0;
    for (const wave of waves) {
      const age = Math.max(0, now - wave.time);
      const distance = Math.hypot(x - wave.x, y - wave.y);
      const band = Math.exp(-(((distance - age * 0.23) / 16) ** 2));
      strength = Math.max(strength, band * Math.max(0, 1 - age / 1300));
    }
    if (pointer) {
      const distance = Math.hypot(x - pointer.x, y - pointer.y);
      strength = Math.max(strength, Math.exp(-((distance / 22) ** 2)) * 0.1);
    }
    return strength;
  }

  function drawGuides(size, cx, cy) {
    const paths = guidePaths.map((path) => path.map((point) => project(point, size, cx, cy)));
    for (const front of [false, true]) {
      context.lineWidth = front
        ? Math.max(1.2, size * 0.0055)
        : Math.max(0.8, size * 0.0035);
      context.beginPath();
      for (const path of paths) {
        for (let index = 1; index < path.length; index += 1) {
          const start = path[index - 1];
          const end = path[index];
          if ((start.depth + end.depth > 0) !== front) continue;
          context.moveTo(start.x, start.y);
          context.lineTo(end.x, end.y);
        }
      }
      context.setLineDash(front ? [] : [4, 6]);
      context.strokeStyle = front ? "rgba(48, 89, 176, 0.42)" : "rgba(48, 89, 176, 0.16)";
      context.stroke();
    }
    context.setLineDash([]);
  }

  function drawCharacters(size, cx, cy, now) {
    const cellWidth = Math.max(10.5, size * 0.049);
    const cellHeight = cellWidth * 1.17;
    context.font = `500 ${cellWidth * 0.96}px ui-monospace, SFMono-Regular, Consolas, monospace`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    let row = 0;
    for (let y = cy - size; y <= cy + size; y += cellHeight) {
      let column = 0;
      for (let x = cx - size; x <= cx + size; x += cellWidth) {
        const u = (x - cx) / size;
        const v = (y - cy) / size;
        const disk = u * u + v * v;
        if (disk > 0.98) {
          column += 1;
          continue;
        }
        const depth = Math.sqrt(1 - disk);
        const turnedY = v * 0.32 + depth * 0.91;
        const turnedZ = -v * 0.91 + depth * 0.32;
        const worldX = u * Math.cos(rotation) + turnedY * Math.sin(rotation);
        const tiltedY = -u * Math.sin(rotation) + turnedY * Math.cos(rotation);
        const worldY = tiltedY * Math.cos(tilt) + turnedZ * Math.sin(tilt);
        const worldZ = -tiltedY * Math.sin(tilt) + turnedZ * Math.cos(tilt);
        const longitude = Math.atan2(worldY, worldX);
        const latitudeDistance = Math.min(...[-0.68, 0, 0.68].map((ring) => Math.abs(worldZ - ring)));
        const meridianDistance = Math.abs(Math.sin(longitude * 3)) * Math.sqrt(1 - worldZ * worldZ);
        const contour = Math.max(0, 1 - latitudeDistance / 0.085, 1 - meridianDistance / 0.105);
        const ripple = waveStrength(x, y, now);
        const seed = Math.abs(row * 71 + column * 47 + Math.floor((longitude + Math.PI) * 8));
        const glyphs = contour > 0.38 ? contourGlyphs : bodyGlyphs;
        const glyph = glyphs[seed % glyphs.length];
        const rippleGlyph = ripple > 0.46 && seed % 2 === 0;
        const visibleGlyph = rippleGlyph ? activeGlyphs[seed % activeGlyphs.length] : glyph;
        const alpha = Math.min(0.94, 0.19 + depth * 0.42 + contour * 0.17 + ripple * 0.3);
        const red = Math.round(35 + ripple * 15);
        const green = Math.round(80 - ripple * 8);
        const blue = Math.round(190 + ripple * 24);
        context.fillStyle = `rgba(${red}, ${green}, ${blue}, ${alpha})`;
        context.fillText(visibleGlyph, x, y);
        column += 1;
      }
      row += 1;
    }
  }

  function drawAxes(size, cx, cy) {
    const axes = [
      { x: 1, y: 0, z: 0 },
      { x: 0, y: 1, z: 0 },
      { x: 0, y: 0, z: 1 },
    ];
    context.lineWidth = Math.max(2, size * 0.01);
    context.lineCap = "round";
    for (const axis of axes) {
      for (const sign of [-1, 1]) {
        const end = project({ x: axis.x * sign * 1.17, y: axis.y * sign * 1.17, z: axis.z * sign * 1.17 }, size, cx, cy);
        const front = end.depth > 0;
        context.setLineDash(front ? [] : [5, 6]);
        context.strokeStyle = front ? "rgba(31, 42, 60, 0.82)" : "rgba(31, 42, 60, 0.42)";
        context.beginPath();
        context.moveTo(cx, cy);
        context.lineTo(end.x, end.y);
        context.stroke();
      }
    }
    context.setLineDash([]);
  }

  function drawAxisLabels(size, cx, cy) {
    context.fillStyle = "#1f2a3c";
    context.font = `600 ${Math.max(13, size * 0.07)}px Cambria Math, Segoe UI Symbol, serif`;
    context.textBaseline = "middle";
    for (const { text, point } of [
      { text: "X", point: { x: 1.28, y: 0, z: 0 } },
      { text: "Y", point: { x: 0, y: 1.28, z: 0 } },
      { text: "|1⟩", point: { x: 0, y: 0, z: 1.35 } },
      { text: "|0⟩", point: { x: 0, y: 0, z: -1.35 } },
    ]) {
      const position = project(point, size, cx, cy);
      context.fillText(text, position.x, position.y);
    }
    for (const point of [
      { x: 1, y: 0, z: 0 }, { x: -1, y: 0, z: 0 },
      { x: 0, y: 1, z: 0 }, { x: 0, y: -1, z: 0 },
      { x: 0, y: 0, z: 1 }, { x: 0, y: 0, z: -1 },
    ]) {
      const position = project(point, size, cx, cy);
      context.beginPath();
      context.arc(position.x, position.y, Math.max(3, size * 0.017), 0, Math.PI * 2);
      context.fill();
    }
  }

  function drawMouseVector(size, cx, cy) {
    const targetX = pointer ? pointer.x - cx : 0;
    const targetY = pointer ? pointer.y - cy : 0;
    const distance = Math.hypot(targetX, targetY);
    const limit = size * 0.82;
    const scale = distance > limit ? limit / distance : 1;
    const easing = reducedMotion.matches ? 1 : 0.12;
    mouseVector.x += (targetX * scale - mouseVector.x) * easing;
    mouseVector.y += (targetY * scale - mouseVector.y) * easing;
    mouseVector.opacity += ((pointer ? 0.78 : 0) - mouseVector.opacity) * easing;
    if (mouseVector.opacity < 0.015) return;

    const endX = cx + mouseVector.x;
    const endY = cy + mouseVector.y;
    context.globalAlpha = mouseVector.opacity;
    context.strokeStyle = "#882644";
    context.lineWidth = Math.max(1.4, size * 0.005);
    context.lineCap = "round";
    context.beginPath();
    context.moveTo(cx, cy);
    context.lineTo(endX, endY);
    context.stroke();
    context.fillStyle = "#882644";
    context.beginPath();
    context.arc(endX, endY, Math.max(2.6, size * 0.011), 0, Math.PI * 2);
    context.fill();
    context.globalAlpha = 1;
  }

  function render(now = performance.now()) {
    if (!width || !height) return;
    context.clearRect(0, 0, width, height);
    const size = Math.min(width, height) * 0.34;
    const cx = width / 2;
    const cy = height / 2;
    drawCharacters(size, cx, cy, now);
    drawGuides(size, cx, cy);
    context.beginPath();
    context.arc(cx, cy, size, 0, Math.PI * 2);
    context.lineWidth = Math.max(1.8, size * 0.009);
    context.strokeStyle = "rgba(39, 76, 159, 0.68)";
    context.stroke();
    drawAxes(size, cx, cy);
    drawMouseVector(size, cx, cy);
    drawAxisLabels(size, cx, cy);
  }

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = bounds.width;
    height = bounds.height;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    render();
  }

  function animate(time) {
    frame = 0;
    if (!visible || reducedMotion.matches) return;
    if (!lastFrame) lastFrame = time;
    const delta = Math.min(time - lastFrame, 80);
    if (delta >= 24) {
      rotation += (delta * Math.PI * 2) / 50000;
      waves = waves.filter((wave) => time - wave.time < 920);
      render(time);
      lastFrame = time;
    }
    frame = requestAnimationFrame(animate);
  }

  function updatePointer(event) {
    const bounds = canvas.getBoundingClientRect();
    const next = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    const size = Math.min(width, height) * 0.34;
    if (Math.hypot(next.x - width / 2, next.y - height / 2) > size) {
      pointer = null;
      if (reducedMotion.matches) render();
      return;
    }
    pointer = next;
    const now = performance.now();
    if (reducedMotion.matches) {
      waves = [{ ...pointer, time: now }];
    } else if (now - lastWaveTime > 90) {
      waves.push({ ...pointer, time: now });
      waves = waves.slice(-2);
      lastWaveTime = now;
    }
    if (reducedMotion.matches) render(now);
    else if (visible && !frame) {
      lastFrame = 0;
      frame = requestAnimationFrame(animate);
    }
  }

  canvas.addEventListener("pointermove", updatePointer);
  canvas.addEventListener("pointerdown", updatePointer);
  canvas.addEventListener("pointerleave", () => {
    pointer = null;
    if (reducedMotion.matches) render();
  });
  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    if (visible && !frame && !reducedMotion.matches) {
      lastFrame = 0;
      frame = requestAnimationFrame(animate);
    }
  }).observe(canvas);
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) {
      cancelAnimationFrame(frame);
      frame = 0;
      waves = [];
      render();
    } else if (visible && !frame) {
      lastFrame = 0;
      frame = requestAnimationFrame(animate);
    }
  });
}
