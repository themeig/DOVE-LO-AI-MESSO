// =========================================================================
// MODULO 3: Gestione Canali Chat (Threads), Gruppi, Modelli AI & Impostazioni
// =========================================================================
    // --- Gestione Threads, Gruppi e Aree Tematiche ---
    async function loadThreads() {
      try {
        const res = await fetch('/api/threads', { headers: authHeaders() });
        if (!res.ok) throw new Error("Errore recupero thread");
        const data = await res.json();
        threadsCache = data.threads || [];
        renderThreadsList();
        updateDashboardThreadFilter();
        const found = threadsCache.find(t => t.id === currentThreadId);
        if (found) {
          updateActiveThreadHeader(found);
        } else if (threadsCache.length > 0) {
          switchThread(threadsCache[0].id, false);
        }
      } catch (err) {
        console.error("Errore loadThreads:", err);
      }
    }

    function sanitizeAssistantText(text) {
      if (!text) return '';
      let cleaned = String(text);
      // Rimuovi tag residui XML di tool o thinking
      cleaned = cleaned.replace(/<(?:thought|think|tool_call|tool_response|\w+_response)[^>]*>[\s\S]*?<\/(?:thought|think|tool_call|tool_response|\w+_response)>/gi, '');
      cleaned = cleaned.replace(/<\/?(?:thought|think|tool_call|tool_response|function|parameter|arg_key|arg_value|\w+_response)[^>]*>/gi, '');
      // Rimuovi blocchi JSON di tool in testa o residui di chiamate tool
      cleaned = cleaned.replace(/^\s*\{"\w*response"\s*:\s*\{[\s\S]*?\}\s*\}\s*/i, '');
      cleaned = cleaned.replace(/^\s*\{"(?:confirmation|target_type|targettype|target_id|targetid|deletevaultrecord|delete_vault_record)"\s*:[\s\S]*?\}\s*\}?\s*/i, '');
      if (/^\s*\{[\s\S]*\}\s*$/.test(cleaned) && (cleaned.includes('response') || cleaned.includes('confirmation') || cleaned.includes('targetid'))) {
        cleaned = '';
      }
      return cleaned.trim();
    }

    function cleanSidebarPreview(text) {
      if (!text) return 'Nessun messaggio';
      let clean = sanitizeAssistantText(String(text))
        .replace(/<[^>]*>/g, '') // rimuovi tag html
        .replace(/[*_~`#>•-]/g, '') // rimuovi caratteri markdown
        .replace(/\r?\n|\r/g, ' ') // sostituisci a capo con spazio singolo
        .replace(/\s+/g, ' ') // collassa spazi multipli
        .trim();
      return clean || 'Nessun messaggio';
    }

    function getTime() {
      const d = new Date();
      return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }

    function formatSidebarTime(t) {
      if (!t) return '';
      const iso = t.last_message_iso || t.created_at;
      if (iso) {
        const d = new Date(iso);
        if (!isNaN(d.getTime())) {
          const now = new Date();
          const targetDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
          const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
          const diffTime = today.getTime() - targetDay.getTime();
          const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));
          if (diffDays <= 0) {
            return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
          } else if (diffDays === 1) {
            return 'Ieri';
          } else if (diffDays > 1 && diffDays < 7) {
            const day = d.toLocaleDateString('it-IT', { weekday: 'short' });
            return day.charAt(0).toUpperCase() + day.slice(1);
          } else {
            return d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' });
          }
        }
      }
      return t.last_message_time || '';
    }

    function renderThreadsList() {
      const container = document.getElementById('threadsContainer');
      const searchVal = (document.getElementById('threadsSearchInput')?.value || '').toLowerCase().trim();
      if (!container) return;

      let filtered = threadsCache;
      if (activeThreadFilter === 'group') {
        filtered = filtered.filter(t => t.thread_type === 'group');
      } else if (activeThreadFilter === 'thematic') {
        filtered = filtered.filter(t => t.thread_type === 'thematic');
      }

      if (searchVal) {
        filtered = filtered.filter(t => 
          (t.name || '').toLowerCase().includes(searchVal) ||
          (t.description || '').toLowerCase().includes(searchVal) ||
          (t.members || []).some(m => m.toLowerCase().includes(searchVal))
        );
      }

      if (filtered.length === 0) {
        container.innerHTML = `
          <div class="p-8 text-center text-slate-400 text-xs">
            <i class="fa-solid fa-comments text-2xl mb-2 text-slate-300"></i>
            <p>Nessun gruppo o area trovata.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = filtered.map(t => {
        const isActive = t.id === currentThreadId;
        const activeClass = isActive ? 'active-thread-item bg-[#FAF8F2] border-l-4 border-[#3C5A48]' : 'hover:bg-[#FAF8F2]';
        const isGroup = t.thread_type === 'group';
        const badgeTag = isGroup 
          ? `<span class="stamp-oli text-[8px]">GRUPPO</span>`
          : `<span class="stamp-oli text-[8px]">AREA</span>`;

        const activeTask = activeThreadTasks[t.id];
        const rawLastMsg = t.last_message || t.description || 'Nessun messaggio';
        const cleanPreview = cleanSidebarPreview(rawLastMsg);
        const timeStr = formatSidebarTime(t);

        // Badge rotella che gira sull'avatar del thread quando l'assistente sta lavorando
        const avatarSpinner = activeTask ? `
          <span class="absolute -bottom-1 -right-1 w-5 h-5 bg-white rounded-full flex items-center justify-center shadow-xs ring-1 ring-[#C84B31] z-10" title="${escapeHtml(activeTask.statusText || 'In elaborazione...')}">
            <i class="fa-solid fa-circle-notch text-[#C84B31] text-[11px] animate-spin"></i>
          </span>
        ` : '';

        let previewHtml = '';
        const rightPillHtml = `<span class="text-[10px] text-[#7A7568] shrink-0 font-mono-code">${escapeHtml(timeStr)}</span>`;

        if (activeTask) {
          const pctStr = (activeTask.progressPercent !== null && activeTask.progressPercent !== undefined && !isNaN(activeTask.progressPercent))
            ? ` (${activeTask.progressPercent}%)`
            : '';
          const statusDesc = activeTask.statusText || 'Elaborazione in corso...';
          previewHtml = `
            <p class="text-[11px] text-[#3C5A48] font-semibold truncate leading-tight flex-1 flex items-center gap-1.5 overflow-hidden whitespace-nowrap block" title="${escapeHtml(statusDesc + pctStr)}">
              <i class="fa-solid fa-circle-notch text-[10px] text-[#C84B31] animate-spin shrink-0"></i>
              <span class="truncate">${escapeHtml(statusDesc + pctStr)}</span>
            </p>
          `;
        } else {
          previewHtml = `
            <p class="text-[11px] text-[#7A7568] truncate leading-tight flex-1 overflow-hidden whitespace-nowrap block font-mono-code" title="${escapeHtml(cleanPreview)}">${escapeHtml(cleanPreview)}</p>
          `;
        }

        return `
          <div onclick="switchThread('${t.id}')" class="h-[72px] min-h-[72px] max-h-[72px] flex items-center gap-3 px-3.5 py-2 cursor-pointer transition select-none ${activeClass} border-b border-[#E3DDD1] overflow-hidden box-border">
            <div class="relative shrink-0">
              <div class="thread-avatar w-11 h-11 rounded-xs flex items-center justify-center text-white text-lg font-bold border border-[#E3DDD1] shadow-2xs ${t.color || 'bg-[#3C5A48]'}">
                <i class="fa-solid ${t.icon || 'fa-compass'}"></i>
              </div>
              ${avatarSpinner}
            </div>
            <div class="flex-1 min-w-0 overflow-hidden">
              <div class="flex items-center justify-between gap-1 mb-1">
                <h4 class="font-bold text-xs text-[#222220] font-space truncate">${escapeHtml(t.name)}</h4>
                ${rightPillHtml}
              </div>
              <div class="flex items-center justify-between gap-2 overflow-hidden">
                ${previewHtml}
                <div class="shrink-0">${badgeTag}</div>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    function setThreadFilter(filter) {
      activeThreadFilter = filter;
      const pAll = document.getElementById('pillAll');
      const pGroup = document.getElementById('pillGroup');
      const pThematic = document.getElementById('pillThematic');
      
      const isOli = getActiveTheme() === 'olivetti';
      const activeStyle = isOli 
        ? 'px-2.5 py-1 text-[10px] rounded-xs font-space font-bold transition bg-[#3C5A48] text-white cursor-pointer'
        : 'px-2.5 py-1 text-xs rounded-full font-medium transition bg-[#E7FFDB] text-[#075E54] border border-[#25D366]/30 cursor-pointer';
      const inactiveStyle = isOli
        ? 'px-2.5 py-1 text-[10px] rounded-xs font-space font-bold transition bg-white border border-[#E3DDD1] text-[#7A7568] hover:text-[#222220] cursor-pointer'
        : 'px-2.5 py-1 text-xs rounded-full font-medium transition bg-slate-100 hover:bg-slate-200 text-slate-600 cursor-pointer';

      if (pAll) pAll.className = filter === 'all' ? activeStyle : inactiveStyle;
      if (pGroup) pGroup.className = filter === 'group' ? activeStyle : inactiveStyle;
      if (pThematic) pThematic.className = filter === 'thematic' ? activeStyle : inactiveStyle;

      renderThreadsList();
    }

    let liveGroupChatWs = null;

    function connectGroupChatWebSocket(groupId) {
      if (liveGroupChatWs) {
        try { liveGroupChatWs.close(); } catch(e){}
        liveGroupChatWs = null;
      }
      if (!groupId || groupId === 'general') return;

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/api/groups/${encodeURIComponent(groupId)}/ws`;

      try {
        const ws = new WebSocket(wsUrl);
        liveGroupChatWs = ws;

        ws.onopen = function() {
          console.log(`[WebSocket] Connesso in tempo reale alla chat di gruppo: ${groupId}`);
        };

        ws.onmessage = async function(event) {
          try {
            const data = JSON.parse(event.data);
            console.log("[WebSocket] Evento gruppo ricevuto:", data);

            // Se l'utente è attualmente nella schermata di questo gruppo, ricarica subito i messaggi
            if (currentThreadId === groupId) {
              await loadThreadMessages(groupId);
              scrollToBottom(true);

              if (data.title && typeof showToast === 'function') {
                showToast(`🔔 ${data.title}`, "info", 3500);
              }
              if (typeof loadDashboard === 'function') {
                loadDashboard('all');
              }
            } else {
              // Se l'utente è in un'altra chat o schermata
              if (typeof showToast === 'function') {
                showToast(`🔔 [Gruppo] ${data.title || 'Nuovo atto registrato'}`, "info", 4000);
              }
              loadThreads();
            }
          } catch(err) {
            console.warn("Errore parsing messaggio WebSocket:", err);
          }
        };

        ws.onerror = function(err) {
          console.warn("[WebSocket] Errore connessione live chat:", err);
        };

        ws.onclose = function() {
          if (liveGroupChatWs === ws) liveGroupChatWs = null;
        };
      } catch(e) {
        console.warn("[WebSocket] Impossibile avviare connessione live:", e);
      }
    }
    window.connectGroupChatWebSocket = connectGroupChatWebSocket;

    async function switchThread(threadId, fetchMessages = true) {
      currentThreadId = threadId;
      window.currentThreadId = threadId;
      if (typeof cancelQuoteReply === 'function') cancelQuoteReply();
      deadlineBannerDismissed = false;
      const thread = threadsCache.find(t => t.id === threadId);
      if (thread) {
        updateActiveThreadHeader(thread);
        if (thread.thread_type === 'group') {
          connectGroupChatWebSocket(thread.id);
        } else {
          if (liveGroupChatWs) {
            try { liveGroupChatWs.close(); } catch(e){}
            liveGroupChatWs = null;
          }
        }
      } else {
        if (liveGroupChatWs) {
          try { liveGroupChatWs.close(); } catch(e){}
          liveGroupChatWs = null;
        }
      }
      renderThreadsList();
      showConversation();
      checkDeadlineAlerts(threadId);

      if (fetchMessages) {
        await loadThreadMessages(threadId);
      }
      scrollToBottom(false);
    }

    function updateActiveThreadHeader(thread) {
      const titleEl = document.getElementById('activeThreadTitle');
      const subEl = document.getElementById('activeThreadSubtitle');
      const iconEl = document.getElementById('activeThreadIcon');
      const avatarEl = document.getElementById('activeThreadAvatar');
      const delBtn = document.getElementById('deleteThreadBtn');
      const groupMembersBtn = document.getElementById('headerGroupMembersBtn');
      const groupMembersBadge = document.getElementById('headerGroupMembersBadge');

      if (titleEl) titleEl.textContent = thread.name;
      if (iconEl) iconEl.className = `fa-solid ${thread.icon || 'fa-compass'}`;
      if (avatarEl) {
        avatarEl.className = `w-8 h-8 rounded-xs flex items-center justify-center text-white text-xs font-bold border border-[#E3DDD1] shadow-2xs shrink-0 ${thread.color || 'bg-[#3C5A48]'}`;
      }

      if (thread.thread_type === 'group') {
        if (groupMembersBtn) groupMembersBtn.classList.remove('hidden');
        const mCount = thread.members ? thread.members.length : 1;
        if (groupMembersBadge) groupMembersBadge.textContent = String(mCount);

        const mList = thread.members && thread.members.length > 0 ? thread.members.join(', ') : 'Io';
        if (subEl) {
          subEl.innerHTML = `<span class="cursor-pointer hover:underline text-[#3C5A48] font-bold inline-flex items-center gap-1" onclick="openGroupMembersModal('${thread.id}')" title="Visualizza i Partecipanti"><i class="fa-solid fa-users text-[9px]"></i> <span id="headerSubMembersCount">${mCount} Partecipanti</span></span> • <span id="headerSubMembersList">${escapeHtml(mList)}</span>`;
        }

        // Recupera in background la lista reale dei partecipanti per aggiornare i nomi
        fetch(`/api/groups/${thread.id}/members`, { headers: authHeaders() })
          .then(r => r.ok ? r.json() : [])
          .then(members => {
            if (Array.isArray(members) && members.length > 0) {
              if (groupMembersBadge) groupMembersBadge.textContent = String(members.length);
              const subCount = document.getElementById('headerSubMembersCount');
              const subList = document.getElementById('headerSubMembersList');
              if (subCount) subCount.textContent = `${members.length} Partecipanti`;
              if (subList) subList.textContent = members.map(m => m.full_name || m.email).join(', ');
            }
          })
          .catch(() => {});
      } else {
        if (groupMembersBtn) groupMembersBtn.classList.add('hidden');
        if (subEl) {
          subEl.textContent = `${thread.description || 'Area tematica'} • ${thread.message_count || 0} messaggi`;
        }
      }

      if (delBtn) {
        if (thread.id === 'general') {
          delBtn.classList.add('hidden');
        } else {
          delBtn.classList.remove('hidden');
        }
      }
    }

    // Estrae e normalizza la data di un messaggio come oggetto Date valido nel fuso orario locale
    function parseMessageDate(m) {
      if (!m) return new Date();
      if (m.created_at) {
        const d = new Date(m.created_at);
        if (!isNaN(d.getTime())) return d;
      }
      if (m.date) {
        const d = new Date(m.date + 'T00:00:00');
        if (!isNaN(d.getTime())) return d;
      }
      if (m.timestamp && typeof m.timestamp === 'string' && m.timestamp.length > 5) {
        const d = new Date(m.timestamp);
        if (!isNaN(d.getTime())) return d;
      }
      return new Date();
    }

    // Formatta l'orario di invio reale del messaggio (HH:MM) nel fuso orario locale del client
    function formatMessageTime(m) {
      if (!m) return getTime();
      if (typeof m === 'string') {
        const trimmed = m.trim();
        if (/^\d{1,2}:\d{2}$/.test(trimmed)) return trimmed.padStart(5, '0');
        const d = new Date(trimmed);
        if (!isNaN(d.getTime())) {
          return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        }
        return trimmed;
      }
      if (m.created_at) {
        const d = new Date(m.created_at);
        if (!isNaN(d.getTime())) {
          return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        }
      }
      if (m.timestamp && typeof m.timestamp === 'string') {
        const trimmed = m.timestamp.trim();
        if (/^\d{1,2}:\d{2}$/.test(trimmed)) return trimmed.padStart(5, '0');
        const d = new Date(trimmed);
        if (!isNaN(d.getTime())) {
          return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        }
      }
      return getTime();
    }

    // Formatta l'etichetta del divisore di data nello stile WhatsApp (OGGI, IERI, giorno della settimana o data completa)
    function formatWhatsAppDateLabel(dateObj) {
      if (!dateObj || isNaN(dateObj.getTime())) return 'OGGI';
      const now = new Date();
      const targetDay = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate());
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const diffTime = today.getTime() - targetDay.getTime();
      const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

      if (diffDays <= 0) {
        return 'OGGI';
      } else if (diffDays === 1) {
        return 'IERI';
      } else if (diffDays > 1 && diffDays < 7) {
        const dayName = targetDay.toLocaleDateString('it-IT', { weekday: 'long' });
        return dayName.toUpperCase();
      } else {
        return targetDay.toLocaleDateString('it-IT', { day: 'numeric', month: 'long', year: 'numeric' }).toUpperCase();
      }
    }

    // Inserisce il separatore di data stile WhatsApp nel flusso della chat (evita duplicati consecutivi)
    function appendDateDivider(dateObj, dateKey = null) {
      if (!chatFeed) return;
      const d = dateObj || new Date();
      const key = dateKey || `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      
      if (chatFeed.querySelector(`[data-chat-date="${key}"]`)) return;

      const label = formatWhatsAppDateLabel(d);
      const divider = document.createElement('div');
      divider.className = 'chat-date-divider-wrapper flex justify-center my-3 select-none';
      divider.setAttribute('data-chat-date', key);

      const isOli = getActiveTheme() === 'olivetti';
      if (isOli) {
        divider.innerHTML = `
          <span class="chat-date-divider stamp-oli text-[9px] font-mono-code font-bold tracking-wider px-3 py-1 bg-[#FAF8F2] border border-[#D8D2C4] text-[#7A7568] shadow-2xs rounded-xs flex items-center gap-1.5">
            <i class="fa-regular fa-calendar text-[9px] opacity-75"></i>
            <span>${escapeHtml(label)}</span>
          </span>
        `;
      } else {
        divider.innerHTML = `
          <span class="chat-date-divider px-3 py-1 bg-white border border-slate-200/80 rounded-lg shadow-2xs text-[11px] font-medium text-[#54656f] flex items-center gap-1.5">
            <i class="fa-regular fa-calendar text-[10px] text-slate-400"></i>
            <span>${escapeHtml(label)}</span>
          </span>
        `;
      }

      chatFeed.appendChild(divider);
    }

    // Assicura che prima di un nuovo messaggio di oggi sia visibile il badge "OGGI"
    function ensureTodayDateDivider() {
      if (!chatFeed) return;
      const today = new Date();
      const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
      if (!chatFeed.querySelector(`[data-chat-date="${todayKey}"]`)) {
        appendDateDivider(today, todayKey);
      }
    }

    async function loadThreadMessages(threadId) {
      chatFeed.innerHTML = `
        <div class="flex justify-center my-4">
          <span class="text-xs text-slate-400 bg-white/80 px-3 py-1 rounded-xs shadow-2xs font-mono-code">
            <i class="fa-solid fa-circle-notch animate-spin mr-1"></i> Caricamento messaggi...
          </span>
        </div>
      `;
      try {
        const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/messages`);
        if (!res.ok) throw new Error("Errore recupero messaggi");
        const data = await res.json();
        if (threadId !== currentThreadId) return; // Se l'utente ha cambiato chat nel frattempo, non sovrascrivere
        const msgs = data.messages || [];

        chatFeed.innerHTML = '';

        if (msgs.length === 0) {
          const today = new Date();
          const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
          appendDateDivider(today, todayKey);
        }

        let lastDateKey = null;

        for (const m of msgs) {
          const mDate = parseMessageDate(m);
          const dateKey = `${mDate.getFullYear()}-${String(mDate.getMonth() + 1).padStart(2, '0')}-${String(mDate.getDate()).padStart(2, '0')}`;
          
          if (dateKey !== lastDateKey) {
            appendDateDivider(mDate, dateKey);
            lastDateKey = dateKey;
          }

          const timeStr = formatMessageTime(m);

          if (m.sender === 'user') {
            const quoted = m.metadata && m.metadata.quoted_message ? m.metadata.quoted_message : null;
            if (m.message_type === 'audio' && m.metadata && m.metadata.audio_url) {
              const trText = m.metadata.transcription || (m.content && m.content.startsWith('🎤 ') ? m.content.slice(2).trim() : null);
              appendUserAudioBubble(m.metadata.audio_url, m.metadata.duration || 0, quoted, trText, timeStr);
            } else if (m.message_type === 'document' || (m.metadata && (m.metadata.file_url || m.metadata.document_id || m.metadata.documents)) || (m.content && m.content.startsWith('Caricato file:'))) {
              const firstDoc = (m.metadata && m.metadata.documents && m.metadata.documents[0]) || null;
              const fileName = (m.metadata && m.metadata.file_name) || (firstDoc && firstDoc.title) || (m.content ? m.content.replace(/^Caricato file:\s*/i, '').trim() : 'Documento');
              const fileUrl = (m.metadata && m.metadata.file_url) || (firstDoc && firstDoc.file_url) || (m.metadata && m.metadata.document_id ? `/uploads/doc_${m.metadata.document_id}` : null);
              const downloadUrl = (m.metadata && m.metadata.download_url) || (firstDoc && firstDoc.download_url) || fileUrl;
              const fileSize = (m.metadata && m.metadata.file_size) || 0;
              const fType = ((m.metadata && m.metadata.file_type) || (firstDoc && firstDoc.file_type) || '').toLowerCase();
              const isImg = fType.startsWith('image') || /\.(jpe?g|png|webp|gif|bmp)$/i.test(fileName) || /\.(jpe?g|png|webp|gif|bmp)$/i.test(fileUrl || '');
              const isPdf = fType.includes('pdf') || /\.pdf$/i.test(fileName) || /\.pdf$/i.test(fileUrl || '');
              const docId = (firstDoc && (firstDoc.id || firstDoc.document_id)) || (m.metadata ? m.metadata.document_id : null);
              appendUserFileBubble(fileName, fileSize, fileUrl, isImg, isPdf, downloadUrl, docId, timeStr);
            } else {
              appendUserBubble(m.content, quoted, timeStr);
            }
          } else {
            let docs = m.metadata && m.metadata.documents ? m.metadata.documents : null;
            if (!docs && m.metadata && m.metadata.document_id) {
              docs = [{
                id: m.metadata.document_id,
                document_id: m.metadata.document_id,
                title: (m.content && m.content.match(/\*\*(.*?)\*\*/)?.[1]) || 'Documento',
                file_url: `/api/documents/${m.metadata.document_id}/file`,
                download_url: `/api/documents/${m.metadata.document_id}/download`,
                file_type: 'application/pdf'
              }];
            }
            const conf = m.metadata && m.metadata.confirmation ? m.metadata.confirmation : null;
            const itemPhoto = m.metadata && m.metadata.item_photo ? m.metadata.item_photo : null;
            const storeItem = m.metadata && m.metadata.store_item ? m.metadata.store_item : null;
            const proposal = (m.metadata && m.metadata.proposal) || (m.metadata && m.metadata.action === 'SENSITIVE_FILE_PROPOSAL' ? m.metadata.proposal : null);
            const routedModel = (m.metadata && m.metadata.routed_model) || null;
            appendAssistantBubble(m.content, docs, conf, itemPhoto, storeItem, proposal, routedModel, timeStr);
          }
        }

        // All'apertura del thread, scorri sempre immediatamente fino all'ultimo messaggio
        scrollToBottom(false);
        requestAnimationFrame(() => {
          scrollToBottom(false);
          setTimeout(() => scrollToBottom(false), 50);
          setTimeout(() => scrollToBottom(false), 180);
          setTimeout(() => scrollToBottom(false), 350);
        });

        // Se ci sono immagini che devono ancora terminare il rendering, mantieni la vista agganciata in fondo al completamento
        const feedImgs = chatFeed.querySelectorAll('img');
        feedImgs.forEach(img => {
          if (!img.complete) {
            img.addEventListener('load', () => scrollToBottom(false), { once: true });
          }
        });

        // Se questo thread ha un'attività in background in corso, mostra la barra di avanzamento / typing indicator
        if (activeThreadTasks[threadId]) {
          const task = activeThreadTasks[threadId];
          showTypingIndicator(task.statusText || 'Elaborazione in corso...', task.progressPercent);
        } else {
          hideTypingIndicator();
        }
        if (typeof syncInputControlsForCurrentThread === 'function') {
          syncInputControlsForCurrentThread();
        }
      } catch (err) {
        if (threadId !== currentThreadId) return;
        console.error("Errore loadThreadMessages:", err);
        chatFeed.innerHTML = `
          <div class="flex justify-center my-4 text-xs text-red-600 bg-red-50 p-2 rounded-lg">
            Impossibile caricare i messaggi di questa chat.
          </div>
        `;
      }
    }
    window.loadThreadMessages = loadThreadMessages;
    window.loadChatHistory = () => loadThreadMessages(currentThreadId);


    // --- Gestione Modale Nuovo Thread / Gruppo Online ---
    function openNewThreadModal() {
      if (!window.currentCloudUser && !localStorage.getItem('supabase_auth_token') && !sessionStorage.getItem('supabase_auth_token')) {
        if (typeof showToast === 'function') {
          showToast("⚠️ Accedi al tuo account prima di creare o gestire gruppi online.", "warning", 3000);
        }
        if (typeof openAccountModal === 'function') openAccountModal('profile', true);
        return;
      }
      const modal = document.getElementById('newThreadModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        const formEl = document.getElementById('newThreadForm');
        const successBox = document.getElementById('newThreadSuccessBox');
        const joinBox = document.getElementById('newThreadJoinBox');
        const joinErr = document.getElementById('newThreadJoinError');
        if (formEl) formEl.classList.remove('hidden');
        if (successBox) successBox.classList.add('hidden');
        if (joinBox) joinBox.classList.add('hidden');
        if (joinErr) joinErr.classList.add('hidden');
        selectThreadType('group');
        const nameInput = document.getElementById('threadNameInput');
        if (nameInput) {
          nameInput.value = '';
          nameInput.focus();
        }
        const descInput = document.getElementById('threadDescInput');
        if (descInput) descInput.value = '';
        const codeInput = document.getElementById('newThreadJoinCodeInput');
        if (codeInput) codeInput.value = '';
      }
    }
    window.openNewThreadModal = openNewThreadModal;

    function closeNewThreadModal() {
      const modal = document.getElementById('newThreadModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }
    window.closeNewThreadModal = closeNewThreadModal;

    function selectThreadType(type) {
      newThreadType = type;
      const tabGroup = document.getElementById('tabTypeGroup');
      const tabThematic = document.getElementById('tabTypeThematic');
      const groupInfoBox = document.getElementById('groupInfoBox');
      const thematicIconGroup = document.getElementById('thematicIconGroup');
      const labelName = document.getElementById('labelThreadName');
      const nameInput = document.getElementById('threadNameInput');
      const submitText = document.getElementById('newThreadSubmitText');
      const joinSection = document.getElementById('newThreadJoinSection');

      if (type === 'group') {
        if (tabGroup) tabGroup.className = 'py-2 text-xs font-bold font-space rounded-xs transition bg-[#3C5A48] text-white shadow-xs flex items-center justify-center gap-1.5 cursor-pointer';
        if (tabThematic) tabThematic.className = 'py-2 text-xs font-bold font-space rounded-xs transition bg-white border border-[#E3DDD1] text-[#7A7568] hover:text-[#222220] flex items-center justify-center gap-1.5 cursor-pointer';
        if (groupInfoBox) groupInfoBox.classList.remove('hidden');
        if (thematicIconGroup) thematicIconGroup.classList.add('hidden');
        if (joinSection) joinSection.classList.remove('hidden');
        if (labelName) labelName.textContent = 'Nome del Gruppo Online';
        if (nameInput) nameInput.placeholder = 'Es. Famiglia, Condominio, Casa Mare, Ufficio...';
        if (submitText) submitText.textContent = 'Crea Gruppo Online';
      } else {
        if (tabThematic) tabThematic.className = 'py-2 text-xs font-bold font-space rounded-xs transition bg-[#3C5A48] text-white shadow-xs flex items-center justify-center gap-1.5 cursor-pointer';
        if (tabGroup) tabGroup.className = 'py-2 text-xs font-bold font-space rounded-xs transition bg-white border border-[#E3DDD1] text-[#7A7568] hover:text-[#222220] flex items-center justify-center gap-1.5 cursor-pointer';
        if (groupInfoBox) groupInfoBox.classList.add('hidden');
        if (thematicIconGroup) thematicIconGroup.classList.remove('hidden');
        if (joinSection) joinSection.classList.add('hidden');
        if (labelName) labelName.textContent = 'Nome dell\'Area Tematica';
        if (nameInput) nameInput.placeholder = 'Es. Lavoro, Fisco & Tasse, Auto & Moto...';
        if (submitText) submitText.textContent = 'Crea Area Tematica';
      }
    }
    window.selectThreadType = selectThreadType;

    function selectThematicIcon(icon) {
      selectedThematicIcon = icon;
      document.querySelectorAll('.icon-choice').forEach(btn => {
        if (btn.getAttribute('data-icon') === icon) {
          btn.classList.add('border-[#3C5A48]', 'bg-[#FAF8F2]', 'text-[#3C5A48]');
          btn.classList.remove('border-[#E3DDD1]', 'bg-white');
        } else {
          btn.classList.remove('border-[#3C5A48]', 'bg-[#FAF8F2]', 'text-[#3C5A48]');
          btn.classList.add('border-[#E3DDD1]', 'bg-white');
        }
      });
    }
    window.selectThematicIcon = selectThematicIcon;

    async function handleCreateThread(e) {
      if (e) e.preventDefault();
      const name = (document.getElementById('threadNameInput')?.value || '').trim();
      if (!name) return;

      const desc = (document.getElementById('threadDescInput')?.value || '').trim();

      if (newThreadType === 'group') {
        const submitBtn = document.getElementById('newThreadSubmitBtn');
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.classList.add('opacity-60');
        }
        try {
          const res = await fetch('/api/groups', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
              name: name,
              description: desc || null,
              icon: 'fa-house'
            })
          });

          if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Errore durante la creazione del gruppo online");
          }

          const group = await res.json();
          const formEl = document.getElementById('newThreadForm');
          const successBox = document.getElementById('newThreadSuccessBox');
          const successName = document.getElementById('newThreadSuccessName');
          const successCode = document.getElementById('newThreadSuccessCode');
          const successEnterBtn = document.getElementById('newThreadSuccessEnterBtn');

          if (formEl) formEl.classList.add('hidden');
          if (successBox) {
            successBox.classList.remove('hidden');
            if (successName) successName.textContent = `Gruppo '${group.name}' Attivato!`;
            if (successCode) successCode.textContent = group.invite_code;
            if (successEnterBtn) {
              successEnterBtn.onclick = async () => {
                closeNewThreadModal();
                await loadThreads();
                await switchThread(group.id);
              };
            }
          }

          if (typeof showToast === 'function') {
            showToast(`🎉 Gruppo online '${group.name}' creato! Codice: ${group.invite_code}`, "success", 5000);
          }
          await loadThreads();
          return;
        } catch (err) {
          console.error("Errore creazione gruppo online:", err);
          alert("Impossibile creare il gruppo online: " + err.message);
          return;
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.classList.remove('opacity-60');
          }
        }
      }

      // Altrimenti: Area Tematica Locale
      const icon = selectedThematicIcon || 'fa-briefcase';
      let color = 'bg-[#3C5A48]';
      if (icon === 'fa-house') color = 'bg-amber-600';
      if (icon === 'fa-car') color = 'bg-blue-600';
      if (icon === 'fa-heart-pulse') color = 'bg-rose-600';
      if (icon === 'fa-receipt') color = 'bg-emerald-700';

      try {
        const res = await fetch('/api/threads', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            name: name,
            thread_type: 'thematic',
            icon: icon,
            color: color,
            description: desc,
            members: ['Io']
          })
        });

        if (!res.ok) throw new Error("Errore durante la creazione dello spazio");
        const newThread = await res.json();
        closeNewThreadModal();
        await loadThreads();
        await switchThread(newThread.id);
      } catch (err) {
        console.error("Errore handleCreateThread:", err);
        alert("Errore durante la creazione dell'area tematica: " + err.message);
      }
    }
    window.handleCreateThread = handleCreateThread;

    async function handleNewThreadJoinSubmit() {
      const input = document.getElementById('newThreadJoinCodeInput');
      const errEl = document.getElementById('newThreadJoinError');
      const code = input ? input.value.trim().toUpperCase() : '';
      if (!code) return;
      if (errEl) errEl.classList.add('hidden');

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

        if (typeof showToast === 'function') {
          showToast(data.message || `Benvenuto nel gruppo '${data.name}'!`, "success", 4000);
        }
        closeNewThreadModal();
        await loadThreads();
        await switchThread(data.group_id);
      } catch (err) {
        if (errEl) {
          errEl.textContent = err.message;
          errEl.classList.remove('hidden');
        } else {
          alert("Errore adesione gruppo: " + err.message);
        }
      }
    }
    window.handleNewThreadJoinSubmit = handleNewThreadJoinSubmit;

    function toggleNewThreadJoinBox() {
      const box = document.getElementById('newThreadJoinBox');
      if (box) box.classList.toggle('hidden');
    }
    window.toggleNewThreadJoinBox = toggleNewThreadJoinBox;

    function copyNewThreadCode() {
      const codeEl = document.getElementById('newThreadSuccessCode');
      const code = codeEl ? codeEl.textContent.trim() : '';
      if (!code) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(() => {
          if (typeof showToast === 'function') showToast(`📋 Codice invito ${code} copiato!`, "info", 3000);
        }).catch(() => prompt("Copia il codice d'invito:", code));
      } else {
        prompt("Copia il codice d'invito:", code);
      }
    }
    window.copyNewThreadCode = copyNewThreadCode;

    async function confirmDeleteCurrentThread() {
      if (currentThreadId === 'general') {
        alert("Non è possibile eliminare lo spazio principale 'Dove lo AI messo'.");
        return;
      }
      const t = threadsCache.find(th => th.id === currentThreadId);
      const confirmed = await showConfirmModal({
        title: "Elimina Spazio o Gruppo",
        message: `Sei sicuro di voler eliminare lo spazio "${name}"?\nI messaggi verranno eliminati e i file associati saranno ricollocati nel canale principale.`,
        confirmText: "Elimina Spazio",
        danger: true
      });
      if (!confirmed) return;

      try {
        const res = await fetch(`/api/threads/${encodeURIComponent(currentThreadId)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error("Errore eliminazione thread");
        await loadThreads();
        await switchThread('general');
      } catch (err) {
        console.error("Errore confirmDeleteCurrentThread:", err);
        alert("Errore durante l'eliminazione dello spazio: " + err.message);
      }
    }

    // --- Helper Download File: salva tramite Python sul PC (compatibile con pywebview) e via Blob per browser ---
    async function downloadFileFromUrl(url, filename, docId = null) {
      try {
        let savedLocally = false;
        let downloadedFilename = filename || 'documento';

        // 1. In pywebview o ambiente desktop locale, salva nella cartella Download di sistema ed apre Explorer
        if (docId) {
          try {
            const res = await fetch(`/api/documents/${docId}/save-to-downloads`, {
              method: 'POST',
              headers: typeof authHeaders === 'function' ? authHeaders() : {}
            });
            if (res.ok) {
              const data = await res.json();
              savedLocally = true;
              if (data.filename) downloadedFilename = data.filename;
              showToast(`File archiviato nella cartella Download: ${downloadedFilename}`, 'success', 5000);
            }
          } catch (e) {
            console.warn("save-to-downloads background attempt:", e);
          }
        }

        // 2. Download via Blob nativo nel browser (Chrome, Edge, Firefox, Safari, Mobile)
        const targetUrl = url || (docId ? `/api/documents/${docId}/download` : null);
        if (targetUrl) {
          try {
            const res = await fetch(targetUrl, {
              headers: typeof authHeaders === 'function' ? authHeaders() : {}
            });
            if (res.ok) {
              const blob = await res.blob();
              const blobUrl = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = blobUrl;
              a.download = downloadedFilename;
              document.body.appendChild(a);
              a.click();
              setTimeout(() => { URL.revokeObjectURL(blobUrl); a.remove(); }, 2000);
              if (!savedLocally) {
                showToast(`Download completato: ${downloadedFilename}`, 'success', 4000);
              }
            } else if (!savedLocally) {
              throw new Error('Risposta server: ' + res.status);
            }
          } catch (blobErr) {
            if (!savedLocally) throw blobErr;
          }
        }
      } catch (err) {
        console.error('Errore download:', err);
        showToast('Errore durante il download: ' + err.message, 'error');
      }
    }
    window.downloadFileFromUrl = downloadFileFromUrl;

    async function downloadDashboardDoc(docId) {
      if (!docId) return;
      const downloadUrl = `/api/documents/${docId}/download`;
      let docTitle = 'documento';
      if (typeof currentRecords !== 'undefined' && Array.isArray(currentRecords)) {
        const found = currentRecords.find(r => r.id === docId && r.type === 'document');
        if (found && found.title) docTitle = found.title;
      } else if (typeof allDashboardRecordsCache !== 'undefined' && Array.isArray(allDashboardRecordsCache)) {
        const found = allDashboardRecordsCache.find(r => r.id === docId && r.type === 'document');
        if (found && found.title) docTitle = found.title;
      }
      await downloadFileFromUrl(downloadUrl, docTitle, docId);
    }
    window.downloadDashboardDoc = downloadDashboardDoc;

    // --- Gestione Impostazioni Modello AI (Switch Gratuito / Gemini Flash Lite) ---
    let currentAiModel = 'google/gemini-2.5-flash-lite';

    async function loadAiModelSetting() {
      try {
        const res = await fetch('/api/settings/ai-model');
        if (!res.ok) return;
        const data = await res.json();
        currentAiModel = data.current_model || 'google/gemini-2.5-flash-lite';
        updateAiModelUI(data);
      } catch (err) {
        console.warn("Impossibile caricare impostazioni modello AI:", err);
      }
    }

    function updateAiModelUI(data) {
      const isAuto = currentAiModel === 'auto';
      const isThinking = (currentAiModel || '').includes('gemini-2.5-pro');
      const isFree = data.is_free || (currentAiModel.includes(':free'));
      const headerLabel = document.getElementById('aiModelHeaderLabel');
      const headerIcon = document.getElementById('aiModelHeaderIcon');
      const statusDot = document.getElementById('aiModelStatusDot');
      const freeToggle = document.getElementById('freeModelToggle');

      if (freeToggle) {
        freeToggle.checked = isFree;
      }

      if (openrouterCreditsData) {
        updateOpenRouterCreditsUI(openrouterCreditsData);
      }

      if (headerLabel) {
        if (isAuto) {
          headerLabel.textContent = 'Router Intelligente';
        } else if (isThinking) {
          headerLabel.textContent = 'Gemini 2.5 Pro';
        } else if (isFree) {
          headerLabel.textContent = 'Nex-AGI (Free)';
        } else {
          headerLabel.textContent = 'Gemini 2.5 Lite';
        }
      }
      if (headerIcon) {
        if (isAuto) {
          headerIcon.className = 'fa-solid fa-wand-magic-sparkles text-[#3C5A48] text-[9px]';
        } else if (isThinking) {
          headerIcon.className = 'fa-solid fa-brain text-[#222220] text-[9px]';
        } else if (isFree) {
          headerIcon.className = 'fa-solid fa-cube text-[#3C5A48] text-[9px]';
        } else {
          headerIcon.className = 'fa-solid fa-bolt text-[#C84B31] text-[9px]';
        }
      }
      if (statusDot) {
        if (isAuto) {
          statusDot.className = 'w-1.5 h-1.5 rounded-full bg-[#3C5A48] animate-pulse';
        } else if (isThinking) {
          statusDot.className = 'w-1.5 h-1.5 rounded-full bg-[#222220] animate-pulse';
        } else if (isFree) {
          statusDot.className = 'w-1.5 h-1.5 rounded-full bg-[#3C5A48]';
        } else {
          statusDot.className = 'w-1.5 h-1.5 rounded-full bg-[#C84B31] animate-pulse';
        }
      }

      // Aggiorna le card nel modale
      const cardAuto = document.getElementById('modelCard_auto');
      const cardGemini = document.getElementById('modelCard_gemini');
      const cardThinking = document.getElementById('modelCard_thinking');
      const cardNex = document.getElementById('modelCard_nex');
      const checkAuto = document.getElementById('check_auto');
      const checkGemini = document.getElementById('check_gemini');
      const checkThinking = document.getElementById('check_thinking');
      const checkNex = document.getElementById('check_nex');

      [
        { card: cardAuto, check: checkAuto, active: isAuto },
        { card: cardGemini, check: checkGemini, active: !isAuto && !isThinking && !isFree },
        { card: cardThinking, check: checkThinking, active: !isAuto && isThinking },
        { card: cardNex, check: checkNex, active: !isAuto && isFree }
      ].forEach(item => {
        if (!item.card) return;
        if (item.active) {
          item.card.classList.add('border-[#3C5A48]', 'border-2', 'bg-[#FAF8F2]', 'shadow-xs');
          item.card.classList.remove('border-[#E3DDD1]', 'bg-white');
          if (item.check) {
            item.check.classList.remove('hidden');
            item.check.classList.add('stamp-solid-sage');
          }
        } else {
          item.card.classList.remove('border-[#3C5A48]', 'border-2', 'bg-[#FAF8F2]', 'shadow-xs');
          item.card.classList.add('border-[#E3DDD1]', 'bg-white');
          if (item.check) {
            item.check.classList.add('hidden');
            item.check.classList.remove('stamp-solid-sage');
          }
        }
      });
    }

    function openAiSettingsModal() {
      openSystem();
    }

    function closeAiSettingsModal() {
      closeToChat();
    }

    // --- Gestione Bilancio & Crediti OpenRouter ---
    let openrouterCreditsData = null;

    async function loadOpenRouterCredits(forceRefresh = false) {
      const refreshBtn = document.getElementById('btnRefreshCredits');
      const refreshIcon = refreshBtn ? refreshBtn.querySelector('i') : null;
      if (refreshIcon) refreshIcon.classList.add('fa-spin');

      try {
        const res = await fetch('/api/settings/openrouter-credits');
        if (!res.ok) {
          console.warn("Impossibile caricare crediti OpenRouter:", res.status);
          return;
        }
        const data = await res.json();
        openrouterCreditsData = data;
        updateOpenRouterCreditsUI(data);
        if (forceRefresh) {
          showToast('🟢 Saldo crediti OpenRouter aggiornato in tempo reale!', 'success');
        }
      } catch (err) {
        console.warn("Errore fetch crediti OpenRouter:", err);
      } finally {
        if (refreshIcon) {
          setTimeout(() => refreshIcon.classList.remove('fa-spin'), 350);
        }
      }
    }

    function updateOpenRouterCreditsUI(data) {
      if (!data) return;

      const valRemaining = document.getElementById('valCreditsRemaining');
      const valTotal = document.getElementById('valCreditsTotal');
      const valUsage = document.getElementById('valCreditsUsage');
      const labelPct = document.getElementById('labelCreditsPct');
      const ratioText = document.getElementById('creditsRatioText');
      const progressBar = document.getElementById('creditsProgressBar');
      const valKeyUsage = document.getElementById('valKeyUsage');
      const valKeyDaily = document.getElementById('valKeyDaily');
      const valFreeRequests = document.getElementById('valFreeRequests');
      const statusBadge = document.getElementById('creditsStatusBadge');
      const quickCreditsVal = document.getElementById('quickCreditsVal');
      const aiModelSummary = document.getElementById('aiModelCreditsSummary');

      const isConfigured = data.is_configured;
      const rem = typeof data.remaining_credits === 'number' ? data.remaining_credits : 0.0;
      const tot = typeof data.total_credits === 'number' ? data.total_credits : 0.0;
      const usg = typeof data.total_usage === 'number' ? data.total_usage : 0.0;
      const pct = typeof data.percentage_remaining === 'number' ? data.percentage_remaining : 0.0;
      const isFreeTier = data.is_free_tier;

      // Quick badge in top header
      if (quickCreditsVal) {
        if (!isConfigured) {
          quickCreditsVal.textContent = 'Non config.';
          quickCreditsVal.className = 'font-mono-code font-bold text-[#7A7568]';
        } else if (isFreeTier && rem <= 0.001) {
          quickCreditsVal.textContent = 'FREE TIER';
          quickCreditsVal.className = 'font-mono-code font-bold text-[#3C5A48]';
        } else {
          quickCreditsVal.textContent = `$${rem.toFixed(2)}`;
          quickCreditsVal.className = rem < 2.0 
            ? 'font-mono-code font-bold text-[#C84B31]' 
            : 'font-mono-code font-bold text-[#3C5A48]';
        }
      }

      if (aiModelSummary) {
        if (!isConfigured) {
          aiModelSummary.textContent = 'Non configurato';
        } else if (isFreeTier && rem <= 0.001) {
          aiModelSummary.textContent = 'Modalità Gratuita (Free Tier)';
        } else {
          aiModelSummary.textContent = `$${rem.toFixed(2)} disponibili (su $${tot.toFixed(2)} depositati)`;
        }
      }

      if (!isConfigured) {
        if (valRemaining) valRemaining.textContent = 'N/D';
        if (valTotal) valTotal.textContent = '$0.00';
        if (valUsage) valUsage.textContent = '$0.00';
        if (labelPct) labelPct.textContent = '0%';
        if (ratioText) ratioText.textContent = 'Chiave OpenRouter non impostata';
        if (progressBar) progressBar.style.width = '0%';
        if (statusBadge) {
          statusBadge.className = 'stamp-oli text-[8px] border-[#C84B31] text-[#C84B31]';
          statusBadge.textContent = 'NON CONFIGURATO';
        }
        return;
      }

      if (valRemaining) valRemaining.textContent = `$${rem.toFixed(2)}`;
      if (valTotal) valTotal.textContent = `$${tot.toFixed(2)}`;
      if (valUsage) valUsage.textContent = `$${usg.toFixed(2)}`;
      if (labelPct) labelPct.textContent = `${pct.toFixed(1)}%`;
      if (ratioText) ratioText.textContent = `Consumati $${usg.toFixed(2)} di $${tot.toFixed(2)}`;
      
      if (progressBar) {
        progressBar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
        if (pct < 15) {
          progressBar.className = 'h-full bg-[#C84B31] rounded-xs transition-all duration-500';
        } else if (pct < 35) {
          progressBar.className = 'h-full bg-amber-600 rounded-xs transition-all duration-500';
        } else {
          progressBar.className = 'h-full bg-[#3C5A48] rounded-xs transition-all duration-500';
        }
      }

      if (valKeyUsage) {
        const kUsg = (data.key_usage !== null && data.key_usage !== undefined) ? `$${Number(data.key_usage).toFixed(3)}` : `$${usg.toFixed(2)}`;
        valKeyUsage.textContent = kUsg;
      }

      if (valKeyDaily) {
        const kDaily = (data.key_usage_daily !== null && data.key_usage_daily !== undefined) ? `$${Number(data.key_usage_daily).toFixed(3)}` : '0.00 $';
        valKeyDaily.textContent = kDaily;
      }

      if (valFreeRequests) {
        const freeReq = data.free_model_daily_requests;
        valFreeRequests.textContent = (freeReq !== null && freeReq !== undefined) ? `${freeReq} / 100` : 'Illimitate';
      }

      if (statusBadge) {
        if (rem <= 0.05 && tot > 0) {
          statusBadge.className = 'stamp-oli stamp-terracotta text-[8px]';
          statusBadge.textContent = 'IN ESAURIMENTO';
        } else if (rem > 0) {
          statusBadge.className = 'stamp-oli text-[8px] text-[#3C5A48] border-[#3C5A48]';
          statusBadge.textContent = 'SALDO POSITIVO';
        } else {
          statusBadge.className = 'stamp-oli text-[8px] text-[#3C5A48] border-[#3C5A48]';
          statusBadge.textContent = 'ATTIVO (FREE)';
        }
      }
    }

    window.loadOpenRouterCredits = loadOpenRouterCredits;

    // --- Suddivisione Impostazioni Sistema per Aree Tematiche (Stile Smartphone) ---
    let currentOpenSystemSection = null;

    const SYSTEM_SECTION_CONFIG = {
      chat: { title: "Chat & Assistente AI", badge: "AI CORE" },
      google: { title: "Integrazioni Google (Drive & Calendar)", badge: "GOOGLE WORKSPACE" },
      drive: { title: "Integrazioni Google (Drive & Calendar)", badge: "GOOGLE WORKSPACE" },
      calendar: { title: "Integrazioni Google (Drive & Calendar)", badge: "GOOGLE WORKSPACE" },
      pc: { title: "Cartelle PC & Monitoraggio", badge: "DESKTOP" },
      security: { title: "Sicurezza & Crittografia", badge: "AES-256 ZERO-KNOWLEDGE" }
    };

    function updateSystemMenuStatusBadges() {
      // 1. Chat & AI
      const menuStatusChat = document.getElementById('menuStatus_chat');
      if (menuStatusChat) {
        const savedModel = localStorage.getItem('dove_ai_model') || 'google/gemini-2.5-flash';
        const modelLabel = savedModel.includes('pro') ? 'Gemini Pro' : savedModel.includes('flash') ? 'Gemini Flash' : 'Claude 3.7';
        const credits = sessionStorage.getItem('openrouter_credits');
        const creditsText = credits ? ` • Saldo: ${credits}` : '';
        menuStatusChat.textContent = `Modello: ${modelLabel}${creditsText} • Prompt di sistema`;
      }

      // 2. Integrazioni Google (Drive & Calendar)
      const menuBadgeGoogle = document.getElementById('menuBadge_google');
      const menuBadgeDrive = document.getElementById('menuBadge_drive');
      const menuStatusDrive = document.getElementById('menuStatus_drive');
      const driveIsConnected = window.currentDriveConnected || false;
      const calConnected = (window.currentCalendarConnected !== undefined) 
        ? window.currentCalendarConnected 
        : false;
      const anyGoogleConnected = driveIsConnected || calConnected;

      if (menuBadgeGoogle) {
        if (anyGoogleConnected) {
          menuBadgeGoogle.textContent = 'ATTIVO';
          menuBadgeGoogle.className = 'stamp-oli stamp-solid-sage text-[8px] py-0.2 px-1';
        } else {
          menuBadgeGoogle.textContent = 'NON COLLEGATO';
          menuBadgeGoogle.className = 'stamp-oli text-[8px] py-0.2 px-1';
        }
      }

      if (menuBadgeDrive) {
        if (driveIsConnected) {
          menuBadgeDrive.textContent = 'COLLEGATO';
          menuBadgeDrive.className = 'stamp-oli stamp-solid-sage text-[8px] py-0.2 px-1';
        } else {
          menuBadgeDrive.textContent = 'CLOUD';
          menuBadgeDrive.className = 'stamp-oli text-[8px] py-0.2 px-1';
        }
      }
      if (menuStatusDrive) {
        if (driveIsConnected) {
          menuStatusDrive.textContent = 'Sincronizzazione cloud attiva • Backup automatico';
        } else {
          menuStatusDrive.textContent = 'Backup remoto, modalità Dual/Cloud, sincronizzazione file';
        }
      }

      // 3. Google Calendar
      const menuBadgeCalendar = document.getElementById('menuBadge_calendar');
      const menuStatusCalendar = document.getElementById('menuStatus_calendar');
      if (menuBadgeCalendar) {
        if (calConnected) {
          menuBadgeCalendar.textContent = 'ATTIVO';
          menuBadgeCalendar.className = 'stamp-oli stamp-solid-sage text-[8px] py-0.2 px-1';
        } else {
          menuBadgeCalendar.textContent = 'CALENDARIO';
          menuBadgeCalendar.className = 'stamp-oli text-[8px] py-0.2 px-1';
        }
      }
      if (menuStatusCalendar) {
        if (calConnected) {
          menuStatusCalendar.textContent = 'Sincronizzazione tributi e bollette attiva';
        } else {
          menuStatusCalendar.textContent = 'Sincronizzazione automatica scadenze fiscali, bollette e promemoria';
        }
      }

      // 4. Cartelle PC
      const menuStatusPc = document.getElementById('menuStatus_pc');
      if (menuStatusPc) {
        menuStatusPc.textContent = 'Monitoraggio cartelle locali, Download, scansione automatica file';
      }
    }
    window.updateSystemMenuStatusBadges = updateSystemMenuStatusBadges;

    function openSystemSection(area) {
      const validAreas = ['chat', 'google', 'drive', 'calendar', 'pc', 'security'];
      if (!validAreas.includes(area)) {
        closeSystemSection();
        return;
      }
      const mappedArea = (area === 'drive' || area === 'calendar') ? 'google' : area;
      currentOpenSystemSection = mappedArea;
      sessionStorage.setItem('dove_system_open_section', mappedArea);
      sessionStorage.setItem('dove_system_active_area', mappedArea);

      const menu = document.getElementById('systemSectionsMenu');
      const detail = document.getElementById('systemSectionDetailView');
      if (menu) menu.classList.add('hidden');
      if (detail) detail.classList.remove('hidden');

      // Imposta titolo e badge della sezione attiva nel sub-header
      const titleEl = document.getElementById('activeSectionTitle');
      const badgeEl = document.getElementById('activeSectionBadge');
      const cfg = SYSTEM_SECTION_CONFIG[mappedArea] || { title: mappedArea.toUpperCase(), badge: "ATTIVA" };
      if (titleEl) titleEl.textContent = cfg.title;
      if (badgeEl) badgeEl.textContent = cfg.badge;

      // Aggiorna visibilità sezioni (solo quella selezionata è visibile)
      const sectionIds = ['settingsArea_chat', 'settingsArea_google', 'settingsArea_pc', 'settingsArea_security'];
      sectionIds.forEach(id => {
        const sec = document.getElementById(id);
        if (!sec) return;
        const secArea = id.replace('settingsArea_', '');
        if (secArea === mappedArea) {
          sec.classList.remove('hidden');
        } else {
          sec.classList.add('hidden');
        }
      });

      // Assicura che i sotto-moduli drive e calendar rimangano visibili dentro settingsArea_google
      if (mappedArea === 'google') {
        const driveSub = document.getElementById('settingsArea_drive');
        const calSub = document.getElementById('settingsArea_calendar');
        if (driveSub) driveSub.classList.remove('hidden');
        if (calSub) calSub.classList.remove('hidden');
      }

      // Aggiorna classi bottoni Tab per coerenza
      ['all', 'chat', 'google', 'drive', 'calendar', 'pc', 'security'].forEach(a => {
        const btn = document.getElementById(`btnSystemArea_${a}`);
        if (!btn) return;
        const isActive = (a === mappedArea) || ((a === 'drive' || a === 'calendar') && mappedArea === 'google');
        if (isActive) {
          btn.className = 'system-area-tab px-3 py-1.5 rounded-xs text-xs font-space font-bold uppercase transition flex items-center gap-1.5 cursor-pointer bg-[#3C5A48] text-white shadow-2xs shrink-0';
        } else {
          btn.className = 'system-area-tab px-3 py-1.5 rounded-xs text-xs font-space font-bold uppercase transition flex items-center gap-1.5 cursor-pointer bg-white text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1] shrink-0';
        }
      });

      // Scroll verso l'alto
      const scrollable = document.querySelector('#viewSettings main') || document.querySelector('#viewSettings') || window;
      if (scrollable && scrollable.scrollTo) {
        scrollable.scrollTo({ top: 0, behavior: 'smooth' });
      }
    }
    window.openSystemSection = openSystemSection;

    function closeSystemSection() {
      currentOpenSystemSection = null;
      sessionStorage.setItem('dove_system_open_section', 'none');
      sessionStorage.setItem('dove_system_active_area', 'all');

      const menu = document.getElementById('systemSectionsMenu');
      const detail = document.getElementById('systemSectionDetailView');
      if (menu) menu.classList.remove('hidden');
      if (detail) detail.classList.add('hidden');

      // Mantieni tutte le sezioni visibili per compatibilità
      const sectionIds = ['settingsArea_chat', 'settingsArea_google', 'settingsArea_drive', 'settingsArea_calendar', 'settingsArea_pc', 'settingsArea_security'];
      sectionIds.forEach(id => {
        const sec = document.getElementById(id);
        if (sec) sec.classList.remove('hidden');
      });

      // Aggiorna stato tab 'all'
      const btnAll = document.getElementById('btnSystemArea_all');
      if (btnAll) {
        btnAll.className = 'system-area-tab px-3 py-1.5 rounded-xs text-xs font-space font-bold uppercase transition flex items-center gap-1.5 cursor-pointer bg-[#3C5A48] text-white shadow-2xs shrink-0';
      }
      ['chat', 'google', 'drive', 'calendar', 'pc', 'security'].forEach(a => {
        const btn = document.getElementById(`btnSystemArea_${a}`);
        if (btn) {
          btn.className = 'system-area-tab px-3 py-1.5 rounded-xs text-xs font-space font-bold uppercase transition flex items-center gap-1.5 cursor-pointer bg-white text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1] shrink-0';
        }
      });

      updateSystemMenuStatusBadges();

      const scrollable = document.querySelector('#viewSettings main') || document.querySelector('#viewSettings') || window;
      if (scrollable && scrollable.scrollTo) {
        scrollable.scrollTo({ top: 0, behavior: 'smooth' });
      }
    }
    window.closeSystemSection = closeSystemSection;

    function setSystemArea(area) {
      const validAreas = ['all', 'chat', 'google', 'drive', 'calendar', 'pc', 'security'];
      const targetArea = validAreas.includes(area) ? area : 'all';
      if (targetArea === 'all') {
        closeSystemSection();
      } else {
        openSystemSection(targetArea);
      }
    }
    window.setSystemArea = setSystemArea;

    function updateHeaderCloudIndicators(driveConnected, calendarConnected) {
      if (driveConnected !== null && driveConnected !== undefined) {
        ['chatHeaderDriveStatus', 'sidebarHeaderDriveStatus'].forEach(id => {
          const el = document.getElementById(id);
          if (el) {
            if (driveConnected) {
              el.classList.remove('hidden');
              el.classList.add('inline-flex');
            } else {
              el.classList.add('hidden');
              el.classList.remove('inline-flex');
            }
          }
        });
      }
      if (calendarConnected !== null && calendarConnected !== undefined) {
        ['chatHeaderCalendarStatus', 'sidebarHeaderCalendarStatus'].forEach(id => {
          const el = document.getElementById(id);
          if (el) {
            if (calendarConnected) {
              el.classList.remove('hidden');
              el.classList.add('inline-flex');
            } else {
              el.classList.add('hidden');
              el.classList.remove('inline-flex');
            }
          }
        });
      }
    }
    window.updateHeaderCloudIndicators = updateHeaderCloudIndicators;

    async function loadCalendarStatus() {
      const badge = document.getElementById('systemCalendarStatusBadge');
      const details = document.getElementById('systemCalendarStatusDetails');
      const toggleCal = document.getElementById('toggleCalendarSync');
      try {
        const res = await fetch('/api/calendar/status', { headers: authHeaders() });
        if (!res.ok) throw new Error('Stato non disponibile');
        const data = await res.json();
        const isConnected = !!data.connected;
        window.currentCalendarConnected = isConnected;
        updateHeaderCloudIndicators(null, isConnected);
        if (typeof updateSystemMenuStatusBadges === 'function') updateSystemMenuStatusBadges();
        if (typeof currentFilter !== 'undefined' && currentFilter === 'scadenzario' && typeof renderScadenzarioView === 'function' && typeof currentRecords !== 'undefined' && currentRecords && currentRecords.length > 0) {
          renderScadenzarioView(currentRecords);
        }
        if (toggleCal) {
          toggleCal.checked = (data.calendar_enabled !== false);
        }
        const targetVal = data.calendar_target || 'dedicated';
        const targetRadios = document.querySelectorAll('input[name="calendarTarget"]');
        targetRadios.forEach(r => {
          r.checked = (r.value === targetVal);
        });

        if (badge) {
          if (isConnected) {
            badge.textContent = (data.calendar_enabled !== false) ? 'ATTIVO & COLLEGATO' : 'DISATTIVATO';
            badge.className = (data.calendar_enabled !== false) ? 'stamp-oli stamp-solid-sage text-[8px] font-bold' : 'stamp-oli text-[8px] font-bold text-[#7A7568]';
            if (details) {
              const targetDesc = (targetVal === 'primary') ? 'CALENDARIO PRINCIPALE' : (data.calendar_name || 'DOVE LO AI MESSO - SCADENZE').toUpperCase();
              details.textContent = `ACCOUNT: ${(data.user_email || 'GOOGLE').toUpperCase()} • DESTINAZIONE: ${targetDesc}`;
            }
          } else {
            badge.textContent = 'NON COLLEGATO';
            badge.className = 'stamp-oli stamp-terracotta text-[8px] font-bold';
            if (details) {
              details.textContent = 'Collega il tuo account Google per sincronizzare automaticamente le scadenze.';
            }
          }
        }
      } catch (e) {
        window.currentCalendarConnected = false;
        updateHeaderCloudIndicators(null, false);
        if (typeof updateSystemMenuStatusBadges === 'function') updateSystemMenuStatusBadges();
        if (badge) {
          badge.textContent = 'LOCALE / ICAL PRONTO';
          badge.className = 'stamp-oli text-[8px] font-bold text-[#7A7568]';
        }
      }
    }
    window.loadCalendarStatus = loadCalendarStatus;

