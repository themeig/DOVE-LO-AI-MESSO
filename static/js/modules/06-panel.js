// =========================================================================
// MODULO 6: Pannello Operativo (Hub 4 Quadrati, Panoramica, Ledger & Scadenze)
// =========================================================================
    // --- Fetch Dashboard Live: GET /api/dashboard ---
    async function loadDashboard(filter = null) {
      if (filter !== null) currentFilter = filter;
      const tSelect = document.getElementById('dashboardThreadSelect');
      const threadId = tSelect ? tSelect.value : '';

      try {
        let url = `/api/dashboard?filter=${encodeURIComponent(currentFilter)}`;
        if (threadId) {
          url += `&thread_id=${encodeURIComponent(threadId)}`;
        }
        const res = await fetch(url, { headers: authHeaders() });
        if (!res.ok) throw new Error("Errore recupero feed dashboard");
        const data = await res.json();

        currentRecords = data.records || [];
        if (currentFilter === 'all' && (!threadId || threadId === 'all')) {
          allDashboardRecordsCache = [...currentRecords];
          try {
            sessionStorage.setItem('vault_records_cache', JSON.stringify(allDashboardRecordsCache));
          } catch (e) {}
        } else if (!allDashboardRecordsCache || allDashboardRecordsCache.length === 0) {
          allDashboardRecordsCache = [...currentRecords];
        }

        // 1. Aggiorna Card KPI
        const kpi = data.kpi || {};
        const upcomingAmt = kpi.total_upcoming_amount != null ? kpi.total_upcoming_amount : 0;
        const formattedAmount = upcomingAmt.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        
        const kpiAmtEl = document.getElementById('kpiUpcomingAmount');
        if (kpiAmtEl) {
          kpiAmtEl.innerHTML = `<span class="text-xl sm:text-2xl font-bold text-[#7A7568] select-none">€</span> <span>${formattedAmount}</span>`;
        }

        const kpiBadgeEl = document.getElementById('kpiUpcomingBadge');
        if (kpiBadgeEl) {
          const count = kpi.pending_deadlines_count || 0;
          kpiBadgeEl.textContent = count > 0 ? `${count} in scadenza` : `REGOLARE`;
          kpiBadgeEl.className = count > 0
            ? "stamp-oli stamp-terracotta text-[9px] font-bold"
            : "stamp-oli text-[9px] font-bold";
        }

        const kpiDocsEl = document.getElementById('kpiDocsCount');
        if (kpiDocsEl) kpiDocsEl.textContent = `${kpi.total_documents_count || 0}`;

        const kpiItemsEl = document.getElementById('kpiItemsCount');
        if (kpiItemsEl) kpiItemsEl.textContent = `${kpi.total_items_count || 0}`;

        const kpiTotEl = document.getElementById('kpiTotalRecordsCount');
        if (kpiTotEl) {
          const tot = (kpi.total_documents_count || 0) + (kpi.total_items_count || 0);
          kpiTotEl.textContent = `${tot}`;
        }

        // Popola Statistiche Generali di Utilizzo (sezione Panoramica)
        const elMsg = document.getElementById('statTotalMessages');
        if (elMsg) elMsg.textContent = `${kpi.total_messages_count || 0}`;

        const elTh = document.getElementById('statTotalThreads');
        if (elTh) elTh.textContent = `${kpi.total_threads_count || 0}`;

        const elDocs = document.getElementById('statTotalDocs');
        if (elDocs) elDocs.textContent = `${kpi.total_documents_count || 0}`;

        const elResp = document.getElementById('statRespectedDeadlines');
        if (elResp) elResp.textContent = `${kpi.quietanzati_count || 0}`;

        const elPaidAmt = document.getElementById('statPaidAmount');
        if (elPaidAmt) {
          const pAmt = kpi.paid_deadlines_amount != null ? kpi.paid_deadlines_amount : 0;
          elPaidAmt.textContent = `€ ${pAmt.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        }

        const elUnresp = document.getElementById('statUnrespectedDeadlines');
        if (elUnresp) {
          const unresp = (kpi.overdue_deadlines_count || 0) + (kpi.pending_deadlines_count || 0);
          elUnresp.textContent = `${unresp}`;
        }

        const elOver = document.getElementById('statOverdueCount');
        if (elOver) elOver.textContent = `${kpi.overdue_deadlines_count || 0}`;

        const elPend = document.getElementById('statPendingCount');
        if (elPend) elPend.textContent = `${kpi.pending_deadlines_count || 0}`;

        const elComp = document.getElementById('statComplianceRate');
        if (elComp) elComp.textContent = `${kpi.compliance_rate != null ? kpi.compliance_rate : 100}%`;

        const elIt = document.getElementById('statTotalItems');
        if (elIt) elIt.textContent = `${kpi.total_items_count || 0}`;

        // Aggiorna data display
        const dateEl = document.getElementById('dashboardDateDisplay');
        if (dateEl) {
          const now = new Date();
          const options = { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' };
          dateEl.textContent = now.toLocaleDateString('it-IT', options).toUpperCase();
        }

        // Aggiorna contatori filtri
        const bDaPagare = document.getElementById('tabBadgeDaPagare');
        if (bDaPagare) {
          const count = kpi.pending_deadlines_count || 0;
          bDaPagare.textContent = count;
          if (count > 0) bDaPagare.classList.remove('hidden');
          else bDaPagare.classList.add('hidden');
        }
        const bQuiet = document.getElementById('tabBadgeQuietanzati');
        if (bQuiet) {
          const qCount = kpi.quietanzati_count || 0;
          bQuiet.textContent = qCount;
          if (qCount > 0) bQuiet.classList.remove('hidden');
          else bQuiet.classList.add('hidden');
        }
        const bScad = document.getElementById('tabBadgeScadenzario');
        if (bScad) {
          const sCount = kpi.total_deadlines_count || 0;
          bScad.textContent = sCount;
          if (sCount > 0) bScad.classList.remove('hidden');
          else bScad.classList.add('hidden');
        }
        const fI = document.getElementById('fItems');
        if (fI) fI.textContent = kpi.total_items_count ? `Oggetti (${kpi.total_items_count})` : 'Oggetti';

        // 2. Render vista attiva (categorizzata o tabellare)
        renderDashboardView();

        // 3. Footer contatore
        const tableFooterCount = document.getElementById('tableFooterCount');
        if (tableFooterCount) {
          tableFooterCount.textContent = `Mostrati ${currentRecords.length} elementi sincronizzati`;
        }

        // 4. Aggiorna banner notifiche file sensibili rilevati
        checkPendingProposalsBanner();
      } catch (err) {
        console.error("Errore loadDashboard:", err);
      }
    }
    window.loadDashboard = loadDashboard;
    window.loadDashboardData = loadDashboard;

    // --- Modalità Vista Dashboard (Raggruppata per Categoria o Tabellare) ---
    let dashboardViewMode = 'grouped';

    function setDashboardViewMode(mode) {
      dashboardViewMode = mode;
      const btnG = document.getElementById('btnViewGrouped');
      const btnT = document.getElementById('btnViewTable');
      if (mode === 'grouped') {
        if (btnG) btnG.className = 'px-3 py-1 rounded-lg bg-white text-slate-900 shadow-2xs font-semibold flex items-center gap-1.5 transition';
        if (btnT) btnT.className = 'px-3 py-1 rounded-lg text-slate-500 hover:text-slate-900 flex items-center gap-1.5 transition';
      } else {
        if (btnG) btnG.className = 'px-3 py-1 rounded-lg text-slate-500 hover:text-slate-900 flex items-center gap-1.5 transition';
        if (btnT) btnT.className = 'px-3 py-1 rounded-lg bg-white text-slate-900 shadow-2xs font-semibold flex items-center gap-1.5 transition';
      }
      renderDashboardView();
    }

    // =========================================================================
    // MODULO SCADENZARIO UNIVERSALE & CALENDARIO ATTI
    // =========================================================================
    let scadenzarioCategoryFilter = 'all';
    let scadenzarioStatusFilter = 'all';
    const expandedScadenzarioWidgetIds = new Set();

    function setScadenzarioCategoryFilter(cat) {
      scadenzarioCategoryFilter = cat;
      renderScadenzarioView(currentRecords);
    }
    window.setScadenzarioCategoryFilter = setScadenzarioCategoryFilter;

    function setScadenzarioStatusFilter(status) {
      scadenzarioStatusFilter = status;
      renderScadenzarioView(currentRecords);
    }
    window.setScadenzarioStatusFilter = setScadenzarioStatusFilter;

    function toggleScadenzarioWidget(docId) {
      if (expandedScadenzarioWidgetIds.has(docId)) {
        expandedScadenzarioWidgetIds.delete(docId);
      } else {
        expandedScadenzarioWidgetIds.add(docId);
      }
      renderScadenzarioView(currentRecords);
    }
    window.toggleScadenzarioWidget = toggleScadenzarioWidget;

    // Generatore file RFC 5545 iCalendar (.ics) per Google Calendar, Apple, Outlook
    function generateICSContent(records) {
      const pad = n => n < 10 ? '0' + n : n;
      const now = new Date();
      const nowStr = now.getUTCFullYear() +
        pad(now.getUTCMonth() + 1) +
        pad(now.getUTCDate()) + 'T' +
        pad(now.getUTCHours()) +
        pad(now.getUTCMinutes()) +
        pad(now.getUTCSeconds()) + 'Z';

      let lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//DoveLoAIMesso//Scadenzario Universale//IT',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:Scadenzario Caveau - Dove Lo AI Messo',
        'X-WR-TIMEZONE:Europe/Rome'
      ];

      (records || []).forEach(r => {
        if (!r.due_date) return;
        const cleanDate = r.due_date.replace(/-/g, '');
        const uid = `scadenza-${r.id}-${cleanDate}@doveloaimesso.local`;
        const summary = (r.title || 'Scadenza Documento').replace(/[,;\\]/g, ' ');
        const category = (r.category_label || r.category || 'Generale').replace(/[,;\\]/g, ' ');
        let desc = `Titolo: ${summary}\\nCategoria: ${category}`;
        if (r.amount != null) desc += `\\nImporto: € ${r.amount.toFixed(2)}`;
        if (r.source) desc += `\\nEnte/Fornitore: ${r.source}`;
        if (r.status) desc += `\\nStato: ${r.status.toUpperCase()}`;
        if (r.location_or_notes) desc += `\\nNote: ${(r.location_or_notes || '').replace(/[\r\n]+/g, ' ')}`;

        lines.push('BEGIN:VEVENT');
        lines.push(`UID:${uid}`);
        lines.push(`DTSTAMP:${nowStr}`);
        lines.push(`DTSTART;VALUE=DATE:${cleanDate}`);
        lines.push(`DTEND;VALUE=DATE:${cleanDate}`);
        lines.push(`SUMMARY:${summary} [${category}]`);
        lines.push(`DESCRIPTION:${desc}`);
        lines.push(`CATEGORIES:${category}`);
        if (r.status === 'quietanzato') {
          lines.push('STATUS:COMPLETED');
        } else {
          lines.push('STATUS:CONFIRMED');
        }
        lines.push('BEGIN:VALARM');
        lines.push('TRIGGER:-P1D');
        lines.push('ACTION:DISPLAY');
        lines.push(`DESCRIPTION:Promemoria Scadenza: ${summary}`);
        lines.push('END:VALARM');
        lines.push('END:VEVENT');
      });

      lines.push('END:VCALENDAR');
      return lines.join('\r\n');
    }

    function exportDeadlinesToICS(records, filename = 'scadenzario_caveau.ics') {
      const valid = (records || []).filter(r => r.due_date);
      if (!valid || valid.length === 0) {
        alert("Nessuna scadenza con data definita da esportare.");
        return;
      }
      const ics = generateICSContent(valid);
      const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    window.exportDeadlinesToICS = exportDeadlinesToICS;

    function exportSingleDeadlineToICS(docId) {
      const doc = (currentRecords || []).find(r => r.id === docId);
      if (!doc || !doc.due_date) {
        alert("Documento non trovato o privo di data di scadenza.");
        return;
      }
      const safeName = (doc.title || 'scadenza').toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 30);
      exportDeadlinesToICS([doc], `${safeName}_${doc.due_date}.ics`);
    }
    window.exportSingleDeadlineToICS = exportSingleDeadlineToICS;

    // Genera URL diretto template Google Calendar 1-Tap
    function getGoogleCalendarDirectLink(doc) {
      if (!doc || !doc.due_date) return '#';
      try {
        const rawDateStr = String(doc.due_date).split('T')[0];
        const parts = rawDateStr.split('-');
        if (parts.length !== 3) return '#';
        const y = parseInt(parts[0], 10);
        const m = parseInt(parts[1], 10);
        const d = parseInt(parts[2], 10);

        const startRaw = `${parts[0]}${parts[1]}${parts[2]}`;
        const nextDate = new Date(Date.UTC(y, m - 1, d + 1));
        const nextY = nextDate.getUTCFullYear();
        const nextM = String(nextDate.getUTCMonth() + 1).padStart(2, '0');
        const nextD = String(nextDate.getUTCDate()).padStart(2, '0');
        const endRaw = `${nextY}${nextM}${nextD}`;

        const catLabel = doc.category_label || doc.category || 'Scadenza';
        const title = encodeURIComponent(`[${catLabel}] ${doc.title || 'Scadenza'}`);
        let details = `Atto archiviato: ${doc.title || ''}\nCategoria: ${catLabel}`;
        if (doc.issuer) details += `\nEnte/Fornitore: ${doc.issuer}`;
        if (doc.amount != null) details += `\nImporto: € ${Number(doc.amount).toFixed(2)}`;
        if (doc.status) details += `\nStato: ${doc.status.toUpperCase()}`;
        if (doc.summary) details += `\n\nSintesi & Note:\n${doc.summary}`;
        details += `\n\nArchivio: Dove Lo AI Messo`;
        const encDetails = encodeURIComponent(details);

        return `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${title}&dates=${startRaw}/${endRaw}&details=${encDetails}`;
      } catch (e) {
        return '#';
      }
    }
    window.getGoogleCalendarDirectLink = getGoogleCalendarDirectLink;

    // Sincronizzazione massiva API Google Calendar
    async function syncAllToGoogleCalendar() {
      const btn = document.getElementById('btnSyncGoogleCalendar');
      const txt = document.getElementById('txtSyncGoogleCalendar');
      if (btn) btn.disabled = true;
      if (txt) txt.textContent = 'SINCRONIZZAZIONE IN CORSO...';

      try {
        const res = await fetch('/api/calendar/sync', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
          const err = data.detail || 'Impossibile sincronizzare con Google Calendar';
          if (typeof showSystemToast === 'function') {
            showSystemToast(`⚠️ ${err}`, 'warning');
          } else {
            alert(err);
          }
          return;
        }
        const msg = data.message || `Sincronizzate con successo ${data.synced_count || 0} scadenze su Google Calendar.`;
        if (typeof showSystemToast === 'function') {
          showSystemToast(`📅 ${msg}`, 'success');
        }
        if (typeof loadDashboard === 'function') {
          loadDashboard(currentFilter);
        }
        // Mostra guida pratica per visualizzare e filtrare subito su Google Calendar
        showCalendarFilterGuideModal(data.user_email);
      } catch (err) {
        console.error('Errore sync Google Calendar:', err);
        if (typeof showSystemToast === 'function') {
          showSystemToast(`❌ Errore durante la sincronizzazione: ${err.message}`, 'error');
        } else {
          alert(`Errore: ${err.message}`);
        }
      } finally {
        if (btn) btn.disabled = false;
        if (txt) txt.textContent = 'SINCRONIZZA GOOGLE CALENDAR';
      }
    }
    window.syncAllToGoogleCalendar = syncAllToGoogleCalendar;

    // Modal interattivo Guida Filtro Google Calendar
    function showCalendarFilterGuideModal(userEmail = '') {
      let modal = document.getElementById('calendarFilterGuideModal');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'calendarFilterGuideModal';
        modal.className = 'fixed inset-0 z-50 bg-black/60 backdrop-blur-2xs flex items-center justify-center p-3 sm:p-4';
        document.body.appendChild(modal);
      }

      const emailStr = userEmail || 'il tuo account Google';

      modal.innerHTML = `
        <div class="bg-[#F8F5EE] border-2 border-[#3C5A48] rounded-xs shadow-xl max-w-lg w-full max-h-[90vh] flex flex-col overflow-hidden text-[#222220]">
          <!-- Header Modal -->
          <div class="bg-[#3C5A48] text-white p-3.5 flex items-center justify-between">
            <div class="flex items-center gap-2">
              <i class="fa-brands fa-google text-base"></i>
              <span class="font-space font-bold text-sm tracking-tight uppercase">Guida: Scadenze su Google Calendar</span>
            </div>
            <button onclick="closeCalendarFilterGuideModal()" class="text-white/80 hover:text-white text-base cursor-pointer">
              <i class="fa-solid fa-xmark"></i>
            </button>
          </div>

          <!-- Corpo Modal -->
          <div class="p-4 sm:p-5 overflow-y-auto space-y-4 text-xs font-mono-code leading-relaxed">
            <div class="bg-white border border-[#E3DDD1] p-3 rounded-xs space-y-1">
              <div class="flex items-center gap-1.5 text-[#3C5A48] font-bold font-space uppercase text-[11px]">
                <i class="fa-solid fa-circle-check"></i>
                <span>Sincronizzazione Effettuata con Successo</span>
              </div>
              <p class="text-[#7A7568]">
                Le tue scadenze sono salvate nel calendario dedicato secondario:
                <strong class="text-[#222220] block font-space text-xs mt-0.5">"Dove Lo AI Messo - Scadenze"</strong>
                collegato all'account <strong>${escapeHtml(emailStr)}</strong>.
              </p>
            </div>

            <!-- Sezione Web -->
            <div class="space-y-1.5">
              <h4 class="font-space font-bold text-[#222220] text-xs uppercase flex items-center gap-1.5">
                <i class="fa-solid fa-desktop text-[#3C5A48]"></i>
                <span>1. Da Computer / Browser (calendar.google.com)</span>
              </h4>
              <ol class="list-decimal list-inside space-y-1.5 text-[#4A473E] bg-white p-3 rounded-xs border border-[#E3DDD1]">
                <li>Se avevi già aperta la scheda di Google Calendar, premi <strong>F5 (Ricarica pagina)</strong>.</li>
                <li>Nella colonna sinistra, sotto la sezione <strong>"I miei calendari"</strong>, troverai <strong>"Dove Lo AI Messo - Scadenze"</strong> (se la colonna è nascosta, aprila dal menu ☰ in alto a sinistra).</li>
                <li class="pt-1 font-semibold text-[#222220]">
                  🎯 <strong>Filtro per vedere SOLO queste scadenze:</strong> passa il mouse sopra <em>"Dove Lo AI Messo - Scadenze"</em>, clicca sui <strong>tre puntini verticali (⋮)</strong> a destra e seleziona <strong>"Mostra solo questo"</strong>!
                </li>
              </ol>
            </div>

            <!-- Sezione Smartphone -->
            <div class="space-y-1.5">
              <h4 class="font-space font-bold text-[#222220] text-xs uppercase flex items-center gap-1.5">
                <i class="fa-solid fa-mobile-screen text-[#C84B31]"></i>
                <span>2. Da Smartphone (App Google Calendar per Android / iOS)</span>
              </h4>
              <ol class="list-decimal list-inside space-y-1.5 text-[#4A473E] bg-white p-3 rounded-xs border border-[#E3DDD1]">
                <li>Apri l'app Google Calendar sul telefono.</li>
                <li>Tocca il menu in alto a sinistra (☰) e scorri in fondo su <strong>Impostazioni</strong>.</li>
                <li>Tocca il tuo account Google (<strong>${escapeHtml(emailStr)}</strong>).</li>
                <li>Tocca <strong>"Dove Lo AI Messo - Scadenze"</strong> (se non compare subito, tocca prima <em>"Mostra altri"</em>).</li>
                <li class="pt-1 text-[#C84B31] font-bold">
                  ⚡ <strong>Attiva la levetta "Sincronizza"</strong> (su Android i nuovi calendari secondari hanno la sincronizzazione disattivata per impostazione predefinita).
                </li>
              </ol>
            </div>
          </div>

          <!-- Footer Modal -->
          <div class="bg-[#FAF8F2] border-t border-[#E3DDD1] p-3 flex items-center justify-between gap-2 flex-wrap">
            <a href="https://calendar.google.com/calendar/u/0/r" target="_blank" rel="noopener noreferrer" class="px-3 py-2 bg-[#2B4C7E] hover:bg-[#1E3557] text-white text-xs font-bold font-space rounded-xs transition shadow-xs flex items-center gap-1.5">
              <i class="fa-solid fa-arrow-up-right-from-square"></i>
              <span>Apri Google Calendar ↗</span>
            </a>
            <button onclick="closeCalendarFilterGuideModal()" class="px-3 py-2 bg-white hover:bg-[#F8F5EE] border border-[#E3DDD1] text-[#222220] text-xs font-bold font-space rounded-xs transition cursor-pointer">
              Ho Capito
            </button>
          </div>
        </div>
      `;

      modal.classList.remove('hidden');
      modal.classList.add('flex');
    }
    window.showCalendarFilterGuideModal = showCalendarFilterGuideModal;

    function closeCalendarFilterGuideModal() {
      const modal = document.getElementById('calendarFilterGuideModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }
    window.closeCalendarFilterGuideModal = closeCalendarFilterGuideModal;

    // Render del widget interattivo Olivetti Industrial per ogni atto
    function renderDocumentWidgetHtml(doc) {
      const docId = doc.id || doc.document_id;
      const title = escapeHtml(doc.title || 'Documento');
      const escapedTitle = title.replace(/'/g, "\\'");
      const issuer = escapeHtml(doc.source || doc.issuer || 'Atto Archiviato');
      const fileUrl = doc.file_url ? escapeHtml(doc.file_url) : '';
      const fileType = escapeHtml(doc.file_type || 'application/pdf');
      const downloadUrl = doc.download_url || `/api/documents/${docId}/download`;
      const isZip = (doc.file_type === 'zip' || (doc.title && doc.title.toLowerCase().endsWith('.zip')));
      const summary = doc.location_or_notes || doc.summary || '';

      let amountHtml = '';
      if (doc.amount != null) {
        amountHtml = `<span class="stamp-oli stamp-solid-terracotta text-[9px] font-bold">€ ${doc.amount.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
      }
      let dueHtml = '';
      if (doc.due_date) {
        dueHtml = `<span class="stamp-oli text-[9px] font-bold">Scadenza: ${doc.due_date}</span>`;
      }

      return `
        <div class="mt-3 p-3.5 bg-white border-2 border-[#3C5A48]/50 rounded-xs shadow-xs text-left animate-in fade-in duration-150">
          <div class="flex items-start justify-between gap-3 flex-wrap sm:flex-nowrap">
            <div class="flex items-start gap-2.5 min-w-0">
              <div class="w-8 h-8 rounded-xs bg-[#3C5A48] text-white flex items-center justify-center shrink-0 mt-0.5 shadow-2xs">
                <i class="fa-solid ${doc.category_icon || 'fa-file-invoice'} text-sm"></i>
              </div>
              <div class="min-w-0">
                <div class="flex items-center gap-1.5 flex-wrap">
                  <span class="stamp-oli text-[8px] font-bold">SCHEDA ATTO #${docId}</span>
                  <span class="stamp-oli stamp-solid-sage text-[8px] font-bold">${escapeHtml(doc.category_label || 'Archivio')}</span>
                  ${doc.thread_name ? `<span class="stamp-oli text-[8px]">${escapeHtml(doc.thread_name)}</span>` : ''}
                </div>
                <h4 class="font-bold text-[#222220] text-sm font-space mt-1">${title}</h4>
                <p class="text-[11px] text-[#7A7568] font-mono-code">${issuer}</p>
                <div class="flex items-center gap-1.5 mt-1.5 flex-wrap">
                  ${amountHtml}
                  ${dueHtml}
                  ${doc.urgency_label ? `<span class="stamp-oli ${doc.urgency === 'overdue' ? 'stamp-terracotta' : ''} text-[8px] font-bold">${escapeHtml(doc.urgency_label)}</span>` : ''}
                </div>
              </div>
            </div>
            <!-- Azioni Widget -->
            <div class="flex items-center gap-1.5 flex-wrap shrink-0 self-start sm:self-center">
              ${doc.drive_web_url ? `
                <a href="${doc.drive_web_url}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1.5 stamp-oli text-[9px] font-bold hover:bg-[#3C5A48] hover:text-white transition flex items-center gap-1">
                  <i class="fa-brands fa-google-drive text-[10px]"></i> <span>Drive ↗</span>
                </a>
              ` : ''}
              ${fileUrl ? `
                <button type="button" onclick="openMediaModal('${fileUrl}', '${escapedTitle}', '${fileType}', '${downloadUrl}', ${docId})" class="bg-[#3C5A48] hover:bg-[#2F4738] text-white text-[10px] font-bold px-2.5 py-1.5 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Visualizza documento">
                  <i class="fa-regular fa-eye text-xs"></i> <span>Vedi</span>
                </button>
              ` : ''}
              ${isZip ? `
                <button type="button" onclick="unzipDocumentById(${docId})" class="bg-amber-600 hover:bg-amber-700 text-white text-[10px] font-bold px-2.5 py-1.5 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Decomprimi archivio">
                  <i class="fa-solid fa-file-zipper text-xs"></i> <span>Estrai</span>
                </button>
              ` : ''}
              <button type="button" onclick="downloadDashboardDoc(${docId})" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2.5 py-1.5 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Scarica file">
                <i class="fa-solid fa-download text-xs"></i> <span>Scarica</span>
              </button>
              <button type="button" onclick="openFileInExplorer(${docId})" class="bg-[#FAF8F2] hover:bg-white text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1] text-[10px] font-bold px-2 py-1.5 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Apri in Esplora Risorse">
                <i class="fa-regular fa-folder-open text-xs text-[#C84B31]"></i> <span class="hidden sm:inline">PC</span>
              </button>
              <button type="button" onclick="exportSingleDeadlineToICS(${docId})" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2.5 py-1.5 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Scarica promemoria iCalendar">
                <i class="fa-regular fa-calendar-plus text-xs text-[#3C5A48]"></i> <span>.ics</span>
              </button>
              ${doc.due_date ? `
                <a href="${getGoogleCalendarDirectLink(doc)}" target="_blank" rel="noopener noreferrer" class="bg-[#2B4C7E] hover:bg-[#1E3557] text-white text-[10px] font-bold px-2.5 py-1.5 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Aggiungi promemoria a Google Calendar con 1 tap">
                  <i class="fa-brands fa-google text-xs"></i> <span>Google Cal</span>
                </a>
              ` : ''}
            </div>
          </div>
          ${summary ? `
            <div class="mt-2.5 pt-2 border-t border-[#E3DDD1] text-[11px] text-[#222220] font-mono-code leading-relaxed bg-[#FAF8F2] p-2 rounded-xs border border-[#E3DDD1]/50">
              <span class="text-[#7A7568] font-bold uppercase text-[9px] block mb-0.5">Sintesi Dati & Contenuto:</span>
              ${formatMessageText(summary)}
            </div>
          ` : ''}
        </div>
      `;
    }

    // Render della Vista Scadenzario Dedicato
    function renderScadenzarioView(records) {
      const container = document.getElementById('dashboardScadenzarioContainer');
      if (!container) return;
      container.innerHTML = '';

      const allDeadlines = (records || []).filter(r => r.type === 'document' && r.due_date);

      if (!allDeadlines || allDeadlines.length === 0) {
        container.innerHTML = `
          <div class="py-12 text-center bg-white rounded-xs border border-[#E3DDD1] p-8 shadow-xs">
            <div class="w-12 h-12 rounded-xs bg-[#FAF8F2] border border-[#E3DDD1] text-[#3C5A48] flex items-center justify-center mx-auto mb-3 text-xl">
              <i class="fa-solid fa-calendar-check"></i>
            </div>
            <h3 class="font-space font-bold text-sm text-[#222220] uppercase">Nessuna Scadenza Registrata</h3>
            <p class="text-xs text-[#7A7568] font-mono-code mt-1 max-w-md mx-auto">Non sono presenti documenti, bollette o atti con data di scadenza definita nel faldone corrente.</p>
            <div class="mt-4 flex items-center justify-center gap-2">
              <button onclick="filterTable('all')" class="px-3.5 py-2 bg-[#3C5A48] text-white rounded-xs text-xs font-bold font-space transition hover:bg-[#2F4738] cursor-pointer">
                Torna al Registro Completo
              </button>
            </div>
          </div>
        `;
        return;
      }

      // 1. Mappa categorie presenti con conteggio
      const catCounts = {};
      allDeadlines.forEach(d => {
        const catName = d.category_label || 'Altri Documenti Archiviati';
        catCounts[catName] = (catCounts[catName] || 0) + 1;
      });

      // 2. Filtro per Categoria e Stato
      let filtered = allDeadlines.filter(d => {
        if (scadenzarioCategoryFilter !== 'all') {
          const catName = d.category_label || 'Altri Documenti Archiviati';
          if (catName !== scadenzarioCategoryFilter) return false;
        }
        if (scadenzarioStatusFilter === 'da_pagare') {
          if (d.status !== 'da_pagare') return false;
        } else if (scadenzarioStatusFilter === 'overdue') {
          if (d.urgency !== 'overdue' && (d.days_remaining == null || d.days_remaining >= 0)) return false;
        } else if (scadenzarioStatusFilter === 'quietanzati') {
          if (d.status !== 'quietanzato') return false;
        }
        return true;
      });

      // Metriche di sintesi per lo scadenzario
      const totalDue = filtered.filter(d => d.status === 'da_pagare' && d.amount).reduce((acc, d) => acc + d.amount, 0);
      const overdueCount = filtered.filter(d => d.status === 'da_pagare' && (d.urgency === 'overdue' || (d.days_remaining != null && d.days_remaining < 0))).length;
      const upcomingSoonCount = filtered.filter(d => d.status === 'da_pagare' && d.days_remaining != null && d.days_remaining >= 0 && d.days_remaining <= 30).length;

      // 3. Riquadro di Collegamento Google Calendar (mostrato solo se non collegato)
      if (typeof window.currentCalendarConnected === 'undefined' && typeof loadCalendarStatus === 'function') {
        loadCalendarStatus();
      }
      const isCalConnected = (window.currentCalendarConnected === true) || (window.currentDriveConnected === true);
      
      if (!isCalConnected) {
        // Se non è collegato: riquadro bianco con invito a collegare l'account
        const calBannerBox = document.createElement('div');
        calBannerBox.className = 'bg-white border border-[#E3DDD1] rounded-xs p-3.5 shadow-2xs flex flex-col md:flex-row items-start md:items-center justify-between gap-3 text-xs';
        calBannerBox.innerHTML = `
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-xs bg-[#FAF8F2] border border-[#E3DDD1] text-[#2B4C7E] flex items-center justify-center shrink-0 text-sm shadow-2xs">
              <i class="fa-brands fa-google"></i>
            </div>
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-space font-bold text-[#222220]">Vuoi collegare Google Calendar?</span>
                <span class="stamp-oli text-[8px] font-bold text-[#7A7568]">NON COLLEGATO</span>
              </div>
              <p class="text-[11px] text-[#7A7568] font-mono-code mt-0.5">
                Collega il tuo account Google per sincronizzare automaticamente tributi, bollette e scadenze nel calendario dedicato.
              </p>
            </div>
          </div>
          <div class="flex items-center gap-2 flex-wrap shrink-0">
            <button onclick="openGoogleDriveModal()" class="px-3.5 py-2 bg-[#2B4C7E] hover:bg-[#1E3557] active:scale-95 text-white rounded-xs text-xs font-bold font-space transition shadow-xs flex items-center gap-1.5 cursor-pointer" title="Collega il tuo account Google per sincronizzare le scadenze">
              <i class="fa-brands fa-google"></i>
              <span>COLLEGA GOOGLE CALENDAR</span>
            </button>
            <button onclick="exportDeadlinesToICS(currentRecords)" class="px-2.5 py-1.5 bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48]/40 active:scale-95 rounded-xs text-[11px] font-space font-bold transition flex items-center gap-1.5 shadow-2xs cursor-pointer" title="Scarica file .ics con promemoria compatibile Google Calendar, Apple e Outlook">
              <i class="fa-solid fa-calendar-arrow-down"></i>
              <span>Esporta .ics</span>
            </button>
          </div>
        `;
        container.appendChild(calBannerBox);
      }

      // 4. Bento KPI Scadenzario
      const statsBox = document.createElement('div');
      statsBox.className = 'grid grid-cols-2 sm:grid-cols-4 gap-2.5';
      statsBox.innerHTML = `
        <div class="bg-white border border-[#E3DDD1] p-3 rounded-xs shadow-2xs">
          <span class="text-[9px] font-mono-code text-[#7A7568] uppercase font-bold block">TOTALE DA SALDARE</span>
          <span class="text-lg sm:text-xl font-black font-mono-code text-[#C84B31]">€ ${totalDue.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div class="bg-white border border-[#E3DDD1] p-3 rounded-xs shadow-2xs">
          <span class="text-[9px] font-mono-code text-[#7A7568] uppercase font-bold block">TERMINE SCADUTO</span>
          <span class="text-lg sm:text-xl font-black font-mono-code ${overdueCount > 0 ? 'text-red-700' : 'text-[#7A7568]'}">${overdueCount} atti</span>
        </div>
        <div class="bg-white border border-[#E3DDD1] p-3 rounded-xs shadow-2xs">
          <span class="text-[9px] font-mono-code text-[#7A7568] uppercase font-bold block">QUESTO MESE (≤ 30 GG)</span>
          <span class="text-lg sm:text-xl font-black font-mono-code ${upcomingSoonCount > 0 ? 'text-amber-800' : 'text-[#7A7568]'}">${upcomingSoonCount} atti</span>
        </div>
        <div class="bg-white border border-[#E3DDD1] p-3 rounded-xs shadow-2xs">
          <span class="text-[9px] font-mono-code text-[#7A7568] uppercase font-bold block">PAGATI / SALDATI</span>
          <span class="text-lg sm:text-xl font-black font-mono-code text-[#3C5A48]">${filtered.filter(d=>d.status==='quietanzato').length} atti</span>
        </div>
      `;
      container.appendChild(statsBox);

      // 5. Filtri Categorie & Sub-Filtri Stato
      const filterBox = document.createElement('div');
      filterBox.className = 'bg-white border border-[#E3DDD1] rounded-xs p-3 shadow-xs space-y-2.5';

      let catChipsHtml = `
        <button onclick="setScadenzarioCategoryFilter('all')" class="px-2.5 py-1 rounded-xs text-[10px] font-space font-bold transition cursor-pointer ${scadenzarioCategoryFilter === 'all' ? 'bg-[#3C5A48] text-white shadow-2xs' : 'bg-[#F8F5EE] text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1]'}">
          TUTTE (${allDeadlines.length})
        </button>
      `;
      Object.keys(catCounts).sort().forEach(cat => {
        const count = catCounts[cat];
        const isActive = (scadenzarioCategoryFilter === cat);
        catChipsHtml += `
          <button onclick="setScadenzarioCategoryFilter('${cat.replace(/'/g, "\\'")}')" class="px-2.5 py-1 rounded-xs text-[10px] font-space font-bold transition cursor-pointer ${isActive ? 'bg-[#3C5A48] text-white shadow-2xs' : 'bg-[#F8F5EE] text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1]'}">
            ${escapeHtml(cat.toUpperCase())} (${count})
          </button>
        `;
      });

      const totalUnpaid = allDeadlines.filter(d => d.status === 'da_pagare').length;
      const totalOverdue = allDeadlines.filter(d => d.status === 'da_pagare' && (d.urgency === 'overdue' || (d.days_remaining != null && d.days_remaining < 0))).length;
      const totalPaid = allDeadlines.filter(d => d.status === 'quietanzato').length;

      let statusChipsHtml = `
        <button onclick="setScadenzarioStatusFilter('all')" class="px-2.5 py-1 rounded-xs text-[10px] font-space font-bold transition cursor-pointer ${scadenzarioStatusFilter === 'all' ? 'bg-[#222220] text-white shadow-2xs' : 'bg-[#F8F5EE] text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1]'}">
          TUTTI GLI STATI
        </button>
        <button onclick="setScadenzarioStatusFilter('da_pagare')" class="px-2.5 py-1 rounded-xs text-[10px] font-space font-bold transition cursor-pointer flex items-center gap-1 ${scadenzarioStatusFilter === 'da_pagare' ? 'bg-[#C84B31] text-white shadow-2xs' : 'bg-[#F8F5EE] text-[#C84B31] hover:text-[#C84B31]/90 border border-[#E3DDD1]'}">
          <span>🔴 DA SALDARE</span>
          <span class="text-[8px] bg-white/20 px-1 py-0.2 rounded-xs font-mono-code">${totalUnpaid}</span>
        </button>
        <button onclick="setScadenzarioStatusFilter('overdue')" class="px-2.5 py-1 rounded-xs text-[10px] font-space font-bold transition cursor-pointer flex items-center gap-1 ${scadenzarioStatusFilter === 'overdue' ? 'bg-red-800 text-white shadow-2xs' : 'bg-[#F8F5EE] text-red-800 hover:text-red-900 border border-[#E3DDD1]'}">
          <span>⚠️ SCADUTE</span>
          <span class="text-[8px] bg-white/20 px-1 py-0.2 rounded-xs font-mono-code">${totalOverdue}</span>
        </button>
        <button onclick="setScadenzarioStatusFilter('quietanzati')" class="px-2.5 py-1 rounded-xs text-[10px] font-space font-bold transition cursor-pointer flex items-center gap-1 ${scadenzarioStatusFilter === 'quietanzati' ? 'bg-emerald-800 text-white shadow-2xs' : 'bg-[#F8F5EE] text-emerald-800 hover:text-emerald-900 border border-[#E3DDD1]'}">
          <span>✅ PAGATI</span>
          <span class="text-[8px] bg-white/20 px-1 py-0.2 rounded-xs font-mono-code">${totalPaid}</span>
        </button>
      `;

      filterBox.innerHTML = `
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="text-[10px] font-bold font-mono-code text-[#7A7568] uppercase mr-1 flex items-center gap-1">
            <i class="fa-solid fa-folder-tree text-[#3C5A48]"></i> Categoria:
          </span>
          ${catChipsHtml}
        </div>
        <div class="flex items-center gap-1.5 flex-wrap pt-2 border-t border-[#E3DDD1]">
          <span class="text-[10px] font-bold font-mono-code text-[#7A7568] uppercase mr-1 flex items-center gap-1">
            <i class="fa-solid fa-clock text-[#C84B31]"></i> Stato:
          </span>
          ${statusChipsHtml}
        </div>
      `;
      container.appendChild(filterBox);

      if (filtered.length === 0) {
        const noMatchBox = document.createElement('div');
        noMatchBox.className = 'py-10 text-center bg-white rounded-xs border border-[#E3DDD1] p-6 shadow-xs';
        noMatchBox.innerHTML = `
          <i class="fa-solid fa-filter-circle-xmark text-3xl text-slate-300 mb-2 block"></i>
          <p class="font-space font-bold text-xs text-[#222220]">Nessuna scadenza corrisponde ai filtri selezionati</p>
          <button onclick="setScadenzarioCategoryFilter('all'); setScadenzarioStatusFilter('all');" class="mt-3 px-3 py-1.5 bg-[#F8F5EE] border border-[#E3DDD1] text-[#222220] rounded-xs text-xs font-bold font-space hover:bg-[#FAF8F2] transition cursor-pointer">
            Azzera Filtri
          </button>
        `;
        container.appendChild(noMatchBox);
        return;
      }

      // 6. Ripartizione nei Blocchi Temporali
      const MONTH_NAMES = ['GEN', 'FEB', 'MAR', 'APR', 'MAG', 'GIU', 'LUG', 'AGO', 'SET', 'OTT', 'NOV', 'DIC'];
      
      function getDays(d) {
        if (typeof d.days_remaining === 'number') return d.days_remaining;
        if (!d.due_date) return null;
        try {
          const dDate = new Date(d.due_date + 'T00:00:00');
          const todayObj = new Date();
          todayObj.setHours(0, 0, 0, 0);
          return Math.round((dDate - todayObj) / (1000 * 60 * 60 * 24));
        } catch (e) {
          return null;
        }
      }

      const bScadute = filtered.filter(d => d.status === 'da_pagare' && (d.urgency === 'overdue' || (getDays(d) != null && getDays(d) < 0)));
      const bOggi = filtered.filter(d => d.status === 'da_pagare' && (d.urgency === 'today' || getDays(d) === 0));
      const bDomani = filtered.filter(d => d.status === 'da_pagare' && getDays(d) === 1 && d.urgency !== 'today');
      const bQuestaSettimana = filtered.filter(d => d.status === 'da_pagare' && getDays(d) != null && getDays(d) >= 2 && getDays(d) <= 7);
      const bQuestoMese = filtered.filter(d => d.status === 'da_pagare' && getDays(d) != null && getDays(d) > 7 && getDays(d) <= 30);
      const bEntroAnno = filtered.filter(d => d.status !== 'quietanzato' && getDays(d) != null && getDays(d) > 30 && getDays(d) <= 365);
      const bLungoTermine = filtered.filter(d => d.status !== 'quietanzato' && (getDays(d) == null || getDays(d) > 365));
      const bQuietanzate = filtered.filter(d => d.status === 'quietanzato');

      const blocks = [
        {
          title: "SCADUTE / TERMINE SUPERATO",
          icon: "fa-fire",
          headerColor: "text-red-800 bg-red-100 border-red-300",
          badgeColor: "bg-red-200 text-red-900",
          items: bScadute
        },
        {
          title: "IN SCADENZA OGGI (ENTRO 24 ORE)",
          icon: "fa-bell",
          headerColor: "text-red-900 bg-red-50 border-red-200",
          badgeColor: "bg-red-100 text-red-900",
          items: bOggi
        },
        {
          title: "IN SCADENZA DOMANI",
          icon: "fa-hourglass-half",
          headerColor: "text-orange-900 bg-orange-100 border-orange-300",
          badgeColor: "bg-orange-200 text-orange-950",
          items: bDomani
        },
        {
          title: "IN SCADENZA QUESTA SETTIMANA (ENTRO 7 GIORNI)",
          icon: "fa-calendar-week",
          headerColor: "text-amber-900 bg-amber-100 border-amber-300",
          badgeColor: "bg-amber-200 text-amber-950",
          items: bQuestaSettimana
        },
        {
          title: "IN SCADENZA QUESTO MESE (ENTRO 30 GIORNI)",
          icon: "fa-clock",
          headerColor: "text-amber-800 bg-amber-50 border-amber-200",
          badgeColor: "bg-amber-100 text-amber-900",
          items: bQuestoMese
        },
        {
          title: "PROSSIMI MESI (ENTRO L'ANNO CORRENTE)",
          icon: "fa-calendar-day",
          headerColor: "text-[#3C5A48] bg-[#FAF8F2] border-[#E3DDD1]",
          badgeColor: "bg-[#3C5A48]/10 text-[#3C5A48]",
          items: bEntroAnno
        },
        {
          title: "A LUNGO TERMINE (VALIDITÀ PLURIENNALE)",
          icon: "fa-id-card-clip",
          headerColor: "text-slate-800 bg-slate-100 border-slate-300",
          badgeColor: "bg-slate-200 text-slate-900",
          items: bLungoTermine
        },
        {
          title: "PAGATE, SALDATE & RINNOVATE",
          icon: "fa-circle-check",
          headerColor: "text-emerald-800 bg-emerald-50 border-emerald-300",
          badgeColor: "bg-emerald-200 text-emerald-950",
          items: bQuietanzate
        }
      ];

      blocks.forEach(block => {
        if (!block.items || block.items.length === 0) return;

        const blockSection = document.createElement('div');
        blockSection.className = 'space-y-2.5';

        // Intestazione Blocco
        const bHeader = document.createElement('div');
        bHeader.className = `flex items-center justify-between px-3.5 py-2 rounded-xs border text-xs font-bold font-space uppercase ${block.headerColor}`;
        bHeader.innerHTML = `
          <div class="flex items-center gap-2">
            <i class="fa-solid ${block.icon}"></i>
            <span>${block.title}</span>
          </div>
          <span class="text-[10px] font-mono-code px-2 py-0.5 rounded-xs font-bold ${block.badgeColor}">${block.items.length} ATTI</span>
        `;
        blockSection.appendChild(bHeader);

        // Lista Atti del Blocco
        const itemsList = document.createElement('div');
        itemsList.className = 'space-y-2';

        block.items.forEach(doc => {
          const docItem = document.createElement('div');
          docItem.className = 'bg-white border border-[#E3DDD1] hover:border-[#3C5A48] rounded-xs p-3 transition shadow-2xs';

          // Calcolo Date Tile
          let dayStr = '--';
          let monthStr = '---';
          let yearStr = '----';
          if (doc.due_date) {
            const parts = doc.due_date.split('-');
            if (parts.length === 3) {
              yearStr = parts[0];
              const mIdx = parseInt(parts[1], 10) - 1;
              monthStr = (mIdx >= 0 && mIdx < 12) ? MONTH_NAMES[mIdx] : parts[1];
              dayStr = parts[2];
            }
          }

          // Countdown Urgenza
          let urgencyBadgeHtml = '';
          if (doc.status === 'quietanzato') {
            urgencyBadgeHtml = `<span class="stamp-oli stamp-solid-sage text-[8px] font-bold">PAGATO / RINNOVATO</span>`;
          } else if (doc.urgency_label) {
            const isRed = doc.urgency === 'overdue';
            const isAmber = doc.urgency === 'today' || doc.urgency === 'urgent';
            const cls = isRed ? 'stamp-oli stamp-terracotta' : (isAmber ? 'stamp-oli stamp-terracotta' : 'stamp-oli');
            urgencyBadgeHtml = `<span class="${cls} text-[8px] font-bold">${escapeHtml(doc.urgency_label)}</span>`;
          }

          // Importo
          let amountStr = '';
          if (doc.amount != null) {
            amountStr = `<span class="font-mono-code font-black text-sm text-[#222220]">€ ${doc.amount.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
          }

          const isExpanded = expandedScadenzarioWidgetIds.has(doc.id);
          const toggleWidgetBtnText = isExpanded ? `▴ Chiudi Scheda` : `📋 Scheda / Widget ▾`;

          docItem.innerHTML = `
            <div class="flex items-start justify-between gap-3 flex-wrap sm:flex-nowrap">
              <!-- Riquadro Data Calendario Dattiloscritto -->
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <div class="w-14 sm:w-16 bg-[#FAF8F2] border border-[#E3DDD1] rounded-xs p-1.5 flex flex-col items-center justify-center text-center shrink-0 select-none">
                  <span class="text-[8px] font-mono-code font-bold uppercase text-[#7A7568] leading-tight">${monthStr}</span>
                  <span class="text-xl sm:text-2xl font-black font-space text-[#222220] leading-none my-0.5">${dayStr}</span>
                  <span class="text-[8px] font-mono-code text-[#7A7568] leading-tight">${yearStr}</span>
                </div>

                <!-- Info Atto -->
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    <span class="stamp-oli text-[8px] font-bold">
                      <i class="fa-solid ${doc.category_icon || 'fa-file-invoice'} mr-1 text-[#3C5A48]"></i>
                      ${escapeHtml(doc.category_label || 'Archivio')}
                    </span>
                    ${urgencyBadgeHtml}
                    ${doc.google_calendar_event_id ? `<span class="stamp-oli stamp-solid-sage text-[8px] font-bold" title="Sincronizzato sul tuo calendario Google dedicato"><i class="fa-solid fa-cloud-check mr-0.5"></i> CALENDAR</span>` : ''}
                    ${doc.thread_name ? `<span class="stamp-oli text-[8px]"><i class="fa-solid fa-folder text-[#7A7568] mr-1"></i>${escapeHtml(doc.thread_name)}</span>` : ''}
                  </div>
                  <h3 class="font-bold text-[#222220] text-xs sm:text-sm font-space mt-1 truncate">
                    ${escapeHtml(doc.title)}
                  </h3>
                  <div class="flex items-center gap-2 mt-0.5 text-[11px] text-[#7A7568] font-mono-code flex-wrap">
                    <span>${escapeHtml(doc.source || 'Ente')}</span>
                    ${doc.location_or_notes ? `<span>• ${escapeHtml(doc.location_or_notes)}</span>` : ''}
                  </div>
                </div>
              </div>

              <!-- Importo & Azioni Scadenza -->
              <div class="flex flex-col sm:items-end justify-between gap-2 shrink-0 self-start sm:self-center w-full sm:w-auto pt-2 sm:pt-0 border-t sm:border-t-0 border-[#E3DDD1]">
                <div class="flex items-center gap-2 justify-between sm:justify-end">
                  ${amountStr}
                  ${doc.status === 'da_pagare' ? `
                    <button onclick="markAsPaid(${doc.id})" class="stamp-oli stamp-solid-terracotta text-[8px] font-bold hover:opacity-90 transition active:scale-95 cursor-pointer" title="Segna come saldato/rinnovato">
                      SALDA / RINNOVA
                    </button>
                  ` : ''}
                </div>

                <!-- Pulsanti Azione Principali -->
                <div class="flex items-center gap-1.5 flex-wrap justify-end">
                  <button onclick="toggleScadenzarioWidget(${doc.id})" class="px-2.5 py-1 bg-[#FAF8F2] hover:bg-white text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold font-space rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer" title="Apri/chiudi il widget completo di questo documento">
                    <i class="fa-solid fa-file-lines text-xs"></i>
                    <span>${toggleWidgetBtnText}</span>
                  </button>
                  <button onclick="exportSingleDeadlineToICS(${doc.id})" class="px-2.5 py-1 bg-white hover:bg-[#FAF8F2] text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1] text-[10px] font-bold font-space rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer" title="Scarica evento .ics compatibile con Google Calendar">
                    <i class="fa-regular fa-calendar-plus text-xs text-[#3C5A48]"></i>
                    <span>.ics</span>
                  </button>
                  <a href="${getGoogleCalendarDirectLink(doc)}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 bg-white hover:bg-[#FAF8F2] text-[#2B4C7E] border border-[#2B4C7E]/40 text-[10px] font-bold font-space rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer" title="Aggiungi con 1 tap a Google Calendar">
                    <i class="fa-brands fa-google text-xs text-[#2B4C7E]"></i>
                    <span>Google Cal</span>
                  </a>
                  ${doc.file_url ? `
                    <button onclick="openMediaModal('${escapeHtml(doc.file_url)}', '${escapeHtml(doc.title).replace(/'/g, "\\'")}', '${escapeHtml(doc.file_type || 'application/pdf')}', '${doc.download_url || `/api/documents/${doc.id}/download`}', ${doc.id})" class="p-1 bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] rounded-xs text-[10px] transition active:scale-95 flex items-center justify-center w-6 h-6 cursor-pointer" title="Anteprima documento">
                      <i class="fa-regular fa-eye text-xs"></i>
                    </button>
                  ` : ''}
                  ${doc.drive_web_url ? `
                    <a href="${doc.drive_web_url}" target="_blank" rel="noopener noreferrer" class="p-1 stamp-oli text-[8px] hover:bg-[#3C5A48] hover:text-white transition flex items-center justify-center w-6 h-6" title="Apri in Google Drive">
                      <i class="fa-brands fa-google-drive text-[9px]"></i>
                    </a>
                  ` : ''}
                </div>
              </div>
            </div>

            <!-- Widget Interattivo Espandibile Inline -->
            ${isExpanded ? renderDocumentWidgetHtml(doc) : ''}
          `;

          itemsList.appendChild(docItem);
        });

        blockSection.appendChild(itemsList);
        container.appendChild(blockSection);
      });
    }
    window.renderScadenzarioView = renderScadenzarioView;

    function renderDashboardView() {
      const groupedCont = document.getElementById('dashboardGroupedContainer');
      const tableCont = document.getElementById('dashboardTableContainer');
      const scadCont = document.getElementById('dashboardScadenzarioContainer');

      if (currentFilter === 'scadenzario' || currentFilter === 'scadenziario' || currentFilter === 'calendar') {
        if (dashboardViewMode === 'table') {
          if (groupedCont) groupedCont.classList.add('hidden');
          if (scadCont) scadCont.classList.add('hidden');
          if (tableCont) tableCont.classList.remove('hidden');
          renderTableRows(currentRecords);
        } else {
          if (groupedCont) groupedCont.classList.add('hidden');
          if (tableCont) tableCont.classList.add('hidden');
          if (scadCont) {
            scadCont.classList.remove('hidden');
            renderScadenzarioView(currentRecords);
          }
        }
        return;
      }

      if (scadCont) scadCont.classList.add('hidden');

      if (dashboardViewMode === 'grouped') {
        if (groupedCont) groupedCont.classList.remove('hidden');
        if (tableCont) tableCont.classList.add('hidden');
        renderGroupedView(currentRecords);
      } else {
        if (groupedCont) groupedCont.classList.add('hidden');
        if (tableCont) tableCont.classList.remove('hidden');
        renderTableRows(currentRecords);
      }
    }

    // --- Helper Badge Scadenza con Countdown Dinamico ---
    function getDueDateBadge(rec) {
      if (!rec.due_date) return '<span class="text-slate-400 font-normal">-</span>';
      const parts = rec.due_date.split('-');
      const formatted = parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : rec.due_date;
      if (rec.status === 'da_pagare') {
        let days = rec.days_remaining;
        if (days == null) {
          const dDate = new Date(rec.due_date + 'T00:00:00');
          const todayObj = new Date();
          todayObj.setHours(0, 0, 0, 0);
          days = Math.round((dDate - todayObj) / (1000 * 60 * 60 * 24));
        }

        let countdownBadge = '';
        if (days < 0) {
          const absD = Math.abs(days);
          countdownBadge = `
            <span class="inline-flex items-center gap-1 bg-red-100 text-red-800 border border-red-200 text-[10px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap mt-1">
              <i class="fa-solid fa-fire text-red-600"></i> Scaduta da ${absD} ${absD === 1 ? 'giorno' : 'giorni'}
            </span>
          `;
          return `<div class="flex flex-col"><span class="font-bold text-red-700">${formatted}</span>${countdownBadge}</div>`;
        } else if (days === 0) {
          countdownBadge = `
            <span class="inline-flex items-center gap-1 bg-amber-100 text-amber-900 border border-amber-300 text-[10px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap mt-1 animate-pulse">
              <i class="fa-solid fa-clock text-amber-700"></i> Scade oggi!
            </span>
          `;
          return `<div class="flex flex-col"><span class="font-bold text-amber-800">${formatted}</span>${countdownBadge}</div>`;
        } else if (days <= 3) {
          countdownBadge = `
            <span class="inline-flex items-center gap-1 bg-amber-50 text-amber-800 border border-amber-200 text-[10px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap mt-1">
              <i class="fa-solid fa-triangle-exclamation text-amber-600"></i> Scade tra ${days} ${days === 1 ? 'giorno' : 'giorni'}
            </span>
          `;
          return `<div class="flex flex-col"><span class="font-semibold text-amber-800">${formatted}</span>${countdownBadge}</div>`;
        } else if (days <= 7) {
          countdownBadge = `
            <span class="inline-flex items-center gap-1 bg-yellow-50 text-yellow-800 border border-yellow-200 text-[10px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap mt-1">
              <i class="fa-regular fa-clock text-yellow-600"></i> In scadenza (${days} gg)
            </span>
          `;
          return `<div class="flex flex-col"><span class="font-medium text-slate-700">${formatted}</span>${countdownBadge}</div>`;
        } else {
          countdownBadge = `
            <span class="inline-flex items-center gap-1 bg-slate-50 text-slate-600 border border-slate-200 text-[10px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap mt-1">
              Tra ${days} gg
            </span>
          `;
          return `<div class="flex flex-col"><span class="text-slate-600">${formatted}</span>${countdownBadge}</div>`;
        }
      } else {
        return `<span class="text-slate-500">${formatted}</span>`;
      }
    }

    // --- Rendering Vista Raggruppata per Categoria (Documenti) e Ambiente (Oggetti) ---
    function renderGroupedView(records) {
      const container = document.getElementById('dashboardGroupedContainer');
      if (!container) return;
      container.innerHTML = '';

      if (!records || records.length === 0) {
        container.innerHTML = `
          <div class="py-12 text-center text-slate-400 text-xs bg-white rounded-2xl border border-slate-200/80 p-8">
            <i class="fa-solid fa-folder-open text-4xl mb-3 block text-slate-300"></i>
            <p class="font-semibold text-slate-700 text-sm">Nessun elemento trovato</p>
            <p class="text-slate-400 mt-1">Non ci sono documenti o oggetti per il filtro o lo spazio selezionato.</p>
          </div>
        `;
        return;
      }

      const docs = records.filter(r => r.type === 'document');
      const items = records.filter(r => r.type === 'physical_item');

      // --- SEZIONE 1: DOCUMENTI PER CATEGORIA ---
      if (docs.length > 0) {
        const docSection = document.createElement('div');
        docSection.id = 'docSection';
        docSection.className = 'space-y-4';

        docSection.innerHTML = `
          <div class="flex items-center justify-between pb-1 border-b border-slate-200/70">
            <div class="flex items-center gap-2">
              <span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
              <h3 class="text-xs font-bold text-slate-800 uppercase tracking-wider">Documenti Raggruppati per Categoria</h3>
              <span class="text-xs bg-emerald-50 text-emerald-700 font-bold px-2 py-0.5 rounded-full border border-emerald-200/50">${docs.length}</span>
            </div>
            <div class="flex items-center gap-2 text-[11px]">
              <button onclick="toggleAllAccordions('docSection', true)" class="text-slate-400 hover:text-emerald-700 font-medium transition cursor-pointer">Espandi tutti</button>
              <span class="text-slate-300">|</span>
              <button onclick="toggleAllAccordions('docSection', false)" class="text-slate-400 hover:text-slate-700 font-medium transition cursor-pointer">Comprimi tutti</button>
            </div>
          </div>
        `;

        const docGroups = {};
        docs.forEach(doc => {
          let catLabel = doc.category_label || 'Altri Documenti';
          if (catLabel.toLowerCase().includes('oggetti fisic') || catLabel.toLowerCase() === 'oggetti' || catLabel.toLowerCase() === 'oggetto fisico') {
            const isImg = doc.file_type && ['jpg', 'jpeg', 'png', 'webp', 'image'].includes(doc.file_type.toLowerCase());
            catLabel = isImg ? 'Foto & Immagini' : 'Altri Documenti Archiviati';
            doc.category_icon = isImg ? 'fa-image' : 'fa-folder-closed';
          }
          if (!docGroups[catLabel]) {
            docGroups[catLabel] = {
              icon: doc.category_icon || 'fa-folder-closed',
              categoryKey: doc.category || 'altro',
              items: []
            };
          }
          docGroups[catLabel].items.push(doc);
        });

        const categoryOrder = [
          "Utenze & Bollette",
          "Fisco, Tributi & F24",
          "Documenti Personali & Identità",
          "Contratti, Polizze & Assicurazioni",
          "Fatture, Spese & Ricevute",
          "Sanità & Spese Mediche",
          "Canzoni & Testi Musicali",
          "Note, Canzoni & Testi Personali",
          "Altri Documenti Archiviati",
          "Altri Documenti"
        ];

        const sortedDocCatKeys = Object.keys(docGroups).sort((a, b) => {
          const isOtherA = a.toLowerCase().includes("altri document");
          const isOtherB = b.toLowerCase().includes("altri document");
          if (isOtherA && !isOtherB) return 1;
          if (!isOtherA && isOtherB) return -1;
          const idxA = categoryOrder.indexOf(a);
          const idxB = categoryOrder.indexOf(b);
          if (idxA !== -1 && idxB !== -1) return idxA - idxB;
          if (idxA !== -1) return -1;
          if (idxB !== -1) return 1;
          return a.localeCompare(b);
        });

        sortedDocCatKeys.forEach(catLabel => {
          const group = docGroups[catLabel];
          const catDocs = group.items;

          let catTotalAmount = 0;
          let hasAmounts = false;
          let catUnpaidCount = 0;
          catDocs.forEach(d => {
            if (d.amount != null) {
              catTotalAmount += d.amount;
              hasAmounts = true;
            }
            if (d.status === 'da_pagare') catUnpaidCount++;
          });

          let iconColor = 'bg-slate-100 text-slate-700';
          const ck = (group.categoryKey || '').toLowerCase();
          const cl = catLabel.toLowerCase();
          const ic = (group.icon || '').toLowerCase();

          if (ck.includes('utenz') || cl.includes('bollett') || ic.includes('bolt')) iconColor = 'bg-amber-100 text-amber-700';
          else if (ck.includes('fisco') || cl.includes('f24') || ic.includes('landmark')) iconColor = 'bg-blue-100 text-blue-700';
          else if (ck.includes('identita') || cl.includes('personal') || ic.includes('id-card')) iconColor = 'bg-indigo-100 text-indigo-700';
          else if (ck.includes('contratt') || ic.includes('signature') || ic.includes('contract')) iconColor = 'bg-violet-100 text-violet-700';
          else if (ck.includes('spes') || ck.includes('ricevut') || ic.includes('receipt')) iconColor = 'bg-emerald-100 text-emerald-700';
          else if (ck.includes('sanit') || ic.includes('pulse') || ic.includes('medical')) iconColor = 'bg-rose-100 text-rose-700';
          else if (ck.includes('canzon') || ck.includes('music') || cl.includes('canzon') || ic.includes('music')) iconColor = 'bg-pink-100 text-pink-700';
          else if (ck.includes('ricett') || cl.includes('cucin') || ic.includes('utensils')) iconColor = 'bg-orange-100 text-orange-700';
          else if (ck.includes('studio') || ck.includes('universit') || ic.includes('graduation')) iconColor = 'bg-teal-100 text-teal-700';
          else if (ck.includes('auto') || ic.includes('car')) iconColor = 'bg-sky-100 text-sky-700';
          else if (ck.includes('animal') || ic.includes('paw')) iconColor = 'bg-amber-100 text-amber-800';
          else if (ck.includes('viagg') || ic.includes('plane')) iconColor = 'bg-cyan-100 text-cyan-700';
          else if (ck.includes('zip') || ic.includes('zipper')) iconColor = 'bg-yellow-100 text-yellow-800';
          else iconColor = 'bg-purple-100 text-purple-700';

          const detailsEl = document.createElement('details');
          detailsEl.open = false;
          detailsEl.className = 'group dashboard-accordion bg-white border border-[#E3DDD1] rounded-xs shadow-xs transition-all overflow-hidden';

          let unpaidBadge = '';
          if (catUnpaidCount > 0) {
            unpaidBadge = `
              <span class="stamp-oli stamp-terracotta text-[9px]">
                ⚠️ ${catUnpaidCount} DA SALDARE
              </span>
            `;
          }

          let totalBadge = '';
          if (hasAmounts) {
            totalBadge = `
              <span class="text-xs font-black font-mono-code text-[#222220] bg-[#FAF8F2] px-2.5 py-1 rounded-xs border border-[#E3DDD1]">
                ${catTotalAmount.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €
              </span>
            `;
          }

          let cardsHtml = '';
          const subfoldersSet = new Set();
          catDocs.forEach(rec => {
            if (rec.subfolder) subfoldersSet.add(rec.subfolder);
            const escapedTitle = escapeHtml(rec.title).replace(/'/g, "\\'");
            const threadName = escapeHtml(rec.thread_name || 'Principale');
            const isGroup = (rec.thread_id || '').includes('famiglia') || (rec.thread_id || '').includes('gruppo');
            const threadIcon = isGroup ? 'fa-users text-[#3C5A48]' : 'fa-folder text-[#3C5A48]';

            const amountDisplay = rec.amount != null
              ? `${rec.amount.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
              : '<span class="text-slate-300 font-normal text-xs">-</span>';

            const dueDateBadge = getDueDateBadge(rec);

            let statusBadge = '';
            if (rec.status === 'da_pagare') {
              const lbl = rec.amount != null ? 'DA SALDARE' : 'IN SCADENZA';
              statusBadge = `<span class="stamp-oli stamp-terracotta text-[8px]">${lbl}</span>`;
            } else if (rec.status === 'quietanzato') {
              const lbl = rec.amount != null ? 'PAGATO' : 'RINNOVATO';
              statusBadge = `<span class="stamp-oli text-emerald-800 border-emerald-700 text-[8px]">${lbl}</span>`;
            } else {
              statusBadge = `<span class="stamp-oli text-[8px]">${escapeHtml(rec.status).toUpperCase()}</span>`;
            }

            let previewBtn = '';
            if (rec.file_url) {
              const escapedUrl = escapeHtml(rec.file_url);
              const escapedType = escapeHtml(rec.file_type || 'application/pdf');
              const downloadUrl = `/api/documents/${rec.id}/download`;
              const isZipRec = (rec.file_type === 'zip' || rec.doc_type === 'archivio_zip' || (rec.title && rec.title.toLowerCase().endsWith('.zip')));
              const unzipBtn = isZipRec ? `
                <button onclick="unzipDocumentById(${rec.id})" title="Decomprimi tutti i file nel caveau" class="bg-amber-600 hover:bg-amber-700 text-white text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer font-space">
                  <i class="fa-solid fa-file-zipper text-xs"></i> Estrai
                </button>
              ` : '';
              const driveBtn = rec.drive_web_url ? `
                <a href="${rec.drive_web_url}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 stamp-oli text-[8px] hover:bg-[#3C5A48] hover:text-white transition" title="Apri su Google Drive">
                  <i class="fa-brands fa-google-drive text-[9px]"></i> <span>Drive ↗</span>
                </a>
              ` : '';
              previewBtn = `
                ${driveBtn}
                <button onclick="openMediaModal('${escapedUrl}', '${escapedTitle}', '${escapedType}', '${downloadUrl}', ${rec.id})" title="Anteprima documento" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer font-space">
                  <i class="fa-regular fa-eye text-xs"></i> Vedi
                </button>
                ${unzipBtn}
                <button onclick="downloadDashboardDoc(${rec.id})" title="Scarica documento" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer font-space">
                  <i class="fa-solid fa-download text-xs"></i>
                </button>
                <button onclick="openFileInExplorer(${rec.id})" title="Apri in Esplora Risorse di Windows" class="bg-white hover:bg-[#FAF8F2] text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer font-space">
                  <i class="fa-regular fa-folder-open text-xs text-[#C84B31]"></i>
                </button>
              `;
            }

            let payBtn = '';
            if (rec.status === 'da_pagare') {
              const lbl = rec.amount != null ? 'SALDA' : 'RINNOVA';
              const titleAction = rec.amount != null ? 'Segna come pagato' : 'Segna come rinnovato o archiviato';
              payBtn = `<button onclick="markAsPaid(${rec.id})" class="stamp-oli stamp-solid-terracotta text-[8px] hover:opacity-90 transition active:scale-95 cursor-pointer" title="${titleAction}">${lbl}</button>`;
            }

            const deleteBtn = `
              <button onclick="confirmDashboardDelete('${rec.type}', ${rec.id}, '${escapedTitle}')" title="Elimina dal caveau" class="text-slate-400 hover:text-[#C84B31] p-1 rounded-xs hover:bg-[#FAECE8] transition active:scale-95 text-xs ml-auto">
                <i class="fa-regular fa-trash-can"></i>
              </button>
            `;

            const isUnpaid = rec.status === 'da_pagare';
            const isPaid = rec.status === 'quietanzato';
            const cardBorder = isUnpaid ? 'border-l-3 border-[#C84B31]' : (isPaid ? 'border-l-3 border-[#E3DDD1]' : 'border-l-3 border-[#3C5A48]');

            cardsHtml += `
              <div class="dashboard-card bg-[#FAF8F2] hover:bg-white border border-[#E3DDD1] ${cardBorder} rounded-xs p-3.5 flex flex-col justify-between transition-all shadow-xs">
                <div>
                  <div class="flex items-start justify-between gap-2">
                    <div class="flex items-center gap-2 min-w-0">
                      <div class="w-7 h-7 rounded-xs ${iconColor} flex items-center justify-center shrink-0 text-xs border border-[#E3DDD1]">
                        <i class="fa-solid ${group.icon}"></i>
                      </div>
                      <div class="min-w-0">
                        <h4 class="font-bold text-[#222220] text-xs truncate font-space" title="${escapeHtml(rec.title)}">${escapeHtml(rec.title)}</h4>
                        <div class="flex items-center gap-1.5 flex-wrap mt-0.5">
                          <p class="text-[11px] text-[#7A7568] truncate font-mono-code">${escapeHtml(rec.source || '')}</p>
                          ${rec.subfolder ? `
                            <span class="inline-flex items-center gap-1 text-[9px] font-mono-code text-[#7A7568] bg-white px-1.5 py-0.5 rounded-xs border border-[#E3DDD1] shrink-0" title="Sottocartella: ${escapeHtml(rec.subfolder)}">
                              <i class="fa-solid fa-folder text-[8px] text-[#C84B31]"></i>
                              <span>${escapeHtml(rec.subfolder)}</span>
                            </span>
                          ` : ''}
                        </div>
                      </div>
                    </div>
                    <span class="stamp-oli text-[8px] shrink-0">
                      <i class="fa-solid ${threadIcon} text-[8px]"></i>
                      <span>${threadName}</span>
                    </span>
                  </div>

                  <!-- Dettagli Importo & Scadenza -->
                  <div class="mt-3 pt-2.5 border-t border-[#E3DDD1] flex items-end justify-between gap-2">
                    <div>
                      <span class="text-[9px] font-mono-code text-[#7A7568] uppercase tracking-wider block">Importo</span>
                      <span class="text-sm font-black font-mono-code text-[#222220]">${amountDisplay}</span>
                    </div>
                    <div class="text-right">
                      <span class="text-[9px] font-mono-code text-[#7A7568] uppercase tracking-wider block">Scadenza</span>
                      <div class="text-xs font-semibold">${dueDateBadge}</div>
                    </div>
                  </div>

                  ${rec.location_or_notes ? `<p class="text-[11px] font-mono-code text-[#7A7568] mt-2 bg-white px-2 py-1 rounded-xs border border-[#E3DDD1] line-clamp-1">📍 ${escapeHtml(rec.location_or_notes)}</p>` : ''}
                </div>

                <!-- Footer Azioni & Stato -->
                <div class="mt-3 pt-2 border-t border-[#E3DDD1] flex items-center gap-2 flex-wrap">
                  ${statusBadge}
                  ${payBtn}
                  <div class="flex items-center gap-1.5 ml-auto">
                    ${previewBtn}
                    ${deleteBtn}
                  </div>
                </div>
              </div>
            `;
          });

          let subfoldersBar = '';
          if (subfoldersSet.size > 0) {
            const sortedSubs = Array.from(subfoldersSet).sort();
            subfoldersBar = `
              <div class="flex items-center gap-1.5 flex-wrap mt-2.5 pt-2 border-t border-[#E3DDD1] text-[11px]">
                <span class="font-bold text-[#7A7568] text-[9px] font-mono-code uppercase tracking-wider">Sottocartelle:</span>
                ${sortedSubs.map(s => `
                  <span class="inline-flex items-center gap-1 bg-white text-[#222220] px-2 py-0.5 rounded-xs border border-[#E3DDD1] font-bold text-[9px] font-mono-code">
                    <i class="fa-solid fa-folder text-[#C84B31] text-[8px]"></i>
                    <span>${escapeHtml(s)}</span>
                  </span>
                `).join('')}
              </div>
            `;
          }

          detailsEl.innerHTML = `
            <summary class="list-none flex items-center justify-between p-3.5 cursor-pointer select-none hover:bg-[#FAF8F2] transition">
              <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-xs ${iconColor} flex items-center justify-center shrink-0 text-sm border border-[#E3DDD1]">
                  <i class="fa-solid ${group.icon}"></i>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                  <h4 class="font-bold text-[#222220] text-sm font-space">${escapeHtml(catLabel)}</h4>
                  <span class="stamp-oli text-[9px]">${catDocs.length} ${catDocs.length === 1 ? 'DOC' : 'DOC'}</span>
                  ${unpaidBadge}
                </div>
              </div>
              <div class="flex items-center gap-3">
                ${totalBadge}
                <i class="fa-solid fa-chevron-down text-[#7A7568] group-open:rotate-180 transition-transform text-xs"></i>
              </div>
            </summary>
            <div class="p-4 pt-0 border-t border-[#E3DDD1]">
              ${subfoldersBar}
              <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3.5 mt-3">
                ${cardsHtml}
              </div>
            </div>
          `;

          docSection.appendChild(detailsEl);
        });

        container.appendChild(docSection);
      }

      // --- SEZIONE 2: OGGETTI PER AMBIENTE / STANZA ---
      if (items.length > 0) {
        const itemSection = document.createElement('div');
        itemSection.id = 'itemSection';
        itemSection.className = 'space-y-4 pt-2';

        itemSection.innerHTML = `
          <div class="flex items-center justify-between pb-1 border-b border-slate-200/70">
            <div class="flex items-center gap-2">
              <span class="w-2.5 h-2.5 rounded-full bg-purple-500"></span>
              <h3 class="text-xs font-bold text-slate-800 uppercase tracking-wider">Oggetti Fisici</h3>
              <span class="text-xs bg-purple-50 text-purple-700 font-bold px-2 py-0.5 rounded-full border border-purple-200/50">${items.length}</span>
            </div>
            <div class="flex items-center gap-2 text-[11px]">
              <button onclick="toggleAllAccordions('itemSection', true)" class="text-slate-400 hover:text-purple-700 font-medium transition cursor-pointer">Espandi tutti</button>
              <span class="text-slate-300">|</span>
              <button onclick="toggleAllAccordions('itemSection', false)" class="text-slate-400 hover:text-slate-700 font-medium transition cursor-pointer">Comprimi tutti</button>
            </div>
          </div>
        `;

        const roomGroups = {};
        items.forEach(item => {
          const roomName = item.room || 'Altro Spazio';
          if (!roomGroups[roomName]) {
            roomGroups[roomName] = [];
          }
          roomGroups[roomName].push(item);
        });

        const roomStyles = {
          "Studio & Scrivania": { icon: "fa-laptop", color: "bg-indigo-100 text-indigo-700" },
          "Camera da letto": { icon: "fa-bed", color: "bg-purple-100 text-purple-700" },
          "Salotto & Living": { icon: "fa-couch", color: "bg-amber-100 text-amber-700" },
          "Cucina": { icon: "fa-kitchen-set", color: "bg-emerald-100 text-emerald-700" },
          "Garage & Ripostiglio": { icon: "fa-warehouse", color: "bg-cyan-100 text-cyan-700" },
          "Altro Spazio": { icon: "fa-location-dot", color: "bg-slate-100 text-slate-700" }
        };

        const roomKeys = Object.keys(roomGroups).sort();

        roomKeys.forEach(roomName => {
          const roomItems = roomGroups[roomName];
          const style = roomStyles[roomName] || { icon: "fa-location-dot", color: "bg-slate-100 text-slate-700" };

          const detailsEl = document.createElement('details');
          detailsEl.open = (currentFilter === 'items' || currentFilter === 'oggetti') ? true : false;
          detailsEl.className = 'group dashboard-accordion bg-white border border-[#E3DDD1] rounded-xs shadow-xs transition-all overflow-hidden';

          let itemCardsHtml = '';
          roomItems.forEach(rec => {
            const escapedTitle = escapeHtml(rec.title).replace(/'/g, "\\'");
            const threadName = escapeHtml(rec.thread_name || 'Principale');
            const isGroup = (rec.thread_id || '').includes('famiglia') || (rec.thread_id || '').includes('gruppo');
            const threadIcon = isGroup ? 'fa-users text-[#3C5A48]' : 'fa-folder text-[#3C5A48]';

            let catChip = 'Oggetto';
            let catChipIcon = 'fa-box-archive';
            const lowerCat = (rec.category || '').toLowerCase();
            if (lowerCat.includes('document')) {
              catChip = 'Documento Cartaceo';
              catChipIcon = 'fa-file-lines';
            } else if (lowerCat.includes('chiav')) {
              catChip = 'Chiavi & Accessori';
              catChipIcon = 'fa-key';
            } else if (lowerCat.includes('elettron')) {
              catChip = 'Elettronica';
              catChipIcon = 'fa-plug';
            } else if (lowerCat.includes('attrezzatur') || lowerCat.includes('strument')) {
              catChip = 'Attrezzatura';
              catChipIcon = 'fa-wrench';
            }

            const deleteBtn = `
              <button onclick="confirmDashboardDelete('${rec.type}', ${rec.id}, '${escapedTitle}')" title="Elimina dal caveau" class="text-slate-400 hover:text-[#C84B31] p-1.5 rounded-xs hover:bg-[#FAECE8] transition active:scale-95 text-xs">
                <i class="fa-regular fa-trash-can"></i>
              </button>
            `;

            itemCardsHtml += `
              <div class="dashboard-card bg-[#FAF8F2] hover:bg-white border border-[#E3DDD1] border-l-3 border-[#3C5A48] rounded-xs p-3.5 flex flex-col justify-between transition-all shadow-xs">
                <div>
                  <div class="flex items-start justify-between gap-2">
                    <div class="flex items-center gap-2 min-w-0">
                      <div class="w-7 h-7 rounded-xs ${style.color} flex items-center justify-center shrink-0 text-xs border border-[#E3DDD1]">
                        <i class="fa-solid ${style.icon}"></i>
                      </div>
                      <div class="min-w-0">
                        <h4 class="font-bold text-[#222220] text-xs truncate font-space" title="${escapeHtml(rec.title)}">${escapeHtml(rec.title)}</h4>
                        <span class="stamp-oli text-[8px] mt-0.5">
                          <i class="fa-solid ${catChipIcon} text-[8px]"></i> ${catChip.toUpperCase()}
                        </span>
                      </div>
                    </div>
                    <span class="stamp-oli text-[8px] shrink-0">
                      <i class="fa-solid ${threadIcon} text-[8px]"></i>
                      <span>${threadName}</span>
                    </span>
                  </div>

                  <!-- Foto Posizione (se presente) -->
                  ${rec.file_url ? `
                    <div class="mt-2.5 relative group/img cursor-pointer overflow-hidden rounded-xs border border-[#E3DDD1] bg-white" onclick="openMediaModal('${escapeHtml(rec.file_url)}', '${escapedTitle} (Foto Posizione)', 'image')">
                      <img src="${escapeHtml(rec.file_url)}" alt="${escapedTitle}" class="w-full h-28 object-cover group-hover/img:scale-105 transition duration-200">
                      <div class="absolute inset-0 bg-black/30 opacity-0 group-hover/img:opacity-100 transition flex items-center justify-center gap-1.5 text-white text-xs font-semibold backdrop-blur-2xs">
                        <i class="fa-solid fa-magnifying-glass-plus"></i> Ingrandisci Foto
                      </div>
                      <span class="absolute bottom-1.5 right-1.5 stamp-oli stamp-solid-sage text-[8px]">
                        <i class="fa-solid fa-camera text-[8px]"></i> FOTO
                      </span>
                    </div>
                  ` : ''}

                  <!-- Posizione Dettagliata -->
                  <div class="mt-2.5 p-2 bg-white rounded-xs border border-[#E3DDD1]">
                    <div class="flex items-center gap-1.5 text-xs font-bold text-[#222220] font-space">
                      <i class="fa-solid fa-location-dot text-[#3C5A48] text-xs"></i>
                      <span>${escapeHtml(rec.detailed_location || rec.location_or_notes || 'Posizione registrata')}</span>
                    </div>
                    ${rec.location_or_notes && rec.location_or_notes !== rec.detailed_location ? `<p class="text-[11px] font-mono-code text-[#7A7568] mt-1 pl-4">${escapeHtml(rec.location_or_notes)}</p>` : ''}
                  </div>
                </div>

                <!-- Footer Azioni -->
                <div class="mt-3 pt-2 border-t border-[#E3DDD1] flex items-center justify-between">
                  ${!rec.file_url ? `
                    <button onclick="promptUploadItemPhoto(${rec.id}, '${escapedTitle}')" class="text-[10px] font-bold font-space text-[#3C5A48] hover:bg-[#3C5A48] hover:text-white bg-white px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 border border-[#3C5A48] cursor-pointer">
                      <i class="fa-solid fa-camera text-[9px]"></i> + Foto
                    </button>
                  ` : `<span class="stamp-oli text-[8px]"><i class="fa-solid fa-camera text-[8px]"></i> CON FOTO</span>`}
                  ${deleteBtn}
                </div>
              </div>
            `;
          });

          detailsEl.innerHTML = `
            <summary class="list-none flex items-center justify-between p-3.5 cursor-pointer select-none hover:bg-[#FAF8F2] transition">
              <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-xs ${style.color} flex items-center justify-center shrink-0 text-sm border border-[#E3DDD1]">
                  <i class="fa-solid ${style.icon}"></i>
                </div>
                <div class="flex items-center gap-2">
                  <h4 class="font-bold text-[#222220] text-sm font-space">${escapeHtml(roomName)}</h4>
                  <span class="stamp-oli text-[9px]">${roomItems.length} ${roomItems.length === 1 ? 'OGGETTO' : 'OGGETTI'}</span>
                </div>
              </div>
              <div class="flex items-center gap-3">
                <i class="fa-solid fa-chevron-down text-[#7A7568] group-open:rotate-180 transition-transform text-xs"></i>
              </div>
            </summary>
            <div class="p-4 pt-0 border-t border-[#E3DDD1]">
              <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3 mt-3">
                ${itemCardsHtml}
              </div>
            </div>
          `;

          itemSection.appendChild(detailsEl);
        });

        container.appendChild(itemSection);
      }
    }

    // --- Helper Espandi / Comprimi Tutti gli Accordion di Categoria ---
    function toggleAllAccordions(sectionId, openState) {
      const section = document.getElementById(sectionId) || document.getElementById('dashboardGroupedContainer');
      if (!section) return;
      const detailsList = section.querySelectorAll('details');
      detailsList.forEach(d => { d.open = openState; });
    }

    // --- Rendering Righe Tabella con Design Moderno ---
    function renderTableRows(records) {
      const tbody = document.getElementById('tableBody');
      if (!tbody) return;
      tbody.innerHTML = '';

      if (!records || records.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="7" class="py-10 text-center text-slate-400 text-xs">
              <i class="fa-solid fa-folder-open text-3xl mb-2.5 block text-slate-300"></i>
              Nessun record trovato per il filtro selezionato.
            </td>
          </tr>
        `;
        return;
      }

      records.forEach(rec => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-[#FAF8F2] transition-colors border-b border-[#E3DDD1]';

        // Icona e stile tipo elemento
        let iconClass = 'fa-file-lines';
        let iconBg = 'bg-[#FAF8F2] text-[#3C5A48] border border-[#E3DDD1]';
        if (rec.type === 'physical_item') {
          iconClass = 'fa-box-archive';
          iconBg = 'bg-[#FAF8F2] text-[#3C5A48] border border-[#E3DDD1]';
          const lowerTitle = (rec.title || '').toLowerCase();
          if (lowerTitle.includes('chiav')) {
            iconClass = 'fa-key';
          } else if (lowerTitle.includes('passaporto') || lowerTitle.includes('carta') || lowerTitle.includes('patente')) {
            iconClass = 'fa-id-card';
          }
        } else {
          const lowerTitle = (rec.title || '').toLowerCase();
          if (lowerTitle.includes('bolletta') || lowerTitle.includes('luce') || lowerTitle.includes('enel') || lowerTitle.includes('gas') || lowerTitle.includes('energia')) {
            iconClass = 'fa-bolt';
            iconBg = 'bg-[#FAECE8] text-[#C84B31] border border-[#C84B31]';
          } else if (lowerTitle.includes('f24') || lowerTitle.includes('iva') || lowerTitle.includes('tribut') || lowerTitle.includes('fisco')) {
            iconClass = 'fa-file-invoice-dollar';
            iconBg = 'bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48]';
          } else {
            iconClass = 'fa-file-invoice';
            iconBg = 'bg-[#FAF8F2] text-[#3C5A48] border border-[#E3DDD1]';
          }
        }

        // Badge Origine
        let originBadge = '';
        if (rec.type === 'physical_item') {
          originBadge = `
            <span class="stamp-oli text-[8px]">
              📱 CHAT
            </span>
          `;
        } else {
          originBadge = `
            <span class="stamp-oli text-[8px]">
              📄 ${escapeHtml(rec.source || 'ATTO').toUpperCase()}
            </span>
          `;
        }

        // Importo formattato
        let amountHtml = '<span class="text-slate-300 font-mono-code">-</span>';
        if (rec.amount != null) {
          amountHtml = `<span class="font-mono-code font-black text-xs sm:text-sm text-[#222220]">€ ${rec.amount.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
        }

        // Scadenza formattata con countdown dinamico
        const dueDateHtml = getDueDateBadge(rec);

        // Stato / Coordinate
        let statusHtml = '';
        if (rec.type === 'physical_item') {
          statusHtml = `<span class="text-[#222220] font-mono-code text-xs">📍 ${escapeHtml(rec.location_or_notes || 'Posizione registrata')}</span>`;
        } else if (rec.status === 'da_pagare') {
          const lbl = rec.amount != null ? 'DA SALDARE' : 'IN SCADENZA';
          statusHtml = `<span class="stamp-oli stamp-terracotta text-[8px]">${lbl}</span>`;
        } else if (rec.status === 'quietanzato') {
          const lbl = rec.amount != null ? 'PAGATO' : 'RINNOVATO';
          statusHtml = `<span class="stamp-oli text-emerald-800 border-emerald-700 text-[8px]">${lbl}</span>`;
        } else {
          statusHtml = `<span class="stamp-oli text-[8px]">${escapeHtml(rec.status).toUpperCase()}</span>`;
        }

        // Azioni
        let actionHtml = '<span class="text-slate-400 text-xs">-</span>';
        const escapedTitle = escapeHtml(rec.title).replace(/'/g, "\\'");
        const deleteBtn = `
          <button onclick="confirmDashboardDelete('${rec.type}', ${rec.id}, '${escapedTitle}')" title="Elimina dal caveau" class="text-slate-400 hover:text-[#C84B31] p-1.5 rounded-xs hover:bg-[#FAECE8] transition active:scale-95 text-xs">
            <i class="fa-regular fa-trash-can"></i>
          </button>
        `;

        if (rec.type === 'document') {
          let previewBtn = '';
          if (rec.file_url) {
            const escapedUrl = escapeHtml(rec.file_url);
            const escapedType = escapeHtml(rec.file_type || 'application/pdf');
            const downloadUrl = `/api/documents/${rec.id}/download`;
            const isZipRec = (rec.file_type === 'zip' || rec.doc_type === 'archivio_zip' || (rec.title && rec.title.toLowerCase().endsWith('.zip')));
            const unzipBtn = isZipRec ? `
              <button onclick="unzipDocumentById(${rec.id})" title="Decomprimi tutti i file nel caveau" class="bg-amber-600 hover:bg-amber-700 text-white text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer font-space">
                <i class="fa-solid fa-file-zipper text-xs"></i> Estrai
              </button>
            ` : '';
            const driveBtn = rec.drive_web_url ? `
              <a href="${rec.drive_web_url}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 stamp-oli text-[8px] hover:bg-[#3C5A48] hover:text-white transition" title="Apri su Google Drive">
                <i class="fa-brands fa-google-drive text-[9px]"></i> <span>Drive ↗</span>
              </a>
            ` : '';
            previewBtn = `
              ${driveBtn}
              <button onclick="openMediaModal('${escapedUrl}', '${escapedTitle}', '${escapedType}', '${downloadUrl}', ${rec.id})" title="Anteprima documento" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer font-space">
                <i class="fa-regular fa-eye text-xs"></i> Vedi
              </button>
              ${unzipBtn}
              <button onclick="downloadDashboardDoc(${rec.id})" title="Scarica documento" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer font-space">
                <i class="fa-solid fa-download text-xs"></i>
              </button>
              <button onclick="openFileInExplorer(${rec.id})" title="Apri file in Esplora Risorse del PC" class="bg-white hover:bg-[#FAF8F2] text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 cursor-pointer font-space">
                <i class="fa-regular fa-folder-open text-xs text-[#C84B31]"></i>
              </button>
            `;
          }
          let payBtn = '';
          if (rec.status === 'da_pagare') {
            const lbl = rec.amount != null ? 'SALDA' : 'RINNOVA';
            const titleAction = rec.amount != null ? 'Segna come pagato' : 'Segna come rinnovato o archiviato';
            payBtn = `<button onclick="markAsPaid(${rec.id})" class="stamp-oli stamp-solid-terracotta text-[8px] hover:opacity-90 transition active:scale-95 cursor-pointer" title="${titleAction}">${lbl}</button>`;
          } else if (rec.status === 'quietanzato') {
            const lbl = rec.amount != null ? 'SALDATO' : 'RINNOVATO';
            payBtn = `<span class="stamp-oli text-emerald-800 border-emerald-700 text-[8px]">${lbl}</span>`;
          }
          actionHtml = `
            <div class="flex items-center justify-end gap-1.5 flex-wrap">
              ${previewBtn}
              ${payBtn}
              ${deleteBtn}
            </div>
          `;
        } else if (rec.type === 'physical_item') {
          let photoBtn = '';
          if (rec.file_url) {
            const escapedUrl = escapeHtml(rec.file_url);
            photoBtn = `
              <button onclick="openMediaModal('${escapedUrl}', '${escapedTitle} (Foto Posizione)', 'image')" title="Vedi foto posizione" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space">
                <i class="fa-solid fa-camera text-xs"></i> Vedi Foto
              </button>
            `;
          } else {
            photoBtn = `
              <button onclick="promptUploadItemPhoto(${rec.id}, '${escapedTitle}')" title="Scatta o aggiungi foto" class="bg-white hover:bg-[#FAF8F2] text-[#7A7568] border border-[#E3DDD1] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space cursor-pointer">
                <i class="fa-solid fa-camera text-[#3C5A48] text-xs"></i> + Foto
              </button>
            `;
          }
          actionHtml = `
            <div class="flex items-center justify-end gap-1.5">
              ${photoBtn}
              ${deleteBtn}
            </div>
          `;
        }

        // Badge Spazio / Gruppo
        const threadName = escapeHtml(rec.thread_name || 'Principale');
        const isGroup = (rec.thread_id || '').includes('famiglia') || (rec.thread_id || '').includes('gruppo');
        const threadIcon = isGroup ? 'fa-users text-[#3C5A48]' : 'fa-folder text-[#3C5A48]';
        const threadBadge = `
          <span class="stamp-oli text-[8px]">
            <i class="fa-solid ${threadIcon} text-[8px] mr-1"></i>
            <span>${threadName}</span>
          </span>
        `;

        tr.innerHTML = `
          <td class="py-3 px-4">
            <div class="flex items-center gap-2.5">
              <div class="w-7 h-7 rounded-xs ${iconBg} flex items-center justify-center shrink-0">
                <i class="fa-solid ${iconClass} text-xs"></i>
              </div>
              <div>
                <p class="font-bold text-[#222220] font-space text-xs">${escapeHtml(rec.title)}</p>
                <p class="text-[10px] text-[#7A7568] font-mono-code">${escapeHtml(rec.location_or_notes || '')}</p>
              </div>
            </div>
          </td>
          <td class="py-3 px-3">${threadBadge}</td>
          <td class="py-3 px-3">${originBadge}</td>
          <td class="py-3 px-3 text-right">${amountHtml}</td>
          <td class="py-3 px-3">${dueDateHtml}</td>
          <td class="py-3 px-3">${statusHtml}</td>
          <td class="py-3 px-4 text-right">${actionHtml}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    // --- Filtri Tabella ---
    function filterTable(filter) {
      currentFilter = filter;
      const btnA = document.getElementById('fAll');
      const btnScad = document.getElementById('fScadenzario');
      const btnAtti = document.getElementById('fAtti');
      const btnD = document.getElementById('fDeadlines');
      const btnQ = document.getElementById('fQuietanzati');
      const btnI = document.getElementById('fItems');
      
      const baseBtnClass = 'px-2.5 py-1 rounded-xs font-space font-bold transition cursor-pointer text-[10px]';
      const inactiveClass = `${baseBtnClass} text-[#7A7568] hover:text-[#222220]`;
      const activeClass = `${baseBtnClass} bg-[#3C5A48] text-white`;

      [btnA, btnScad, btnAtti, btnD, btnQ, btnI].forEach(b => {
        if (b) {
          b.className = inactiveClass;
          if (b === btnScad || b === btnD || b === btnQ) b.classList.add('flex', 'items-center', 'gap-1');
        }
      });

      if (filter === 'all' && btnA) btnA.className = activeClass;
      if ((filter === 'scadenzario' || filter === 'scadenziario' || filter === 'calendar') && btnScad) {
        btnScad.className = `${activeClass} flex items-center gap-1`;
      }
      if ((filter === 'documents' || filter === 'atti' || filter === 'atto') && btnAtti) {
        btnAtti.className = activeClass;
      }
      if ((filter === 'deadlines' || filter === 'da_pagare') && btnD) {
        btnD.className = `${activeClass} flex items-center gap-1`;
      }
      if ((filter === 'quietanzati' || filter === 'quietanzato') && btnQ) {
        btnQ.className = `${activeClass} flex items-center gap-1`;
      }
      if ((filter === 'items' || filter === 'oggetti') && btnI) btnI.className = activeClass;

      // Filtro immediato sincrono in memoria dalla cache: elimina ogni ritardo o schermata bianca
      if (allDashboardRecordsCache && allDashboardRecordsCache.length > 0) {
        if (filter === 'all') {
          currentRecords = [...allDashboardRecordsCache];
        } else if (filter === 'items' || filter === 'oggetti') {
          currentRecords = allDashboardRecordsCache.filter(r => r.type === 'physical_item');
        } else if (filter === 'documents' || filter === 'atti' || filter === 'atto') {
          currentRecords = allDashboardRecordsCache.filter(r => r.type === 'document');
        } else if (filter === 'deadlines' || filter === 'da_pagare') {
          currentRecords = allDashboardRecordsCache.filter(r => r.type === 'document' && r.status === 'da_pagare');
        } else if (filter === 'quietanzati' || filter === 'quietanzato') {
          currentRecords = allDashboardRecordsCache.filter(r => r.status === 'quietanzato');
        } else if (filter === 'scadenzario' || filter === 'scadenziario' || filter === 'calendar') {
          currentRecords = allDashboardRecordsCache.filter(r => r.type === 'document' && r.due_date);
          currentRecords.sort((a, b) => (a.due_date || '9999').localeCompare(b.due_date || '9999'));
        }
        renderDashboardView();
      }

      loadDashboard(filter);
    }

    // --- Azione Segna Pagato: PATCH /api/documents/{id}/status ---
    async function markAsPaid(documentId) {
      try {
        const res = await fetch(`/api/documents/${documentId}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'quietanzato' })
        });
        if (!res.ok) throw new Error("Impossibile aggiornare lo stato");
        await loadDashboard(currentFilter);
        await checkDeadlineAlerts(currentThreadId);
      } catch (err) {
        console.error("Errore markAsPaid:", err);
        alert("Errore nell'aggiornamento dello stato del documento.");
      }
    }

    // --- Sistema Avvisi Automatici Scadenze & Bollette ---
    let deadlineAlertsCache = null;
    let deadlineBannerDismissed = false;

    async function checkDeadlineAlerts(threadId = null) {
      try {
        const targetThread = threadId || currentThreadId || 'all';
        const url = `/api/deadlines/alerts?thread_id=${encodeURIComponent(targetThread)}&days_ahead=7`;
        const res = await fetch(url, { headers: authHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        deadlineAlertsCache = data;
        updateDeadlineAlertsUI(data);
      } catch (err) {
        console.warn("Impossibile recuperare avvisi scadenze:", err);
      }
    }

    function updateDeadlineAlertsUI(data) {
      const banner = document.getElementById('deadlinesBanner');
      const bannerText = document.getElementById('deadlinesBannerText');
      const bannerSubtext = document.getElementById('deadlinesBannerSubtext');
      const bannerIcon = document.getElementById('deadlinesBannerIcon');
      const bannerIconBox = document.getElementById('deadlinesBannerIconBox');
      const bellBadge = document.getElementById('deadlinesBellBadge');

      if (!data) return;

      // 1. Aggiorna Campanella Notifiche nell'Header
      if (bellBadge) {
        if (data.has_alerts && data.total_alerts > 0) {
          bellBadge.textContent = data.total_alerts > 9 ? '9+' : data.total_alerts;
          bellBadge.classList.remove('hidden');
          if (data.overdue_count > 0) {
            bellBadge.className = 'absolute -top-0.5 -right-0.5 min-w-[17px] h-[17px] bg-red-600 text-white text-[10px] font-bold rounded-full px-1 flex items-center justify-center border-2 border-[#075E54] shadow-xs animate-pulse';
          } else {
            bellBadge.className = 'absolute -top-0.5 -right-0.5 min-w-[17px] h-[17px] bg-amber-500 text-white text-[10px] font-bold rounded-full px-1 flex items-center justify-center border-2 border-[#075E54] shadow-xs';
          }
        } else {
          bellBadge.classList.add('hidden');
        }
      }

      // 2. Aggiorna Banner Notifica Scadenze
      if (banner && bannerText && bannerSubtext) {
        if (data.has_alerts && !deadlineBannerDismissed) {
          banner.classList.remove('hidden');

          if (data.overdue_count > 0) {
            // Allerta per scadenze già passate
            if (bannerIcon) bannerIcon.className = 'fa-solid fa-triangle-exclamation text-red-700';
            if (bannerIconBox) bannerIconBox.className = 'w-7 h-7 rounded-lg bg-red-100 text-red-700 flex items-center justify-center shrink-0 text-xs';
            bannerText.innerHTML = `⚠️ <strong class="text-red-700 font-bold">${data.overdue_count} scadenza/e passata/e</strong> richiedono attenzione immediata!`;
          } else {
            // Avviso per scadenze imminenti entro 7 giorni
            if (bannerIcon) bannerIcon.className = 'fa-solid fa-clock text-amber-800';
            if (bannerIconBox) bannerIconBox.className = 'w-7 h-7 rounded-lg bg-amber-200 text-amber-800 flex items-center justify-center shrink-0 text-xs';
            bannerText.innerHTML = `⏰ Hai <strong>${data.due_soon_count} pagamento/i in scadenza</strong> nei prossimi 7 giorni.`;
          }

          const amtStr = data.total_amount > 0 ? `Totale da saldare: <strong>${data.total_amount.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €</strong>` : 'Verifica i dettagli nel caveau';
          bannerSubtext.innerHTML = amtStr;
        } else {
          banner.classList.add('hidden');
        }
      }
    }

    function dismissDeadlinesBanner() {
      deadlineBannerDismissed = true;
      const banner = document.getElementById('deadlinesBanner');
      if (banner) banner.classList.add('hidden');
    }

    function askAssistantAboutDeadlines() {
      if (!input) return;
      input.value = "Cosa ho in scadenza o scaduto da pagare?";
      micBtn.classList.add('hidden');
      sendBtn.classList.remove('hidden');
      sendBtn.classList.add('flex');
      handleSend(new Event('submit'));
    }

    // --- Esportazione Report CSV ---
    function exportCSV() {
      if (!currentRecords || currentRecords.length === 0) {
        alert("Nessun record da esportare.");
        return;
      }
      const headers = ["ID", "Tipo", "Titolo", "Origine", "Importo", "Scadenza", "Stato", "Dettagli"];
      const rows = currentRecords.map(r => [
        r.id,
        r.type,
        `"${(r.title || '').replace(/"/g, '""')}"`,
        `"${(r.source || '').replace(/"/g, '""')}"`,
        r.amount != null ? r.amount : '',
        r.due_date || '',
        r.status || '',
        `"${(r.location_or_notes || '').replace(/"/g, '""')}"`
      ]);
      const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");
      const encodedUri = encodeURI(csvContent);
      const link = document.createElement("a");
      link.setAttribute("href", encodedUri);
      link.setAttribute("download", `dovelhomesso_report_${new Date().toISOString().slice(0, 10)}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }

