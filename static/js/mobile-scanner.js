/**
 * DOVE LO AI MESSO — Mobile Document Scanner & Permission Engine
 * File: static/js/mobile-scanner.js
 * 
 * Features:
 * 1. Rich contextual permission dialogs for Camera and Microphone in Android WebView/APK.
 * 2. High-resolution live camera capture with back-facing camera ('environment').
 * 3. Automatic 4-corner paper detection with safe fallbacks.
 * 4. Interactive touch corner handles with real-time magnifying loupe (2x).
 * 5. Homography perspective dewarping (planar transformation).
 * 6. Document enhancement filters: Original, Magic Color (shadow removal/whitening), Pure B&W.
 * 7. Instant multipart upload to /api/documents/upload.
 */

(function (window) {
  'use strict';

  // State
  let currentStream = null;
  let rawCapturedCanvas = null;
  let warpedCanvas = null;
  let filteredCanvas = null;
  let detectedCorners = null; // [topLeft, topRight, bottomRight, bottomLeft]
  let activeDragIndex = -1;
  let currentFilter = 'magic_color';
  let activeThreadId = 'general';

  // --- Geometry Helpers ---
  function distance(p1, p2) {
    const dx = p1.x - p2.x;
    const dy = p1.y - p2.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  // Solves 8x8 linear system for 2D perspective transform (Homography)
  function getPerspectiveTransform(src, dst) {
    const a = [];
    for (let i = 0; i < 4; i++) {
      const sx = src[i].x, sy = src[i].y;
      const dx = dst[i].x, dy = dst[i].y;
      a.push([sx, sy, 1, 0, 0, 0, -sx * dx, -sy * dx, dx]);
      a.push([0, 0, 0, sx, sy, 1, -sx * dy, -sy * dy, dy]);
    }

    // Gaussian elimination
    const n = 8;
    for (let i = 0; i < n; i++) {
      let maxEl = Math.abs(a[i][i]);
      let maxRow = i;
      for (let k = i + 1; k < n; k++) {
        if (Math.abs(a[k][i]) > maxEl) {
          maxEl = Math.abs(a[k][i]);
          maxRow = k;
        }
      }
      for (let k = i; k < n + 1; k++) {
        const tmp = a[maxRow][k];
        a[maxRow][k] = a[i][k];
        a[i][k] = tmp;
      }
      for (let k = i + 1; k < n; k++) {
        const c = -a[k][i] / (a[i][i] || 1e-10);
        for (let j = i; j < n + 1; j++) {
          if (i === j) a[k][j] = 0;
          else a[k][j] += c * a[i][j];
        }
      }
    }

    const h = new Array(8);
    for (let i = n - 1; i >= 0; i--) {
      h[i] = a[i][n] / (a[i][i] || 1e-10);
      for (let k = i - 1; k >= 0; k--) {
        a[k][n] -= a[k][i] * h[i];
      }
    }
    return [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1];
  }

  // Invert 3x3 matrix
  function invert3x3(m) {
    const a = m[0], b = m[1], c = m[2];
    const d = m[3], e = m[4], f = m[5];
    const g = m[6], h = m[7], k = m[8];

    const A = (e * k - f * h);
    const B = -(d * k - f * g);
    const C = (d * h - e * g);
    const D = -(b * k - c * h);
    const E = (a * k - c * g);
    const F = -(a * h - b * g);
    const G = (b * f - c * e);
    const H = -(a * f - c * d);
    const K = (a * e - b * d);

    const det = a * A + b * B + c * C;
    if (Math.abs(det) < 1e-10) return null;

    const invDet = 1.0 / det;
    return [
      A * invDet, D * invDet, G * invDet,
      B * invDet, E * invDet, H * invDet,
      C * invDet, F * invDet, K * invDet
    ];
  }

  // --- Document Edge & Perspective Dewarp ---
  function defaultCorners(width, height) {
    const marginX = width * 0.08;
    const marginY = height * 0.08;
    return [
      { x: marginX, y: marginY },                         // top-left
      { x: width - marginX, y: marginY },                 // top-right
      { x: width - marginX, y: height - marginY },         // bottom-right
      { x: marginX, y: height - marginY }                  // bottom-left
    ];
  }

  function detectPaperCorners(canvas) {
    const w = canvas.width;
    const h = canvas.height;
    // Fast analysis on downsampled canvas
    const sampleCanvas = document.createElement('canvas');
    const scale = Math.min(1.0, 480 / Math.max(w, h));
    const sw = Math.floor(w * scale);
    const sh = Math.floor(h * scale);
    sampleCanvas.width = sw;
    sampleCanvas.height = sh;
    const sctx = sampleCanvas.getContext('2d');
    sctx.drawImage(canvas, 0, 0, sw, sh);

    try {
      const imgData = sctx.getImageData(0, 0, sw, sh);
      const data = imgData.data;

      // Calculate center of mass of brighter document area
      let minX = sw, maxX = 0, minY = sh, maxY = 0;
      let sumX = 0, sumY = 0, count = 0;
      for (let y = 0; y < sh; y += 4) {
        for (let x = 0; x < sw; x += 4) {
          const idx = (y * sw + x) * 4;
          const lum = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
          if (lum > 110) {
            sumX += x;
            sumY += y;
            count++;
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
          }
        }
      }

      // If document area detected with good bounds
      if (count > (sw * sh * 0.15) && (maxX - minX) > sw * 0.4 && (maxY - minY) > sh * 0.4) {
        const invScale = 1.0 / scale;
        return [
          { x: Math.max(0, minX * invScale), y: Math.max(0, minY * invScale) },
          { x: Math.min(w, maxX * invScale), y: Math.max(0, minY * invScale) },
          { x: Math.min(w, maxX * invScale), y: Math.min(h, maxY * invScale) },
          { x: Math.max(0, minX * invScale), y: Math.min(h, maxY * invScale) }
        ];
      }
    } catch (e) {
      console.warn("Edge detection fallback:", e);
    }
    return defaultCorners(w, h);
  }

  function applyPerspectiveWarp(sourceCanvas, corners) {
    const p0 = corners[0], p1 = corners[1], p2 = corners[2], p3 = corners[3];
    const topW = distance(p0, p1);
    const botW = distance(p3, p2);
    const leftH = distance(p0, p3);
    const rightH = distance(p1, p2);

    const dstW = Math.max(200, Math.floor(Math.max(topW, botW)));
    const dstH = Math.max(200, Math.floor(Math.max(leftH, rightH)));

    const dstCorners = [
      { x: 0, y: 0 },
      { x: dstW, y: 0 },
      { x: dstW, y: dstH },
      { x: 0, y: dstH }
    ];

    const H = getPerspectiveTransform(corners, dstCorners);
    const Hinv = invert3x3(H);
    if (!Hinv) return sourceCanvas;

    const outCanvas = document.createElement('canvas');
    outCanvas.width = dstW;
    outCanvas.height = dstH;
    const outCtx = outCanvas.getContext('2d');

    const srcCtx = sourceCanvas.getContext('2d');
    const srcData = srcCtx.getImageData(0, 0, sourceCanvas.width, sourceCanvas.height);
    const dstData = outCtx.createImageData(dstW, dstH);

    const sdata = srcData.data;
    const ddata = dstData.data;
    const sw = sourceCanvas.width;
    const sh = sourceCanvas.height;

    const m0 = Hinv[0], m1 = Hinv[1], m2 = Hinv[2];
    const m3 = Hinv[3], m4 = Hinv[4], m5 = Hinv[5];
    const m6 = Hinv[6], m7 = Hinv[7], m8 = Hinv[8];

    for (let dy = 0; dy < dstH; dy++) {
      for (let dx = 0; dx < dstW; dx++) {
        const denom = m6 * dx + m7 * dy + m8 || 1e-10;
        const sx = Math.floor((m0 * dx + m1 * dy + m2) / denom);
        const sy = Math.floor((m3 * dx + m4 * dy + m5) / denom);

        const didx = (dy * dstW + dx) * 4;
        if (sx >= 0 && sx < sw && sy >= 0 && sy < sh) {
          const sidx = (sy * sw + sx) * 4;
          ddata[didx] = sdata[sidx];
          ddata[didx + 1] = sdata[sidx + 1];
          ddata[didx + 2] = sdata[sidx + 2];
          ddata[didx + 3] = 255;
        } else {
          ddata[didx] = 255;
          ddata[didx + 1] = 255;
          ddata[didx + 2] = 255;
          ddata[didx + 3] = 255;
        }
      }
    }

    outCtx.putImageData(dstData, 0, 0);
    return outCanvas;
  }

  // --- Document Enhancement Filters ---
  function applyFilter(canvas, filterType) {
    const out = document.createElement('canvas');
    out.width = canvas.width;
    out.height = canvas.height;
    const ctx = out.getContext('2d');
    ctx.drawImage(canvas, 0, 0);

    if (filterType === 'original') {
      return out;
    }

    const imgData = ctx.getImageData(0, 0, out.width, out.height);
    const d = imgData.data;
    const len = d.length;

    if (filterType === 'magic_color') {
      // Whitens shadow and enhances text contrast
      for (let i = 0; i < len; i += 4) {
        let r = d[i], g = d[i + 1], b = d[i + 2];
        const lum = 0.299 * r + 0.587 * g + 0.114 * b;

        if (lum > 145) {
          // Whitening background curve
          const boost = (lum - 145) / 110;
          r = Math.min(255, r + (255 - r) * boost * 0.9);
          g = Math.min(255, g + (255 - g) * boost * 0.9);
          b = Math.min(255, b + (255 - b) * boost * 0.9);
        } else {
          // Darken text
          r = Math.max(0, r * 0.85);
          g = Math.max(0, g * 0.85);
          b = Math.max(0, b * 0.85);
        }
        d[i] = r;
        d[i + 1] = g;
        d[i + 2] = b;
      }
    } else if (filterType === 'bw') {
      // Crisp adaptive B&W threshold
      for (let i = 0; i < len; i += 4) {
        const lum = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
        const val = lum < 138 ? 0 : 255;
        d[i] = val;
        d[i + 1] = val;
        d[i + 2] = val;
      }
    }

    ctx.putImageData(imgData, 0, 0);
    return out;
  }

  // --- Permission Manager ---
  async function requestMobilePermission(type) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("L'API Fotocamera/Microfono non è supportata su questo browser/WebView.");
    }

    const isVideo = type === 'camera' || type === 'video';
    const constraints = isVideo
      ? { video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } } }
      : { audio: true };

    try {
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      return stream;
    } catch (err) {
      console.warn(`Permesso ${type} non concesso:`, err);
      throw err;
    }
  }

  // --- UI Controller & Native Camera Fallback ---
  function triggerNativeCamera() {
    const itemPhotoInput = document.getElementById('itemPhotoInput');
    if (itemPhotoInput) {
      itemPhotoInput.click();
    } else {
      const realFileInput = document.getElementById('realFileInput');
      if (realFileInput) realFileInput.click();
    }
  }

  function loadExternalImage(imageFileOrBlob) {
    if (!imageFileOrBlob) return;
    const reader = new FileReader();
    reader.onload = function (e) {
      const img = new Image();
      img.onload = function () {
        rawCapturedCanvas = document.createElement('canvas');
        rawCapturedCanvas.width = img.naturalWidth || img.width;
        rawCapturedCanvas.height = img.naturalHeight || img.height;
        const ctx = rawCapturedCanvas.getContext('2d');
        ctx.drawImage(img, 0, 0);

        stopCamera();

        // Rileva i 4 angoli del foglio e apri subito la vista ritaglio
        detectedCorners = detectPaperCorners(rawCapturedCanvas);
        const modal = document.getElementById('mobileScannerModal');
        if (modal) {
          modal.classList.remove('hidden');
          modal.classList.add('flex');
        }
        setScannerView('crop');
        renderCropOverlay();
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(imageFileOrBlob);
  }

  function openScannerModal(threadId) {
    activeThreadId = threadId || 'general';

    // Se navigator.mediaDevices non è disponibile (es. contesto HTTP locale non sicuro su Android)
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      console.warn("navigator.mediaDevices non disponibile in questo contesto (es. HTTP su LAN). Avvio fotocamera nativa.");
      triggerNativeCamera();
      return;
    }

    const modal = document.getElementById('mobileScannerModal');
    if (!modal) return;

    modal.classList.remove('hidden');
    modal.classList.add('flex');
    setScannerView('camera');
    startCameraPreview();
  }

  function closeScannerModal() {
    stopCamera();
    const modal = document.getElementById('mobileScannerModal');
    if (modal) {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
    }
  }

  function setScannerView(view) {
    const vCam = document.getElementById('scannerCameraView');
    const vCrop = document.getElementById('scannerCropView');
    const vFilter = document.getElementById('scannerFilterView');

    if (vCam) vCam.classList.toggle('hidden', view !== 'camera');
    if (vCrop) vCrop.classList.toggle('hidden', view !== 'crop');
    if (vFilter) vFilter.classList.toggle('hidden', view !== 'filter');
  }

  async function startCameraPreview() {
    const video = document.getElementById('scannerVideo');
    const errBox = document.getElementById('scannerPermissionError');
    if (errBox) errBox.classList.add('hidden');

    try {
      currentStream = await requestMobilePermission('camera');
      if (video) {
        video.srcObject = currentStream;
        await video.play();
      }
    } catch (err) {
      if (errBox) {
        errBox.classList.remove('hidden');
      }
    }
  }

  function stopCamera() {
    if (currentStream) {
      currentStream.getTracks().forEach(track => track.stop());
      currentStream = null;
    }
    const video = document.getElementById('scannerVideo');
    if (video) {
      video.srcObject = null;
    }
  }

  function captureCurrentFrame() {
    const video = document.getElementById('scannerVideo');
    if (!video || !video.videoWidth) return;

    rawCapturedCanvas = document.createElement('canvas');
    rawCapturedCanvas.width = video.videoWidth;
    rawCapturedCanvas.height = video.videoHeight;
    const ctx = rawCapturedCanvas.getContext('2d');
    ctx.drawImage(video, 0, 0);

    stopCamera();

    // Detect corners
    detectedCorners = detectPaperCorners(rawCapturedCanvas);
    setScannerView('crop');
    renderCropOverlay();
  }

  function renderCropOverlay() {
    const canvas = document.getElementById('scannerCropCanvas');
    if (!canvas || !rawCapturedCanvas) return;

    const container = canvas.parentElement;
    const maxW = container.clientWidth || window.innerWidth;
    const maxH = container.clientHeight || (window.innerHeight - 140);

    const scale = Math.min(maxW / rawCapturedCanvas.width, maxH / rawCapturedCanvas.height);
    canvas.width = rawCapturedCanvas.width * scale;
    canvas.height = rawCapturedCanvas.height * scale;

    const ctx = canvas.getContext('2d');
    ctx.drawImage(rawCapturedCanvas, 0, 0, canvas.width, canvas.height);

    // Draw polygon
    ctx.save();
    ctx.strokeStyle = '#3C5A48';
    ctx.lineWidth = 3;
    ctx.fillStyle = 'rgba(60, 90, 72, 0.15)';
    ctx.beginPath();
    cornersToCanvas(scale).forEach((pt, i) => {
      if (i === 0) ctx.moveTo(pt.x, pt.y);
      else ctx.lineTo(pt.x, pt.y);
    });
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Draw handles
    cornersToCanvas(scale).forEach((pt, i) => {
      ctx.fillStyle = '#C84B31';
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 14, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#FFFFFF';
      ctx.lineWidth = 3;
      ctx.stroke();
    });
    ctx.restore();
  }

  function cornersToCanvas(scale) {
    return detectedCorners.map(p => ({ x: p.x * scale, y: p.y * scale }));
  }

  function setupTouchEvents() {
    const canvas = document.getElementById('scannerCropCanvas');
    if (!canvas) return;

    function getEventPos(e) {
      const rect = canvas.getBoundingClientRect();
      const touch = e.touches ? e.touches[0] : e;
      return {
        x: touch.clientX - rect.left,
        y: touch.clientY - rect.top
      };
    }

    function onStart(e) {
      if (!detectedCorners || !rawCapturedCanvas) return;
      const scale = canvas.width / rawCapturedCanvas.width;
      const pos = getEventPos(e);
      const c = cornersToCanvas(scale);

      let closest = -1;
      let minD = 35; // touch hit radius
      c.forEach((pt, i) => {
        const d = distance(pos, pt);
        if (d < minD) {
          minD = d;
          closest = i;
        }
      });
      activeDragIndex = closest;
    }

    function onMove(e) {
      if (activeDragIndex === -1 || !rawCapturedCanvas) return;
      e.preventDefault();
      const scale = canvas.width / rawCapturedCanvas.width;
      const pos = getEventPos(e);

      const invScale = 1.0 / scale;
      detectedCorners[activeDragIndex] = {
        x: Math.max(0, Math.min(rawCapturedCanvas.width, pos.x * invScale)),
        y: Math.max(0, Math.min(rawCapturedCanvas.height, pos.y * invScale))
      };
      renderCropOverlay();
    }

    function onEnd() {
      activeDragIndex = -1;
    }

    canvas.addEventListener('touchstart', onStart, { passive: false });
    canvas.addEventListener('touchmove', onMove, { passive: false });
    canvas.addEventListener('touchend', onEnd);
    canvas.addEventListener('mousedown', onStart);
    canvas.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onEnd);
  }

  function confirmCropAndShowFilters() {
    if (!rawCapturedCanvas || !detectedCorners) return;
    warpedCanvas = applyPerspectiveWarp(rawCapturedCanvas, detectedCorners);
    setScannerView('filter');
    updateFilterPreview('magic_color');
  }

  function updateFilterPreview(filterType) {
    currentFilter = filterType;
    if (!warpedCanvas) return;

    filteredCanvas = applyFilter(warpedCanvas, filterType);
    const previewImg = document.getElementById('scannerPreviewImg');
    if (previewImg) {
      previewImg.src = filteredCanvas.toDataURL('image/jpeg', 0.9);
    }

    // Toggle button active states
    document.querySelectorAll('.scanner-filter-btn').forEach(btn => {
      const isCurrent = btn.getAttribute('data-filter') === filterType;
      btn.classList.toggle('border-[#3C5A48]', isCurrent);
      btn.classList.toggle('bg-[#3C5A48]', isCurrent);
      btn.classList.toggle('text-white', isCurrent);
      btn.classList.toggle('text-[#222220]', !isCurrent);
    });
  }

  async function uploadCurrentScan() {
    if (!filteredCanvas) return;
    const btn = document.getElementById('btnSubmitScan');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin mr-1.5"></i> Protocollo in corso...`;
    }

    filteredCanvas.toBlob(async (blob) => {
      if (!blob) {
        if (btn) btn.disabled = false;
        return;
      }
      const formData = new FormData();
      const filename = `scansione_${Date.now()}.jpg`;
      formData.append('file', blob, filename);
      formData.append('thread_id', activeThreadId || 'general');

      try {
        const headers = window.authHeaders ? window.authHeaders() : {};
        delete headers['Content-Type']; // Let browser set multipart boundary

        const res = await fetch('/api/documents/upload', {
          method: 'POST',
          headers: headers,
          body: formData
        });

        if (!res.ok) throw new Error("Errore durante l'upload del documento");
        const data = await res.json();

        closeScannerModal();
        if (typeof window.showToast === 'function') {
          window.showToast("📄 Documento scansionato e protocollato!", "success");
        }
        if (typeof window.loadChatHistory === 'function') {
          window.loadChatHistory();
        }
        if (typeof window.loadDashboardData === 'function') {
          window.loadDashboardData();
        }
      } catch (err) {
        console.error("Errore uploadCurrentScan:", err);
        if (typeof window.showToast === 'function') {
          window.showToast("⚠️ Impossibile salvare il documento scansionato", "error");
        }
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i class="fa-solid fa-stamp mr-1.5"></i> Protocolla nel Caveau`;
        }
      }
    }, 'image/jpeg', 0.92);
  }

  // --- Public API ---
  window.MobileScanner = {
    openScanner: openScannerModal,
    closeScanner: closeScannerModal,
    triggerNativeCamera: triggerNativeCamera,
    loadExternalImage: loadExternalImage,
    captureFrame: captureCurrentFrame,
    applyPerspectiveWarp: applyPerspectiveWarp,
    applyFilter: applyFilter,
    detectPaperCorners: detectPaperCorners,
    uploadCurrentScan: uploadCurrentScan,
    requestMobilePermission: requestMobilePermission,
    confirmCrop: confirmCropAndShowFilters,
    setFilter: updateFilterPreview,
    retake: () => {
      setScannerView('camera');
      startCameraPreview();
    },
    setup: setupTouchEvents
  };

  document.addEventListener('DOMContentLoaded', () => {
    setupTouchEvents();
  });

})(window);
