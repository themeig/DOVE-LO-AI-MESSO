// =========================================================================
// MODULO 7: Modali Operativi (Viewer File Office/PDF, Backup ZIP, Folders Watcher & Pitch Deck)
// =========================================================================
    // --- White Paper Modal Handlers ---
    function openWhitePaperModal() {
      const modal = document.getElementById('whitePaperModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        const searchInput = document.getElementById('wpSearchInput');
        if (searchInput) {
          searchInput.value = '';
          filterWhitePaperContent('');
        }
      }
    }

    function closeWhitePaperModal() {
      const modal = document.getElementById('whitePaperModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function scrollWhitePaperSection(sectionId) {
      const el = document.getElementById(sectionId);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }

    function filterWhitePaperContent(query) {
      const q = (query || '').toLowerCase().trim();
      const sections = document.querySelectorAll('#whitePaperContent section');
      sections.forEach(sec => {
        if (!q || sec.textContent.toLowerCase().includes(q)) {
          sec.style.display = '';
        } else {
          sec.style.display = 'none';
        }
      });
    }

    async function downloadWhitePaperMarkdown() {
      try {
        const res = await fetch('/api/whitepaper');
        if (!res.ok) throw new Error('Errore nel recupero del White Paper');
        const text = await res.text();
        const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'WHITE_PAPER_DOVE_LO_AI_MESSO.md';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        alert('Errore download White Paper: ' + err.message);
      }
    }

    async function selectAiModel(modelId) {
      const notice = document.getElementById('aiModelSavingNotice');
      if (notice) notice.innerHTML = '<i class="fa-solid fa-circle-notch animate-spin mr-1"></i> Salvataggio...';
      try {
        const res = await fetch('/api/settings/ai-model', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_id: modelId })
        });
        if (!res.ok) throw new Error("Errore aggiornamento modello");
        const data = await res.json();
        currentAiModel = data.current_model;
        updateAiModelUI(data);
        if (notice) notice.innerHTML = '<span class="text-[#3C5A48] font-bold font-mono-code"><i class="fa-solid fa-check mr-1"></i> Modello configurato e attivo</span>';
        setTimeout(() => {
          if (notice) notice.textContent = 'Salvataggio automatico istantaneo';
        }, 2000);
      } catch (err) {
        console.error("Errore selectAiModel:", err);
        if (notice) notice.innerHTML = '<span class="text-[#C84B31] font-bold font-mono-code"><i class="fa-solid fa-triangle-exclamation mr-1"></i> Errore salvataggio</span>';
      }
    }

    function handleFreeToggle(isFree) {
      const targetModel = isFree ? 'nex-agi/nex-n2.5-pro:free' : 'google/gemini-2.5-flash-lite';
      selectAiModel(targetModel);
    }


    function updateDashboardThreadFilter() {
      const select = document.getElementById('dashboardThreadSelect');
      if (!select) return;
      const currentVal = select.value;
      select.innerHTML = '<option value="">📁 Tutti gli Spazi / Gruppi</option>';
      threadsCache.forEach(t => {
        const isGroup = t.thread_type === 'group';
        const prefix = isGroup ? '👥' : '🗂️';
        const opt = document.createElement('option');
        opt.value = t.id;
        opt.textContent = `${prefix} ${t.name}`;
        if (t.id === currentVal) opt.selected = true;
        select.appendChild(opt);
      });
    }


    // --- Modale Viewer Documenti & Immagini (PDF, Immagini, Excel, Word, CSV) ---
    function switchOfficeSheet(targetIdx) {
      const panels = document.querySelectorAll('.office-sheet-panel');
      const tabs = document.querySelectorAll('.office-sheet-tab');
      panels.forEach((p, idx) => {
        if (idx === targetIdx) {
          p.classList.remove('hidden');
        } else {
          p.classList.add('hidden');
        }
      });
      tabs.forEach((t, idx) => {
        if (idx === targetIdx) {
          t.className = 'office-sheet-tab px-3 py-1 text-xs rounded-md border transition flex items-center gap-1.5 shrink-0 bg-white text-emerald-800 font-bold shadow-2xs border-emerald-300';
        } else {
          t.className = 'office-sheet-tab px-3 py-1 text-xs rounded-md border transition flex items-center gap-1.5 shrink-0 text-slate-600 hover:text-slate-900 hover:bg-slate-100 border-transparent';
        }
      });
    }

    // ==========================================
    // MOTORE RENDERING PDF.JS (OFFLINE & MOBILE)
    // ==========================================
    let currentPdfDoc = null;
    let currentPdfPage = 1;
    let currentPdfScale = 1.0;
    let isPdfRendering = false;
    let pdfPagePending = null;

    if (typeof window !== 'undefined' && window.pdfjsLib) {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/js/pdf.worker.min.js';
    }

    function renderPdfPage(num) {
      if (!currentPdfDoc) return;
      isPdfRendering = true;
      const canvas = document.getElementById('pdfRenderCanvas');
      const spinner = document.getElementById('pdfLoadingSpinner');
      const pageNumEl = document.getElementById('pdfCurrentPage');
      const totalPagesEl = document.getElementById('pdfTotalPages');
      const zoomLevelEl = document.getElementById('pdfZoomLevel');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');

      currentPdfDoc.getPage(num).then(page => {
        let viewport = page.getViewport({ scale: currentPdfScale || 1.0 });

        // Calcolo larghezza ottimale per container mobile o desktop
        const container = document.getElementById('pdfCanvasContainer');
        if (container && (!currentPdfScale || currentPdfScale === 1.0)) {
          const containerWidth = Math.max(container.clientWidth - 32, 260);
          const unscaledViewport = page.getViewport({ scale: 1.0 });
          currentPdfScale = Math.min(Math.max(containerWidth / unscaledViewport.width, 0.5), 2.5);
          viewport = page.getViewport({ scale: currentPdfScale });
        }

        const outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = Math.floor(viewport.width) + "px";
        canvas.style.height = Math.floor(viewport.height) + "px";

        const transform = outputScale !== 1
          ? [outputScale, 0, 0, outputScale, 0, 0]
          : null;

        const renderContext = {
          canvasContext: ctx,
          transform: transform,
          viewport: viewport
        };

        const renderTask = page.render(renderContext);
        renderTask.promise.then(() => {
          isPdfRendering = false;
          if (spinner) spinner.classList.add('hidden');
          canvas.classList.remove('hidden');
          if (pageNumEl) pageNumEl.textContent = num;
          if (totalPagesEl) totalPagesEl.textContent = currentPdfDoc.numPages;
          if (zoomLevelEl) zoomLevelEl.textContent = Math.round(currentPdfScale * 100) + "%";

          if (pdfPagePending !== null) {
            const nextP = pdfPagePending;
            pdfPagePending = null;
            renderPdfPage(nextP);
          }
        }).catch(err => {
          console.warn("Errore rendering pagina PDF:", err);
          isPdfRendering = false;
        });
      }).catch(err => {
        console.warn("Errore getPage PDF:", err);
        isPdfRendering = false;
      });
    }

    function queueRenderPdfPage(num) {
      if (isPdfRendering) {
        pdfPagePending = num;
      } else {
        renderPdfPage(num);
      }
    }

    function pdfPrevPage() {
      if (currentPdfPage <= 1) return;
      currentPdfPage--;
      queueRenderPdfPage(currentPdfPage);
    }

    function pdfNextPage() {
      if (!currentPdfDoc || currentPdfPage >= currentPdfDoc.numPages) return;
      currentPdfPage++;
      queueRenderPdfPage(currentPdfPage);
    }

    function pdfZoomIn() {
      currentPdfScale = Math.min((currentPdfScale || 1.0) + 0.25, 3.0);
      queueRenderPdfPage(currentPdfPage);
    }

    function pdfZoomOut() {
      currentPdfScale = Math.max((currentPdfScale || 1.0) - 0.25, 0.4);
      queueRenderPdfPage(currentPdfPage);
    }

    function pdfFitWidth() {
      const container = document.getElementById('pdfCanvasContainer');
      if (!container || !currentPdfDoc) return;
      currentPdfDoc.getPage(currentPdfPage).then(page => {
        const unscaledViewport = page.getViewport({ scale: 1.0 });
        const containerWidth = Math.max(container.clientWidth - 32, 260);
        currentPdfScale = Math.min(Math.max(containerWidth / unscaledViewport.width, 0.5), 2.5);
        queueRenderPdfPage(currentPdfPage);
      });
    }

    window.pdfPrevPage = pdfPrevPage;
    window.pdfNextPage = pdfNextPage;
    window.pdfZoomIn = pdfZoomIn;
    window.pdfZoomOut = pdfZoomOut;
    window.pdfFitWidth = pdfFitWidth;

    function renderPdfInModal(url, docId, safeTitle, targetDl) {
      const pdfViewer = document.getElementById('modalPdfViewer');
      const canvas = document.getElementById('pdfRenderCanvas');
      const spinner = document.getElementById('pdfLoadingSpinner');
      const subtitleEl = document.getElementById('modalSubtitle');
      const pdfFrame = document.getElementById('modalPdfFrame');

      if (!pdfViewer) {
        if (pdfFrame) {
          pdfFrame.src = url;
          pdfFrame.classList.remove('hidden');
        }
        return;
      }

      pdfViewer.classList.remove('hidden');
      if (canvas) canvas.classList.add('hidden');
      if (spinner) spinner.classList.remove('hidden');

      if (typeof window.pdfjsLib === 'undefined') {
        console.warn("PDF.js non caricato, uso fallback");
        fallbackToPdfHtmlOrFrame(url, docId, safeTitle, targetDl);
        return;
      }

      window.pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/js/pdf.worker.min.js';

      let pdfFetchUrl = url;
      if (docId && (!url || url.includes('/uploads/'))) {
        pdfFetchUrl = `/api/documents/${docId}/file`;
      }

      const loadingTask = window.pdfjsLib.getDocument({
        url: pdfFetchUrl,
        withCredentials: true
      });

      loadingTask.promise.then(pdfDoc => {
        currentPdfDoc = pdfDoc;
        currentPdfPage = 1;
        currentPdfScale = 1.0;
        if (subtitleEl) {
          subtitleEl.textContent = `Documento PDF protetto (${pdfDoc.numPages} pagin${pdfDoc.numPages === 1 ? 'a' : 'e'})`;
        }
        renderPdfPage(1);
      }).catch(err => {
        console.warn("PDF.js errore caricamento:", err);
        if (docId && pdfFetchUrl !== `/api/documents/${docId}/file`) {
          const retryTask = window.pdfjsLib.getDocument({
            url: `/api/documents/${docId}/file`,
            withCredentials: true
          });
          retryTask.promise.then(pdfDoc => {
            currentPdfDoc = pdfDoc;
            currentPdfPage = 1;
            currentPdfScale = 1.0;
            if (subtitleEl) {
              subtitleEl.textContent = `Documento PDF protetto (${pdfDoc.numPages} pagin${pdfDoc.numPages === 1 ? 'a' : 'e'})`;
            }
            renderPdfPage(1);
          }).catch(retryErr => {
            console.warn("Retry PDF.js fallito:", retryErr);
            fallbackToPdfHtmlOrFrame(url, docId, safeTitle, targetDl);
          });
        } else {
          fallbackToPdfHtmlOrFrame(url, docId, safeTitle, targetDl);
        }
      });
    }

    function fallbackToPdfHtmlOrFrame(url, docId, safeTitle, targetDl) {
      const pdfViewer = document.getElementById('modalPdfViewer');
      const pdfFrame = document.getElementById('modalPdfFrame');
      const officePreview = document.getElementById('modalOfficePreview');
      const officeContent = document.getElementById('modalOfficeContent');
      const fallback = document.getElementById('modalFallback');
      const subtitleEl = document.getElementById('modalSubtitle');

      if (pdfViewer) pdfViewer.classList.add('hidden');

      if (officePreview && officeContent) {
        officePreview.classList.remove('hidden');
        officeContent.innerHTML = `
          <div class="flex flex-col items-center justify-center p-12 text-[#222220] gap-3 font-mono-code">
            <i class="fa-solid fa-circle-notch fa-spin text-2xl text-[#3C5A48]"></i>
            <span class="text-xs font-bold">Generazione anteprima strutturata in corso...</span>
          </div>
        `;
        const previewUrl = `/api/documents/preview-content?document_id=${encodeURIComponent(docId || '')}&file_url=${encodeURIComponent(url || '')}`;
        fetch(previewUrl, {
          headers: (typeof authHeaders === 'function' ? authHeaders() : {})
        })
          .then(res => {
            if (!res.ok) throw new Error("Errore risposta preview (" + res.status + ")");
            return res.json();
          })
          .then(data => {
            if (data.html_content) {
              officeContent.innerHTML = data.html_content;
              if (subtitleEl) subtitleEl.textContent = "Documento PDF (Estratto strutturato)";
            } else {
              throw new Error("Nessun contenuto estraibile");
            }
          })
          .catch(err => {
            console.warn("Fallback HTML fallito:", err);
            if (officePreview) officePreview.classList.add('hidden');
            const isMobile = window.innerWidth <= 768 || /Android|iPhone|iPad/i.test(navigator.userAgent);
            if (!isMobile && pdfFrame) {
              pdfFrame.src = url;
              pdfFrame.classList.remove('hidden');
            } else if (fallback) {
              fallback.classList.remove('hidden');
              if (subtitleEl) subtitleEl.textContent = "Anteprima non disponibile";
            }
          });
      } else if (pdfFrame) {
        pdfFrame.src = url;
        pdfFrame.classList.remove('hidden');
      } else if (fallback) {
        fallback.classList.remove('hidden');
      }
    }

    function openMediaModal(url, title, fileType = '', downloadUrl = '', docId = null) {
      window.currentModalDocId = docId;
      window.currentModalDocUrl = url;
      const modal = document.getElementById('mediaModal');
      const titleEl = document.getElementById('modalTitle');
      const subtitleEl = document.getElementById('modalSubtitle');
      const downloadBtn = document.getElementById('modalDownloadBtn');
      const pdfViewer = document.getElementById('modalPdfViewer');
      const pdfFrame = document.getElementById('modalPdfFrame');
      const imgPreview = document.getElementById('modalImagePreview');
      const officePreview = document.getElementById('modalOfficePreview');
      const officeContent = document.getElementById('modalOfficeContent');
      const fallback = document.getElementById('modalFallback');

      if (!modal) return;

      const safeTitle = title || 'Documento';
      titleEl.textContent = safeTitle;
      const targetDl = downloadUrl || url || '#';
      const safeDownloadName = safeTitle.toLowerCase().replace(/[^a-z0-9]/g, '_');
      // Usa fetch+Blob per compatibilità con pywebview (l'attributo download non funziona nel webview nativo)
      downloadBtn.removeAttribute('href');
      downloadBtn.removeAttribute('download');
      downloadBtn.onclick = (targetDl && targetDl !== '#')
        ? () => downloadFileFromUrl(targetDl, safeDownloadName, docId || null)
        : null;

      if (pdfViewer) pdfViewer.classList.add('hidden');
      currentPdfDoc = null;
      isPdfRendering = false;
      pdfPagePending = null;

      pdfFrame.classList.add('hidden');
      pdfFrame.src = '';
      imgPreview.classList.add('hidden');
      imgPreview.src = '';
      imgPreview.onerror = null;
      if (officePreview) officePreview.classList.add('hidden');
      if (officeContent) officeContent.innerHTML = '';
      fallback.classList.add('hidden');

      const lowerType = (fileType || '').toLowerCase();
      const lowerUrl = (url || '').toLowerCase();
      const cleanUrl = lowerUrl.split('?')[0];
      const lowerTitle = (safeTitle || '').toLowerCase();

      const isZip = lowerType.includes('zip') || cleanUrl.endsWith('.zip') || lowerTitle.endsWith('.zip');
      const isPdf = !isZip && (lowerType.includes('pdf') || cleanUrl.endsWith('.pdf') || lowerTitle.endsWith('.pdf'));
      const isOffice = !isZip && !isPdf && (
        lowerType.includes('officedocument') ||
        lowerType.includes('excel') ||
        lowerType.includes('word') ||
        lowerType.includes('sheet') ||
        lowerType.includes('spreadsheet') ||
        lowerType.includes('csv') ||
        /\.(xlsx?|xlsm|docx?|csv|tsv|txt|json|md)$/i.test(cleanUrl) ||
        /\.(xlsx?|xlsm|docx?|csv|tsv)$/i.test(lowerTitle)
      );
      const isImg = !isZip && !isPdf && !isOffice && (
        lowerType.includes('image') ||
        lowerType.includes('png') ||
        lowerType.includes('jpg') ||
        lowerType.includes('jpeg') ||
        lowerType.includes('webp') ||
        /\.(png|jpe?g|webp|gif|svg)$/i.test(cleanUrl)
      );

      if (isPdf) {
        subtitleEl.textContent = "Documento PDF protetto";
        renderPdfInModal(url, docId, safeTitle, targetDl);
      } else if (isZip || isOffice) {
        const isExcel = /\.(xlsx?|xlsm|csv|tsv)$/i.test(cleanUrl) || /\.(xlsx?|xlsm|csv|tsv)$/i.test(lowerTitle) || lowerType.includes('excel') || lowerType.includes('sheet') || lowerType.includes('spreadsheet');
        if (isZip) {
          subtitleEl.textContent = "Archivio compresso ZIP";
        } else if (isExcel) {
          subtitleEl.textContent = "Foglio di calcolo Excel interattivo";
        } else {
          subtitleEl.textContent = "Documento di testo Word formattato";
        }
        if (officePreview && officeContent) {
          officePreview.classList.remove('hidden');
          fallback.classList.add('hidden');
          officeContent.innerHTML = `
            <div class="flex flex-col items-center justify-center p-12 text-[#222220] gap-3 font-mono-code">
              <i class="fa-solid fa-circle-notch fa-spin text-2xl text-[#3C5A48]"></i>
              <span class="text-xs font-semibold">${isZip ? 'Lettura archivio compresso...' : 'Caricamento e decifratura anteprima in corso...'}</span>
            </div>
          `;
          const previewQuery = `/api/documents/preview-content?document_id=${encodeURIComponent(docId || '')}&file_url=${encodeURIComponent(url || '')}`;
          fetch(previewQuery, {
            headers: (typeof authHeaders === 'function' ? authHeaders() : {})
          })
            .then(res => {
              if (!res.ok) throw new Error("Errore risposta server (" + res.status + ")");
              return res.json();
            })
            .then(data => {
              fallback.classList.add('hidden');
              if (data.html_content) {
                officeContent.innerHTML = data.html_content;
                if (isZip && data.file_count != null) {
                  subtitleEl.textContent = `Archivio compresso ZIP (${data.file_count} file)`;
                }
              } else {
                officeContent.innerHTML = `
                  <div class="p-8 text-center text-slate-500 font-mono-code">
                    <p class="font-semibold text-slate-700 text-sm mb-2">Nessun contenuto visualizzabile direttamente</p>
                    <p class="text-xs text-slate-400">Puoi scaricare il file originale usando il pulsante Scarica in alto.</p>
                  </div>
                `;
              }
            })
            .catch(err => {
              console.warn("Errore caricamento anteprima:", err);
              fallback.classList.add('hidden');
              officeContent.innerHTML = `
                <div class="p-8 text-center text-slate-500 font-mono-code">
                  <i class="fa-solid fa-triangle-exclamation text-amber-500 text-2xl mb-2"></i>
                  <p class="font-semibold text-slate-700 text-sm">Impossibile generare l'anteprima del documento</p>
                  <p class="text-xs text-slate-400 mt-1 mb-4">${escapeHtml(err.message || 'Errore lettura file')}</p>
                  <a href="${targetDl}" download class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#3C5A48] text-white text-xs font-semibold rounded-xs shadow-xs hover:bg-[#2F4738]">
                    <i class="fa-solid fa-download"></i> Scarica file originale
                  </a>
                </div>
              `;
            });
        }
      } else if (isImg) {
        subtitleEl.textContent = "Immagine / Scansione";
        let hasRetried = false;
        imgPreview.onerror = function() {
          if (!hasRetried && docId && !url.includes(`/api/documents/${docId}/file`)) {
            hasRetried = true;
            console.log("Retry loading image via /api/documents/" + docId + "/file");
            imgPreview.src = `/api/documents/${docId}/file`;
            return;
          }
          sendUITelemetry('MEDIA_PREVIEW_ERROR', {
            title: safeTitle,
            error_details: `Impossibile caricare anteprima immagine per '${safeTitle}' da ${url}`
          });
          imgPreview.classList.add('hidden');
          fallback.classList.remove('hidden');
          subtitleEl.textContent = "Errore anteprima - Usa il pulsante Scarica in alto";
        };
        imgPreview.src = url;
        imgPreview.classList.remove('hidden');
      } else if (url) {
        subtitleEl.textContent = "Visualizzazione file";
        const isMobile = window.innerWidth <= 768 || /Android|iPhone|iPad/i.test(navigator.userAgent);
        if (isMobile) {
          // Su mobile non tentare iframe per file non-immagine: usa preview-content
          fallbackToPdfHtmlOrFrame(url, docId, safeTitle, targetDl);
        } else {
          pdfFrame.src = url;
          pdfFrame.classList.remove('hidden');
        }
      } else {
        fallback.classList.remove('hidden');
      }

      modal.classList.remove('hidden');
      modal.classList.add('flex');
    }

    function closeMediaModal() {
      window.currentModalDocId = null;
      window.currentModalDocUrl = null;
      const modal = document.getElementById('mediaModal');
      const pdfViewer = document.getElementById('modalPdfViewer');
      const pdfFrame = document.getElementById('modalPdfFrame');
      const imgPreview = document.getElementById('modalImagePreview');
      const officePreview = document.getElementById('modalOfficePreview');
      const officeContent = document.getElementById('modalOfficeContent');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
      if (pdfViewer) pdfViewer.classList.add('hidden');
      currentPdfDoc = null;
      isPdfRendering = false;
      pdfPagePending = null;
      if (pdfFrame) pdfFrame.src = '';
      if (imgPreview) imgPreview.src = '';
      if (officePreview) officePreview.classList.add('hidden');
      if (officeContent) officeContent.innerHTML = '';
    }

    window.openMediaModal = openMediaModal;
    window.closeMediaModal = closeMediaModal;

    function handleModalBackdropClick(e) {
      if (e.target && e.target.id === 'mediaModal') {
        closeMediaModal();
      }
    }

    async function unzipDocumentById(docId, fileUrl = null) {
      try {
        if (typeof showToast === 'function') {
          showToast('📦 Decompressione ed estrazione dei file in corso...', 'info', 3000);
        }
        const endpoint = docId ? `/api/documents/${docId}/unzip` : '/api/documents/unzip';
        const bodyPayload = {};
        if (docId) bodyPayload.document_id = docId;
        if (fileUrl) bodyPayload.file_url = fileUrl;
        if (typeof currentThreadId !== 'undefined' && currentThreadId) {
          bodyPayload.thread_id = currentThreadId;
        }

        const res = await fetch(endpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(typeof authHeaders === 'function' ? authHeaders() : {})
          },
          body: JSON.stringify(bodyPayload)
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Impossibile decomprimere l'archivio ZIP");
        }

        const data = await res.json();
        if (typeof showToast === 'function') {
          showToast(`⚡ Estratti con successo ${data.count || ''} documenti nel caveau!`, 'success', 5000);
        }

        closeMediaModal();

        if (typeof loadDashboard === 'function') {
          await loadDashboard(typeof currentFilter !== 'undefined' ? currentFilter : 'all');
        }
        if (typeof loadMessages === 'function' && typeof currentThreadId !== 'undefined') {
          await loadMessages(currentThreadId);
        }
        if (typeof checkDeadlineAlerts === 'function') {
          await checkDeadlineAlerts(typeof currentThreadId !== 'undefined' ? currentThreadId : null);
        }
      } catch (err) {
        console.error("Errore unzipDocument:", err);
        if (typeof showToast === 'function') {
          showToast(`⚠️ ${err.message}`, 'error', 5000);
        } else {
          alert("Errore: " + err.message);
        }
      }
    }
    window.unzipDocumentById = unzipDocumentById;

    function unzipCurrentModalArchive() {
      const docId = window.currentModalDocId;
      const docUrl = window.currentModalDocUrl;
      unzipDocumentById(docId, docUrl);
    }
    window.unzipCurrentModalArchive = unzipCurrentModalArchive;

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeMediaModal();
        closeExportVaultModal();
      }
    });

    // --- Export / Backup Caveau ---
    function openExportVaultModal() {
      const modal = document.getElementById('exportVaultModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
      }
      const canPick = typeof window.showSaveFilePicker === 'function';
      const infoEl = document.getElementById('exportDestInfoText');
      const infoIcon = document.getElementById('exportDestInfoIcon');
      const btnSpan = document.getElementById('confirmExportVaultBtnText');
      const btnIcon = document.getElementById('confirmExportVaultBtnIcon');
      if (infoEl) {
        infoEl.innerHTML = canPick 
          ? 'Potrai scegliere la cartella o l\'unità del PC (es. Desktop, Documenti o Chiavetta USB) in cui salvare il file.'
          : 'Il tuo browser salverà il file nella cartella predefinita <strong>Download</strong> del PC.';
      }
      if (infoIcon) {
        infoIcon.className = canPick ? 'fa-solid fa-folder-tree text-emerald-600' : 'fa-solid fa-circle-info text-blue-500';
      }
      if (btnSpan) {
        btnSpan.textContent = canPick ? 'Scegli dove salvare ed Esporta' : 'Scarica Archivio ZIP (Download)';
      }
      if (btnIcon) {
        btnIcon.className = canPick ? 'fa-solid fa-folder-open' : 'fa-solid fa-download';
      }
    }

    function closeExportVaultModal() {
      const modal = document.getElementById('exportVaultModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    // Alias per compatibilità
    function exportVault() {
      openExportVaultModal();
    }

    async function startVaultExport() {
      const btn = document.getElementById('confirmExportVaultBtn');
      const originalContent = btn ? btn.innerHTML : '';
      const d = new Date();
      const pad = n => String(n).padStart(2, '0');
      const dateStr = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
      const suggestedFilename = `caveau_backup_${dateStr}.zip`;

      let fileHandle = null;

      // 1. Invoca SUBITO showSaveFilePicker con il gesto utente (click) attivo al 100%!
      //    In Chromium, se viene chiamato dopo una fetch() asincrona, l'attivazione utente scade e viene bloccato.
      if (typeof window.showSaveFilePicker === 'function') {
        try {
          fileHandle = await window.showSaveFilePicker({
            suggestedName: suggestedFilename,
            types: [{
              description: 'Archivio ZIP (*.zip)',
              accept: { 'application/zip': ['.zip'] }
            }]
          });
        } catch (pickerErr) {
          if (pickerErr.name === 'AbortError') {
            // L'utente ha annullato la finestra nativa di salvataggio
            return;
          }
          console.warn('showSaveFilePicker non consentito o fallito, procedo con download standard:', pickerErr);
        }
      }

      // 2. Mostra lo stato di avanzamento e avvia il download dal backend
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Preparazione ZIP...</span>';
      }
      if (typeof showToast === 'function') {
        showToast('📦 Generazione archivio ZIP in corso...', 'info', 3500);
      }

      try {
        const res = await fetch('/api/export/vault', {
          headers: typeof authHeaders === 'function' ? authHeaders() : {}
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Errore sconosciuto' }));
          const errMsg = 'Errore durante l\'esportazione: ' + (err.detail || res.statusText);
          if (typeof showToast === 'function') {
            showToast(errMsg, 'error', 4500);
          } else {
            alert(errMsg);
          }
          return;
        }

        const blob = await res.blob();

        if (fileHandle) {
          // Scrittura diretta nel file scelto dall'utente tramite File System Access API
          const writableStream = await fileHandle.createWritable();
          await writableStream.write(blob);
          await writableStream.close();
          if (typeof showToast === 'function') {
            showToast(`✅ Backup salvato con successo in: ${fileHandle.name}`, 'success', 5000);
          }
          closeExportVaultModal();
        } else {
          // Fallback per browser che non supportano showSaveFilePicker (es. Firefox)
          const cd = res.headers.get('Content-Disposition') || '';
          const fnMatch = cd.match(/filename[^;=\n]*=["']?([^"'\n]+)/i);
          const actualFilename = fnMatch ? fnMatch[1] : suggestedFilename;
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.download = actualFilename;
          a.href = url;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          if (typeof showToast === 'function') {
            showToast(`✅ Backup scaricato con successo: ${actualFilename}`, 'success', 5000);
          }
          closeExportVaultModal();
        }
      } catch (err) {
        const errMsg = 'Errore durante l\'esportazione: ' + err.message;
        if (typeof showToast === 'function') {
          showToast(errMsg, 'error', 4500);
        } else {
          alert(errMsg);
        }
      } finally {
        if (btn && originalContent) {
          btn.disabled = false;
          btn.innerHTML = originalContent;
        }
      }
    }

    // --- Import / Ripristino Backup Caveau ---
    let selectedImportZipFile = null;

    function openImportVaultModal() {
      const modal = document.getElementById('importVaultModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
      }
      resetImportZipSelection();
      setupImportZipDropZone();
    }

    function closeImportVaultModal() {
      const modal = document.getElementById('importVaultModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
      resetImportZipSelection();
    }

    function resetImportZipSelection(e) {
      if (e) e.stopPropagation();
      selectedImportZipFile = null;
      const input = document.getElementById('importZipFileInput');
      if (input) input.value = '';
      const infoEl = document.getElementById('importZipFileInfo');
      if (infoEl) infoEl.classList.add('hidden');
      const btn = document.getElementById('confirmImportVaultBtn');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-file-import" id="confirmImportVaultBtnIcon"></i> <span id="confirmImportVaultBtnText">Avvia Ripristino</span>';
      }
    }

    function handleImportZipSelected(event) {
      const file = event.target.files?.[0];
      if (!file) return;
      if (!file.name.toLowerCase().endsWith('.zip')) {
        if (typeof showToast === 'function') {
          showToast('Seleziona un archivio compresso in formato .zip', 'warning');
        }
        return;
      }
      selectedImportZipFile = file;
      const infoEl = document.getElementById('importZipFileInfo');
      const nameEl = document.getElementById('importZipFileName');
      const sizeEl = document.getElementById('importZipFileSize');
      const btn = document.getElementById('confirmImportVaultBtn');

      if (infoEl) infoEl.classList.remove('hidden');
      if (nameEl) nameEl.textContent = file.name;
      if (sizeEl) sizeEl.textContent = typeof formatBytes === 'function' ? formatBytes(file.size) : `${Math.round(file.size / 1024)} KB`;
      if (btn) {
        btn.disabled = false;
      }
    }

    let isImportZipDropZoneSetup = false;
    function setupImportZipDropZone() {
      if (isImportZipDropZoneSetup) return;
      const dz = document.getElementById('importZipDropZone');
      if (!dz) return;
      isImportZipDropZoneSetup = true;

      dz.addEventListener('dragover', (e) => {
        e.preventDefault();
        dz.classList.add('border-purple-500', 'bg-purple-100/50');
      });
      dz.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dz.classList.remove('border-purple-500', 'bg-purple-100/50');
      });
      dz.addEventListener('drop', (e) => {
        e.preventDefault();
        dz.classList.remove('border-purple-500', 'bg-purple-100/50');
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          handleImportZipSelected({ target: { files: e.dataTransfer.files } });
        }
      });
    }

    async function submitVaultImport() {
      if (!selectedImportZipFile) {
        if (typeof showToast === 'function') {
          showToast('Seleziona un file ZIP da ripristinare', 'warning');
        }
        return;
      }

      const btn = document.getElementById('confirmImportVaultBtn');
      const originalContent = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Ripristino in corso...</span>';
      }
      if (typeof showToast === 'function') {
        showToast('📦 Elaborazione e ripristino dell\'archivio ZIP in corso...', 'info', 4000);
      }

      const formData = new FormData();
      formData.append('file', selectedImportZipFile);

      try {
        const res = await fetch('/api/export/import', {
          method: 'POST',
          headers: typeof authHeaders === 'function' ? authHeaders() : {},
          body: formData
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Errore durante l\'importazione' }));
          throw new Error(err.detail || res.statusText);
        }

        const data = await res.json();
        const docs = data.restored?.documents || 0;
        const items = data.restored?.physical_items || 0;
        if (typeof showToast === 'function') {
          showToast(`✅ Ripristino completato! ${docs} documenti e ${items} oggetti registrati nel caveau.`, 'success', 6000);
        }

        closeImportVaultModal();
        if (typeof loadDashboard === 'function') loadDashboard(currentFilter);
        if (typeof loadThreads === 'function') loadThreads();
      } catch (err) {
        console.error('Errore import backup:', err);
        if (typeof showToast === 'function') {
          showToast(`⚠️ ${err.message}`, 'error', 5000);
        } else {
          alert(`Errore: ${err.message}`);
        }
      } finally {
        if (btn && originalContent) {
          btn.disabled = false;
          btn.innerHTML = originalContent;
        }
      }
    }

    // --- Eliminazione Totale Database (Reset Caveau) ---
    function openWipeDatabaseModal() {
      const modal = document.getElementById('wipeDatabaseModal');
      const pwdInput = document.getElementById('wipePasswordInput');
      const errBox = document.getElementById('wipeDatabaseError');
      const driveCheck = document.getElementById('wipeDeleteDriveCheckbox');
      if (pwdInput) pwdInput.value = '';
      if (errBox) errBox.classList.add('hidden');
      if (driveCheck) driveCheck.checked = false;
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        setTimeout(() => { if (pwdInput) pwdInput.focus(); }, 100);
      }
    }

    function closeWipeDatabaseModal() {
      const modal = document.getElementById('wipeDatabaseModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function toggleWipePasswordVisibility() {
      const input = document.getElementById('wipePasswordInput');
      const icon = document.getElementById('wipeEyeIcon');
      if (input && icon) {
        if (input.type === 'password') {
          input.type = 'text';
          icon.classList.remove('fa-eye');
          icon.classList.add('fa-eye-slash');
        } else {
          input.type = 'password';
          icon.classList.remove('fa-eye-slash');
          icon.classList.add('fa-eye');
        }
      }
    }

    async function confirmWipeDatabase() {
      const pwdInput = document.getElementById('wipePasswordInput');
      const driveCheck = document.getElementById('wipeDeleteDriveCheckbox');
      const errBox = document.getElementById('wipeDatabaseError');
      const errText = document.getElementById('wipeDatabaseErrorText');
      const btn = document.getElementById('confirmWipeBtn');

      const password = pwdInput ? pwdInput.value : '';
      const deleteDrive = driveCheck ? driveCheck.checked : false;

      if (!password) {
        if (errBox && errText) {
          errText.textContent = "Inserisci la password master del caveau.";
          errBox.classList.remove('hidden');
        }
        return;
      }

      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin text-xs"></i> Eliminazione in corso...`;
      }

      try {
        const res = await fetch('/api/settings/wipe-database', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(typeof authHeaders === 'function' ? authHeaders() : {})
          },
          body: JSON.stringify({
            password: password,
            delete_drive: deleteDrive
          })
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Impossibile eliminare il database. Password non corretta.");
        }

        const data = await res.json();
        closeWipeDatabaseModal();

        if (typeof showToast === 'function') {
          showToast("🗑️ Database azzerato con successo!", "success", 5000);
        }

        // Ricarica Dashboard e canali
        if (typeof loadDashboard === 'function') {
          await loadDashboard(typeof currentFilter !== 'undefined' ? currentFilter : 'all');
        }
        if (typeof checkDeadlineAlerts === 'function') {
          await checkDeadlineAlerts(null);
        }
        if (typeof loadThreads === 'function') {
          await loadThreads();
        }
        if (typeof switchThread === 'function') {
          switchThread('general');
        } else if (typeof loadMessages === 'function') {
          await loadMessages('general');
        }
      } catch (err) {
        console.error("Errore wipe database:", err);
        if (errBox && errText) {
          errText.textContent = err.message || "Password errata.";
          errBox.classList.remove('hidden');
        }
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i class="fa-solid fa-trash-can text-xs"></i> Elimina Tutto Definitivamente`;
        }
      }
    }

    window.openWipeDatabaseModal = openWipeDatabaseModal;
    window.closeWipeDatabaseModal = closeWipeDatabaseModal;
    window.toggleWipePasswordVisibility = toggleWipePasswordVisibility;
    window.confirmWipeDatabase = confirmWipeDatabase;

    // --- Gestione Cartelle PC Monitorate & Explorer ---
    let watchedFoldersCache = [];

    function openWatchedFoldersModal() {
      const modal = document.getElementById('watchedFoldersModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        loadFolderPresets();
        loadPendingProposals();
        loadWatchedFolders();
      }
    }

    function closeWatchedFoldersModal() {
      const modal = document.getElementById('watchedFoldersModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    async function loadWatchedFolders() {
      const listEl = document.getElementById('watchedFoldersList');
      const countEl = document.getElementById('watchedFoldersCountText');
      if (listEl) {
        listEl.innerHTML = `
          <div class="p-6 text-center text-slate-400 text-xs">
            <i class="fa-solid fa-circle-notch animate-spin text-xl mb-2 text-emerald-600"></i>
            <p>Caricamento cartelle in corso...</p>
          </div>
        `;
      }
      try {
        const res = await fetch('/api/folders', { headers: authHeaders() });
        if (!res.ok) throw new Error("Errore recupero cartelle");
        const folders = await res.json();
        watchedFoldersCache = folders;
        renderWatchedFoldersList(folders);
        if (countEl) {
          countEl.textContent = `${folders.length} cartelle collegate sul PC`;
        }
      } catch (err) {
        console.error("Errore loadWatchedFolders:", err);
        if (listEl) {
          listEl.innerHTML = `
            <div class="p-6 text-center text-rose-500 text-xs bg-rose-50 rounded-2xl border border-rose-200">
              Impossibile caricare le cartelle: ${escapeHtml(err.message)}
            </div>
          `;
        }
      }
    }

    function renderWatchedFoldersList(folders) {
      const listEl = document.getElementById('watchedFoldersList');
      if (!listEl) return;

      if (!folders || folders.length === 0) {
        listEl.innerHTML = `
          <div class="p-8 text-center text-slate-400 text-xs bg-slate-50 rounded-2xl border border-dashed border-slate-300">
            <i class="fa-solid fa-folder-open text-3xl mb-2 text-slate-300"></i>
            <p class="font-bold text-slate-700 text-sm">Nessuna cartella locale collegata</p>
            <p class="text-slate-400 mt-1">Clicca su "Sfoglia Cartella PC..." in alto per selezionare una cartella (es. Documenti o Fatture) e indicizzare subito i tuoi file.</p>
          </div>
        `;
        return;
      }

      listEl.innerHTML = folders.map(f => {
        const lastScan = f.last_scanned_at ? new Date(f.last_scanned_at).toLocaleString('it-IT') : 'Mai';
        const escapedPath = escapeHtml(f.path).replace(/'/g, "\\'");
        const escapedName = escapeHtml(f.name).replace(/'/g, "\\'");

        return `
          <div class="bg-slate-50 hover:bg-slate-100/90 border border-slate-200/90 rounded-2xl p-3.5 transition flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-2xs">
            <div class="flex items-start gap-3 min-w-0">
              <div class="w-10 h-10 rounded-xl bg-emerald-100 text-[#075E54] flex items-center justify-center shrink-0 text-base shadow-2xs">
                <i class="fa-solid fa-folder"></i>
              </div>
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <h4 class="font-bold text-slate-900 text-xs truncate" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</h4>
                  <span class="bg-emerald-50 text-emerald-800 text-[10px] font-bold px-2 py-0.5 rounded-full border border-emerald-200">${f.file_count} file</span>
                </div>
                <p class="text-[11px] font-mono text-slate-500 truncate mt-0.5" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</p>
                <p class="text-[10px] text-slate-400 mt-0.5">Ultima scansione: ${lastScan}</p>
              </div>
            </div>

            <div class="flex items-center gap-1.5 shrink-0 self-end sm:self-center">
              <button 
                onclick="scanWatchedFolder(${f.id})" 
                id="btnScanFolder_${f.id}"
                class="bg-white hover:bg-slate-200 text-slate-700 text-xs font-semibold px-2.5 py-1.5 rounded-xl border border-slate-200 transition active:scale-95 flex items-center gap-1 shadow-2xs cursor-pointer"
                title="Esegui nuova scansione e indicizza nuovi documenti"
              >
                <i class="fa-solid fa-arrows-rotate text-emerald-600 text-[11px]"></i>
                <span>Scansiona</span>
              </button>

              <button 
                onclick="openExplorerPath('${escapedPath}')" 
                class="bg-white hover:bg-slate-200 text-slate-700 text-xs font-semibold px-2.5 py-1.5 rounded-xl border border-slate-200 transition active:scale-95 flex items-center gap-1 shadow-2xs cursor-pointer"
                title="Apri in Esplora File di Windows"
              >
                <i class="fa-regular fa-folder-open text-amber-600 text-[11px]"></i>
                <span class="hidden sm:inline">Esplora</span>
              </button>

              <button 
                onclick="deleteWatchedFolder(${f.id}, '${escapedName}')" 
                class="text-slate-400 hover:text-red-600 hover:bg-red-50 p-2 rounded-xl transition active:scale-95 text-xs cursor-pointer"
                title="Rimuovi dal monitoraggio (non cancella i file dal disco)"
              >
                <i class="fa-regular fa-trash-can"></i>
              </button>
            </div>
          </div>
        `;
      }).join('');
    }

    async function selectFolderFromPC() {
      const btn = document.getElementById('btnSelectFolderPC');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-circle-notch animate-spin mr-1"></i> Selezione in corso...`;
      }
      try {
        const res = await fetch('/api/folders/select', {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore apertura finestra di dialogo");
        const data = await res.json();
        if (data.cancelled || !data.selected_path) {
          return;
        }

        const path = data.selected_path;
        const folderName = path.split(/[\\/]/).pop() || 'Cartella PC';
        const addRes = await fetch('/api/folders', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...authHeaders()
          },
          body: JSON.stringify({
            path: path,
            name: folderName,
            thread_id: currentThreadId || 'general',
            auto_scan: true
          })
        });
        if (!addRes.ok) {
          const errData = await addRes.json().catch(() => ({}));
          throw new Error(errData.detail || "Impossibile registrare la cartella");
        }
        await loadWatchedFolders();
        await loadDashboard(currentFilter);
      } catch (err) {
        console.error("Errore selectFolderFromPC:", err);
        alert("Errore durante la selezione cartella: " + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i class="fa-solid fa-folder-plus text-xs"></i><span>Sfoglia Cartella PC...</span>`;
        }
      }
    }

    async function scanWatchedFolder(folderId) {
      const btn = document.getElementById(`btnScanFolder_${folderId}`);
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-circle-notch animate-spin text-emerald-600 text-[11px]"></i> Scansione...`;
      }
      try {
        const res = await fetch(`/api/folders/${folderId}/scan`, {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore scansione cartella");
        const data = await res.json();
        await loadWatchedFolders();
        await loadDashboard(currentFilter);
        alert(`Scansione completata!\n• Nuovi file indicizzati: ${data.new_indexed_count}\n• Già presenti: ${data.skipped_count}\n• Totale esaminati: ${data.scanned_files_count}`);
      } catch (err) {
        console.error("Errore scanWatchedFolder:", err);
        alert("Errore scansione: " + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i class="fa-solid fa-arrows-rotate text-emerald-600 text-[11px]"></i><span>Scansiona</span>`;
        }
      }
    }

    async function deleteWatchedFolder(folderId, name) {
      const confirmed = await showConfirmModal({
        title: "Rimuovi Cartella dal Monitoraggio",
        message: `Vuoi rimuovere la cartella "${name}" dal monitoraggio?\n(I tuoi file rimarranno intatti sul tuo computer).`,
        confirmText: "Rimuovi Monitoraggio",
        danger: false
      });
      if (!confirmed) return;
      try {
        const res = await fetch(`/api/folders/${folderId}`, {
          method: 'DELETE',
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore rimozione cartella");
        await loadWatchedFolders();
      } catch (err) {
        console.error("Errore deleteWatchedFolder:", err);
        alert("Errore: " + err.message);
      }
    }

    async function openFileInExplorer(docId) {
      try {
        const res = await fetch('/api/folders/open-in-explorer', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...authHeaders()
          },
          body: JSON.stringify({ document_id: docId })
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Impossibile aprire Esplora File per questo documento");
        }
        showToast("File aperto sul computer ed evidenziato in Esplora Risorse", "success", 4000);
      } catch (err) {
        console.error("Errore openFileInExplorer:", err);
        showToast("Errore apertura su PC: " + err.message, "error", 4000);
      }
    }

    async function openExplorerPath(path) {
      try {
        const res = await fetch('/api/folders/open-in-explorer', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...authHeaders()
          },
          body: JSON.stringify({ path: path })
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Impossibile aprire Esplora File");
        }
      } catch (err) {
        console.error("Errore openExplorerPath:", err);
        alert(err.message);
      }
    }

    // --- Monitoraggio 1-Click Presets (Download, Documenti, Desktop) ---
    async function loadFolderPresets() {
      const presetsEl = document.getElementById('folderPresetsList');
      if (!presetsEl) return;
      try {
        const res = await fetch('/api/folders/presets', { headers: authHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const presets = data.presets || [];
        presetsEl.innerHTML = presets.map(p => {
          const isWatched = p.is_watched;
          const escapedPath = escapeHtml(p.path).replace(/'/g, "\\'");
          const escapedName = escapeHtml(p.name).replace(/'/g, "\\'");
          return `
            <div class="bg-white/95 border border-emerald-200/90 rounded-xl p-2.5 flex items-center justify-between gap-2 shadow-2xs">
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-base shrink-0">${p.icon}</span>
                <div class="min-w-0">
                  <div class="font-bold text-slate-800 text-xs truncate">${escapeHtml(p.name)}</div>
                  <div class="text-[10px] text-slate-400 truncate" title="${escapeHtml(p.path)}">${escapeHtml(p.path)}</div>
                </div>
              </div>
              <button 
                onclick="togglePresetFolder('${escapedPath}', '${escapedName}', ${isWatched})"
                class="${isWatched ? 'bg-emerald-100 text-emerald-800 border border-emerald-300' : 'bg-[#075E54] hover:bg-[#128C7E] text-white'} text-[10px] font-bold px-2 py-1 rounded-lg transition shrink-0 cursor-pointer active:scale-95"
              >
                ${isWatched ? '✅ Attiva' : '+ Collega'}
              </button>
            </div>
          `;
        }).join('');
      } catch (err) {
        console.error("Errore loadFolderPresets:", err);
      }
    }

    async function togglePresetFolder(path, name, isWatched) {
      if (isWatched) {
        const norm = path.toLowerCase();
        const found = watchedFoldersCache.find(f => (f.path || '').toLowerCase() === norm);
        if (found) {
          await deleteWatchedFolder(found.id, found.name);
          await loadFolderPresets();
        }
      } else {
        try {
          const res = await fetch('/api/folders', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...authHeaders()
            },
            body: JSON.stringify({
              path: path,
              name: name,
              thread_id: currentThreadId || 'general',
              auto_scan: true
            })
          });
          if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Impossibile collegare la cartella");
          }
          await loadWatchedFolders();
          await loadFolderPresets();
          await loadPendingProposals();
          await checkPendingProposalsBanner();
          await loadDashboard(currentFilter);
        } catch (err) {
          alert("Errore: " + err.message);
        }
      }
    }

    // --- File Sensibili Rilevati: Proposte & Caveau ---
    async function loadPendingProposals() {
      const section = document.getElementById('pendingProposalsSection');
      const list = document.getElementById('pendingProposalsList');
      if (!section || !list) return;

      try {
        const res = await fetch('/api/folders/proposals?status=pending', { headers: authHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const proposals = data.proposals || [];

        if (proposals.length === 0) {
          section.classList.add('hidden');
          return;
        }

        section.classList.remove('hidden');
        list.innerHTML = proposals.map(prop => {
          const fileName = escapeHtml(prop.file_name);
          const folderName = escapeHtml(prop.folder_name || 'Cartella');
          const reason = escapeHtml(prop.sensitivity_reason || 'Dati sensibili');
          const amountBadge = prop.amount ? `<span class="bg-amber-100 text-amber-900 font-bold px-1.5 py-0.5 rounded text-[10px]">€ ${Number(prop.amount).toFixed(2)}</span>` : '';
          const dueBadge = prop.due_date ? `<span class="bg-rose-100 text-rose-800 font-bold px-1.5 py-0.5 rounded text-[10px]">Scad: ${prop.due_date}</span>` : '';

          return `
            <div id="modal-prop-${prop.id}" class="bg-gradient-to-r from-amber-50/80 to-emerald-50/80 border border-amber-200/90 rounded-2xl p-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2 shadow-2xs">
              <div class="flex items-start gap-2.5 min-w-0">
                <div class="w-8 h-8 rounded-xl bg-white border border-amber-200 text-red-600 flex items-center justify-center shrink-0 shadow-2xs text-xs">
                  <i class="fa-solid fa-file-shield"></i>
                </div>
                <div class="min-w-0">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    <span class="font-bold text-slate-900 text-xs truncate" title="${fileName}">${fileName}</span>
                    <span class="bg-white/90 text-slate-500 text-[10px] px-1.5 py-0.2 rounded-md border border-amber-200">${folderName}</span>
                    ${amountBadge}
                    ${dueBadge}
                  </div>
                  <p class="text-[11px] text-slate-600 truncate mt-0.5">${reason}</p>
                </div>
              </div>
              <div class="flex items-center gap-1.5 shrink-0 self-end sm:self-center">
                <button 
                  onclick="approveProposalFromModal(${prop.id}, this)"
                  class="bg-[#075E54] hover:bg-[#128C7E] text-white text-xs font-bold px-2.5 py-1.5 rounded-xl shadow-2xs transition active:scale-95 flex items-center gap-1 cursor-pointer"
                >
                  <i class="fa-solid fa-lock text-[10px]"></i>
                  <span>Salva nel Caveau</span>
                </button>
                <button 
                  onclick="dismissProposalFromModal(${prop.id}, this)"
                  class="bg-white hover:bg-slate-100 text-slate-600 text-xs font-semibold px-2 py-1.5 rounded-xl border border-slate-200 transition active:scale-95 cursor-pointer"
                >
                  Ignora
                </button>
              </div>
            </div>
          `;
        }).join('');
      } catch (err) {
        console.error("Errore loadPendingProposals:", err);
      }
    }

    async function approveProposalFromModal(id, btnEl) {
      const card = document.getElementById(`modal-prop-${id}`);
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = `<i class="fa-solid fa-circle-notch animate-spin text-[10px]"></i> Cifratura...`;
      }
      try {
        const res = await fetch(`/api/folders/proposals/${id}/approve`, {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Errore durante l'approvazione");
        }
        if (card) {
          card.className = 'bg-emerald-50 border border-emerald-200 rounded-2xl p-2.5 text-xs text-emerald-800 font-bold flex items-center gap-2';
          card.innerHTML = `<i class="fa-solid fa-shield-check text-emerald-600"></i> File salvato e cifrato con successo nel Caveau!`;
          setTimeout(() => card.remove(), 2500);
        }
        await loadDashboard(currentFilter);
        await checkPendingProposalsBanner();
      } catch (err) {
        showToast(`⚠️ ${err.message}`, 'error');
        if (card) {
          card.className = 'bg-rose-50 border border-rose-200 rounded-2xl p-2.5 text-xs text-rose-700 font-medium flex items-center justify-between gap-2';
          card.innerHTML = `<span>⚠️ ${escapeHtml(err.message)}</span> <button onclick="this.parentElement.remove()" class="text-rose-500 hover:text-rose-800 text-xs font-bold px-2 py-1">✕</button>`;
        }
        await loadPendingProposals();
        await checkPendingProposalsBanner();
      }
    }

    async function dismissProposalFromModal(id, btnEl) {
      const card = document.getElementById(`modal-prop-${id}`);
      try {
        const res = await fetch(`/api/folders/proposals/${id}/dismiss`, {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Errore durante la dismissione");
        }
        if (card) card.remove();
        await checkPendingProposalsBanner();
      } catch (err) {
        console.error("Errore dismissProposalFromModal:", err);
        showToast(`⚠️ ${err.message}`, 'error');
        await loadPendingProposals();
      }
    }

    async function triggerScanSensitiveFiles() {
      const btn = document.getElementById('btnScanSensitiveNow');
      if (btn) {
        btn.innerHTML = `<i class="fa-solid fa-circle-notch animate-spin text-[10px]"></i> Scansione...`;
      }
      try {
        const res = await fetch('/api/folders/scan-sensitive', {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore scansione sensibile");
        const data = await res.json();
        await loadPendingProposals();
        await checkPendingProposalsBanner();
        await loadWatchedFolders();
        if (data.new_proposals_count > 0) {
          alert(`Rilevati ${data.new_proposals_count} nuovi file sensibili pronti da approvare!`);
        } else {
          alert("Nessun nuovo file sensibile da approvare trovato nelle cartelle monitorate.");
        }
      } catch (err) {
        console.error("Errore triggerScanSensitiveFiles:", err);
      } finally {
        if (btn) {
          btn.innerHTML = `<i class="fa-solid fa-arrows-rotate text-[10px]"></i><span>Controlla Ora</span>`;
        }
      }
    }

    // Gestione Azioni Card Chat
    async function approveProposal(proposalId, btnEl) {
      const card = btnEl ? btnEl.closest(`#proposal-bubble-${proposalId}`) : document.getElementById(`proposal-bubble-${proposalId}`);
      if (card) {
        card.innerHTML = `
          <div class="p-3 text-center text-xs text-slate-600 flex items-center justify-center gap-2">
            <i class="fa-solid fa-circle-notch animate-spin text-emerald-600"></i>
            <span>Cifratura AES-256 e salvataggio nel Caveau in corso...</span>
          </div>
        `;
      }

      try {
        const res = await fetch(`/api/folders/proposals/${proposalId}/approve`, {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || "Errore approvazione file");
        }
        const data = await res.json();
        if (card) {
          card.className = 'mt-2.5 bg-emerald-50 border border-emerald-300 rounded-2xl p-3 shadow-2xs text-left';
          card.innerHTML = `
            <div class="flex items-center gap-2 text-emerald-800 text-xs font-bold">
              <i class="fa-solid fa-shield-check text-emerald-600"></i>
              <span>🔒 Salvato e Cifrato nel Caveau!</span>
            </div>
            <p class="text-[11px] text-emerald-700 mt-0.5">${escapeHtml(data.message || '')}</p>
          `;
        }
        await loadDashboard(currentFilter);
        await checkPendingProposalsBanner();
      } catch (err) {
        console.error("Errore approveProposal:", err);
        if (card) {
          card.innerHTML = `<div class="text-xs text-red-600 p-2 font-medium">⚠️ Errore: ${escapeHtml(err.message)}</div>`;
        }
      }
    }

    async function dismissProposal(proposalId, btnEl) {
      const card = btnEl ? btnEl.closest(`#proposal-bubble-${proposalId}`) : document.getElementById(`proposal-bubble-${proposalId}`);
      try {
        const res = await fetch(`/api/folders/proposals/${proposalId}/dismiss`, {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore durante l'operazione");
        if (card) {
          card.className = 'mt-2.5 bg-slate-100 border border-slate-200 rounded-2xl p-2.5 shadow-2xs text-left';
          card.innerHTML = `
            <div class="text-xs text-slate-500 font-medium flex items-center gap-1.5">
              <i class="fa-solid fa-eye-slash"></i>
              <span>File ignorato. Non verrà salvato nel Caveau.</span>
            </div>
          `;
        }
        await checkPendingProposalsBanner();
      } catch (err) {
        console.error("Errore dismissProposal:", err);
      }
    }

    function dismissChatSensitiveBanner() {
      window._chatSensitiveBannerDismissed = true;
      const banner = document.getElementById('chatSensitiveAlertBanner');
      if (banner) banner.classList.add('hidden');
    }

    async function approveFirstPendingProposal(btn) {
      const propId = btn ? btn.getAttribute('data-prop-id') : null;
      if (!propId) {
        openWatchedFoldersModal();
        return;
      }
      await approveProposal(parseInt(propId, 10), btn);
      dismissChatSensitiveBanner();
    }

    async function checkPendingProposalsBanner() {
      try {
        const res = await fetch('/api/folders/proposals?status=pending', { headers: authHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const proposals = data.proposals || [];
        const banner = document.getElementById('sensitiveFilesAlertBanner');
        const badge = document.getElementById('sensitiveBannerBadge');
        const text = document.getElementById('sensitiveBannerText');
        const toolsBadge = document.getElementById('toolsFoldersBadge');
        const chatBanner = document.getElementById('chatSensitiveAlertBanner');
        const chatDashBadge = document.getElementById('chatDashboardBadge');
        const chatBannerText = document.getElementById('chatSensitiveBannerText');
        const chatBannerSubtext = document.getElementById('chatSensitiveBannerSubtext');
        const chatActionBtn = document.getElementById('chatSensitiveBannerActionBtn');

        if (proposals.length > 0) {
          if (banner) banner.classList.remove('hidden');
          if (badge) badge.textContent = `${proposals.length} da verificare`;
          const first = proposals[0];
          if (text) {
            text.innerHTML = `L'AI ha individuato <strong>${escapeHtml(first.file_name)}</strong> in <em>${escapeHtml(first.folder_name || 'cartella monitorata')}</em> (${escapeHtml(first.sensitivity_reason || '')}). Vuoi salvarlo cifrato nel Caveau?`;
          }
          if (toolsBadge) {
            toolsBadge.classList.remove('hidden');
            toolsBadge.textContent = proposals.length;
          }
          if (chatDashBadge) {
            chatDashBadge.classList.remove('hidden');
            chatDashBadge.textContent = proposals.length;
          }
          if (chatBanner && !window._chatSensitiveBannerDismissed) {
            chatBanner.classList.remove('hidden');
            if (chatBannerText) {
              chatBannerText.innerHTML = `🛡️ Rilevato <strong>${escapeHtml(first.file_name)}</strong> in ${escapeHtml(first.folder_name || 'Download')}`;
            }
            if (chatBannerSubtext) {
              chatBannerSubtext.innerHTML = `${escapeHtml(first.sensitivity_reason || 'File sensibile')} • Vuoi proteggerlo cifrato nel Caveau?`;
            }
            if (chatActionBtn) {
              chatActionBtn.setAttribute('data-prop-id', first.id);
            }
          }

          // Se siamo nella chat attiva e la bolla per questa proposta non è ancora nel feed, iniettiamola dal vivo!
          const chatFeed = document.getElementById('chatFeed');
          if (chatFeed) {
            for (const prop of proposals) {
              const existingBubble = document.getElementById(`proposal-bubble-${prop.id}`);
              if (!existingBubble) {
                const proposalData = {
                  id: prop.id,
                  file_name: prop.file_name,
                  folder_name: prop.folder_name,
                  file_size: prop.file_size,
                  doc_type: prop.doc_type,
                  issuer: prop.issuer,
                  amount: prop.amount,
                  due_date: prop.due_date,
                  sensitivity_reason: prop.sensitivity_reason,
                  summary: prop.summary,
                  status: prop.status || 'pending'
                };
                const bubbleText = `🛡️ **Rilevato nuovo file sensibile** in \`${escapeHtml(prop.folder_name || 'cartella monitorata')}\`:\n\n📄 **${escapeHtml(prop.file_name)}**\n_${escapeHtml(prop.sensitivity_reason || 'Documento rilevato')}_\n\nVuoi che lo protegga salvandolo cifrato nel Caveau e lo indicizzi nello scadenzario?`;
                ensureTodayDateDivider();
                appendAssistantBubble(bubbleText, null, null, null, null, proposalData, null, getTime());
                scrollBottom();
              }
            }
          }
        } else {
          if (banner) banner.classList.add('hidden');
          if (toolsBadge) toolsBadge.classList.add('hidden');
          if (chatBanner) chatBanner.classList.add('hidden');
          if (chatDashBadge) chatDashBadge.classList.add('hidden');
          window._chatSensitiveBannerDismissed = false;
        }
      } catch (e) {
        console.warn("checkPendingProposalsBanner err:", e);
      }
    }

    let isAppInitialized = false;

    async function initApp() {
      if (isAppInitialized) return;
      isAppInitialized = true;

      if (typeof checkSimulatorParam === 'function') {
        await checkSimulatorParam();
      }

      applyLayout();
      updateAllBottomNavs('chat');
      loadAiModelSetting();
      loadOpenRouterCredits();
      loadThreads();
      loadDashboard('all');
      checkDeadlineAlerts();
      checkPendingProposalsBanner();
      checkGoogleDriveStatus();
      // Controllo autenticazione cloud: obbligatorio per utilizzare l'applicazione
      const savedToken = sessionStorage.getItem('supabase_auth_token') || localStorage.getItem('supabase_auth_token');
      if (!savedToken) {
        if (typeof openAccountModal === 'function') openAccountModal('profile', true);
      } else if (typeof checkCloudAuthStatus === 'function') {
        checkCloudAuthStatus().then(user => {
          if (!user) {
            if (typeof openAccountModal === 'function') openAccountModal('profile', true);
          }
        });
      }
      if (typeof loadCalendarStatus === 'function') loadCalendarStatus();
      if (typeof setSystemArea === 'function') setSystemArea(sessionStorage.getItem('dove_system_active_area') || 'all');
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('drive_connected') === 'true') {
        showToast('🟢 Google Drive collegato con successo!', 'success');
        window.history.replaceState({}, document.title, window.location.pathname);
      }
      if (typeof initMobileSwipeGestures === 'function') initMobileSwipeGestures();
      // Polling periodico per rilevare nuovi file sensibili segnalati dal monitor di background
      setInterval(checkPendingProposalsBanner, 20000);
    }

    // Inizializzazione al caricamento della pagina con controllo di sicurezza Caveau
    document.addEventListener('DOMContentLoaded', () => {
      checkVaultAuth();
    });
    // Verifica immediata se il DOM è già pronto
    checkVaultAuth();


    // =========================================================================
    // CONTROLLER ACCOUNT & GRUPPI CONDIVISI (OLIVETTI INDUSTRIAL)
    // =========================================================================
    let currentAuthMode = 'login'; // 'login' | 'signup'
    let accountModalIsMandatory = false;

    function openAccountModal(defaultTab = 'profile', isMandatory = false) {
      const modal = document.getElementById('accountModal');
      const closeBtn = document.getElementById('accountModalCloseBtn');
      const subtitleEl = document.getElementById('accountModalSubtitle');
      const tabGroups = document.getElementById('tabBtnAccountGroups');

      const hasUser = !!(window.currentCloudUser || localStorage.getItem('supabase_auth_token') || sessionStorage.getItem('supabase_auth_token'));
      accountModalIsMandatory = isMandatory || !hasUser;

      if (closeBtn) {
        if (accountModalIsMandatory) {
          closeBtn.classList.add('hidden');
        } else {
          closeBtn.classList.remove('hidden');
        }
      }

      if (tabGroups) {
        if (accountModalIsMandatory) {
          tabGroups.classList.add('opacity-40', 'pointer-events-none');
        } else {
          tabGroups.classList.remove('opacity-40', 'pointer-events-none');
        }
      }

      if (subtitleEl) {
        if (accountModalIsMandatory) {
          subtitleEl.innerHTML = `<span class="stamp-oli stamp-terracotta text-[8px] uppercase mr-1">ACCESSO RICHIESTO</span> Effettua il login o registrati per utilizzare il Caveau`;
        } else {
          subtitleEl.textContent = "Accesso Cloud, profilo e registro eventi di gruppo";
        }
      }

      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        switchAccountTab(accountModalIsMandatory ? 'profile' : defaultTab);
        if (typeof checkCloudAuthStatus === 'function') {
          checkCloudAuthStatus();
        }
        loadUserGroupsList();
      }
    }
    window.openAccountModal = openAccountModal;

    function closeAccountModal(force = false) {
      const hasUser = !!(window.currentCloudUser || localStorage.getItem('supabase_auth_token') || sessionStorage.getItem('supabase_auth_token'));
      if (!force && (accountModalIsMandatory || !hasUser)) {
        const card = document.querySelector('#accountModal .modal-card');
        if (card) {
          card.classList.remove('animate-shake');
          void card.offsetWidth;
          card.classList.add('animate-shake');
        }
        if (typeof showToast === 'function') {
          showToast("⚠️ È necessario accedere o registrarsi per utilizzare il Caveau in questa sessione.", "warning", 3000);
        }
        return;
      }
      const modal = document.getElementById('accountModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        accountModalIsMandatory = false;
      }
    }
    window.closeAccountModal = closeAccountModal;

    function switchAccountTab(tab) {
      if (tab === 'groups' && !window.currentCloudUser && !localStorage.getItem('supabase_auth_token')) {
        if (typeof showToast === 'function') {
          showToast("Accedi prima al tuo account per visualizzare i gruppi.", "warning", 2500);
        }
        tab = 'profile';
      }

      const tabProfile = document.getElementById('tabBtnAccountProfile');
      const tabGroups = document.getElementById('tabBtnAccountGroups');
      const contentProfile = document.getElementById('tabContentProfile');
      const contentGroups = document.getElementById('tabContentGroups');

      if (tab === 'profile') {
        if (tabProfile) {
          tabProfile.classList.add('border-[#3C5A48]', 'text-[#3C5A48]');
          tabProfile.classList.remove('border-transparent', 'text-[#7A7568]');
        }
        if (tabGroups) {
          tabGroups.classList.remove('border-[#3C5A48]', 'text-[#3C5A48]');
          tabGroups.classList.add('border-transparent', 'text-[#7A7568]');
        }
        if (contentProfile) contentProfile.classList.remove('hidden');
        if (contentGroups) contentGroups.classList.add('hidden');
      } else {
        if (tabGroups) {
          tabGroups.classList.add('border-[#3C5A48]', 'text-[#3C5A48]');
          tabGroups.classList.remove('border-transparent', 'text-[#7A7568]');
        }
        if (tabProfile) {
          tabProfile.classList.remove('border-[#3C5A48]', 'text-[#3C5A48]');
          tabProfile.classList.add('border-transparent', 'text-[#7A7568]');
        }
        if (contentProfile) contentProfile.classList.add('hidden');
        if (contentGroups) contentGroups.classList.remove('hidden');
        loadUserGroupsList();
      }
    }
    window.switchAccountTab = switchAccountTab;

    function setAuthMode(mode) {
      currentAuthMode = mode;
      const loginBtn = document.getElementById('authModeLoginBtn');
      const signupBtn = document.getElementById('authModeSignupBtn');
      const fullNameField = document.getElementById('authFullNameField');
      const submitBtnText = document.getElementById('authSubmitBtnText');
      const errorMsg = document.getElementById('authErrorMsg');
      if (errorMsg) errorMsg.classList.add('hidden');

      if (mode === 'signup') {
        if (loginBtn) {
          loginBtn.classList.remove('bg-white', 'text-[#222220]', 'shadow-xs');
          loginBtn.classList.add('text-[#7A7568]');
        }
        if (signupBtn) {
          signupBtn.classList.add('bg-white', 'text-[#222220]', 'shadow-xs');
          signupBtn.classList.remove('text-[#7A7568]');
        }
        if (fullNameField) fullNameField.classList.remove('hidden');
        if (submitBtnText) submitBtnText.textContent = "Crea Nuovo Account";
      } else {
        if (signupBtn) {
          signupBtn.classList.remove('bg-white', 'text-[#222220]', 'shadow-xs');
          signupBtn.classList.add('text-[#7A7568]');
        }
        if (loginBtn) {
          loginBtn.classList.add('bg-white', 'text-[#222220]', 'shadow-xs');
          loginBtn.classList.remove('text-[#7A7568]');
        }
        if (fullNameField) fullNameField.classList.add('hidden');
        if (submitBtnText) submitBtnText.textContent = "Accedi al Caveau";
      }
    }
    window.setAuthMode = setAuthMode;

    async function handleCloudAuthSubmit(e) {
      if (e) e.preventDefault();
      const emailInput = document.getElementById('authEmailInput');
      const passwordInput = document.getElementById('authPasswordInput');
      const fullNameInput = document.getElementById('authFullNameInput');
      const errorMsg = document.getElementById('authErrorMsg');
      const submitBtn = document.getElementById('authSubmitBtn');

      const email = emailInput ? emailInput.value.trim() : '';
      const password = passwordInput ? passwordInput.value : '';
      const fullName = fullNameInput ? fullNameInput.value.trim() : '';

      if (!email || !password) return;

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add('opacity-60');
      }
      if (errorMsg) errorMsg.classList.add('hidden');

      try {
        const endpoint = currentAuthMode === 'signup' ? '/api/auth/cloud/signup' : '/api/auth/cloud/login';
        const payload = { email, password };
        if (currentAuthMode === 'signup') {
          payload.full_name = fullName || email.split('@')[0];
        }

        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "Errore durante l'autenticazione");
        }

        if (data.access_token) {
          localStorage.setItem('supabase_auth_token', data.access_token);
          sessionStorage.setItem('supabase_auth_token', data.access_token);
          if (typeof checkCloudAuthStatus === 'function') {
            await checkCloudAuthStatus();
          }
          if (typeof showToast === 'function') {
            showToast(currentAuthMode === 'signup' ? "✨ Account creato con successo!" : "✅ Accesso eseguito con successo!", "success", 3000);
          }
          if (typeof loadThreads === 'function') {
            loadThreads();
          }
          if (typeof loadDashboard === 'function') {
            loadDashboard('all');
          }
          loadUserGroupsList();
          // Accesso completato: sblocca e chiudi il modale
          accountModalIsMandatory = false;
          closeAccountModal(true);
        }
      } catch (err) {
        if (errorMsg) {
          errorMsg.textContent = err.message;
          errorMsg.classList.remove('hidden');
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.classList.remove('opacity-60');
        }
      }
    }
    window.handleCloudAuthSubmit = handleCloudAuthSubmit;

    function handleCloudLogout() {
      localStorage.removeItem('supabase_auth_token');
      sessionStorage.removeItem('supabase_auth_token');
      window.currentCloudUser = null;
      if (typeof checkCloudAuthStatus === 'function') {
        checkCloudAuthStatus();
      }
      if (typeof showToast === 'function') {
        showToast("Sessione terminata. Effettua nuovamente il login per continuare.", "info", 3000);
      }
      loadUserGroupsList();
      openAccountModal('profile', true);
    }
    window.handleCloudLogout = handleCloudLogout;

    function toggleInlineGroupAction(action) {
      const createBox = document.getElementById('inlineCreateGroupBox');
      const joinBox = document.getElementById('inlineJoinGroupBox');
      const successBox = document.getElementById('groupCreatedSuccessBox');

      if (successBox) successBox.classList.add('hidden');

      if (action === 'create') {
        if (createBox) createBox.classList.toggle('hidden');
        if (joinBox) joinBox.classList.add('hidden');
      } else if (action === 'join') {
        if (joinBox) joinBox.classList.toggle('hidden');
        if (createBox) createBox.classList.add('hidden');
      } else {
        if (createBox) createBox.classList.add('hidden');
        if (joinBox) joinBox.classList.add('hidden');
      }
    }
    window.toggleInlineGroupAction = toggleInlineGroupAction;

    async function handleCreateGroupSubmit(e) {
      if (e) e.preventDefault();
      const nameInput = document.getElementById('groupNameInput');
      const descInput = document.getElementById('groupDescInput');
      const name = nameInput ? nameInput.value.trim() : '';
      const desc = descInput ? descInput.value.trim() : '';

      if (!name) return;

      try {
        const res = await fetch('/api/groups', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ name, description: desc, icon: 'fa-house' })
        });
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || "Errore nella creazione del gruppo");
        }
        const group = await res.json();

        // Mostra banner codice generato
        const successBox = document.getElementById('groupCreatedSuccessBox');
        const nameDisplay = document.getElementById('groupCreatedNameDisplay');
        const codeDisplay = document.getElementById('groupCreatedCodeDisplay');
        if (nameDisplay) nameDisplay.textContent = `Gruppo '${group.name}' Creato!`;
        if (codeDisplay) codeDisplay.textContent = group.invite_code;

        if (nameInput) nameInput.value = '';
        if (descInput) descInput.value = '';
        toggleInlineGroupAction(null);
        if (successBox) successBox.classList.remove('hidden');

        if (typeof showToast === 'function') {
          showToast(`🎉 Gruppo '${group.name}' attivato! Codice: ${group.invite_code}`, "success", 5000);
        }

        loadUserGroupsList();
        if (typeof loadThreads === 'function') loadThreads();
      } catch (err) {
        alert("Errore creazione gruppo: " + err.message);
      }
    }
    window.handleCreateGroupSubmit = handleCreateGroupSubmit;

    async function handleJoinGroupSubmit(e) {
      if (e) e.preventDefault();
      const codeInput = document.getElementById('groupInviteCodeInput');
      const errorMsg = document.getElementById('joinGroupErrorMsg');
      const code = codeInput ? codeInput.value.trim().toUpperCase() : '';

      if (!code) return;
      if (errorMsg) errorMsg.classList.add('hidden');

      try {
        const res = await fetch('/api/groups/join', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ invite_code: code })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "Codice invito non valido");
        }

        if (codeInput) codeInput.value = '';
        toggleInlineGroupAction(null);
        if (typeof showToast === 'function') {
          showToast(data.message || `Benvenuto nel gruppo '${data.name}'!`, "success", 4000);
        }
        loadUserGroupsList();
        if (typeof loadThreads === 'function') loadThreads();
      } catch (err) {
        if (errorMsg) {
          errorMsg.textContent = err.message;
          errorMsg.classList.remove('hidden');
        }
      }
    }
    window.handleJoinGroupSubmit = handleJoinGroupSubmit;

    function copyGroupCode() {
      const codeDisplay = document.getElementById('groupCreatedCodeDisplay');
      const btnText = document.getElementById('copyGroupCodeBtnText');
      const code = codeDisplay ? codeDisplay.textContent.trim() : '';
      if (!code) return;

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(() => {
          if (btnText) btnText.textContent = "Copiato!";
          setTimeout(() => { if (btnText) btnText.textContent = "Copia"; }, 2000);
          if (typeof showToast === 'function') showToast("Codice copiato negli appunti!", "success", 2000);
        });
      } else {
        prompt("Copia il codice d'invito:", code);
      }
    }
    window.copyGroupCode = copyGroupCode;

    async function loadUserGroupsList() {
      const listEl = document.getElementById('accountGroupsList');
      const countBadge = document.getElementById('accountGroupsCountBadge');
      if (!listEl) return;

      try {
        const res = await fetch('/api/groups', { headers: authHeaders() });
        if (!res.ok) {
          listEl.innerHTML = `<div class="p-4 text-center text-[#7A7568] text-xs font-mono-code">Accedi con il tuo account per visualizzare i tuoi gruppi.</div>`;
          if (countBadge) countBadge.textContent = '0';
          return;
        }
        const groups = await res.json();
        if (countBadge) countBadge.textContent = String(groups.length);

        if (groups.length === 0) {
          listEl.innerHTML = `
            <div class="bg-[#FAF8F2] border border-[#E3DDD1] rounded-xs p-5 text-center space-y-2">
              <i class="fa-solid fa-users text-2xl text-[#7A7568]"></i>
              <p class="text-xs font-bold text-[#222220] font-space uppercase">Nessun Gruppo Attivo</p>
              <p class="text-[11px] text-[#7A7568] font-mono-code">Crea un gruppo per la tua famiglia o unisciti tramite codice invito.</p>
            </div>
          `;
          return;
        }

        listEl.innerHTML = groups.map(g => `
          <div class="bg-white border border-[#E3DDD1] rounded-xs p-3.5 space-y-2.5 shadow-2xs hover:border-[#3C5A48] transition">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2.5 min-w-0">
                <div class="w-8 h-8 rounded-xs bg-[#3C5A48] text-white flex items-center justify-center text-xs shrink-0 shadow-xs">
                  <i class="fa-solid ${g.icon || 'fa-house'}"></i>
                </div>
                <div class="min-w-0">
                  <h4 class="font-bold text-xs text-[#222220] font-space truncate">${g.name}</h4>
                  <p class="text-[10px] text-[#7A7568] font-mono-code">${g.members_count} ${g.members_count === 1 ? 'membro' : 'membri'}</p>
                </div>
              </div>
              <span class="stamp-oli ${g.role === 'admin' ? 'stamp-terracotta' : 'stamp-solid-sage'} text-[8px] uppercase">${g.role}</span>
            </div>
            ${g.description ? `<p class="text-[11px] text-[#7A7568] font-mono-code line-clamp-2">${g.description}</p>` : ''}
            <div class="flex items-center justify-between pt-2 border-t border-[#E3DDD1] text-[10px] font-mono-code">
              <span class="bg-[#FAF8F2] border border-[#E3DDD1] px-2 py-0.5 rounded-xs text-[#222220] font-bold tracking-wider">
                INVITO: ${g.invite_code}
              </span>
              <button 
                type="button" 
                onclick="openGroupActivityLedger('${g.id}', '${g.name.replace(/'/g, "\\'")}')" 
                class="bg-[#3C5A48] hover:bg-[#2F4738] text-white font-space font-bold px-2.5 py-1 rounded-xs transition flex items-center gap-1 cursor-pointer active:scale-95 shadow-xs"
              >
                <span>Apri Registro</span>
                <i class="fa-solid fa-arrow-right text-[9px]"></i>
              </button>
            </div>
          </div>
        `).join('');
      } catch (err) {
        listEl.innerHTML = `<div class="p-4 text-center text-[#C84B31] text-xs font-mono-code">Errore caricamento gruppi: ${err.message}</div>`;
      }
    }
    window.loadUserGroupsList = loadUserGroupsList;

    let activeGroupWs = null;

    async function openGroupActivityLedger(groupId, groupName) {
      closeAccountModal();
      if (typeof switchScreen === 'function') switchScreen('chat');

      // Aggiorna header conversazione
      const titleEl = document.getElementById('activeThreadTitle');
      const subtitleEl = document.getElementById('activeThreadSubtitle');
      const iconEl = document.getElementById('activeThreadIcon');
      if (titleEl) titleEl.textContent = groupName;
      if (subtitleEl) subtitleEl.textContent = `👥 Registro Operativo Condiviso • Connesso`;
      if (iconEl) iconEl.className = "fa-solid fa-users";

      // Chiudi eventuale websocket precedente
      if (activeGroupWs) {
        try { activeGroupWs.close(); } catch(e){}
        activeGroupWs = null;
      }

      // Carica feed ufficiale dal ledger
      const chatFeed = document.getElementById('chatFeed');
      if (chatFeed) {
        chatFeed.innerHTML = `
          <div class="py-12 text-center text-[#7A7568] font-mono-code space-y-2">
            <i class="fa-solid fa-spinner fa-spin text-xl text-[#3C5A48]"></i>
            <p class="text-xs">Sincronizzazione Registro Operativo Gruppo '${groupName}'...</p>
          </div>
        `;
      }

      try {
        const res = await fetch(`/api/groups/${groupId}/feed`, { headers: authHeaders() });
        if (!res.ok) throw new Error("Impossibile caricare il registro");
        const events = await res.json();

        if (!chatFeed) return;
        chatFeed.innerHTML = '';

        // Intestazione registro ufficiale stile Olivetti Ledger
        const headerBanner = document.createElement('div');
        headerBanner.className = "p-4 mb-4 bg-white border border-[#3C5A48] rounded-xs shadow-xs text-xs space-y-1.5 font-mono-code";
        headerBanner.innerHTML = `
          <div class="flex items-center justify-between border-b border-[#E3DDD1] pb-2">
            <span class="font-bold text-[#3C5A48] font-space uppercase flex items-center gap-1.5">
              <i class="fa-solid fa-scroll"></i> REGISTRO OPERATIVO UFFICIALE
            </span>
            <span class="stamp-oli stamp-solid-sage text-[8px]">PROT. GRUPPO</span>
          </div>
          <p class="text-[11px] text-[#222220]">In questo canale sono ammessi esclusivamente <strong>atti ufficiali, quietanze e notifiche di scadenza</strong>. Nessuna chat informale.</p>
        `;
        chatFeed.appendChild(headerBanner);

        if (events.length === 0) {
          const emptyCard = document.createElement('div');
          emptyCard.className = "p-8 text-center text-[#7A7568] font-mono-code text-xs space-y-2";
          emptyCard.innerHTML = `
            <i class="fa-solid fa-inbox text-2xl text-[#3C5A48]/50"></i>
            <p>Nessun atto registrato nel gruppo al momento.</p>
            <p class="text-[10px]">Tutte le bollette o documenti caricati per questo gruppo compariranno qui automaticamente.</p>
          `;
          chatFeed.appendChild(emptyCard);
        } else {
          events.forEach(ev => {
            const card = document.createElement('div');
            card.className = "mb-3 p-3.5 bg-white border border-[#E3DDD1] rounded-xs shadow-2xs font-mono-code text-xs space-y-1.5";
            let stampHtml = '<span class="stamp-oli stamp-solid-sage text-[8px]">NOTIFICA</span>';
            if (ev.event_type === 'DOCUMENT_UPLOADED') stampHtml = '<span class="stamp-oli stamp-terracotta text-[8px]">NUOVO ATTO</span>';
            if (ev.event_type === 'DOCUMENT_PAID') stampHtml = '<span class="stamp-oli stamp-solid-sage text-[8px]">QUIETANZATO</span>';

            card.innerHTML = `
              <div class="flex items-center justify-between border-b border-[#E3DDD1] pb-1.5 text-[10px] text-[#7A7568]">
                <span class="font-bold text-[#222220]">${ev.actor_name || 'Sistema'}</span>
                <div class="flex items-center gap-2">
                  <span>${ev.created_at ? new Date(ev.created_at).toLocaleString('it-IT') : ''}</span>
                  ${stampHtml}
                </div>
              </div>
              <div class="font-bold text-[#222220] font-space text-xs">${ev.title}</div>
              ${ev.content ? `<p class="text-[11px] text-[#7A7568] leading-relaxed">${ev.content}</p>` : ''}
            `;
            chatFeed.appendChild(card);
          });
        }

        // Connessione WebSocket Real-time
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/groups/${groupId}/ws`;
        try {
          activeGroupWs = new WebSocket(wsUrl);
          activeGroupWs.onmessage = function(event) {
            try {
              const msg = JSON.parse(event.data);
              if (typeof showToast === 'function') {
                showToast(`🔔 Nuovo evento gruppo: ${msg.title || msg.event}`, "info", 4000);
              }
              openGroupActivityLedger(groupId, groupName);
            } catch(e){}
          };
        } catch(wsErr) {
          console.warn("WebSocket non disponibile:", wsErr);
        }

      } catch(err) {
        if (chatFeed) {
          chatFeed.innerHTML = `<div class="p-6 text-center text-[#C84B31] font-mono-code text-xs">Errore sincronizzazione: ${err.message}</div>`;
        }
      }
    }
    window.openGroupActivityLedger = openGroupActivityLedger;

    // =========================================================================
    // MODALE PARTECIPANTI GRUPPO CONDIVISO (OLIVETTI INDUSTRIAL)
    // =========================================================================
    async function openGroupMembersModal(targetGroupId) {
      const groupId = targetGroupId || currentThreadId;
      if (!groupId || groupId === 'general') return;

      const modal = document.getElementById('groupMembersModal');
      const listEl = document.getElementById('groupMembersModalList');
      const titleEl = document.getElementById('groupMembersModalGroupName');
      const countEl = document.getElementById('groupMembersModalCount');
      const inviteCodeDisplay = document.getElementById('groupMembersModalInviteCode');

      const thread = (threadsCache || []).find(t => t.id === groupId);
      if (titleEl) titleEl.textContent = thread ? thread.name : 'Gruppo Condiviso';

      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
      }

      if (listEl) {
        listEl.innerHTML = `
          <div class="py-8 text-center text-[#7A7568] font-mono-code text-xs space-y-2">
            <i class="fa-solid fa-spinner fa-spin text-lg text-[#3C5A48]"></i>
            <p>Caricamento partecipanti del gruppo...</p>
          </div>
        `;
      }

      try {
        const res = await fetch(`/api/groups/${groupId}/members`, { headers: authHeaders() });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Impossibile recuperare i membri del gruppo.");
        }
        const members = await res.json();

        if (countEl) countEl.textContent = `${members.length} ${members.length === 1 ? 'partecipante' : 'partecipanti'}`;
        const badge = document.getElementById('headerGroupMembersBadge');
        if (badge) badge.textContent = String(members.length);

        // Recupera codice invito dal thread o dall'API
        if (inviteCodeDisplay) {
          if (thread && thread.description && thread.description.includes('Codice:')) {
            const match = thread.description.match(/Codice:\s*([A-Z0-9\-]+)/i);
            if (match) inviteCodeDisplay.textContent = match[1];
          } else {
            fetch('/api/groups', { headers: authHeaders() })
              .then(r => r.json())
              .then(grps => {
                const g = grps.find(x => x.id === groupId);
                if (g && inviteCodeDisplay) inviteCodeDisplay.textContent = g.invite_code;
              })
              .catch(() => {});
          }
        }

        if (listEl) {
          if (members.length === 0) {
            listEl.innerHTML = `
              <div class="p-6 text-center text-[#7A7568] font-mono-code text-xs">
                Nessun partecipante trovato in questo gruppo.
              </div>
            `;
          } else {
            listEl.innerHTML = members.map(m => {
              const initial = (m.full_name || m.email || 'U')[0].toUpperCase();
              const isAdmin = m.role === 'admin';
              const roleStamp = isAdmin 
                ? '<span class="stamp-oli stamp-terracotta text-[8px] uppercase">AMMINISTRATORE</span>'
                : '<span class="stamp-oli stamp-solid-sage text-[8px] uppercase">PARTECIPANTE</span>';

              const dateStr = m.joined_at ? new Date(m.joined_at).toLocaleDateString('it-IT') : '';

              return `
                <div class="flex items-center justify-between p-3 bg-[#FAF8F2] border border-[#E3DDD1] rounded-xs shadow-2xs hover:border-[#3C5A48] transition">
                  <div class="flex items-center gap-3 min-w-0">
                    <div class="w-9 h-9 rounded-xs bg-[#3C5A48] text-white flex items-center justify-center font-bold text-sm shrink-0 shadow-xs">
                      ${initial}
                    </div>
                    <div class="min-w-0">
                      <div class="font-bold text-xs text-[#222220] font-space truncate">${escapeHtml(m.full_name || m.email)}</div>
                      <div class="text-[10px] text-[#7A7568] font-mono-code truncate">${escapeHtml(m.email)}</div>
                      ${dateStr ? `<div class="text-[9px] text-[#7A7568]/80 font-mono-code">Adesione: ${dateStr}</div>` : ''}
                    </div>
                  </div>
                  <div class="shrink-0 ml-2">
                    ${roleStamp}
                  </div>
                </div>
              `;
            }).join('');
          }
        }
      } catch (err) {
        if (listEl) {
          listEl.innerHTML = `
            <div class="p-5 text-center text-[#C84B31] font-mono-code text-xs space-y-1">
              <i class="fa-solid fa-triangle-exclamation text-lg"></i>
              <p>${escapeHtml(err.message)}</p>
              <p class="text-[10px] text-[#7A7568]">Verifica di essere autenticato con un account associato a questo gruppo.</p>
            </div>
          `;
        }
      }
    }
    window.openGroupMembersModal = openGroupMembersModal;

    function closeGroupMembersModal() {
      const modal = document.getElementById('groupMembersModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }
    window.closeGroupMembersModal = closeGroupMembersModal;

    function copyGroupMembersInviteCode() {
      const el = document.getElementById('groupMembersModalInviteCode');
      const text = el ? el.textContent.trim() : '';
      if (!text || text === '...') return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          if (typeof showToast === 'function') showToast(`Codice d'invito '${text}' copiato!`, "success", 2500);
        });
      } else {
        prompt("Copia il codice d'invito:", text);
      }
    }
    window.copyGroupMembersInviteCode = copyGroupMembersInviteCode;
