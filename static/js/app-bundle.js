    const chatView = document.getElementById('chatView');
    const dashboardView = document.getElementById('dashboardView');
    const systemView = document.getElementById('systemView');
    const sidebarPanel = document.getElementById('sidebarPanel');
    const conversationPanel = document.getElementById('conversationPanel');
    const input = document.getElementById('messageInput');
    const micBtn = document.getElementById('micBtn');
    const sendBtn = document.getElementById('sendBtn');
    const chatFeed = document.getElementById('chatFeed');
    const scrollToBottomBtn = document.getElementById('scrollToBottomBtn');
    const scrollUnreadBadge = document.getElementById('scrollUnreadBadge');
    const realFileInput = document.getElementById('realFileInput');

    let currentThreadId = 'general';
    let threadsCache = [];
    const activeThreadTasks = {}; // Task in background per thread: { [threadId]: { abortController, statusText, progressPercent, startedAt } }
    let activeThreadFilter = 'all'; // 'all', 'group', 'thematic'
    let newThreadType = 'group';
    let selectedThematicIcon = 'fa-briefcase';

    let currentFilter = 'all';
    let currentRecords = [];
    let allDashboardRecordsCache = [];
    try {
      const _cachedRecords = sessionStorage.getItem('vault_records_cache');
      if (_cachedRecords) {
        allDashboardRecordsCache = JSON.parse(_cachedRecords);
        currentRecords = [...allDashboardRecordsCache];
      }
    } catch (e) {}

    // Allinea dinamicamente i badge di versione all'avvio
    (function syncAppVersion() {
      fetch('/api/version')
        .then(res => res.json())
        .then(data => {
          if (data && data.version) {
            document.querySelectorAll('.app-version-badge').forEach(el => {
              el.textContent = 'v' + data.version;
            });
          }
        })
        .catch(() => {});
    })();

    // Allinea dinamicamente i badge di rilevamento ambiente (DESKTOP vs MOBILE)
    function syncDeviceEnvironment() {
      const isMobilePath = window.location.pathname.startsWith('/m');
      const isMobileUA = /android|iphone|ipad|ipod|mobile/i.test(navigator.userAgent);
      const isMobile = isMobilePath || isMobileUA;

      document.querySelectorAll('.env-device-badge').forEach(el => {
        if (isMobile) {
          el.innerHTML = '<i class="fa-solid fa-mobile-screen mr-1 text-[#C84B31]"></i>MOBILE';
          el.className = 'stamp-oli stamp-terracotta text-[8px] sm:text-[9px] font-mono-code font-bold env-device-badge select-none';
          el.title = 'Ambiente Rilevato: Smartphone / APK Mobile';
        } else {
          el.innerHTML = '<i class="fa-solid fa-desktop mr-1 text-[#3C5A48]"></i>DESKTOP';
          el.className = 'stamp-oli text-[8px] sm:text-[9px] font-mono-code font-bold env-device-badge select-none';
          el.title = 'Ambiente Rilevato: Computer / Desktop';
        }
      });

      document.querySelectorAll('.env-device-label').forEach(el => {
        el.textContent = isMobile ? 'MOBILE' : 'DESKTOP';
      });
    }
    syncDeviceEnvironment();
    window.syncDeviceEnvironment = syncDeviceEnvironment;
    document.addEventListener('DOMContentLoaded', syncDeviceEnvironment);
    window.addEventListener('resize', syncDeviceEnvironment);

    // --- Helper Autenticazione con Token Cifrato ---
    function authHeaders(extra = {}) {
      const token = sessionStorage.getItem('vault_token');
      const h = { ...extra };
      if (token) {
        h['X-Vault-Token'] = token;
      }
      return h;
    }
    const getAuthHeaders = authHeaders;
    window.getAuthHeaders = authHeaders;

    // --- Sincronizzazione Versione App Dinamica ---
    async function fetchAppVersion() {
      try {
        const res = await fetch('/api/version');
        if (res.ok) {
          const data = await res.json();
          if (data && data.version) {
            document.querySelectorAll('.app-version-badge').forEach(el => {
              el.textContent = 'v' + data.version;
            });
          }
        }
      } catch (err) {
        // Mantieni fallback statico
      }
    }
    fetchAppVersion();

    // --- Design Sistemico Olivetti Industrial ---
    function getActiveTheme() {
      return 'olivetti';
    }

    function setAppTheme(theme = 'olivetti') {
      const body = document.body;
      body.classList.add('theme-olivetti');
      localStorage.setItem('app_theme', 'olivetti');
    }

    // Inizializza subito il design sistemico Olivetti Industrial
    setAppTheme();

    // --- Gestione Sicurezza Caveau & Lock Screen ---
    function togglePasswordVisibility() {
      const pwd = document.getElementById('vaultPasswordInput');
      const icon = document.getElementById('eyeIcon');
      if (pwd && icon) {
        if (pwd.type === 'password') {
          pwd.type = 'text';
          icon.classList.remove('fa-eye');
          icon.classList.add('fa-eye-slash');
        } else {
          pwd.type = 'password';
          icon.classList.remove('fa-eye-slash');
          icon.classList.add('fa-eye');
        }
      }
    }

    async function checkVaultAuth() {
      const token = sessionStorage.getItem('vault_token');
      try {
        const res = await fetch('/api/auth/status', {
          headers: authHeaders()
        });
        if (res.ok) {
          const data = await res.json();
          if (data.unlocked && token) {
            hideLockScreen();
            initApp();
            return true;
          }
        }
      } catch (err) {
        console.error('Errore verifica stato caveau:', err);
      }
      showLockScreen();
      return false;
    }

    function showLockScreen() {
      const modal = document.getElementById('lockScreenModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        const pwdInput = document.getElementById('vaultPasswordInput');
        if (pwdInput) {
          pwdInput.value = '';
          setTimeout(() => pwdInput.focus(), 100);
        }
        const errEl = document.getElementById('lockScreenError');
        if (errEl) errEl.classList.add('hidden');
      }
    }

    function hideLockScreen() {
      const modal = document.getElementById('lockScreenModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    let vaultLockoutTimer = null;
    function startVaultLockoutCountdown(seconds) {
      window._vaultLockoutActive = true;
      const btn = document.getElementById('unlockVaultBtn');
      const pwdInput = document.getElementById('vaultPasswordInput');
      const errEl = document.getElementById('lockScreenError');
      const errText = document.getElementById('lockScreenErrorText');

      if (pwdInput) pwdInput.disabled = true;
      if (btn) btn.disabled = true;
      if (errEl) errEl.classList.remove('hidden');

      let remaining = Math.max(1, parseInt(seconds, 10) || 1);
      if (vaultLockoutTimer) clearInterval(vaultLockoutTimer);

      const renderCountdown = () => {
        if (btn) {
          btn.innerHTML = `<i class="fa-solid fa-hourglass-half animate-pulse mr-1.5"></i> Attendi ${remaining}s`;
        }
        if (errText) {
          errText.textContent = `Troppi tentativi errati o attesa di sicurezza. Riprova tra ${remaining}s...`;
        }
      };
      renderCountdown();

      vaultLockoutTimer = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
          clearInterval(vaultLockoutTimer);
          vaultLockoutTimer = null;
          window._vaultLockoutActive = false;
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i class="fa-solid fa-lock-open mr-1.5"></i> Sblocca Caveau`;
          }
          if (pwdInput) {
            pwdInput.disabled = false;
            pwdInput.focus();
            pwdInput.select();
          }
          if (errText) {
            errText.textContent = "Ora puoi riprovare ad inserire la password.";
          }
        } else {
          renderCountdown();
        }
      }, 1000);
    }

    async function unlockVault() {
      if (window._vaultLockoutActive) return;
      const pwdInput = document.getElementById('vaultPasswordInput');
      const errEl = document.getElementById('lockScreenError');
      const errText = document.getElementById('lockScreenErrorText');
      const btn = document.getElementById('unlockVaultBtn');
      const pwd = pwdInput ? pwdInput.value : '';

      if (!pwd) {
        if (errEl && errText) {
          errText.textContent = "Inserisci la password.";
          errEl.classList.remove('hidden');
        }
        return;
      }

      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-circle-notch animate-spin mr-1.5"></i> Sblocco in corso...`;
      }

      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: pwd })
        });
        if (!res.ok) {
          const retryAfter = res.headers.get('Retry-After');
          const errData = await res.json().catch(() => ({}));
          const waitSec = retryAfter ? parseInt(retryAfter, 10) : 0;
          if (res.status === 429 || (res.status === 401 && waitSec > 0)) {
            startVaultLockoutCountdown(waitSec || 30);
            return;
          }
          throw new Error(errData.detail || "Password non corretta. Riprova.");
        }
        const data = await res.json();
        sessionStorage.setItem('vault_token', data.token);
        hideLockScreen();
        initApp();
      } catch (err) {
        if (errEl && errText) {
          errText.textContent = err.message || "Password non corretta. Riprova.";
          errEl.classList.remove('hidden');
        }
        if (pwdInput) {
          pwdInput.focus();
          pwdInput.select();
        }
      } finally {
        if (btn && !window._vaultLockoutActive) {
          btn.disabled = false;
          btn.innerHTML = `<i class="fa-solid fa-lock-open mr-1.5"></i> Sblocca Caveau`;
        }
      }
    }

    async function lockVault() {
      try {
        await fetch('/api/auth/lock', {
          method: 'POST',
          headers: authHeaders()
        });
      } catch (e) {
        console.error('Errore lock vault:', e);
      }
      sessionStorage.removeItem('vault_token');
      showLockScreen();
    }

    // --- Gestione Foto Posizione Oggetti Fisici ---
    let pendingPhotoItemId = null;

    function promptUploadItemPhoto(itemId, itemName) {
      pendingPhotoItemId = itemId;
      const input = document.getElementById('itemPhotoInput');
      if (input) {
        input.value = '';
        input.click();
      }
    }

    async function handleItemPhotoSelected(event) {
      const file = event.target.files && event.target.files[0];
      if (!file || !pendingPhotoItemId) return;
      const itemId = pendingPhotoItemId;
      pendingPhotoItemId = null;

      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch(`/api/items/${itemId}/photo`, {
          method: 'POST',
          headers: authHeaders(),
          body: formData
        });
        if (!res.ok) throw new Error('Errore durante il caricamento della foto');
        const data = await res.json();

        loadDashboard(currentFilter);

        if (data.image_url) {
          appendAssistantBubble(
            `📸 **Foto memorizzata!** Ho salvato la foto della posizione per **${data.item_name}**.`,
            null,
            null,
            { item_name: data.item_name, image_url: data.image_url }
          );
        }
      } catch (err) {
        console.error('Errore caricamento foto:', err);
        alert('Impossibile salvare la foto: ' + err.message);
      }
    }

    function openCreateItemModal() {
      const modal = document.getElementById('createItemModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.getElementById('createItemForm').reset();
        clearNewItemPhoto();
        setTimeout(() => document.getElementById('newItemName').focus(), 100);
      }
    }

    function closeCreateItemModal() {
      const modal = document.getElementById('createItemModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function previewNewItemPhoto(event) {
      const file = event.target.files && event.target.files[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = (e) => {
          document.getElementById('newItemPhotoPreview').src = e.target.result;
          document.getElementById('newItemPhotoPreviewContainer').classList.remove('hidden');
        };
        reader.readAsDataURL(file);
      }
    }

    function clearNewItemPhoto() {
      const fileInput = document.getElementById('newItemPhotoFile');
      if (fileInput) fileInput.value = '';
      const previewCont = document.getElementById('newItemPhotoPreviewContainer');
      if (previewCont) previewCont.classList.add('hidden');
    }

    async function handleCreateItemSubmit(e) {
      e.preventDefault();
      const name = document.getElementById('newItemName').value.trim();
      const room = document.getElementById('newItemRoom').value.trim();
      const detail = document.getElementById('newItemDetail').value.trim();
      const category = document.getElementById('newItemCategory').value;
      const fileInput = document.getElementById('newItemPhotoFile');
      const file = fileInput.files && fileInput.files[0];

      if (!name || !room) {
        alert('Inserisci il nome dell\'oggetto e la stanza/ambiente.');
        return;
      }

      const btn = document.getElementById('saveNewItemBtn');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-circle-notch animate-spin mr-1"></i> Salvataggio...`;
      }

      const formData = new FormData();
      formData.append('item_name', name);
      formData.append('primary_location', room);
      if (detail) formData.append('detailed_location', detail);
      if (category) formData.append('category', category);
      formData.append('thread_id', currentThreadId);
      if (file) formData.append('file', file);

      try {
        const res = await fetch('/api/items/with-photo', {
          method: 'POST',
          headers: authHeaders(),
          body: formData
        });
        if (!res.ok) throw new Error('Errore durante la creazione dell\'oggetto');
        closeCreateItemModal();
        loadDashboard(currentFilter);
      } catch (err) {
        console.error('Errore create item with photo:', err);
        alert('Errore: ' + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i class="fa-solid fa-check text-xs"></i> Salva Oggetto`;
        }
      }
    }

    // --- Navigazione & Scorrimento Orizzontale a Slide tra Schermate (Slides Carousel) ---
    let isTransitioningScreens = false;
    let currentActiveScreen = 'chat'; // 'dashboard' | 'chat' | 'settings'

    const SCREEN_ORDER = {
      'dashboard': 0,
      'chat': 1,
      'settings': 2,
      'system': 2
    };

    function getScreenElement(name) {
      if (name === 'dashboard') return document.getElementById('dashboardView');
      if (name === 'settings' || name === 'system') return document.getElementById('systemView');
      return document.getElementById('chatView');
    }

    function updateAllBottomNavs(activeScreen) {
      const normActive = (activeScreen === 'system' || activeScreen === 'settings') ? 'settings' : activeScreen;
      document.querySelectorAll('.bottom-nav-bar').forEach(nav => {
        const btns = nav.querySelectorAll('button');
        btns.forEach(btn => {
          const oc = btn.getAttribute('onclick') || '';
          let isTarget = false;
          if (normActive === 'dashboard' && oc.includes("'dashboard'")) isTarget = true;
          if (normActive === 'chat' && oc.includes("'chat'")) isTarget = true;
          if (normActive === 'settings' && (oc.includes("'settings'") || oc.includes("'system'"))) isTarget = true;

          if (isTarget) {
            btn.classList.add('text-[#3C5A48]', 'font-bold');
            btn.classList.remove('text-[#7A7568]', 'hover:text-[#222220]');
          } else {
            btn.classList.remove('text-[#3C5A48]', 'font-bold');
            btn.classList.add('text-[#7A7568]', 'hover:text-[#222220]');
          }
        });
      });
    }

    function slideToScreen(targetScreen, onComplete = null) {
      const normalizedTarget = (targetScreen === 'system') ? 'settings' : targetScreen;
      const normalizedCurrent = (currentActiveScreen === 'system') ? 'settings' : currentActiveScreen;

      // Se siamo già nella schermata richiesta
      if (normalizedCurrent === normalizedTarget) {
        if (typeof onComplete === 'function') onComplete();
        return;
      }

      if (isTransitioningScreens) return;
      isTransitioningScreens = true;

      const fromEl = getScreenElement(normalizedCurrent);
      const toEl = getScreenElement(normalizedTarget);

      if (!fromEl || !toEl) {
        isTransitioningScreens = false;
        return;
      }

      // Aggiorna subito lo stato attivo della barra inferiore fissa
      updateAllBottomNavs(normalizedTarget);

      const fromIndex = SCREEN_ORDER[normalizedCurrent] ?? 1;
      const toIndex = SCREEN_ORDER[normalizedTarget] ?? 1;
      const movingForward = toIndex > fromIndex; // true: verso destra (slides scorrono a sinistra), false: verso sinistra (slides scorrono a destra)

      // Pre-caricamento dati per la schermata di destinazione
      if (normalizedTarget === 'dashboard') {
        renderDashboardView();
        loadDashboard(currentFilter);
      } else if (normalizedTarget === 'settings') {
        loadAiModelSetting();
        loadOpenRouterCredits();
        loadGoogleDriveStatus();
        loadWatchedFolders();
      } else if (normalizedTarget === 'chat') {
        if (isMobileView) {
          if (conversationPanel.classList.contains('mobile-active')) {
            _mobileShowConversation(false);
          } else {
            _mobileShowSidebar(false);
          }
        } else {
          applyLayout();
        }
      }

      const startIncomingX = movingForward ? '100%' : '-100%';
      const endOutgoingX = movingForward ? '-100%' : '100%';

      // 1. Prepara il container di destinazione all'offset di partenza
      toEl.classList.remove('hidden');
      toEl.classList.add('flex');
      toEl.style.zIndex = '20';
      toEl.style.transform = `translate3d(${startIncomingX}, 0, 0)`;
      toEl.style.transition = 'none';

      // 2. Prepara la schermata corrente come livello sottostante
      fromEl.style.zIndex = '10';
      fromEl.style.transform = 'translate3d(0, 0, 0)';
      fromEl.style.transition = 'none';

      // 3. Avvia lo scorrimento orizzontale sincronizzato tra le due schermate (effetto slide fluido)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const slideEasing = 'transform 0.35s cubic-bezier(0.25, 1, 0.5, 1)';
          toEl.style.transition = slideEasing;
          fromEl.style.transition = slideEasing;

          toEl.style.transform = 'translate3d(0, 0, 0)';
          fromEl.style.transform = `translate3d(${endOutgoingX}, 0, 0)`;

          setTimeout(() => {
            // 4. Pulizia al termine dello scorrimento
            fromEl.classList.add('hidden');
            fromEl.classList.remove('flex');
            fromEl.style.zIndex = '';
            fromEl.style.transform = '';
            fromEl.style.transition = '';

            toEl.style.zIndex = '';
            toEl.style.transform = '';
            toEl.style.transition = '';

            currentActiveScreen = normalizedTarget;
            isTransitioningScreens = false;

            updateAllBottomNavs(normalizedTarget);

            if (typeof onComplete === 'function') {
              onComplete();
            }
          }, 360);
        });
      });
    }

    function openDashboard(filter = null) {
      slideToScreen('dashboard', () => {
        if (filter) filterTable(filter);
      });
    }

    function openSystem() {
      slideToScreen('settings');
    }

    function closeToChat() {
      slideToScreen('chat');
    }

    function closeDashboard() {
      slideToScreen('chat');
    }

    function switchScreen(screen) {
      if (screen === 'dashboard') {
        openDashboard('all');
      } else if (screen === 'chat') {
        closeToChat();
      } else if (screen === 'archive') {
        openDashboard('items');
      } else if (screen === 'settings' || screen === 'system') {
        openSystem();
      }
    }

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
        const timeStr = t.last_message_time || '';

        // Badge rotella che gira sull'avatar del thread quando l'assistente sta lavorando
        const avatarSpinner = activeTask ? `
          <span class="absolute -bottom-1 -right-1 w-5 h-5 bg-white rounded-full flex items-center justify-center shadow-xs ring-1 ring-[#C84B31] z-10" title="${escapeHtml(activeTask.statusText || 'In elaborazione...')}">
            <i class="fa-solid fa-circle-notch text-[#C84B31] text-[11px] animate-spin"></i>
          </span>
        ` : '';

        let previewHtml = '';
        let rightPillHtml = '';

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
          rightPillHtml = `
            <span class="stamp-oli stamp-terracotta text-[8px] flex items-center gap-1 shrink-0 animate-pulse">
              <span class="w-1.5 h-1.5 rounded-full bg-[#C84B31] animate-ping"></span>
              <span>AI</span>
            </span>
          `;
        } else {
          previewHtml = `
            <p class="text-[11px] text-[#7A7568] truncate leading-tight flex-1 overflow-hidden whitespace-nowrap block font-mono-code" title="${escapeHtml(cleanPreview)}">${escapeHtml(cleanPreview)}</p>
          `;
          rightPillHtml = `<span class="text-[10px] text-[#7A7568] shrink-0 font-mono-code">${escapeHtml(timeStr)}</span>`;
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

    async function switchThread(threadId, fetchMessages = true) {
      currentThreadId = threadId;
      if (typeof cancelQuoteReply === 'function') cancelQuoteReply();
      deadlineBannerDismissed = false;
      const thread = threadsCache.find(t => t.id === threadId);
      if (thread) {
        updateActiveThreadHeader(thread);
      }
      renderThreadsList();
      showConversation();
      checkDeadlineAlerts(threadId);

      if (fetchMessages) {
        await loadThreadMessages(threadId);
      }
    }

    function updateActiveThreadHeader(thread) {
      const titleEl = document.getElementById('activeThreadTitle');
      const subEl = document.getElementById('activeThreadSubtitle');
      const iconEl = document.getElementById('activeThreadIcon');
      const avatarEl = document.getElementById('activeThreadAvatar');
      const delBtn = document.getElementById('deleteThreadBtn');

      if (titleEl) titleEl.textContent = thread.name;
      if (iconEl) iconEl.className = `fa-solid ${thread.icon || 'fa-compass'}`;
      if (avatarEl) {
        const isOli = getActiveTheme() === 'olivetti';
        avatarEl.className = isOli
          ? `w-8 h-8 rounded-xs flex items-center justify-center text-white text-xs font-bold border border-[#E3DDD1] shadow-xs shrink-0 ${thread.color || 'bg-[#3C5A48]'}`
          : `w-10 h-10 rounded-full flex items-center justify-center text-white text-base font-bold border border-white/20 shrink-0 ${thread.color || 'bg-[#128C7E]'}`;
      }

      if (subEl) {
        if (thread.thread_type === 'group') {
          const mList = thread.members && thread.members.length > 0 ? thread.members.join(', ') : 'Io';
          subEl.textContent = `Membri: ${mList} • online`;
        } else {
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

        const dateStr = new Date().toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).toUpperCase();
        chatFeed.innerHTML = `
          <div class="text-center my-2 select-none">
            <span class="stamp-oli text-[8px] text-[#7A7568] border-[#D8D2C4]">REGISTRO SESSIONE • ${dateStr}</span>
          </div>
        `;

        for (const m of msgs) {
          if (m.sender === 'user') {
            const quoted = m.metadata && m.metadata.quoted_message ? m.metadata.quoted_message : null;
            if (m.message_type === 'audio' && m.metadata && m.metadata.audio_url) {
              const trText = m.metadata.transcription || (m.content && m.content.startsWith('🎤 ') ? m.content.slice(2).trim() : null);
              appendUserAudioBubble(m.metadata.audio_url, m.metadata.duration || 0, quoted, trText);
            } else {
              appendUserBubble(m.content, quoted);
            }
          } else {
            const docs = m.metadata && m.metadata.documents ? m.metadata.documents : null;
            const conf = m.metadata && m.metadata.confirmation ? m.metadata.confirmation : null;
            const itemPhoto = m.metadata && m.metadata.item_photo ? m.metadata.item_photo : null;
            const storeItem = m.metadata && m.metadata.store_item ? m.metadata.store_item : null;
            const proposal = (m.metadata && m.metadata.proposal) || (m.metadata && m.metadata.action === 'SENSITIVE_FILE_PROPOSAL' ? m.metadata.proposal : null);
            const routedModel = (m.metadata && m.metadata.routed_model) || null;
            appendAssistantBubble(m.content, docs, conf, itemPhoto, storeItem, proposal, routedModel);
          }
        }
        scrollBottom();

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

    // --- Sistema Responsivo Mobile/Desktop ---

    const MOBILE_BREAKPOINT = 768;
    let isMobileView = window.innerWidth < MOBILE_BREAKPOINT;

    function applyLayout() {
      const mobile = window.innerWidth < MOBILE_BREAKPOINT;
      isMobileView = mobile;

      if (mobile) {
        // ── MOBILE ── layout a singolo pannello sovrapposto
        // Sidebar: posizione assoluta, larghezza 100%, sovrapposta
        sidebarPanel.style.cssText = `
          position: absolute;
          top: 0; left: 0;
          width: 100%;
          height: 100%;
          display: flex;
          flex-direction: column;
          z-index: 20;
        `;
        // ConversationPanel: posizione assoluta, larghezza 100%
        conversationPanel.style.cssText = `
          position: absolute;
          top: 0; left: 0;
          width: 100%;
          height: 100%;
          display: flex;
          flex-direction: column;
          z-index: 10;
        `;
        // Stato iniziale: mostra sidebar, nascondi conversazione
        // (gestito da mobileShowSidebar / mobileShowConversation)
        if (!conversationPanel.classList.contains('mobile-active')) {
          _mobileShowSidebar(false);
        } else {
          _mobileShowConversation(false);
        }
      } else {
        // ── DESKTOP ── layout affiancato
        sidebarPanel.style.cssText = `
          position: relative;
          width: 350px;
          min-width: 350px;
          max-width: 390px;
          height: 100%;
          display: flex;
          flex-direction: column;
          z-index: 10;
          transform: none;
          opacity: 1;
        `;
        conversationPanel.style.cssText = `
          position: relative;
          flex: 1;
          height: 100%;
          display: flex;
          flex-direction: column;
          z-index: 10;
          transform: none;
          opacity: 1;
        `;
        sidebarPanel.classList.remove('mobile-active');
        conversationPanel.classList.remove('mobile-active');
      }
    }

    function _mobileShowSidebar(animate) {
      // Sidebar visibile (sopra, z-index più alto)
      sidebarPanel.style.zIndex = '20';
      conversationPanel.style.zIndex = '10';
      sidebarPanel.classList.add('mobile-active');
      conversationPanel.classList.remove('mobile-active');

      if (animate) {
        sidebarPanel.style.transform = 'translateX(-100%)';
        sidebarPanel.style.opacity = '0';
        requestAnimationFrame(() => {
          sidebarPanel.style.transition = 'transform 0.28s cubic-bezier(.4,0,.2,1), opacity 0.25s ease';
          sidebarPanel.style.transform = 'translateX(0)';
          sidebarPanel.style.opacity = '1';
          conversationPanel.style.transition = 'transform 0.28s cubic-bezier(.4,0,.2,1)';
          conversationPanel.style.transform = 'translateX(20px)';
          conversationPanel.style.opacity = '0.4';
        });
      } else {
        sidebarPanel.style.transition = 'none';
        sidebarPanel.style.transform = 'translateX(0)';
        sidebarPanel.style.opacity = '1';
        conversationPanel.style.transition = 'none';
        conversationPanel.style.transform = 'translateX(20px)';
        conversationPanel.style.opacity = '0.4';
      }
    }

    function _mobileShowConversation(animate) {
      // Conversazione visibile (sopra, z-index più alto)
      sidebarPanel.style.zIndex = '10';
      conversationPanel.style.zIndex = '20';
      conversationPanel.classList.add('mobile-active');
      sidebarPanel.classList.remove('mobile-active');

      if (animate) {
        conversationPanel.style.transform = 'translateX(100%)';
        conversationPanel.style.opacity = '0';
        requestAnimationFrame(() => {
          conversationPanel.style.transition = 'transform 0.28s cubic-bezier(.4,0,.2,1), opacity 0.22s ease';
          conversationPanel.style.transform = 'translateX(0)';
          conversationPanel.style.opacity = '1';
          sidebarPanel.style.transition = 'transform 0.28s cubic-bezier(.4,0,.2,1)';
          sidebarPanel.style.transform = 'translateX(-20px)';
          sidebarPanel.style.opacity = '0.4';
        });
      } else {
        conversationPanel.style.transition = 'none';
        conversationPanel.style.transform = 'translateX(0)';
        conversationPanel.style.opacity = '1';
        sidebarPanel.style.transition = 'none';
        sidebarPanel.style.transform = 'translateX(-20px)';
        sidebarPanel.style.opacity = '0.4';
      }
    }

    function showThreadsSidebar() {
      if (isMobileView) {
        _mobileShowSidebar(true);
      }
      // Su desktop non fa nulla — entrambi i pannelli sono sempre visibili
    }

    function showConversation() {
      if (isMobileView) {
        _mobileShowConversation(true);
      }
    }

    // Listener resize e orientamento — ricalcola layout
    let resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(applyLayout, 80);
    });
    window.addEventListener('orientationchange', () => {
      setTimeout(applyLayout, 200);
    });

    // --- Gestione Modale Nuovo Thread / Gruppo ---
    function openNewThreadModal() {
      const modal = document.getElementById('newThreadModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        selectThreadType('group');
        document.getElementById('threadNameInput').value = '';
        document.getElementById('threadMembersInput').value = '';
        document.getElementById('threadDescInput').value = '';
        document.getElementById('threadNameInput').focus();
      }
    }

    function closeNewThreadModal() {
      const modal = document.getElementById('newThreadModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function selectThreadType(type) {
      newThreadType = type;
      const tabGroup = document.getElementById('tabTypeGroup');
      const tabThematic = document.getElementById('tabTypeThematic');
      const groupGroup = document.getElementById('groupMembersGroup');
      const thematicGroup = document.getElementById('thematicIconGroup');
      const labelName = document.getElementById('labelThreadName');
      const nameInput = document.getElementById('threadNameInput');

      if (type === 'group') {
        tabGroup.className = 'py-2 text-xs font-semibold rounded-lg transition bg-white text-slate-900 shadow-xs flex items-center justify-center gap-1.5';
        tabThematic.className = 'py-2 text-xs font-semibold rounded-lg transition text-slate-500 hover:text-slate-900 flex items-center justify-center gap-1.5';
        groupGroup.classList.remove('hidden');
        thematicGroup.classList.add('hidden');
        labelName.textContent = 'Nome del Gruppo';
        nameInput.placeholder = 'Es. Famiglia, Condominio, Amici Vacanze...';
      } else {
        tabThematic.className = 'py-2 text-xs font-semibold rounded-lg transition bg-white text-slate-900 shadow-xs flex items-center justify-center gap-1.5';
        tabGroup.className = 'py-2 text-xs font-semibold rounded-lg transition text-slate-500 hover:text-slate-900 flex items-center justify-center gap-1.5';
        groupGroup.classList.add('hidden');
        thematicGroup.classList.remove('hidden');
        labelName.textContent = 'Nome dell\'Area Tematica';
        nameInput.placeholder = 'Es. Lavoro, Fisco & Tasse, Auto & Moto...';
      }
    }

    function selectThematicIcon(icon) {
      selectedThematicIcon = icon;
      document.querySelectorAll('.icon-choice').forEach(btn => {
        if (btn.getAttribute('data-icon') === icon) {
          btn.classList.add('border-[#128C7E]', 'bg-emerald-50');
        } else {
          btn.classList.remove('border-[#128C7E]', 'bg-emerald-50');
        }
      });
    }

    async function handleCreateThread(e) {
      if (e) e.preventDefault();
      const name = (document.getElementById('threadNameInput')?.value || '').trim();
      if (!name) return;

      const desc = (document.getElementById('threadDescInput')?.value || '').trim();
      let members = [];
      if (newThreadType === 'group') {
        const rawM = (document.getElementById('threadMembersInput')?.value || '').trim();
        members = rawM ? rawM.split(',').map(m => m.trim()).filter(m => m.length > 0) : ['Io'];
      }

      let icon = newThreadType === 'group' ? 'fa-users' : selectedThematicIcon;
      let color = newThreadType === 'group' ? 'bg-emerald-600' : 'bg-indigo-600';
      if (icon === 'fa-house') color = 'bg-amber-600';
      if (icon === 'fa-car') color = 'bg-blue-600';
      if (icon === 'fa-heart-pulse') color = 'bg-rose-600';
      if (icon === 'fa-receipt') color = 'bg-emerald-700';

      try {
        const res = await fetch('/api/threads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: name,
            thread_type: newThreadType,
            icon: icon,
            color: color,
            description: desc,
            members: members
          })
        });

        if (!res.ok) throw new Error("Errore durante la creazione dello spazio");
        const newThread = await res.json();
        closeNewThreadModal();
        await loadThreads();
        await switchThread(newThread.id);
      } catch (err) {
        console.error("Errore handleCreateThread:", err);
        alert("Errore durante la creazione del gruppo o area: " + err.message);
      }
    }

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

    // --- Google Drive Cloud Sync Handlers ---
    let googleDriveStatusCache = null;

    function openGoogleDriveModal() {
      const modal = document.getElementById('googleDriveModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        loadGoogleDriveStatus();
      }
    }

    function closeGoogleDriveModal() {
      const modal = document.getElementById('googleDriveModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    async function loadGoogleDriveStatus() {
      const loadingEl = document.getElementById('driveLoadingState');
      const disconnectedEl = document.getElementById('driveDisconnectedState');
      const connectedEl = document.getElementById('driveConnectedState');
      const emailEl = document.getElementById('driveConnectedEmail');
      const toolsBadge = document.getElementById('toolsDriveBadge');

      if (loadingEl) loadingEl.classList.remove('hidden');
      if (disconnectedEl) disconnectedEl.classList.add('hidden');
      if (connectedEl) connectedEl.classList.add('hidden');

      try {
        const res = await fetch('/api/drive/status', {
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore recupero stato Google Drive");
        const data = await res.json();
        googleDriveStatusCache = data;

        if (loadingEl) loadingEl.classList.add('hidden');

        if (data.connected) {
          if (connectedEl) connectedEl.classList.remove('hidden');
          if (disconnectedEl) disconnectedEl.classList.add('hidden');
          if (emailEl) emailEl.textContent = data.user_email || 'Account Google';

          const targetMode = data.storage_mode || 'dual';
          const radio = document.querySelector(`input[name="driveStorageMode"][value="${targetMode}"]`);
          if (radio) radio.checked = true;

          if (toolsBadge) {
            toolsBadge.classList.remove('hidden');
          }

          const kpiDriveEl = document.getElementById('kpiDriveState');
          if (kpiDriveEl) {
            let label = 'DUAL';
            if (targetMode === 'cloud_only') label = 'CLOUD';
            else if (targetMode === 'local_only') label = 'LOCALE';
            kpiDriveEl.textContent = label;
            kpiDriveEl.className = "text-2xl sm:text-3xl lg:text-4xl font-black tracking-tight text-[#3C5A48] font-mono-code leading-none";
          }
          const kpiDriveDot = document.getElementById('kpiDriveDot');
          if (kpiDriveDot) {
            kpiDriveDot.className = "w-2.5 h-2.5 rounded-full bg-emerald-600 animate-pulse";
          }
        } else {
          if (connectedEl) connectedEl.classList.add('hidden');
          if (disconnectedEl) disconnectedEl.classList.remove('hidden');
          if (toolsBadge) {
            toolsBadge.classList.add('hidden');
          }

          const kpiDriveEl = document.getElementById('kpiDriveState');
          if (kpiDriveEl) {
            kpiDriveEl.textContent = "LOCALE";
            kpiDriveEl.className = "text-2xl sm:text-3xl lg:text-4xl font-black tracking-tight text-[#7A7568] font-mono-code leading-none";
          }
          const kpiDriveDot = document.getElementById('kpiDriveDot');
          if (kpiDriveDot) {
            kpiDriveDot.className = "w-2.5 h-2.5 rounded-full bg-slate-400";
          }
        }
      } catch (err) {
        console.error("Errore loadGoogleDriveStatus:", err);
        if (loadingEl) loadingEl.classList.add('hidden');
        if (disconnectedEl) disconnectedEl.classList.remove('hidden');
      }
    }

    async function connectGoogleDrive() {
      try {
        const res = await fetch('/api/drive/auth-url', {
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore recupero URL di autorizzazione");
        const data = await res.json();
        if (data.auth_url) {
          window.open(data.auth_url, 'google_oauth', 'width=600,height=700');
        } else {
          throw new Error("URL autorizzazione non valido");
        }
      } catch (err) {
        console.error("Errore connectGoogleDrive:", err);
        showToast("⚠️ Impossibile avviare il collegamento con Google Drive", "error");
      }
    }

    async function disconnectGoogleDrive() {
      if (!confirm("Sei sicuro di voler disconnettere il tuo account Google Drive?")) {
        return;
      }
      try {
        const res = await fetch('/api/drive/disconnect', {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore durante la disconnessione");
        await loadGoogleDriveStatus();
        showToast("Google Drive disconnesso con successo", "info");
      } catch (err) {
        console.error("Errore disconnectGoogleDrive:", err);
        showToast("⚠️ Errore durante la disconnessione di Google Drive", "error");
      }
    }

    async function updateDriveStorageMode(mode) {
      try {
        const res = await fetch('/api/drive/settings', {
          method: 'PATCH',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ storage_mode: mode })
        });
        if (!res.ok) throw new Error("Errore aggiornamento impostazioni Google Drive");
        const data = await res.json();
        if (googleDriveStatusCache) {
          googleDriveStatusCache.storage_mode = data.storage_mode;
        }
        const kpiDriveEl = document.getElementById('kpiDriveState');
        if (kpiDriveEl) {
          let label = 'DUAL';
          if (data.storage_mode === 'cloud_only') label = 'CLOUD';
          else if (data.storage_mode === 'local_only') label = 'LOCALE';
          kpiDriveEl.textContent = label;
        }
        showToast("Modalità archiviazione aggiornata", "success");
      } catch (err) {
        console.error("Errore updateDriveStorageMode:", err);
        showToast("⚠️ Impossibile aggiornare la modalità di archiviazione", "error");
        loadGoogleDriveStatus();
      }
    }

    // Window message listener per popup OAuth
    window.addEventListener('message', (e) => {
      if (e.origin !== window.location.origin) return;
      if (e.data && (e.data.type === 'google_drive_auth_success' || e.data.type === 'GOOGLE_DRIVE_AUTH_SUCCESS')) {
        loadGoogleDriveStatus();
        showToast(`🟢 Google Drive collegato con successo!`, 'success');
      }
    });

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

    // --- Toggle Tasto Invio / Microfono ---
    input.addEventListener('input', () => {
      if (isGenerationActive) return;
      if (input.value.trim().length > 0) {
        micBtn.classList.add('hidden');
        sendBtn.classList.remove('hidden');
        sendBtn.classList.add('flex');
      } else {
        micBtn.classList.remove('hidden');
        sendBtn.classList.add('hidden');
        sendBtn.classList.remove('flex');
      }
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && typeof cancelQuoteReply === 'function') {
        cancelQuoteReply();
      }
    });

    function updateScrollToBottomVisibility() {
      if (!chatFeed || !scrollToBottomBtn) return;
      const distanceFromBottom = chatFeed.scrollHeight - chatFeed.scrollTop - chatFeed.clientHeight;
      if (distanceFromBottom > 140) {
        scrollToBottomBtn.classList.remove('hidden');
      } else {
        scrollToBottomBtn.classList.add('hidden');
        if (scrollUnreadBadge) scrollUnreadBadge.classList.add('hidden');
      }
    }

    if (chatFeed) {
      chatFeed.addEventListener('scroll', updateScrollToBottomVisibility, { passive: true });
    }

    function scrollToBottom(smooth = false) {
      if (!chatFeed) return;
      if (smooth) {
        chatFeed.scrollTo({ top: chatFeed.scrollHeight, behavior: 'smooth' });
      } else {
        chatFeed.scrollTop = chatFeed.scrollHeight;
      }
      if (scrollToBottomBtn) scrollToBottomBtn.classList.add('hidden');
      if (scrollUnreadBadge) scrollUnreadBadge.classList.add('hidden');
    }
    window.scrollToBottom = scrollToBottom;

    function scrollBottom(force = false) {
      if (!chatFeed) return;
      const distanceFromBottom = chatFeed.scrollHeight - chatFeed.scrollTop - chatFeed.clientHeight;
      if (force || distanceFromBottom <= 140) {
        chatFeed.scrollTop = chatFeed.scrollHeight;
        if (scrollToBottomBtn) scrollToBottomBtn.classList.add('hidden');
        if (scrollUnreadBadge) scrollUnreadBadge.classList.add('hidden');
      } else {
        if (scrollToBottomBtn) {
          scrollToBottomBtn.classList.remove('hidden');
          if (scrollUnreadBadge) scrollUnreadBadge.classList.remove('hidden');
        }
      }
    }

    function getTime() {
      const d = new Date();
      return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
    }

    function escapeHtml(string) {
      if (!string) return '';
      return String(string).replace(/[&<>"']/g, function (s) {
        return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[s];
      });
    }

    // Formattazione markdown completa per la chat: gestisce titoli (###), divisori (---), elenchi puntati (*, -), numerati (1.), grassetto (** o *), corsivo (_) e blocchi codice
    function formatMessageText(text) {
      if (!text) return '';
      let cleanRaw = sanitizeAssistantText(text);
      if (!cleanRaw) return '';
      let formatted = escapeHtml(cleanRaw);

      // 1. Blocchi di codice (```code```)
      formatted = formatted.replace(/```(?:[a-zA-Z0-9_\-]+)?\n?([\s\S]*?)```/g, '<pre class="bg-slate-800 text-emerald-300 p-2.5 rounded-lg text-xs font-mono overflow-x-auto my-2 leading-relaxed">$1</pre>');

      // 2. Divisori orizzontali (--- o *** o ___ su riga singola)
      formatted = formatted.replace(/^(?:-{3,}|_{3,}|\*{3,})$/gm, '<hr class="my-2.5 border-t border-slate-200/90">');

      // 3. Intestazioni / Titoli Markdown (#, ##, ###, ####)
      formatted = formatted.replace(/^####\s+(.+)$/gm, '<h4 class="font-bold text-slate-900 text-xs mt-2.5 mb-1">$1</h4>');
      formatted = formatted.replace(/^###\s+(.+)$/gm, '<h3 class="font-bold text-slate-900 text-xs mt-2.5 mb-1">$1</h3>');
      formatted = formatted.replace(/^##\s+(.+)$/gm, '<h2 class="font-bold text-slate-900 text-sm mt-3 mb-1">$1</h2>');
      formatted = formatted.replace(/^#\s+(.+)$/gm, '<h1 class="font-extrabold text-slate-900 text-sm mt-3.5 mb-1.5">$1</h1>');

      // 4. Citazioni / Blockquote (> testo)
      formatted = formatted.replace(/^(?:&gt;|>)\s+(.+)$/gm, '<blockquote class="border-l-2 border-[#075E54] pl-2.5 my-1.5 text-slate-600 italic text-xs bg-slate-50 py-1 rounded-r">$1</blockquote>');

      // 5. Elenchi puntati (* elemento, - elemento, • elemento, + elemento)
      formatted = formatted.replace(/^[\s]*[\*\-•\+]\s+(.+)$/gm, '<div class="flex items-start gap-1.5 my-0.5"><span class="text-emerald-700 font-bold shrink-0 leading-tight">•</span><span class="flex-1 min-w-0 leading-snug">$1</span></div>');

      // 6. Elenchi numerati (1. elemento, 2. elemento)
      formatted = formatted.replace(/^[\s]*(\d+)\.\s+(.+)$/gm, '<div class="flex items-start gap-1.5 my-0.5"><span class="text-emerald-800 font-bold shrink-0 text-xs">$1.</span><span class="flex-1 min-w-0 leading-snug">$2</span></div>');

      // 7. Codice inline (`codice`)
      formatted = formatted.replace(/`([^`\n]+)`/g, '<code class="bg-black/5 text-slate-800 px-1 py-0.5 rounded font-mono text-xs">$1</code>');

      // 8. Doppi asterischi o doppi underscore (**grassetto** / __grassetto__)
      formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong class="font-bold text-slate-900 bg-amber-100/40 px-1 py-0.5 rounded-sm">$1</strong>');
      formatted = formatted.replace(/__(.+?)__/g, '<strong class="font-bold text-slate-900 bg-amber-100/40 px-1 py-0.5 rounded-sm">$1</strong>');

      // 9. Singolo asterisco (*grassetto*) e singolo underscore (_corsivo_)
      formatted = formatted.replace(/(^|[^\*])\*([^\*\n]+?)\*([^\*]|$)/g, '$1<strong class="font-bold text-slate-900">$2</strong>$3');
      formatted = formatted.replace(/(^|[^_])_([^_\n]+?)_([^_]|$)/g, '$1<em class="italic text-slate-700">$2</em>$3');
      formatted = formatted.replace(/(^|[^~])~([^~\n]+?)~([^~]|$)/g, '$1<del class="line-through text-slate-400">$2</del>$3');

      // 10. Nuove linee (evitando doppi a capo dopo blocchi contenitore)
      formatted = formatted.replace(/\n/g, '<br>');
      formatted = formatted.replace(/(<\/(?:h[1-4]|div|blockquote|pre|hr)>)<br>/gi, '$1');

      return formatted;
    }

    function formatFileSize(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    // --- Canale di Feedback & Telemetria Silenziosa Frontend-to-Backend ---
    function sendUITelemetry(eventType, details = {}) {
      try {
        const payload = {
          thread_id: (typeof currentThreadId !== 'undefined' && currentThreadId) ? currentThreadId : 'general',
          event_type: eventType,
          target_type: details.target_type || 'document',
          target_id: details.target_id || null,
          title: details.title || null,
          error_details: details.error_details || null
        };
        fetch('/api/telemetry/ui-event', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(typeof authHeaders === 'function' ? authHeaders() : {})
          },
          body: JSON.stringify(payload),
          keepalive: true
        }).catch(() => {});
      } catch (e) {
        // Fallback non-bloccante
      }
    }

    // --- Funzioni Copia Testo & Appunti ---
    function copyMessageText(btnEl) {
      if (!btnEl) return;
      const bubble = btnEl.closest('.wa-bubble-in, .wa-bubble-out');
      if (!bubble) return;
      const bodyEl = bubble.querySelector('.message-body') || bubble.querySelector('p');
      const textToCopy = (bodyEl ? (bodyEl.innerText || bodyEl.textContent) : (bubble.innerText || bubble.textContent)) || '';
      copyTextToClipboard(textToCopy, btnEl);
    }

    function copyTextToClipboard(text, btnEl = null) {
      if (!text) return;
      const clean = text.trim();

      const showFeedback = () => {
        if (btnEl) {
          const icon = btnEl.querySelector('i') || btnEl;
          const oldClass = icon.className;
          icon.className = 'fa-solid fa-check text-emerald-600';
          btnEl.classList.add('text-emerald-600');
          setTimeout(() => {
            icon.className = oldClass;
            btnEl.classList.remove('text-emerald-600');
          }, 1600);
        }
      };

      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(clean).then(showFeedback).catch(() => {
          fallbackCopyText(clean, showFeedback);
        });
      } else {
        fallbackCopyText(clean, showFeedback);
      }
    }

    function fallbackCopyText(text, callback) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.top = '-9999px';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        if (callback) callback();
      } catch (err) {
        console.error('Errore fallback copy:', err);
      }
    }

    // --- Gestione Interruzione Generazione (Stop Button) & Indicatori UI per Thread ---
    let activeAbortController = null;
    let isGenerationActive = false;

    function syncInputControlsForCurrentThread() {
      const isTargetActive = !!activeThreadTasks[currentThreadId];
      isGenerationActive = isTargetActive;
      activeAbortController = isTargetActive ? activeThreadTasks[currentThreadId].abortController : null;

      const stopBtn = document.getElementById('stopBtn');
      const micBtn = document.getElementById('micBtn');
      const sendBtn = document.getElementById('sendBtn');

      if (isTargetActive) {
        if (stopBtn) {
          stopBtn.classList.remove('hidden');
          stopBtn.classList.add('flex');
        }
        if (micBtn) micBtn.classList.add('hidden');
        if (sendBtn) {
          sendBtn.classList.add('hidden');
          sendBtn.classList.remove('flex');
        }
      } else {
        if (stopBtn) {
          stopBtn.classList.add('hidden');
          stopBtn.classList.remove('flex');
        }
        if (input && input.value && input.value.trim().length > 0) {
          if (micBtn) micBtn.classList.add('hidden');
          if (sendBtn) {
            sendBtn.classList.remove('hidden');
            sendBtn.classList.add('flex');
          }
        } else {
          if (micBtn) micBtn.classList.remove('hidden');
          if (sendBtn) {
            sendBtn.classList.add('hidden');
            sendBtn.classList.remove('flex');
          }
        }
      }
    }

    function setGenerationActive(active, statusText = "", progressPercent = null, threadId = null) {
      const targetId = threadId || currentThreadId;
      if (active) {
        let task = activeThreadTasks[targetId];
        if (!task) {
          task = {
            abortController: new AbortController(),
            startedAt: Date.now()
          };
          activeThreadTasks[targetId] = task;
        }
        task.statusText = statusText;
        task.progressPercent = progressPercent;
      } else {
        delete activeThreadTasks[targetId];
      }

      syncInputControlsForCurrentThread();

      if (targetId === currentThreadId) {
        if (active) {
          showTypingIndicator(statusText, progressPercent);
        } else {
          hideTypingIndicator();
        }
      }

      renderThreadsList();
    }

    function abortGeneration(threadId = null) {
      const targetId = threadId || currentThreadId;
      const task = activeThreadTasks[targetId];
      if (task) {
        if (task.abortController) {
          try {
            task.abortController.abort();
          } catch (e) {
            console.warn('Abort error:', e);
          }
        }
        delete activeThreadTasks[targetId];
      }
      syncInputControlsForCurrentThread();
      if (targetId === currentThreadId) {
        hideTypingIndicator();
        appendAssistantBubble("⏹️ *Generazione/elaborazione interrotta dall'utente.*");
      }
      renderThreadsList();
    }

    // --- Sistema Notifiche & Schede Protocollo Toast (Olivetti Industrial) ---
    function showToast(message, type = 'info', duration = 4000) {
      const container = document.getElementById('toastContainer');
      if (!container) return;

      const toast = document.createElement('div');
      toast.className = 'pointer-events-auto bg-white rounded-xs border-2 p-3 shadow-xl transition-all duration-300 transform translate-y-3 opacity-0 select-text';

      let borderColor = 'border-[#3C5A48]';
      let iconBg = 'bg-[#EBF1ED] text-[#3C5A48] border-[#3C5A48]/40';
      let iconHtml = '<i class="fa-solid fa-bell text-xs"></i>';
      let stampText = 'REGISTRO CAVEAU';
      let stampClass = 'stamp-solid-sage';

      if (type === 'success') {
        borderColor = 'border-[#3C5A48]';
        iconBg = 'bg-[#EBF1ED] text-[#3C5A48] border-[#3C5A48]/40';
        iconHtml = '<i class="fa-solid fa-check text-xs"></i>';
        stampText = 'OPERAZIONE COMPLETATA';
        stampClass = 'stamp-solid-sage';
      } else if (type === 'error') {
        borderColor = 'border-[#C84B31]';
        iconBg = 'bg-[#FAECE8] text-[#C84B31] border-[#C84B31]/40';
        iconHtml = '<i class="fa-solid fa-triangle-exclamation text-xs"></i>';
        stampText = 'AVVISO DI SISTEMA';
        stampClass = 'stamp-terracotta';
      } else if (type === 'warning') {
        borderColor = 'border-[#C84B31]';
        iconBg = 'bg-[#FAECE8] text-[#C84B31] border-[#C84B31]/40';
        iconHtml = '<i class="fa-solid fa-circle-exclamation text-xs"></i>';
        stampText = 'ATTENZIONE PROTOCOLLO';
        stampClass = 'stamp-terracotta';
      } else {
        borderColor = 'border-[#7A7568]';
        iconBg = 'bg-[#FAF8F2] text-[#222220] border-[#E3DDD1]';
        iconHtml = '<i class="fa-solid fa-info text-xs"></i>';
        stampText = 'NOTIFICA ATTO';
        stampClass = 'stamp-oli';
      }

      toast.classList.add(borderColor);
      toast.innerHTML = `
        <div class="flex items-start gap-2.5">
          <div class="w-7 h-7 rounded-xs ${iconBg} border flex items-center justify-center shrink-0 mt-0.5 shadow-2xs">
            ${iconHtml}
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between gap-2 mb-1">
              <span class="stamp-oli ${stampClass} text-[8px] tracking-wider">${stampText}</span>
              <button type="button" class="text-[#7A7568] hover:text-[#222220] p-0.5 rounded-xs transition cursor-pointer" title="Chiudi notifica">
                <i class="fa-solid fa-xmark text-xs"></i>
              </button>
            </div>
            <p class="text-xs font-mono-code text-[#222220] leading-snug break-words">${escapeHtml(message)}</p>
          </div>
        </div>
      `;

      const closeBtn = toast.querySelector('button');
      if (closeBtn) {
        closeBtn.onclick = () => {
          toast.classList.add('opacity-0', 'translate-y-3');
          setTimeout(() => toast.remove(), 250);
        };
      }

      container.appendChild(toast);
      requestAnimationFrame(() => {
        toast.classList.remove('translate-y-3', 'opacity-0');
      });

      setTimeout(() => {
        if (toast.parentElement) {
          toast.classList.add('opacity-0', 'translate-y-3');
          setTimeout(() => toast.remove(), 300);
        }
      }, duration);
    }

    // Intercetta e sostituisce alert() nativo in modo non bloccante
    window.alert = function(msg) {
      showToast(String(msg || ''), 'info');
    };

    // --- Modale di Conferma In-App (Sostituisce confirm() nativo) ---
    function showConfirmModal({ title = "Conferma operazione", message = "", confirmText = "Conferma", cancelText = "Annulla", danger = true }) {
      return new Promise((resolve) => {
        const overlay = document.getElementById('confirmModalOverlay');
        const titleEl = document.getElementById('confirmModalTitle');
        const msgEl = document.getElementById('confirmModalMessage');
        const iconBox = document.getElementById('confirmModalIconBox');
        const iconEl = document.getElementById('confirmModalIcon');
        const cancelBtn = document.getElementById('confirmModalCancelBtn');
        const actionBtn = document.getElementById('confirmModalActionBtn');

        if (!overlay) {
          resolve(window.confirm(message));
          return;
        }

        titleEl.textContent = title;
        msgEl.textContent = message;
        cancelBtn.textContent = cancelText;
        actionBtn.textContent = confirmText;

        if (danger) {
          actionBtn.className = "px-4 py-2 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-xl transition shadow-xs cursor-pointer";
          iconBox.className = "w-10 h-10 rounded-2xl bg-rose-100 text-rose-600 flex items-center justify-center text-lg shrink-0";
          iconEl.className = "fa-solid fa-trash-can";
        } else {
          actionBtn.className = "px-4 py-2 text-xs font-bold text-white bg-[#075E54] hover:bg-[#128C7E] rounded-xl transition shadow-xs cursor-pointer";
          iconBox.className = "w-10 h-10 rounded-2xl bg-emerald-100 text-emerald-700 flex items-center justify-center text-lg shrink-0";
          iconEl.className = "fa-solid fa-circle-question";
        }

        const cleanup = (result) => {
          overlay.classList.add('hidden');
          cancelBtn.onclick = null;
          actionBtn.onclick = null;
          resolve(result);
        };

        cancelBtn.onclick = () => cleanup(false);
        actionBtn.onclick = () => cleanup(true);
        overlay.classList.remove('hidden');
      });
    }

    function showTypingIndicator(statusText = "", progressPercent = null) {
      const existing = document.getElementById('typingIndicator');
      if (existing) {
        updateTypingIndicator(statusText, progressPercent);
        return existing;
      }

      const indicator = document.createElement('div');
      indicator.id = 'typingIndicator';
      indicator.className = 'flex justify-start';

      const showProgress = (progressPercent !== null && progressPercent !== undefined && !isNaN(progressPercent));
      const percentVal = showProgress ? Math.min(100, Math.max(0, Math.round(progressPercent))) : 0;

      indicator.innerHTML = `
        <div class="typing-indicator">
          <div class="flex items-center justify-between gap-3 w-full">
            <div class="flex items-center gap-2.5">
              <div class="typing-dots shrink-0">
                <span></span><span></span><span></span>
              </div>
              ${statusText ? `<span id="typingStatusText" class="text-xs font-medium text-slate-700 select-none">${escapeHtml(statusText)}</span>` : `<span id="typingStatusText" class="text-xs font-medium text-slate-700 select-none hidden"></span>`}
            </div>
            <button type="button" onclick="abortGeneration()" title="Interrompi operazione" class="text-[11px] font-semibold text-rose-600 hover:text-rose-800 bg-rose-50 hover:bg-rose-100 border border-rose-200/80 px-2 py-0.5 rounded-full flex items-center gap-1 transition active:scale-95 cursor-pointer ml-auto select-none shadow-2xs">
              <i class="fa-solid fa-stop text-[9px]"></i>
              <span>Interrompi</span>
            </button>
          </div>
          <div id="typingProgressContainer" class="${showProgress ? '' : 'hidden'} w-48 sm:w-64 pt-1">
            <div class="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
              <div id="typingProgressBar" class="bg-[#25D366] h-full rounded-full transition-all duration-300" style="width: ${percentVal}%"></div>
            </div>
            <div class="flex justify-between items-center text-[10px] text-slate-500 font-medium mt-1 select-none">
              <span id="typingProgressSub">In elaborazione...</span>
              <span id="typingProgressPercent">${percentVal}%</span>
            </div>
          </div>
        </div>
      `;
      chatFeed.appendChild(indicator);
      scrollBottom();
      return indicator;
    }

    function updateTypingIndicator(statusText = "", progressPercent = null, threadId = null) {
      const targetId = threadId || currentThreadId;
      const task = activeThreadTasks[targetId];
      if (task) {
        task.statusText = statusText;
        task.progressPercent = progressPercent;
      }

      if (targetId === currentThreadId) {
        const indicator = document.getElementById('typingIndicator');
        if (!indicator) {
          return showTypingIndicator(statusText, progressPercent);
        }

        const textEl = document.getElementById('typingStatusText');
        if (textEl) {
          if (statusText) {
            textEl.textContent = statusText;
            textEl.classList.remove('hidden');
          } else {
            textEl.textContent = '';
            textEl.classList.add('hidden');
          }
        }

        const progContainer = document.getElementById('typingProgressContainer');
        const progBar = document.getElementById('typingProgressBar');
        const progPercentEl = document.getElementById('typingProgressPercent');
        const progSubEl = document.getElementById('typingProgressSub');

        if (progressPercent !== null && progressPercent !== undefined && !isNaN(progressPercent)) {
          const percentVal = Math.min(100, Math.max(0, Math.round(progressPercent)));
          if (progContainer) progContainer.classList.remove('hidden');
          if (progBar) progBar.style.width = `${percentVal}%`;
          if (progPercentEl) progPercentEl.textContent = `${percentVal}%`;
          if (progSubEl) {
            if (percentVal >= 100) progSubEl.textContent = 'Completato';
            else if (percentVal > 0) progSubEl.textContent = 'Elaborazione in corso...';
          }
        } else {
          if (progContainer) progContainer.classList.add('hidden');
        }
        scrollBottom();
      }

      renderThreadsList();
    }

    function hideTypingIndicator() {
      const el = document.getElementById('typingIndicator');
      if (el) el.remove();
    }

    // --- Gestione Citazioni / Rispondi a Messaggio ---
    let currentQuotedMessage = null;

    function replyToMessage(btnEl, senderType = 'assistant', explicitText = null) {
      let text = explicitText;
      if (!text) {
        const selection = window.getSelection() ? window.getSelection().toString().trim() : '';
        if (selection && selection.length > 0) {
          text = selection;
        } else {
          const bubble = btnEl ? btnEl.closest('.group\\/msg') : null;
          const bodyEl = bubble ? bubble.querySelector('.message-body') : null;
          text = bodyEl ? bodyEl.innerText.trim() : '';
        }
      }

      if (!text) return;

      const defaultAssistantName = 'Assistente';
      const senderName = senderType === 'user' ? 'Tu' : defaultAssistantName;
      currentQuotedMessage = {
        sender: senderType,
        senderName: senderName,
        text: text
      };

      const bar = document.getElementById('quotePreviewBar');
      const senderEl = document.getElementById('quoteSenderName');
      const previewEl = document.getElementById('quotePreviewText');

      if (senderEl) senderEl.textContent = senderName;
      if (previewEl) previewEl.textContent = cleanSidebarPreview(text);
      if (bar) bar.classList.remove('hidden');

      if (input) {
        input.focus();
      }
    }

    function cancelQuoteReply() {
      currentQuotedMessage = null;
      const bar = document.getElementById('quotePreviewBar');
      if (bar) bar.classList.add('hidden');
    }

    function appendUserBubble(text, quoted = null) {
      const userBubble = document.createElement('div');
      userBubble.className = 'flex flex-col items-end';
      const isOli = getActiveTheme() === 'olivetti';

      let quoteHtml = '';
      if (quoted && quoted.text) {
        const safeSender = escapeHtml(quoted.sender || quoted.senderName || 'Messaggio');
        const safeQuote = escapeHtml(cleanSidebarPreview(quoted.text));
        if (isOli) {
          quoteHtml = `
            <div class="quoted-msg-widget bg-[#FAF8F2] border-l-4 border-[#3C5A48] border border-[#E3DDD1] rounded-xs p-2.5 mb-2 text-xs select-none shadow-2xs">
              <div class="quoted-sender font-bold text-[#3C5A48] text-[11px] mb-1 flex items-center gap-1.5 font-space uppercase">
                <i class="fa-solid fa-reply text-[9px]"></i>
                <span>${safeSender}</span>
                <span class="stamp-oli text-[7px] py-0 px-1">CITAZIONE</span>
              </div>
              <p class="quoted-text text-[#222220] truncate font-normal leading-tight font-mono-code text-[11px]">${safeQuote}</p>
            </div>
          `;
        } else {
          quoteHtml = `
            <div class="bg-black/5 hover:bg-black/10 transition rounded-lg p-2 mb-1.5 border-l-4 border-[#075E54] text-xs select-none">
              <div class="font-bold text-[#075E54] text-[11px] mb-0.5 flex items-center gap-1">
                <i class="fa-solid fa-reply text-[9px]"></i>
                <span>${safeSender}</span>
              </div>
              <p class="text-slate-600 truncate font-normal leading-tight">${safeQuote}</p>
            </div>
          `;
        }
      }

      userBubble.innerHTML = `
        <span class="text-[9px] font-mono-code text-[#7A7568] mb-1 user-bubble-stamp">UTENTE • ${getTime()}</span>
        <div class="wa-bubble-out p-2.5 max-w-[85%] text-sm text-gray-800 leading-snug relative group/msg select-text">
          ${quoteHtml}
          <div class="message-body selectable-text break-words">
            <p>${formatMessageText(text)}</p>
          </div>
          <div class="flex justify-end items-center gap-1.5 mt-0.5 select-none">
            <button type="button" onclick="replyToMessage(this, 'user')" class="copy-msg-btn hover:text-[#075E54] text-slate-500 text-[11px] p-0.5 rounded transition cursor-pointer" title="Rispondi / Quota">
              <i class="fa-solid fa-reply"></i>
            </button>
            <button type="button" onclick="copyMessageText(this)" class="copy-msg-btn hover:text-slate-900 text-slate-500 text-[11px] p-0.5 rounded transition cursor-pointer" title="Copia testo">
              <i class="fa-regular fa-copy"></i>
            </button>
            <span class="text-[10px] text-gray-500 font-mono-code">${getTime()}</span>
            <i class="fa-solid fa-check-double text-[11px] text-[#53bdeb] wa-ticks-icon"></i>
          </div>
        </div>
      `;
      chatFeed.appendChild(userBubble);
      scrollBottom();
    }

    function formatDurationSeconds(sec) {
      if (!sec || isNaN(sec)) return '0:00';
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    let currentPlayingAudio = null;
    let currentPlayingBtn = null;

    function togglePlayVoice(btn, audioUrl) {
      if (currentPlayingAudio && currentPlayingBtn === btn) {
        if (currentPlayingAudio.paused) {
          currentPlayingAudio.play();
          btn.innerHTML = '<i class="fa-solid fa-pause text-sm"></i>';
        } else {
          currentPlayingAudio.pause();
          btn.innerHTML = '<i class="fa-solid fa-play text-sm ml-0.5"></i>';
        }
        return;
      }

      if (currentPlayingAudio) {
        currentPlayingAudio.pause();
        if (currentPlayingBtn) {
          currentPlayingBtn.innerHTML = '<i class="fa-solid fa-play text-sm ml-0.5"></i>';
        }
        const prevBubble = currentPlayingBtn ? currentPlayingBtn.closest('.wa-bubble-out') : null;
        const prevBar = prevBubble ? prevBubble.querySelector('.voice-progress-bar') : null;
        const prevTime = prevBubble ? prevBubble.querySelector('.voice-current-time') : null;
        if (prevBar) prevBar.style.width = '0%';
        if (prevTime) prevTime.textContent = '0:00';
      }

      const bubble = btn.closest('.wa-bubble-out');
      const progressBar = bubble ? bubble.querySelector('.voice-progress-bar') : null;
      const currentTimeEl = bubble ? bubble.querySelector('.voice-current-time') : null;
      const durationEl = bubble ? bubble.querySelector('.voice-duration-time') : null;

      const audio = new Audio(audioUrl);
      currentPlayingAudio = audio;
      currentPlayingBtn = btn;
      btn.innerHTML = '<i class="fa-solid fa-pause text-sm"></i>';

      audio.addEventListener('timeupdate', () => {
        if (!audio.duration || isNaN(audio.duration)) return;
        const percent = (audio.currentTime / audio.duration) * 100;
        if (progressBar) progressBar.style.width = `${percent}%`;
        if (currentTimeEl) currentTimeEl.textContent = formatDurationSeconds(audio.currentTime);
      });

      audio.addEventListener('loadedmetadata', () => {
        if (durationEl && (!durationEl.textContent || durationEl.textContent === '0:00')) {
          durationEl.textContent = formatDurationSeconds(audio.duration);
        }
      });

      audio.addEventListener('ended', () => {
        btn.innerHTML = '<i class="fa-solid fa-play text-sm ml-0.5"></i>';
        if (progressBar) progressBar.style.width = '0%';
        if (currentTimeEl) currentTimeEl.textContent = '0:00';
        currentPlayingAudio = null;
        currentPlayingBtn = null;
      });

      audio.play().catch(err => {
        console.error("Errore riproduzione vocale:", err);
        btn.innerHTML = '<i class="fa-solid fa-play text-sm ml-0.5"></i>';
        currentPlayingAudio = null;
        currentPlayingBtn = null;
      });
    }

    function seekVoiceAudio(event, trackEl) {
      const bubble = trackEl.closest('.wa-bubble-out');
      const playBtn = bubble ? bubble.querySelector('button') : null;
      if (currentPlayingAudio && currentPlayingBtn === playBtn && !isNaN(currentPlayingAudio.duration)) {
        const rect = trackEl.getBoundingClientRect();
        const clickX = event.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, clickX / rect.width));
        currentPlayingAudio.currentTime = ratio * currentPlayingAudio.duration;
      }
    }

    function appendUserAudioBubble(audioUrl, duration = 0, quoted = null, transcription = null) {
      const userBubble = document.createElement('div');
      userBubble.className = 'flex flex-col items-end user-voice-bubble-wrapper';
      const isOli = getActiveTheme() === 'olivetti';

      let quoteHtml = '';
      if (quoted && quoted.text) {
        const safeSender = escapeHtml(quoted.sender || quoted.senderName || 'Messaggio');
        const safeQuote = escapeHtml(cleanSidebarPreview(quoted.text));
        if (isOli) {
          quoteHtml = `
            <div class="quoted-msg-widget bg-[#FAF8F2] border-l-4 border-[#3C5A48] border border-[#E3DDD1] rounded-xs p-2.5 mb-2 text-xs select-none shadow-2xs">
              <div class="quoted-sender font-bold text-[#3C5A48] text-[11px] mb-1 flex items-center gap-1.5 font-space uppercase">
                <i class="fa-solid fa-reply text-[9px]"></i>
                <span>${safeSender}</span>
                <span class="stamp-oli text-[7px] py-0 px-1">CITAZIONE</span>
              </div>
              <p class="quoted-text text-[#222220] truncate font-normal leading-tight font-mono-code text-[11px]">${safeQuote}</p>
            </div>
          `;
        } else {
          quoteHtml = `
            <div class="bg-black/5 hover:bg-black/10 transition rounded-lg p-2 mb-1.5 border-l-4 border-[#075E54] text-xs select-none">
              <div class="font-bold text-[#075E54] text-[11px] mb-0.5 flex items-center gap-1">
                <i class="fa-solid fa-reply text-[9px]"></i>
                <span>${safeSender}</span>
              </div>
              <p class="text-slate-600 truncate font-normal leading-tight">${safeQuote}</p>
            </div>
          `;
        }
      }

      const durationStr = formatDurationSeconds(duration);
      const playBtnClass = isOli 
        ? 'w-9 h-9 rounded-xs bg-[#3C5A48] hover:bg-[#2F4738] text-white flex items-center justify-center shrink-0 shadow-xs active:scale-95 transition cursor-pointer' 
        : 'w-10 h-10 rounded-full bg-[#128C7E] hover:bg-[#075E54] text-white flex items-center justify-center shrink-0 shadow-2xs active:scale-95 transition cursor-pointer';
      const trackClass = isOli 
        ? 'w-full bg-[#E3DDD1] rounded-xs h-1.5 overflow-hidden pointer-events-none' 
        : 'w-full bg-emerald-200/90 rounded-full h-1.5 overflow-hidden pointer-events-none';
      const progClass = isOli 
        ? 'voice-progress-bar bg-[#3C5A48] h-full w-0 rounded-xs transition-[width] duration-100' 
        : 'voice-progress-bar bg-[#128C7E] h-full w-0 rounded-full transition-[width] duration-100';
      const micBoxClass = isOli 
        ? 'relative w-8 h-8 rounded-xs bg-[#FAF8F2] text-[#3C5A48] flex items-center justify-center shrink-0 text-sm select-none border border-[#E3DDD1] shadow-xs' 
        : 'relative w-9 h-9 rounded-full bg-emerald-100 text-[#128C7E] flex items-center justify-center shrink-0 text-sm select-none border border-emerald-300/60 shadow-2xs';

      let transcriptionHtml = '';
      const cleanTr = (transcription || '').trim();
      if (cleanTr && cleanTr !== '🎤 Messaggio vocale' && !cleanTr.startsWith('🎤 Messaggio vocale')) {
        transcriptionHtml = `
          <div class="voice-transcription-preview text-[11px] text-[#333] italic font-mono-code pt-1.5 mt-1 border-t border-[#E3DDD1]/70 flex items-start gap-1.5 select-text">
            <i class="fa-solid fa-quote-left text-[8px] text-[#3C5A48] mt-0.5 opacity-60 shrink-0"></i>
            <span class="break-words">“${escapeHtml(cleanTr)}”</span>
          </div>
        `;
      }

      const quoteArg = cleanTr ? ('🎤 ' + cleanTr) : '🎤 Messaggio vocale';
      const safeQuoteArg = escapeHtml(quoteArg).replace(/'/g, "\\'");

      userBubble.innerHTML = `
        <span class="text-[9px] font-mono-code text-[#7A7568] mb-1 user-bubble-stamp">UTENTE • ${getTime()}</span>
        <div class="wa-bubble-out p-2.5 max-w-[85%] sm:max-w-[70%] text-sm text-gray-800 leading-snug relative group/msg select-text">
          ${quoteHtml}
          
          <!-- Player Audio -->
          <div class="flex items-center gap-3 py-1 px-1">
            <button type="button" onclick="togglePlayVoice(this, '${escapeHtml(audioUrl)}')" class="${playBtnClass}" title="Ascolta vocale">
              <i class="fa-solid fa-play text-sm ml-0.5"></i>
            </button>
            
            <div class="flex-1 min-w-[140px] sm:min-w-[190px]">
              <!-- Barra avanzamento / scrubber -->
              <div class="relative w-full flex items-center h-4 cursor-pointer" onclick="seekVoiceAudio(event, this)">
                <div class="${trackClass}">
                  <div class="${progClass}"></div>
                </div>
              </div>
              
              <div class="flex justify-between items-center text-[10px] text-slate-500 font-mono-code mt-0.5 select-none">
                <span class="voice-current-time">0:00</span>
                <span class="voice-duration-time">${durationStr}</span>
              </div>
            </div>
            
            <div class="${micBoxClass}">
              <i class="fa-solid fa-microphone"></i>
            </div>
          </div>

          <div class="voice-transcription-slot">${transcriptionHtml}</div>

          <div class="flex justify-end items-center gap-1.5 mt-1 select-none">
            <button type="button" onclick="replyToMessage(this, 'user', '${safeQuoteArg}')" class="copy-msg-btn hover:text-[#075E54] text-slate-500 text-[11px] p-0.5 rounded transition cursor-pointer" title="Rispondi / Quota">
              <i class="fa-solid fa-reply"></i>
            </button>
            <span class="text-[10px] text-gray-500 font-mono-code">${getTime()}</span>
            <i class="fa-solid fa-check-double text-[11px] text-[#53bdeb] wa-ticks-icon"></i>
          </div>
        </div>
      `;
      chatFeed.appendChild(userBubble);
      scrollBottom();
      return userBubble;
    }

    function appendUserFileBubble(fileName, fileSize, previewUrl = null, isImage = false, isPdf = false) {
      const userBubble = document.createElement('div');
      userBubble.className = 'flex flex-col items-end';
      const isOli = getActiveTheme() === 'olivetti';

      const lowerName = (fileName || '').toLowerCase();
      const isOffice = lowerName.endsWith('.docx') || lowerName.endsWith('.doc') || lowerName.endsWith('.xlsx') || lowerName.endsWith('.xls') || lowerName.endsWith('.csv') || lowerName.endsWith('.tsv');
      const isZip = lowerName.endsWith('.zip') || lowerName.endsWith('.rar') || lowerName.endsWith('.7z') || lowerName.endsWith('.tar') || lowerName.endsWith('.gz');

      let previewContent = '';
      if (isImage && previewUrl) {
        previewContent = `
          <div class="cursor-pointer group mb-1" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', 'image')">
            <div class="relative overflow-hidden ${isOli ? 'rounded-xs' : 'rounded-lg'} bg-black/5 max-h-48 flex items-center justify-center">
              <img src="${previewUrl}" class="w-full h-auto object-cover max-h-48 ${isOli ? 'rounded-xs' : 'rounded-lg'} group-hover:scale-105 transition duration-200" alt="Anteprima">
              <div class="absolute inset-0 bg-black/20 opacity-0 group-hover:opacity-100 transition flex items-center justify-center text-white">
                <i class="fa-solid fa-magnifying-glass-plus text-xl drop-shadow"></i>
              </div>
            </div>
            <div class="flex items-center justify-between px-1 pt-1 text-[11px] text-gray-700 font-medium">
              <span class="truncate max-w-[170px] ${isOli ? 'font-mono-code' : ''}">${escapeHtml(fileName)}</span>
              <span class="text-gray-500 font-mono-code">${formatFileSize(fileSize)}</span>
            </div>
          </div>
        `;
      } else if (previewUrl) {
        let iconHtml = '<i class="fa-solid fa-file-lines text-lg text-slate-600"></i>';
        let bgStyle = isOli ? 'bg-[#FAF8F2] text-[#3C5A48]' : 'bg-slate-100 text-slate-600';
        let badgeText = 'FILE';

        if (isPdf) {
          iconHtml = `<i class="fa-solid fa-file-pdf text-lg ${isOli ? 'text-[#C84B31]' : 'text-red-600'}"></i>`;
          bgStyle = isOli ? 'bg-[#FAECE8] text-[#C84B31]' : 'bg-red-100 text-red-600';
          badgeText = 'PDF';
        } else if (lowerName.endsWith('.docx') || lowerName.endsWith('.doc')) {
          iconHtml = `<i class="fa-solid fa-file-word text-lg ${isOli ? 'text-[#3C5A48]' : 'text-blue-600'}"></i>`;
          bgStyle = isOli ? 'bg-[#EBF1ED] text-[#3C5A48]' : 'bg-blue-100 text-blue-600';
          badgeText = 'WORD';
        } else if (lowerName.endsWith('.xlsx') || lowerName.endsWith('.xls') || lowerName.endsWith('.csv')) {
          iconHtml = `<i class="fa-solid fa-file-excel text-lg ${isOli ? 'text-[#3C5A48]' : 'text-emerald-600'}"></i>`;
          bgStyle = isOli ? 'bg-[#EBF1ED] text-[#3C5A48]' : 'bg-emerald-100 text-emerald-600';
          badgeText = 'EXCEL';
        } else if (isZip) {
          iconHtml = `<i class="fa-solid fa-file-zipper text-lg ${isOli ? 'text-amber-600' : 'text-amber-600'}"></i>`;
          bgStyle = isOli ? 'bg-amber-50 text-amber-700' : 'bg-amber-100 text-amber-600';
          badgeText = 'ZIP';
        }

        const boxClass = isOli 
          ? 'bg-[#FAF8F2] p-2.5 rounded-xs flex items-center justify-between gap-3 mb-1 border border-[#E3DDD1]' 
          : 'bg-[#d4f2c5] p-2.5 rounded-lg flex items-center justify-between gap-3 mb-1 border border-emerald-200/70';
        const iconBoxClass = isOli 
          ? `w-8 h-8 rounded-xs ${bgStyle} flex items-center justify-center shrink-0 shadow-xs border border-[#E3DDD1]` 
          : `w-9 h-9 rounded-lg ${bgStyle} flex items-center justify-center shrink-0 shadow-2xs`;
        const vediBtn = isOli 
          ? `<button type="button" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', 'application/pdf', '${previewUrl}')" class="bg-[#3C5A48] hover:bg-[#2F4738] text-white text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space cursor-pointer"><i class="fa-regular fa-eye text-xs"></i> Vedi</button>` 
          : `<button type="button" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', 'application/pdf', '${previewUrl}')" class="bg-white/95 hover:bg-white text-emerald-800 text-xs font-semibold px-2 py-1 rounded-md shadow-2xs border border-emerald-300 transition active:scale-95 flex items-center gap-1"><i class="fa-regular fa-eye text-xs"></i> Vedi</button>`;
        const dlBtn = isOli 
          ? `<a href="${previewUrl}" download="${escapeHtml(fileName)}" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space" title="Scarica file"><i class="fa-solid fa-download text-xs text-[#3C5A48]"></i></a>` 
          : `<a href="${previewUrl}" download="${escapeHtml(fileName)}" class="bg-white/95 hover:bg-white text-emerald-800 text-xs font-semibold px-2 py-1 rounded-md shadow-2xs border border-emerald-300 transition active:scale-95 flex items-center gap-1" title="Scarica file"><i class="fa-solid fa-download text-xs text-emerald-700"></i></a>`;

        previewContent = `
          <div class="${boxClass}">
            <div class="flex items-center gap-2.5 min-w-0">
              <div class="${iconBoxClass}">
                ${iconHtml}
              </div>
              <div class="text-xs min-w-0">
                <p class="font-bold text-[#222220] truncate max-w-[140px] ${isOli ? 'font-space' : ''}">${escapeHtml(fileName)}</p>
                <p class="text-[10px] text-[#7A7568] font-mono-code">${formatFileSize(fileSize)} • ${badgeText}</p>
              </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
              ${isPdf ? vediBtn : ''}
              ${dlBtn}
            </div>
          </div>
        `;
      } else {
        let iconClass = isPdf ? 'fa-solid fa-file-pdf text-red-700' : (isZip ? 'fa-solid fa-file-zipper text-amber-700' : 'fa-solid fa-file-lines text-slate-700');
        const boxClass = isOli ? 'bg-[#FAF8F2] p-2 rounded-xs flex items-center gap-2 mb-1 border border-[#E3DDD1]' : 'bg-[#d4f2c5] p-2 rounded-md flex items-center gap-2 mb-1';
        previewContent = `
          <div class="${boxClass}">
            <i class="${iconClass} text-xl shrink-0"></i>
            <div class="text-xs truncate max-w-[200px]">
              <p class="font-medium text-gray-900 truncate ${isOli ? 'font-space' : ''}">${escapeHtml(fileName)}</p>
              <p class="text-[10px] text-gray-600 font-mono-code">${formatFileSize(fileSize)}</p>
            </div>
          </div>
        `;
      }

      userBubble.innerHTML = `
        <span class="text-[9px] font-mono-code text-[#7A7568] mb-1 user-bubble-stamp">UTENTE • ${getTime()}</span>
        <div class="wa-bubble-out p-2 max-w-[85%] text-sm text-gray-800 select-text group/msg">
          ${previewContent}
          <div class="flex justify-end items-center gap-1.5 mt-0.5 select-none">
            <button type="button" onclick="replyToMessage(this, 'user', 'File: ${escapeHtml(fileName).replace(/'/g, "\\'")}')" class="copy-msg-btn hover:text-[#075E54] text-slate-500 text-[11px] p-0.5 rounded transition cursor-pointer" title="Rispondi / Quota">
              <i class="fa-solid fa-reply"></i>
            </button>
            <button type="button" onclick="copyTextToClipboard('${escapeHtml(fileName).replace(/'/g, "\\'")}', this)" class="copy-msg-btn hover:text-slate-900 text-slate-500 text-[11px] p-0.5 rounded transition cursor-pointer" title="Copia nome file">
              <i class="fa-regular fa-copy"></i>
            </button>
            <span class="text-[10px] text-gray-500 font-mono-code">${getTime()}</span>
            <i class="fa-solid fa-check-double text-[11px] text-[#53bdeb] wa-ticks-icon"></i>
          </div>
        </div>
      `;
      chatFeed.appendChild(userBubble);
      scrollBottom();
    }

    function toggleExtraWidgets(btn) {
      const container = btn.nextElementSibling;
      if (!container) return;
      const isHidden = container.classList.contains('hidden');
      const count = btn.getAttribute('data-count') || '';
      const labelPlural = count === '1' ? 'documento' : 'documenti';
      const textSpan = btn.querySelector('.widget-toggle-text');
      const arrow = btn.querySelector('.widget-toggle-arrow');

      if (isHidden) {
        container.classList.remove('hidden');
        if (arrow) arrow.classList.add('rotate-180');
        if (textSpan) textSpan.textContent = `Nascondi altri ${count} ${labelPlural}`;
        scrollBottom();
      } else {
        container.classList.add('hidden');
        if (arrow) arrow.classList.remove('rotate-180');
        if (textSpan) textSpan.textContent = `Mostra altri ${count} ${labelPlural}`;
      }
    }

    function appendAssistantBubble(text, documents = null, confirmation = null, itemPhoto = null, storeItem = null, proposal = null, routedModel = null) {
      const aiBubble = document.createElement('div');
      aiBubble.className = 'flex flex-col items-start max-w-[90%]';
      const formattedHtml = formatMessageText(text || '');

      let photoHtml = '';
      if (itemPhoto && itemPhoto.image_url) {
        const safeItemName = escapeHtml(itemPhoto.item_name || 'Posizione Oggetto');
        photoHtml = `
          <div class="mt-2.5 relative group/item-img cursor-pointer overflow-hidden rounded-xs border border-[#E3DDD1] shadow-xs max-w-xs" onclick="openMediaModal('${itemPhoto.image_url}', '${safeItemName.replace(/'/g, "\\'")} (Foto Posizione)', 'image')">
            <img src="${itemPhoto.image_url}" alt="${safeItemName}" class="w-full h-40 object-cover group-hover/item-img:scale-105 transition duration-200">
            <div class="absolute inset-0 bg-black/25 opacity-0 group-hover/item-img:opacity-100 transition flex items-center justify-center gap-1.5 text-white text-xs font-semibold backdrop-blur-2xs">
              <i class="fa-solid fa-magnifying-glass-plus"></i> Ingrandisci Foto
            </div>
            <div class="absolute bottom-1.5 left-1.5 right-1.5 flex items-center justify-between pointer-events-none">
              <span class="stamp-oli stamp-solid-sage text-[8px]">
                <i class="fa-solid fa-camera text-[8px]"></i> FOTO POSIZIONE
              </span>
            </div>
          </div>
        `;
      }

      let storeItemHtml = '';
      if (storeItem && storeItem.item_id) {
        const safeItemName = escapeHtml(storeItem.item_name || 'Oggetto');
        storeItemHtml = `
          <div class="mt-2 pt-2 border-t border-[#E3DDD1] flex items-center gap-2">
            <button type="button" onclick="promptUploadItemPhoto(${storeItem.item_id}, '${safeItemName.replace(/'/g, "\\'")}')" class="bg-[#FAF8F2] hover:bg-[#EBF1ED] text-[#3C5A48] border border-[#3C5A48] text-xs font-bold font-space px-2.5 py-1.5 rounded-xs transition active:scale-95 flex items-center gap-1.5 shadow-xs cursor-pointer">
              <i class="fa-solid fa-camera text-[#3C5A48] text-xs"></i>
              <span>📸 Scatta o allega foto posizione</span>
            </button>
          </div>
        `;
      }

      let docsHtml = '';
      if (documents && Array.isArray(documents) && documents.length > 0) {
        try {
          const renderDocCardHtml = (doc) => {
            try {
              const isPdf = (doc.file_type && doc.file_type.includes('pdf')) || (doc.file_url && doc.file_url.toLowerCase().endsWith('.pdf'));
              const isZip = (doc.file_type && doc.file_type.includes('zip')) || (doc.file_url && doc.file_url.toLowerCase().endsWith('.zip')) || (doc.title && doc.title.toLowerCase().endsWith('.zip'));
              const iconClass = isPdf ? 'fa-solid fa-file-pdf text-[#C84B31]' : (isZip ? 'fa-solid fa-file-zipper text-amber-600' : 'fa-solid fa-file-lines text-[#3C5A48]');
              const iconBg = isPdf ? 'bg-[#FAECE8]' : (isZip ? 'bg-amber-50' : 'bg-[#EBF1ED]');
              const title = escapeHtml(doc.title || 'Documento');
              const issuer = escapeHtml(doc.issuer || 'Ente / Mittente');
              const summary = doc.summary || '';
              const url = doc.file_url || '';
              const fileType = doc.file_type || (isPdf ? 'application/pdf' : (isZip ? 'zip' : 'image'));
              const docId = doc.document_id || doc.id;
              const docItem = doc;
              const downloadUrl = doc.download_url || (docId ? `/api/documents/${docId}/download` : url);
              const safeDownloadName = (doc.title || 'documento').replace(/[^a-zA-Z0-9_\-]/g, '_') + (isPdf ? '.pdf' : '');

              let amountStr = '';
              if (doc.amount != null) {
                amountStr = `<span class="inline-block mt-1 font-black font-mono-code text-[#222220] text-xs">€ ${doc.amount.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
              }

              let dueStr = '';
              if (doc.due_date) {
                dueStr = `<span class="inline-block mt-1 ml-1.5 stamp-oli stamp-terracotta text-[8px]">SCAD: ${escapeHtml(doc.due_date)}</span>`;
              }

              const borderClass = (doc.due_date && doc.status === 'da_pagare') ? 'border-l-4 border-[#C84B31]' : 'border-l-4 border-[#3C5A48]';

              return `
                <div class="chat-doc-card bg-[#FAF8F2] hover:bg-white border border-[#E3DDD1] ${borderClass} rounded-xs p-2.5 transition shadow-xs text-left">
                  <div class="flex items-start justify-between gap-2">
                    <div class="flex items-start gap-2.5 min-w-0">
                      <div class="w-8 h-8 rounded-xs ${iconBg} flex items-center justify-center shrink-0 mt-0.5 shadow-2xs">
                        <i class="${iconClass} text-sm"></i>
                      </div>
                      <div class="min-w-0">
                        <p class="font-bold text-[#222220] text-xs truncate font-space">${title}</p>
                        <p class="text-[11px] text-[#7A7568] truncate font-mono-code">${issuer}</p>
                        <div class="flex items-center flex-wrap gap-1">
                          ${amountStr}
                          ${dueStr}
                        </div>
                      </div>
                    </div>
                    <div class="flex items-center gap-1.5 shrink-0">
                      ${docItem.drive_web_url ? `
                        <a href="${docItem.drive_web_url}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 stamp-oli text-[9px] hover:bg-[#3C5A48] hover:text-white transition">
                          <i class="fa-brands fa-google-drive text-[10px]"></i> <span>Drive ↗</span>
                        </a>
                      ` : ''}
                      ${url ? `
                        <button type="button" onclick="openMediaModal('${url}', '${title.replace(/'/g, "\\'")}', '${fileType}', '${downloadUrl}', ${docId || 'null'})" class="bg-[#3C5A48] hover:bg-[#2F4738] text-white text-[10px] font-bold px-2 py-1 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Visualizza anteprima">
                          <i class="fa-regular fa-eye text-xs"></i>
                          <span>Vedi</span>
                        </button>
                      ` : ''}
                      ${(docId && (fileType === 'zip' || (docItem.doc_type && docItem.doc_type === 'archivio_zip') || (title && title.toLowerCase().endsWith('.zip')))) ? `
                        <button type="button" onclick="unzipDocumentById(${docId})" class="bg-amber-600 hover:bg-amber-700 text-white text-[10px] font-bold px-2 py-1 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Decomprimi tutti i file di questo archivio nel caveau">
                          <i class="fa-solid fa-file-zipper text-xs"></i>
                          <span>Estrai</span>
                        </button>
                      ` : ''}
                      ${downloadUrl ? `
                        <button type="button" onclick="downloadFileFromUrl('${downloadUrl}', '${safeDownloadName}', ${docId || 'null'})" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] hover:text-[#2F4738] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Scarica documento sul tuo dispositivo">
                          <i class="fa-solid fa-download text-xs text-[#3C5A48]"></i>
                          <span>Scarica</span>
                        </button>
                      ` : ''}
                      ${docId ? `
                        <button type="button" onclick="openFileInExplorer(${docId})" class="bg-[#FAF8F2] hover:bg-white text-[#7A7568] hover:text-[#222220] border border-[#E3DDD1] text-[10px] font-bold px-2 py-1 rounded-xs shadow-xs transition flex items-center gap-1 active:scale-95 cursor-pointer font-space" title="Apri file in Esplora Risorse del PC">
                          <i class="fa-regular fa-folder-open text-xs text-[#C84B31]"></i>
                          <span class="hidden sm:inline">PC</span>
                        </button>
                      ` : ''}
                    </div>
                  </div>
                  ${summary ? `
                    <p class="mt-2 pt-1.5 border-t border-[#E3DDD1] text-[11px] text-[#7A7568] italic leading-snug line-clamp-2">
                      ${formatMessageText(summary)}
                    </p>
                  ` : ''}
                </div>
              `;
            } catch (docErr) {
              sendUITelemetry('CARD_RENDER_ERROR', {
                target_id: doc.id || doc.document_id,
                title: doc.title || 'Documento',
                error_details: 'Errore generazione singola scheda documento: ' + docErr.message
              });
              const docId = doc.document_id || doc.id;
              const fallbackDl = doc.download_url || (docId ? `/api/documents/${docId}/download` : '#');
              return `
                <div class="bg-amber-50 border border-amber-200 rounded-xs p-2 flex items-center justify-between text-xs">
                  <span class="font-semibold text-slate-800">${escapeHtml(doc.title || 'Documento')}</span>
                  <div class="flex items-center gap-1.5">
                    ${doc.drive_web_url ? `
                      <a href="${doc.drive_web_url}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 rounded-lg text-[10px] font-semibold flex items-center gap-1 transition">
                        <i class="fa-brands fa-google-drive text-xs"></i> <span>Drive ↗</span>
                      </a>
                    ` : ''}
                    <a href="${fallbackDl}" class="bg-[#3C5A48] text-white px-2.5 py-1 rounded-xs text-xs font-bold" download>⬇️ Scarica</a>
                  </div>
                </div>
              `;
            }
          };

          if (documents.length <= 3) {
            docsHtml = `
              <div class="mt-2.5 space-y-2 w-full">
                ${documents.map(renderDocCardHtml).join('')}
              </div>
            `;
          } else {
            const firstThree = documents.slice(0, 3);
            const extraDocs = documents.slice(3);
            const extraCount = extraDocs.length;
            const labelPlural = extraCount === 1 ? 'documento' : 'documenti';

            docsHtml = `
              <div class="mt-2.5 space-y-2 w-full">
                ${firstThree.map(renderDocCardHtml).join('')}

                <!-- Menu a tendina espandibile dopo il 3° widget -->
                <div class="pt-1 w-full">
                  <button 
                    type="button" 
                    onclick="toggleExtraWidgets(this)" 
                    data-count="${extraCount}"
                    class="w-full flex items-center justify-between px-3.5 py-2.5 bg-[#FAF8F2] hover:bg-white text-[#222220] border border-[#E3DDD1] rounded-xs text-xs font-bold font-space transition active:scale-[0.99] cursor-pointer shadow-xs group"
                  >
                    <span class="flex items-center gap-2">
                      <i class="fa-solid fa-layer-group text-[#3C5A48] text-xs transition"></i>
                      <span class="widget-toggle-text">Mostra altri ${extraCount} ${labelPlural}</span>
                    </span>
                    <i class="fa-solid fa-chevron-down text-xs text-[#7A7568] group-hover:text-[#222220] transition-transform duration-200 widget-toggle-arrow"></i>
                  </button>
                  <div class="hidden mt-2 space-y-2 extra-widgets-container animate-fadeIn">
                    ${extraDocs.map(renderDocCardHtml).join('')}
                  </div>
                </div>
              </div>
            `;
          }
        } catch (allDocsErr) {
          sendUITelemetry('CARD_RENDER_ERROR', {
            error_details: 'Errore critico blocco schede: ' + allDocsErr.message
          });
        }
      }

      let confHtml = '';
      if (confirmation && confirmation.type === 'delete_confirmation') {
        const confTitle = escapeHtml(confirmation.title || 'elemento');
        const targetType = escapeHtml(confirmation.target_type || 'document');
        const targetId = confirmation.target_id || 0;
        const targetIds = confirmation.target_ids ? JSON.stringify(confirmation.target_ids) : 'null';
        const details = confirmation.details ? escapeHtml(confirmation.details) : '';
        const isBulk = targetType === 'bulk_documents';
        const btnLabel = isBulk ? (confirmation.target_ids ? `Sì, elimina tutti (${confirmation.target_ids.length})` : 'Sì, elimina tutti') : 'Sì, elimina';

        confHtml = `
          <div id="conf-box-${targetType}-${targetId}" class="mt-3 bg-[#FAECE8] border border-[#C84B31] rounded-xs p-3 shadow-xs text-left">
            <div class="flex items-center gap-2 text-[#C84B31] font-bold text-xs mb-1 font-space">
              <i class="fa-solid fa-triangle-exclamation text-[#C84B31]"></i>
              <span>${isBulk ? 'CONFERMA ELIMINAZIONE MULTIPLA' : 'CONFERMA ELIMINAZIONE'}</span>
            </div>
            <p class="text-xs text-[#222220] leading-snug">
              Sei sicuro di voler eliminare definitivamente <strong>"${confTitle}"</strong>?
              ${details ? `<br><span class="text-[11px] text-[#7A7568] italic">${details}</span>` : ''}
            </p>
            <div class="flex items-center gap-2 mt-2.5">
              <button type="button" onclick="executeDelete('${targetType}', ${targetId}, this, ${targetIds})" class="bg-[#C84B31] hover:bg-[#B23E26] text-white text-xs font-bold px-3 py-1.5 rounded-xs shadow-xs transition active:scale-95 flex items-center gap-1.5 font-space">
                <i class="fa-solid fa-trash-can text-[11px]"></i>
                <span>${btnLabel}</span>
              </button>
              <button type="button" onclick="cancelDelete(this)" class="bg-white hover:bg-[#FAF8F2] text-[#7A7568] hover:text-[#222220] text-xs font-bold border border-[#E3DDD1] px-3 py-1.5 rounded-xs transition active:scale-95 font-space">
                No, annulla
              </button>
            </div>
          </div>
        `;
      }

      let proposalHtml = '';
      if (proposal && proposal.id) {
        const propId = proposal.id;
        const fileName = escapeHtml(proposal.file_name || 'File sensibile');
        const folderName = escapeHtml(proposal.folder_name || 'Cartella');
        const reason = escapeHtml(proposal.sensitivity_reason || 'Rilevati dati personali o fiscali');
        const amountStr = proposal.amount ? `<span class="stamp-oli text-[9px]">€ ${Number(proposal.amount).toFixed(2)}</span>` : '';
        const dueStr = proposal.due_date ? `<span class="stamp-oli stamp-terracotta text-[9px]">Scad: ${proposal.due_date}</span>` : '';
        const docTypeStr = proposal.doc_type ? `<span class="stamp-oli text-[8px] uppercase">${escapeHtml(proposal.doc_type)}</span>` : '';
        const isPending = (proposal.status === 'pending' || !proposal.status);

        proposalHtml = `
          <div id="proposal-bubble-${propId}" class="mt-2.5 bg-[#FAF8F2] border border-[#E3DDD1] border-l-4 border-[#3C5A48] rounded-xs p-3 shadow-xs text-left">
            <div class="flex items-center justify-between gap-2 border-b border-[#E3DDD1] pb-2 mb-2">
              <div class="flex items-center gap-1.5 text-[#3C5A48] font-bold text-xs font-space">
                <i class="fa-solid fa-shield-halved text-[#3C5A48]"></i>
                <span>RILEVAMENTO ATTO SENSIBILE</span>
              </div>
              <span class="stamp-oli text-[8px]">${folderName}</span>
            </div>
            
            <div class="flex items-start gap-2.5">
              <div class="w-8 h-8 rounded-xs bg-white border border-[#E3DDD1] text-[#C84B31] flex items-center justify-center text-sm shrink-0 shadow-2xs">
                <i class="fa-solid fa-file-shield"></i>
              </div>
              <div class="min-w-0 flex-1">
                <h4 class="font-bold text-xs text-[#222220] truncate font-space" title="${fileName}">${fileName}</h4>
                <p class="text-[11px] text-[#7A7568] mt-0.5">${reason}</p>
                <div class="flex items-center flex-wrap gap-1.5 mt-1.5">
                  ${docTypeStr}
                  ${amountStr}
                  ${dueStr}
                </div>
              </div>
            </div>

            ${isPending ? `
              <div class="flex items-center gap-2 mt-2.5 pt-2 border-t border-[#E3DDD1]">
                <button type="button" onclick="approveProposal(${propId}, this)" class="bg-[#3C5A48] hover:bg-[#2F4738] text-white text-xs font-bold px-3 py-1.5 rounded-xs shadow-xs transition active:scale-95 flex items-center gap-1.5 cursor-pointer font-space">
                  <i class="fa-solid fa-lock text-[10px]"></i>
                  <span>Salva nel Caveau</span>
                </button>
                <button type="button" onclick="dismissProposal(${propId}, this)" class="bg-white hover:bg-[#FAF8F2] text-[#7A7568] hover:text-[#222220] text-xs font-bold px-2.5 py-1.5 rounded-xs border border-[#E3DDD1] transition active:scale-95 cursor-pointer font-space">
                  Ignora
                </button>
              </div>
            ` : `
              <div class="mt-2 pt-2 border-t border-[#E3DDD1] text-[11px] text-[#3C5A48] font-bold flex items-center gap-1.5 font-space">
                <i class="fa-solid fa-circle-check"></i>
                <span>${proposal.status === 'approved' ? 'Salvato e Cifrato nel Caveau' : 'Ignorato'}</span>
              </div>
            `}
          </div>
        `;
      }

      aiBubble.innerHTML = `
        <span class="text-[9px] font-mono-code text-[#3C5A48] font-bold mb-1 ai-bubble-stamp">ASSISTENTE • ${getTime()}</span>
        <div class="wa-bubble-in p-2.5 text-sm text-gray-800 leading-snug max-w-full relative group/msg select-text">
          <div class="flex items-start justify-between gap-2">
            <div class="message-body selectable-text min-w-0 flex-1 break-words">
              <p>${formattedHtml}</p>
            </div>
            <div class="flex items-center gap-1 shrink-0 self-start -mt-0.5 -mr-0.5 select-none">
              <button type="button" onclick="replyToMessage(this, 'assistant')" class="copy-msg-btn hover:text-[#075E54] text-slate-400 hover:bg-slate-100 text-xs p-1 rounded transition cursor-pointer" title="Rispondi / Quota">
                <i class="fa-solid fa-reply"></i>
              </button>
              <button type="button" onclick="copyMessageText(this)" class="copy-msg-btn hover:text-slate-900 text-slate-400 hover:bg-slate-100 text-xs p-1 rounded transition cursor-pointer" title="Copia testo">
                <i class="fa-regular fa-copy"></i>
              </button>
            </div>
          </div>
          ${photoHtml}
          ${docsHtml}
          ${confHtml}
          ${storeItemHtml}
          ${proposalHtml}
          <div class="flex items-center justify-end gap-1.5 mt-1 select-none">
            ${(() => {
              if (!routedModel) return '';
              if (routedModel.includes('gemini-2.5-pro')) {
                return '<span class="inline-flex items-center gap-1 text-[9px] font-medium text-purple-700 bg-purple-50 border border-purple-200/70 px-1.5 py-0.5 rounded-full" title="Risposta elaborata con Gemini 2.5 Pro (Thinking Process)"><i class="fa-solid fa-brain text-[8px] text-purple-600"></i> Pro Thinking</span>';
              } else if (routedModel.includes('flash-lite')) {
                return '<span class="inline-flex items-center gap-1 text-[9px] font-medium text-amber-700 bg-amber-50 border border-amber-200/70 px-1.5 py-0.5 rounded-full" title="Risposta rapida elaborata con Gemini 2.5 Flash Lite"><i class="fa-solid fa-bolt text-[8px] text-amber-500"></i> Flash Lite</span>';
              } else if (routedModel.includes(':free')) {
                return '<span class="inline-flex items-center gap-1 text-[9px] font-medium text-emerald-700 bg-emerald-50 border border-emerald-200/70 px-1.5 py-0.5 rounded-full" title="Modello 100% Gratuito"><i class="fa-solid fa-gift text-[8px] text-emerald-600"></i> Free</span>';
              }
              return '';
            })()}
            <span class="text-[10px] text-gray-400 font-mono-code">${getTime()}</span>
          </div>
        </div>
      `;
      chatFeed.appendChild(aiBubble);
      scrollBottom();
    }

    // --- Eliminazione Sicura: Documenti & Posizioni ---
    async function executeDelete(targetType, targetId, btnEl, targetIds = null) {
      const confBox = btnEl ? btnEl.closest('[id^="conf-box-"]') : null;
      if (confBox) {
        confBox.innerHTML = `
          <div class="flex items-center gap-2 text-slate-500 text-xs py-1">
            <span class="inline-block w-2 h-2 rounded-full bg-red-500 animate-ping"></span>
            <span>Eliminazione in corso dal caveau...</span>
          </div>
        `;
      }

      try {
        let res;
        if (targetType === 'bulk_documents') {
          res = await fetch('/api/documents/bulk', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ document_ids: targetIds || [targetId] })
          });
        } else if (targetType === 'physical_item') {
          res = await fetch(`/api/items/${targetId}`, { method: 'DELETE' });
        } else {
          res = await fetch(`/api/documents/${targetId}`, { method: 'DELETE' });
        }
        if (!res.ok) throw new Error("Errore durante l'eliminazione");
        const data = await res.json();

        if (confBox) {
          confBox.className = 'mt-3 bg-emerald-50 border border-emerald-200 rounded-xl p-3 shadow-2xs text-left';
          confBox.innerHTML = `
            <div class="flex items-center gap-2 text-emerald-800 text-xs font-bold">
              <i class="fa-solid fa-circle-check text-emerald-600"></i>
              <span>${escapeHtml(data.message || 'Eliminato con successo dal caveau.')}</span>
            </div>
          `;
        }
        await loadDashboard(currentFilter);
      } catch (err) {
        console.error("Errore executeDelete:", err);
        if (confBox) {
          confBox.innerHTML = `
            <div class="text-xs text-red-600 font-medium">
              ⚠️ Impossibile completare l'eliminazione: riprova più tardi.
            </div>
          `;
        }
      }
    }

    function cancelDelete(btnEl) {
      const confBox = btnEl ? btnEl.closest('[id^="conf-box-"]') : null;
      if (confBox) {
        confBox.className = 'mt-3 bg-slate-100 border border-slate-200 rounded-xl p-2.5 shadow-2xs text-left';
        confBox.innerHTML = `
          <div class="flex items-center gap-1.5 text-slate-600 text-xs font-medium">
            <i class="fa-solid fa-circle-info text-slate-400"></i>
            <span>Operazione annullata. Nessuna modifica effettuata al caveau.</span>
          </div>
        `;
      }
    }

    async function confirmDashboardDelete(targetType, targetId, title) {
      const typeLabel = targetType === 'physical_item' ? "la posizione di quest'oggetto" : "questo documento";
      const confirmed = await showConfirmModal({
        title: "Elimina dal Caveau",
        message: `Sei sicuro di voler eliminare ${typeLabel} ("${title}") dal caveau?\nQuesta operazione è definitiva e permanente.`,
        confirmText: "Elimina Definitivamente",
        danger: true
      });
      if (confirmed) {
        executeDelete(targetType, targetId, null);
      }
    }

    // --- Invio Messaggio Live: POST /api/chat ---
    async function handleSend(e) {
      if (e) e.preventDefault();
      const text = input.value.trim();
      if (!text) return;

      const targetThreadId = currentThreadId; // Memorizza la chat di destinazione
      const quotedToSend = currentQuotedMessage;
      cancelQuoteReply(); // Chiudi subito la barra preview della citazione

      appendUserBubble(text, quotedToSend);
      input.value = '';
      input.dispatchEvent(new Event('input'));
      scrollBottom();

      // Riconoscimento intelligente dell'azione per feedback dinamico
      const lower = text.toLowerCase();
      let statusFeedback = "L'assistente sta rispondendo...";
      if (lower.includes('unzip') || lower.includes('scompatta') || lower.includes('estrai') || lower.includes('estrazione') || lower.includes('decomprim')) {
        statusFeedback = "Sto estraendo l'archivio ZIP e catalogando i file...";
      } else if (lower.includes('comprimi') || lower.includes('archivio zip') || lower.includes('crea zip') || lower.includes('creami uno zip') || lower.includes('fai uno zip') || (lower.includes('zip') && !lower.includes('unzip'))) {
        statusFeedback = "Sto creando l'archivio ZIP...";
      } else if (lower.includes('scansiona') || lower.includes('indicizza') || lower.includes('cartell') || lower.includes('sincronizza') || lower.includes('monitora')) {
        statusFeedback = "Scansione e sincronizzazione cartelle in corso...";
      } else if (lower.includes('dov\'è') || lower.includes('dove si trova') || lower.includes('dove ho messo') || lower.includes('dove sono') || lower.includes('cerca') || lower.includes('trova')) {
        statusFeedback = "Ricerca nel caveau e tra gli oggetti...";
      } else if (lower.includes('scadenz') || lower.includes('bollett') || lower.includes('f24') || lower.includes('da pagare') || lower.includes('quanto devo')) {
        statusFeedback = "Controllo scadenze e pagamenti...";
      } else if (lower.includes('esporta') || lower.includes('backup')) {
        statusFeedback = "Preparazione backup ed esportazione...";
      } else if (lower.includes('elimina') || lower.includes('cancella') || lower.includes('rimuovi')) {
        statusFeedback = "Aggiornamento caveau...";
      }

      setGenerationActive(true, statusFeedback, null, targetThreadId);
      const taskSignal = activeThreadTasks[targetThreadId]?.abortController?.signal;

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            message: text,
            thread_id: targetThreadId,
            quoted_message: quotedToSend ? { sender: quotedToSend.senderName, text: quotedToSend.text } : null
          }),
          signal: taskSignal
        });
        setGenerationActive(false, "", null, targetThreadId);
        if (!res.ok) throw new Error('Errore nella risposta del server');
        const data = await res.json();

        let itemPhoto = null;
        let storeItem = null;
        if (data.data) {
          if (data.action === "store_physical_item" && data.data.item_id) {
            if (data.data.image_url) {
              itemPhoto = { item_name: data.data.item_name, image_url: data.data.image_url };
            } else {
              storeItem = { item_id: data.data.item_id, item_name: data.data.item_name };
            }
          } else if (data.data.found_physical_items && Array.isArray(data.data.found_physical_items)) {
            const itemWithPhoto = data.data.found_physical_items.find(it => it.image_url);
            if (itemWithPhoto) {
              itemPhoto = { item_name: itemWithPhoto.item_name, image_url: itemWithPhoto.image_url };
            }
          }
        }

        let proposal = (data.data && data.data.proposal) || (data.action === "SENSITIVE_FILE_PROPOSAL" ? data.data : null);

        const th = threadsCache.find(t => t.id === targetThreadId);
        if (th) {
          th.last_message = data.reply ? cleanSidebarPreview(data.reply) : text;
          th.last_message_time = getTime();
          th.message_count = (th.message_count || 0) + 2;
          renderThreadsList();
        }

        // Se l'utente è ancora su questa chat, inietta subito la bolla di risposta
        if (currentThreadId === targetThreadId) {
          const routedModel = data.routed_model || (data.data && data.data.routed_model) || null;
          appendAssistantBubble(data.reply, data.documents, data.confirmation, itemPhoto, storeItem, proposal, routedModel);
          scrollBottom();
        } else {
          // L'utente si trova in un'altra chat: mostra toast non invasivo
          const targetName = th ? th.name : 'altra chat';
          showToast(`💬 Nuova risposta dell'assistente in "${targetName}"`, 'info', 4500);
        }
        loadDashboard(currentFilter);
      } catch (err) {
        if (err.name === 'AbortError' || err.message?.includes('aborted')) {
          setGenerationActive(false, "", null, targetThreadId);
          return;
        }
        setGenerationActive(false, "", null, targetThreadId);
        console.error('Errore /api/chat:', err);
        if (currentThreadId === targetThreadId) {
          appendAssistantBubble("⚠️ Errore di connessione: impossibile contattare il server.");
        } else {
          const th = threadsCache.find(t => t.id === targetThreadId);
          showToast(`⚠️ Errore risposta in "${th?.name || targetThreadId}"`, 'error', 4000);
        }
      }
    }

    // --- Upload File & Cartelle Multipli: POST /api/documents/upload o /api/documents/upload-batch ---
    const folderInput = document.getElementById('folderInput');
    const attachmentMenu = document.getElementById('attachmentMenu');

    function toggleAttachmentMenu(e) {
      if (e) e.stopPropagation();
      if (!attachmentMenu) return;
      attachmentMenu.classList.toggle('hidden');
    }

    function toggleDashboardToolsMenu(e) {
      if (e) e.stopPropagation();
      const menu = document.getElementById('dashboardToolsMenu');
      if (menu) menu.classList.toggle('hidden');
    }

    function closeDashboardToolsMenu() {
      const menu = document.getElementById('dashboardToolsMenu');
      if (menu) menu.classList.add('hidden');
    }

    // Chiudi menu a comparsa cliccando altrove
    document.addEventListener('click', (e) => {
      if (attachmentMenu && !attachmentMenu.classList.contains('hidden')) {
        const btn = document.getElementById('attachmentBtn');
        if (!attachmentMenu.contains(e.target) && (!btn || !btn.contains(e.target))) {
          attachmentMenu.classList.add('hidden');
        }
      }
      const dashMenu = document.getElementById('dashboardToolsMenu');
      if (dashMenu && !dashMenu.classList.contains('hidden')) {
        const dashBtn = document.getElementById('dashboardToolsBtn');
        if (!dashMenu.contains(e.target) && (!dashBtn || !dashBtn.contains(e.target))) {
          dashMenu.classList.add('hidden');
        }
      }
    });

    function triggerFileInput() {
      if (attachmentMenu) attachmentMenu.classList.add('hidden');
      closeDashboardToolsMenu();
      if (realFileInput) realFileInput.click();
    }

    function triggerFolderInput() {
      if (attachmentMenu) attachmentMenu.classList.add('hidden');
      closeDashboardToolsMenu();
      if (folderInput) folderInput.click();
    }

    function triggerCameraInput() {
      if (attachmentMenu) attachmentMenu.classList.add('hidden');
      const itemPhotoInput = document.getElementById('itemPhotoInput');
      if (itemPhotoInput) itemPhotoInput.click();
      else if (realFileInput) realFileInput.click();
    }

    function formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    async function processFilesUpload(fileList) {
      if (!fileList || fileList.length === 0) return;
      const files = Array.from(fileList);

      // Filtra file validi (accetta qualsiasi documento/foto/archivio ed esclude solo file di sistema OS e cartelle vuote non risolte)
      const validFiles = files.filter(f => {
        if (!f || !f.name) return false;
        const name = f.name.toLowerCase();
        if (name === '.ds_store' || name === 'thumbs.db' || name === 'desktop.ini' || name.startsWith('~$')) return false;
        if (f.size === 0 && !f.type && !name.includes('.')) return false;
        return true;
      });

      if (validFiles.length === 0) {
        showToast('Nessun file valido trovato da caricare.', 'warning');
        return;
      }

      const targetThreadId = currentThreadId;

      if (validFiles.length === 1) {
        // Upload singolo
        const file = validFiles[0];
        const isImage = file.type.startsWith('image/');
        const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
        const blobUrl = URL.createObjectURL(file);

        if (currentThreadId === targetThreadId) {
          appendUserFileBubble(file.name, file.size, blobUrl, isImage, isPdf);
        }
        setGenerationActive(true, `Analisi intelligente di ${file.name}...`, null, targetThreadId);
        const taskSignal = activeThreadTasks[targetThreadId]?.abortController?.signal;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('thread_id', targetThreadId);

        try {
          const res = await fetch('/api/documents/upload', {
            method: 'POST',
            headers: authHeaders(),
            body: formData,
            signal: taskSignal
          });
          setGenerationActive(false, "", null, targetThreadId);
          if (!res.ok) throw new Error('Errore durante l\'estrazione');
          const data = await res.json();
          const docItem = {
            id: data.document_id,
            title: data.title,
            issuer: data.issuer,
            amount: data.amount,
            due_date: data.due_date,
            status: data.status,
            summary: data.summary,
            file_url: data.file_url || blobUrl,
            download_url: data.download_url,
            drive_web_url: data.drive_web_url,
            file_type: data.file_type || (isPdf ? 'application/pdf' : 'image')
          };

          const th = threadsCache.find(t => t.id === targetThreadId);
          if (th) {
            th.last_message = data.chat_reply ? cleanSidebarPreview(data.chat_reply) : `Caricato ${file.name}`;
            th.last_message_time = getTime();
            th.message_count = (th.message_count || 0) + 2;
            renderThreadsList();
          }

          if (currentThreadId === targetThreadId) {
            appendAssistantBubble(data.chat_reply || "📄 Documento salvato e catalogato!", [docItem], null, null, null, null, data.routed_model || 'google/gemini-2.5-flash-lite');
            scrollBottom();
          } else {
            const targetName = th ? th.name : 'altra chat';
            showToast(`📄 Documento archiviato in "${targetName}": ${file.name}`, 'success', 4500);
          }
          loadDashboard(currentFilter);
        } catch (err) {
          if (err.name === 'AbortError' || err.message?.includes('aborted')) {
            setGenerationActive(false, "", null, targetThreadId);
            return;
          }
          setGenerationActive(false, "", null, targetThreadId);
          console.error('Errore /api/documents/upload:', err);
          if (currentThreadId === targetThreadId) {
            appendAssistantBubble("⚠️ Errore durante il caricamento del documento.");
          } else {
            const th = threadsCache.find(t => t.id === targetThreadId);
            showToast(`⚠️ Errore caricamento in "${th?.name || targetThreadId}"`, 'error', 4000);
          }
        }
      } else {
        // Upload Multiplo o Cartella con avanzamento reale al 100%
        const totalCount = validFiles.length;
        const totalSize = validFiles.reduce((acc, f) => acc + (f.size || 0), 0);
        const userSummaryText = `📁 Caricamento di ${totalCount} file... (${formatBytes(totalSize)})`;
        if (currentThreadId === targetThreadId) {
          appendUserBubble(userSummaryText);
        }

        setGenerationActive(true, `Avvio elaborazione di ${totalCount} file...`, 0, targetThreadId);
        const taskController = activeThreadTasks[targetThreadId]?.abortController;

        try {
          const uploadedDocs = [];
          const errors = [];
          let completedCount = 0;
          let fileIndex = 0;

          // Esecuzione concorrente controllata (3 richieste parallele) per massima velocità e feedback in tempo reale
          const CONCURRENCY = Math.min(3, totalCount);

          const uploadWorker = async () => {
            while (fileIndex < totalCount) {
              if (taskController?.signal?.aborted) break;
              const currentIdx = fileIndex++;
              const file = validFiles[currentIdx];
              
              updateTypingIndicator(`[${completedCount + 1}/${totalCount}] Analisi AI: ${file.name}`, Math.round((completedCount / totalCount) * 100), targetThreadId);

              const formData = new FormData();
              formData.append('file', file);
              formData.append('thread_id', targetThreadId);

              try {
                const res = await fetch('/api/documents/upload', {
                  method: 'POST',
                  headers: authHeaders(),
                  body: formData,
                  signal: taskController ? taskController.signal : undefined
                });

                if (res.ok) {
                  const data = await res.json();
                  uploadedDocs.push({
                    id: data.document_id,
                    title: data.title,
                    issuer: data.issuer,
                    amount: data.amount,
                    due_date: data.due_date,
                    status: data.status,
                    summary: data.summary,
                    file_url: data.file_url,
                    download_url: data.download_url,
                    drive_web_url: data.drive_web_url,
                    file_type: data.file_type
                  });
                } else {
                  console.warn(`Errore upload per ${file.name}: status ${res.status}`);
                  errors.push(file.name);
                }
              } catch (err) {
                if (err.name === 'AbortError' || err.message?.includes('aborted')) break;
                console.error(`Errore rete upload per ${file.name}:`, err);
                errors.push(file.name);
              } finally {
                completedCount++;
                const realPct = Math.round((completedCount / totalCount) * 100);
                updateTypingIndicator(`Elaborati ${completedCount} di ${totalCount} file (${realPct}%)...`, realPct, targetThreadId);
              }
            }
          };

          // Avvia i worker concorrenti
          const workers = [];
          for (let w = 0; w < CONCURRENCY; w++) {
            workers.push(uploadWorker());
          }
          await Promise.all(workers);

          if (taskController?.signal?.aborted) {
            setGenerationActive(false, "", null, targetThreadId);
            return;
          }

          updateTypingIndicator("Completato!", 100, targetThreadId);
          await new Promise(r => setTimeout(r, 300));

          setGenerationActive(false, "", null, targetThreadId);

          const th = threadsCache.find(t => t.id === targetThreadId);
          if (th) {
            th.last_message = `${uploadedDocs.length} file elaborati`;
            th.last_message_time = getTime();
            th.message_count = (th.message_count || 0) + uploadedDocs.length * 2;
            renderThreadsList();
          }

          let replyText = `📁 **${uploadedDocs.length} di ${totalCount}** file archiviati e catalogati nel caveau con successo!`;
          if (errors.length > 0) {
            replyText += `\n⚠️ *Attenzione: ${errors.length} file non sono stati elaborati.*`;
          }

          if (currentThreadId === targetThreadId) {
            if (uploadedDocs.length > 0) {
              appendAssistantBubble(replyText, uploadedDocs, null, null, null, null, 'google/gemini-2.5-flash-lite');
            } else {
              appendAssistantBubble("⚠️ Nessun file è stato elaborato con successo. Verifica i formati o la connessione.");
            }
            scrollBottom();
          } else {
            const targetName = th ? th.name : 'altra chat';
            showToast(`📁 Elaborazione completata in "${targetName}": ${uploadedDocs.length}/${totalCount} file`, 'success', 5000);
          }
          loadDashboard(currentFilter);
        } catch (err) {
          if (err.name === 'AbortError' || err.message?.includes('aborted')) {
            setGenerationActive(false, "", null, targetThreadId);
            return;
          }
          setGenerationActive(false, "", null, targetThreadId);
          console.error('Errore durante il caricamento batch:', err);
          if (currentThreadId === targetThreadId) {
            appendAssistantBubble("⚠️ Errore imprevisto durante il caricamento multiplo dei documenti.");
          } else {
            const th = threadsCache.find(t => t.id === targetThreadId);
            showToast(`⚠️ Errore caricamento multiplo in "${th?.name || targetThreadId}"`, 'error', 4000);
          }
        }
      }
    }

    if (realFileInput) {
      realFileInput.addEventListener('change', async (e) => {
        await processFilesUpload(e.target.files);
        realFileInput.value = '';
      });
    }

    if (folderInput) {
      folderInput.addEventListener('change', async (e) => {
        await processFilesUpload(e.target.files);
        folderInput.value = '';
      });
    }

    // --- Helper Ricorsivo Drag & Drop (Supporto File e Cartelle con Directory Traversal) ---
    async function traverseFileEntry(entry) {
      if (!entry) return [];
      if (entry.isFile) {
        return new Promise((resolve) => {
          entry.file(
            (file) => resolve([file]),
            (err) => {
              console.warn('Errore lettura file entry:', err);
              resolve([]);
            }
          );
        });
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        const readAllEntries = async () => {
          const batch = await new Promise((resolve) => {
            reader.readEntries((entries) => resolve(entries || []), () => resolve([]));
          });
          if (!batch || batch.length === 0) return [];
          const nextBatch = await readAllEntries();
          return batch.concat(nextBatch);
        };

        const entries = await readAllEntries();
        const filesPromises = entries.map(e => traverseFileEntry(e));
        const nestedFiles = await Promise.all(filesPromises);
        return nestedFiles.flat();
      }
      return [];
    }

    async function getFilesFromDataTransfer(dataTransfer) {
      if (!dataTransfer) return [];
      // Se l'API Items con webkitGetAsEntry è disponibile, estrai file e cartelle ricorsivamente
      const items = dataTransfer.items;
      if (items && items.length > 0 && typeof items[0].webkitGetAsEntry === 'function') {
        const promises = [];
        for (let i = 0; i < items.length; i++) {
          const item = items[i];
          if (item.kind === 'file') {
            const entry = item.webkitGetAsEntry();
            if (entry) {
              promises.push(traverseFileEntry(entry));
            } else {
              const f = item.getAsFile();
              if (f) promises.push(Promise.resolve([f]));
            }
          }
        }
        if (promises.length > 0) {
          const results = await Promise.all(promises);
          const flat = results.flat().filter(Boolean);
          if (flat.length > 0) return flat;
        }
      }
      // Fallback standard a dataTransfer.files
      if (dataTransfer.files && dataTransfer.files.length > 0) {
        return Array.from(dataTransfer.files);
      }
      return [];
    }

    // Previeni l'apertura accidentale del file nel browser se rilasciato fuori target
    window.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = 'copy';
      }
    });

    window.addEventListener('drop', (e) => {
      e.preventDefault();
    });

    // --- Drag & Drop su Chat ---
    const chatDropZone = document.getElementById('chatDropZone');
    const dragDropOverlay = document.getElementById('dragDropOverlay');

    if (chatDropZone && dragDropOverlay) {
      let chatDragCounter = 0;
      const chatTarget = chatView || chatDropZone;

      const handleChatDragEnter = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) {
          e.dataTransfer.dropEffect = 'copy';
        }
        chatDragCounter++;
        dragDropOverlay.classList.remove('hidden');
      };

      const handleChatDragOver = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) {
          e.dataTransfer.dropEffect = 'copy';
        }
      };

      const handleChatDragLeave = (e) => {
        e.preventDefault();
        e.stopPropagation();
        chatDragCounter--;
        if (chatDragCounter <= 0) {
          chatDragCounter = 0;
          dragDropOverlay.classList.add('hidden');
        }
      };

      const handleChatDrop = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        chatDragCounter = 0;
        dragDropOverlay.classList.add('hidden');

        try {
          const files = await getFilesFromDataTransfer(e.dataTransfer);
          if (files && files.length > 0) {
            await processFilesUpload(files);
          } else {
            showToast("Nessun file rilevato nel rilascio.", "warning");
          }
        } catch (err) {
          console.error("Errore elaborazione drop chat:", err);
          showToast("Errore durante la lettura dei file rilasciati.", "error");
        }
      };

      chatTarget.addEventListener('dragenter', handleChatDragEnter);
      chatTarget.addEventListener('dragover', handleChatDragOver);
      chatTarget.addEventListener('dragleave', handleChatDragLeave);
      chatTarget.addEventListener('drop', handleChatDrop);

      dragDropOverlay.addEventListener('dragenter', handleChatDragEnter);
      dragDropOverlay.addEventListener('dragover', handleChatDragOver);
      dragDropOverlay.addEventListener('dragleave', handleChatDragLeave);
      dragDropOverlay.addEventListener('drop', handleChatDrop);
    }

    // --- Drag & Drop su Dashboard FinTech ---
    const dashboardDragDropOverlay = document.getElementById('dashboardDragDropOverlay');

    if (dashboardView && dashboardDragDropOverlay) {
      let dashDragCounter = 0;

      const handleDashDragEnter = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) {
          e.dataTransfer.dropEffect = 'copy';
        }
        dashDragCounter++;
        dashboardDragDropOverlay.classList.remove('hidden');
      };

      const handleDashDragOver = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) {
          e.dataTransfer.dropEffect = 'copy';
        }
      };

      const handleDashDragLeave = (e) => {
        e.preventDefault();
        e.stopPropagation();
        dashDragCounter--;
        if (dashDragCounter <= 0) {
          dashDragCounter = 0;
          dashboardDragDropOverlay.classList.add('hidden');
        }
      };

      const handleDashDrop = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        dashDragCounter = 0;
        dashboardDragDropOverlay.classList.add('hidden');

        try {
          const files = await getFilesFromDataTransfer(e.dataTransfer);
          if (files && files.length > 0) {
            await processFilesUpload(files);
          } else {
            showToast("Nessun file rilevato nel rilascio.", "warning");
          }
        } catch (err) {
          console.error("Errore elaborazione drop dashboard:", err);
          showToast("Errore durante la lettura dei file rilasciati.", "error");
        }
      };

      dashboardView.addEventListener('dragenter', handleDashDragEnter);
      dashboardView.addEventListener('dragover', handleDashDragOver);
      dashboardView.addEventListener('dragleave', handleDashDragLeave);
      dashboardView.addEventListener('drop', handleDashDrop);

      dashboardDragDropOverlay.addEventListener('dragenter', handleDashDragEnter);
      dashboardDragDropOverlay.addEventListener('dragover', handleDashDragOver);
      dashboardDragDropOverlay.addEventListener('dragleave', handleDashDragLeave);
      dashboardDragDropOverlay.addEventListener('drop', handleDashDrop);
    }

    // --- Registratore Vocale Reale & Elaborazione Multimodale AI ---
    let voiceMediaStream = null;
    let voiceMediaRecorder = null;
    let voiceSpeechRecognition = null;
    let voiceLiveTranscription = '';
    let voiceAudioChunks = [];
    let voiceTimerInterval = null;
    let voiceRecordStartTime = null;

    async function startVoiceRecording() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showToast("⚠️ Il microfono non è supportato dal tuo browser.", "error");
        return;
      }

      try {
        voiceMediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (err) {
        console.error("Accesso microfono negato:", err);
        showToast("⚠️ Permesso microfono negato. Abilita il microfono per registrare vocali.", "error");
        return;
      }

      voiceLiveTranscription = '';
      if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        try {
          const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
          voiceSpeechRecognition = new SpeechRec();
          voiceSpeechRecognition.lang = 'it-IT';
          voiceSpeechRecognition.continuous = true;
          voiceSpeechRecognition.interimResults = true;
          voiceSpeechRecognition.onresult = (e) => {
            let full = '';
            for (let i = 0; i < e.results.length; i++) {
              if (e.results[i] && e.results[i][0]) {
                full += e.results[i][0].transcript + ' ';
              }
            }
            if (full.trim()) {
              voiceLiveTranscription = full.trim();
            }
          };
          voiceSpeechRecognition.onerror = (e) => {
            console.debug("Web Speech API status:", e.error);
          };
          voiceSpeechRecognition.start();
        } catch (recErr) {
          voiceSpeechRecognition = null;
        }
      }

      voiceAudioChunks = [];
      try {
        let mimeType = '';
        if (typeof MediaRecorder !== 'undefined') {
          if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) mimeType = 'audio/webm;codecs=opus';
          else if (MediaRecorder.isTypeSupported('audio/webm')) mimeType = 'audio/webm';
          else if (MediaRecorder.isTypeSupported('audio/mp4')) mimeType = 'audio/mp4';
          else if (MediaRecorder.isTypeSupported('audio/ogg')) mimeType = 'audio/ogg';
        }
        voiceMediaRecorder = mimeType ? new MediaRecorder(voiceMediaStream, { mimeType }) : new MediaRecorder(voiceMediaStream);
      } catch (e) {
        voiceMediaRecorder = new MediaRecorder(voiceMediaStream);
      }

      voiceMediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          voiceAudioChunks.push(e.data);
        }
      };

      voiceMediaRecorder.start(250);
      voiceRecordStartTime = Date.now();

      // UI: mostra la barra di registrazione
      const chatForm = document.getElementById('chatForm');
      const voiceBar = document.getElementById('voiceRecordingBar');
      const micBtn = document.getElementById('micBtn');
      const sendBtn = document.getElementById('sendBtn');
      const timerEl = document.getElementById('voiceRecordingTimer');

      if (chatForm) chatForm.classList.add('hidden');
      if (micBtn) micBtn.classList.add('hidden');
      if (sendBtn) sendBtn.classList.add('hidden');
      if (voiceBar) voiceBar.classList.remove('hidden');
      if (timerEl) timerEl.textContent = '0:00';

      clearInterval(voiceTimerInterval);
      voiceTimerInterval = setInterval(() => {
        const elapsedSec = Math.floor((Date.now() - voiceRecordStartTime) / 1000);
        if (timerEl) timerEl.textContent = formatDurationSeconds(elapsedSec);
      }, 500);
    }

    function cancelVoiceRecording() {
      cleanupVoiceRecording();
      voiceAudioChunks = [];
      showToast("Registrazione vocale annullata", "info");
    }

    function cleanupVoiceRecording() {
      clearInterval(voiceTimerInterval);
      voiceTimerInterval = null;

      if (voiceSpeechRecognition) {
        try { voiceSpeechRecognition.stop(); } catch (e) {}
        voiceSpeechRecognition = null;
      }

      if (voiceMediaRecorder && voiceMediaRecorder.state !== 'inactive') {
        try {
          voiceMediaRecorder.stop();
        } catch (e) {}
      }
      if (voiceMediaStream) {
        voiceMediaStream.getTracks().forEach(t => t.stop());
        voiceMediaStream = null;
      }

      const chatForm = document.getElementById('chatForm');
      const voiceBar = document.getElementById('voiceRecordingBar');
      const micBtn = document.getElementById('micBtn');
      const inputEl = document.getElementById('messageInput');

      if (voiceBar) voiceBar.classList.add('hidden');
      if (chatForm) chatForm.classList.remove('hidden');
      if (micBtn) micBtn.classList.remove('hidden');

      if (inputEl && inputEl.value.trim().length > 0) {
        const sendBtn = document.getElementById('sendBtn');
        if (sendBtn) sendBtn.classList.remove('hidden');
        if (micBtn) micBtn.classList.add('hidden');
      }
    }

    async function stopAndSendVoiceRecording() {
      if (!voiceMediaRecorder || voiceMediaRecorder.state === 'inactive') {
        cleanupVoiceRecording();
        return;
      }

      const durationSec = Math.max(1, Math.round((Date.now() - voiceRecordStartTime) / 1000));

      if (voiceSpeechRecognition) {
        try { voiceSpeechRecognition.stop(); } catch (e) {}
        voiceSpeechRecognition = null;
      }

      const stopPromise = new Promise(resolve => {
        voiceMediaRecorder.onstop = resolve;
      });

      voiceMediaRecorder.stop();
      if (voiceMediaStream) {
        voiceMediaStream.getTracks().forEach(t => t.stop());
        voiceMediaStream = null;
      }
      clearInterval(voiceTimerInterval);

      // Ripristina l'interfaccia chat standard
      const chatForm = document.getElementById('chatForm');
      const voiceBar = document.getElementById('voiceRecordingBar');
      const micBtn = document.getElementById('micBtn');
      if (voiceBar) voiceBar.classList.add('hidden');
      if (chatForm) chatForm.classList.remove('hidden');
      if (micBtn) micBtn.classList.remove('hidden');

      await stopPromise;

      const rawBlob = new Blob(voiceAudioChunks, { type: voiceMediaRecorder.mimeType || 'audio/webm' });
      voiceAudioChunks = [];

      if (rawBlob.size === 0) {
        showToast("⚠️ Nessun audio rilevato nel microfono", "warning");
        return;
      }

      const targetThreadId = currentThreadId;
      const quotedToSend = currentQuotedMessage;
      cancelQuoteReply();

      // Converti raw audio in WAV PCM 16-bit 16kHz compatibile al 100% con speech_recognition e Gemini
      let wavBlob = rawBlob;
      let base64Audio = '';
      try {
        const arrayBuffer = await rawBlob.arrayBuffer();
        const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
        if (AudioCtxClass) {
          const ctx = new AudioCtxClass();
          const decodedBuffer = await ctx.decodeAudioData(arrayBuffer);
          wavBlob = audioBufferToWav(decodedBuffer, 16000);
          base64Audio = await blobToBase64(wavBlob);
          await ctx.close();
        } else {
          base64Audio = await blobToBase64(rawBlob);
        }
      } catch (convErr) {
        console.warn("Conversione in WAV fallback su raw blob:", convErr);
        wavBlob = rawBlob;
        base64Audio = await blobToBase64(rawBlob);
      }

      const localAudioUrl = URL.createObjectURL(wavBlob);

      // Mostra all'istante la bolla vocale con player nella chat (con testo trascritto se già disponibile)
      const userVoiceBubbleEl = appendUserAudioBubble(localAudioUrl, durationSec, quotedToSend, voiceLiveTranscription || null);

      // Feedback assistente
      setGenerationActive(true, "L'assistente sta ascoltando il tuo messaggio vocale...", null, targetThreadId);
      const taskSignal = activeThreadTasks[targetThreadId]?.abortController?.signal;

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            message: voiceLiveTranscription || "",
            audio_base64: base64Audio,
            audio_format: "wav",
            audio_duration: durationSec,
            thread_id: targetThreadId,
            quoted_message: quotedToSend ? { sender: quotedToSend.senderName, text: quotedToSend.text } : null
          }),
          signal: taskSignal
        });

        setGenerationActive(false, "", null, targetThreadId);
        if (!res.ok) throw new Error('Errore nella risposta del server');
        const data = await res.json();

        // Se il server ha trascritto l'audio e la bolla non mostrava ancora il testo, mostralo adesso!
        if (data.transcription && userVoiceBubbleEl) {
          const slot = userVoiceBubbleEl.querySelector('.voice-transcription-slot');
          if (slot && !slot.innerHTML.trim()) {
            slot.innerHTML = `
              <div class="voice-transcription-preview text-[11px] text-[#333] italic font-mono-code pt-1.5 mt-1 border-t border-[#E3DDD1]/70 flex items-start gap-1.5 select-text">
                <i class="fa-solid fa-quote-left text-[8px] text-[#3C5A48] mt-0.5 opacity-60 shrink-0"></i>
                <span class="break-words">“${escapeHtml(data.transcription.trim())}”</span>
              </div>
            `;
          }
        }

        let itemPhoto = null;
        let storeItem = null;
        if (data.data) {
          if (data.action === "store_physical_item" && data.data.item_id) {
            if (data.data.image_url) {
              itemPhoto = { item_name: data.data.item_name, image_url: data.data.image_url };
            } else {
              storeItem = { item_id: data.data.item_id, item_name: data.data.item_name };
            }
          }
        }

        if (currentThreadId === targetThreadId) {
          const routedModel = data.routed_model || (data.data && data.data.routed_model) || null;
          appendAssistantBubble(data.reply, data.documents, data.confirmation, itemPhoto, storeItem, null, routedModel);
          scrollBottom();
        } else {
          const th = threadsCache.find(t => t.id === targetThreadId);
          showToast(`💬 Nuova risposta in "${th?.name || targetThreadId}"`, 'info', 4000);
        }
        loadDashboard(currentFilter);
      } catch (err) {
        if (err.name === 'AbortError' || err.message?.includes('aborted')) {
          setGenerationActive(false, "", null, targetThreadId);
          return;
        }
        setGenerationActive(false, "", null, targetThreadId);
        console.error('Errore /api/chat vocale:', err);
        if (currentThreadId === targetThreadId) {
          appendAssistantBubble("⚠️ Errore durante l'ascolto o l'elaborazione del messaggio vocale.");
          scrollBottom();
        }
      }
    }

    function blobToBase64(blob) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          const result = reader.result;
          const base64 = (typeof result === 'string' && result.includes(',')) ? result.split(',')[1] : result;
          resolve(base64);
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    }

    function audioBufferToWav(audioBuffer, targetSampleRate = 16000) {
      const numChannels = 1;
      const sourceData = audioBuffer.getChannelData(0);
      const sourceSampleRate = audioBuffer.sampleRate;

      let samples;
      if (sourceSampleRate === targetSampleRate) {
        samples = sourceData;
      } else {
        const ratio = sourceSampleRate / targetSampleRate;
        const newLength = Math.round(sourceData.length / ratio);
        samples = new Float32Array(newLength);
        for (let i = 0; i < newLength; i++) {
          const pos = i * ratio;
          const idx = Math.floor(pos);
          const frac = pos - idx;
          const s1 = sourceData[idx] || 0;
          const s2 = sourceData[idx + 1] || s1;
          samples[i] = s1 + frac * (s2 - s1);
        }
      }

      const byteRate = targetSampleRate * 2;
      const blockAlign = 2;
      const buffer = new ArrayBuffer(44 + samples.length * 2);
      const view = new DataView(buffer);

      function writeStr(v, offset, string) {
        for (let i = 0; i < string.length; i++) {
          v.setUint8(offset + i, string.charCodeAt(i));
        }
      }

      writeStr(view, 0, 'RIFF');
      view.setUint32(4, 36 + samples.length * 2, true);
      writeStr(view, 8, 'WAVE');
      writeStr(view, 12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, numChannels, true);
      view.setUint32(24, targetSampleRate, true);
      view.setUint32(28, byteRate, true);
      view.setUint16(32, blockAlign, true);
      view.setUint16(34, 16, true);
      writeStr(view, 36, 'data');
      view.setUint32(40, samples.length * 2, true);

      let offset = 44;
      for (let i = 0; i < samples.length; i++, offset += 2) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      }

      return new Blob([view], { type: 'audio/wav' });
    }

    // Alias per compatibilità con eventuali vecchie chiamate inline
    function handleVoice() {
      startVoiceRecording();
    }

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
          kpiAmtEl.innerHTML = `<span class="text-lg lg:text-xl font-bold text-[#7A7568] select-none">€</span><span>${formattedAmount}</span>`;
        }

        const kpiBadgeEl = document.getElementById('kpiUpcomingBadge');
        if (kpiBadgeEl) {
          const count = kpi.pending_deadlines_count || 0;
          kpiBadgeEl.textContent = count > 0 ? `${count} in scadenza` : `Nessuna scadenza`;
          kpiBadgeEl.className = count > 0
            ? "stamp-oli stamp-terracotta text-[9px] font-bold"
            : "stamp-oli text-[9px] font-bold";
        }

        const kpiDocsEl = document.getElementById('kpiDocsCount');
        if (kpiDocsEl) kpiDocsEl.textContent = `${kpi.total_documents_count || 0}`;

        const kpiItemsEl = document.getElementById('kpiItemsCount');
        if (kpiItemsEl) kpiItemsEl.textContent = `${kpi.total_items_count || 0}`;

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

    function renderDashboardView() {
      const groupedCont = document.getElementById('dashboardGroupedContainer');
      const tableCont = document.getElementById('dashboardTableContainer');
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
          const catLabel = doc.category_label || 'Altri Documenti';
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
              const lbl = rec.amount != null ? 'QUIETANZATO' : 'RINNOVATO';
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
              const titleAction = rec.amount != null ? 'Segna come pagato/quietanzato' : 'Segna come rinnovato o archiviato';
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
              <h3 class="text-xs font-bold text-slate-800 uppercase tracking-wider">Oggetti & Cespiti per Ambiente / Stanza</h3>
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
          const lbl = rec.amount != null ? 'QUIETANZATO' : 'RINNOVATO';
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
            const titleAction = rec.amount != null ? 'Segna come pagato/quietanzato' : 'Segna come rinnovato o archiviato';
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
      const btnD = document.getElementById('fDeadlines');
      const btnQ = document.getElementById('fQuietanzati');
      const btnI = document.getElementById('fItems');
      
      const baseBtnClass = 'px-2.5 py-1 rounded-xs font-space font-bold transition cursor-pointer text-[10px]';
      const inactiveClass = `${baseBtnClass} text-[#7A7568] hover:text-[#222220]`;
      const activeClass = `${baseBtnClass} bg-[#3C5A48] text-white`;

      [btnA, btnD, btnQ, btnI].forEach(b => {
        if (b) {
          b.className = inactiveClass;
          if (b === btnD || b === btnQ) b.classList.add('flex', 'items-center', 'gap-1');
        }
      });

      if (filter === 'all' && btnA) btnA.className = activeClass;
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
        } else if (filter === 'deadlines' || filter === 'da_pagare') {
          currentRecords = allDashboardRecordsCache.filter(r => r.type === 'document' && r.status === 'da_pagare');
        } else if (filter === 'quietanzati' || filter === 'quietanzato') {
          currentRecords = allDashboardRecordsCache.filter(r => r.status === 'quietanzato');
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

    function openMediaModal(url, title, fileType = '', downloadUrl = '', docId = null) {
      window.currentModalDocId = docId;
      window.currentModalDocUrl = url;
      const modal = document.getElementById('mediaModal');
      const titleEl = document.getElementById('modalTitle');
      const subtitleEl = document.getElementById('modalSubtitle');
      const downloadBtn = document.getElementById('modalDownloadBtn');
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
        pdfFrame.src = url;
        pdfFrame.classList.remove('hidden');
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
            <div class="flex flex-col items-center justify-center p-12 text-slate-500 gap-3">
              <i class="fa-solid fa-circle-notch fa-spin text-2xl text-[#128C7E]"></i>
              <span class="text-xs font-semibold text-slate-700">${isZip ? 'Lettura archivio compresso...' : 'Caricamento e decifratura anteprima in corso...'}</span>
            </div>
          `;
          fetch(`/api/documents/preview-content?file_url=${encodeURIComponent(url)}`)
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
                  <div class="p-8 text-center text-slate-500">
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
                <div class="p-8 text-center text-slate-500">
                  <i class="fa-solid fa-triangle-exclamation text-amber-500 text-2xl mb-2"></i>
                  <p class="font-semibold text-slate-700 text-sm">Impossibile generare l'anteprima del documento</p>
                  <p class="text-xs text-slate-400 mt-1 mb-4">${escapeHtml(err.message || 'Errore lettura file')}</p>
                  <a href="${targetDl}" download class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#075E54] text-white text-xs font-semibold rounded-lg shadow-2xs hover:bg-[#128C7E]">
                    <i class="fa-solid fa-download"></i> Scarica file originale
                  </a>
                </div>
              `;
            });
        }
      } else if (isImg) {
        subtitleEl.textContent = "Immagine / Scansione";
        imgPreview.onerror = function() {
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
        pdfFrame.src = url;
        pdfFrame.classList.remove('hidden');
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
      const pdfFrame = document.getElementById('modalPdfFrame');
      const imgPreview = document.getElementById('modalImagePreview');
      const officePreview = document.getElementById('modalOfficePreview');
      const officeContent = document.getElementById('modalOfficeContent');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
      if (pdfFrame) pdfFrame.src = '';
      if (imgPreview) imgPreview.src = '';
      if (officePreview) officePreview.classList.add('hidden');
      if (officeContent) officeContent.innerHTML = '';
    }

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
                appendAssistantBubble(bubbleText, null, null, null, null, proposalData);
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

    function initApp() {
      applyLayout();
      updateAllBottomNavs('chat');
      loadAiModelSetting();
      loadOpenRouterCredits();
      loadThreads();
      loadDashboard('all');
      checkDeadlineAlerts();
      checkPendingProposalsBanner();
      loadGoogleDriveStatus();
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('drive_connected') === 'true') {
        showToast('🟢 Google Drive collegato con successo!', 'success');
        window.history.replaceState({}, document.title, window.location.pathname);
      }
      // Polling periodico per rilevare nuovi file sensibili segnalati dal monitor di background
      setInterval(checkPendingProposalsBanner, 20000);
    }

    // Inizializzazione al caricamento della pagina con controllo di sicurezza Caveau
    document.addEventListener('DOMContentLoaded', () => {
      checkVaultAuth();
    });
    // Verifica immediata se il DOM è già pronto
    checkVaultAuth();
