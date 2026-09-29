// =========================================================================
// MODULO 1: Core, Autenticazione, Ambiente, Sicurezza & Lock Screen
// =========================================================================
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
    window.currentThreadId = 'general';
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
              el.classList.add('cursor-pointer');
              el.title = 'Versione ' + data.version + ' (clicca per verificare aggiornamenti)';
              el.onclick = () => window.checkAppUpdates && window.checkAppUpdates(true);
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

    // --- Helper Autenticazione con Token Cifrato & Supabase JWT ---
    function authHeaders(extra = {}) {
      const token = sessionStorage.getItem('vault_token') || localStorage.getItem('vault_token');
      const cloudToken = sessionStorage.getItem('supabase_auth_token') || localStorage.getItem('supabase_auth_token');
      const h = { ...extra };
      if (token) {
        h['X-Vault-Token'] = token;
      }
      if (cloudToken) {
        h['Authorization'] = `Bearer ${cloudToken}`;
      }
      return h;
    }
    const getAuthHeaders = authHeaders;
    window.getAuthHeaders = authHeaders;

    let currentCloudUser = null;
    window.currentCloudUser = null;

    async function checkSimulatorParam() {
      const urlParams = new URLSearchParams(window.location.search);
      const simUser = urlParams.get('sim_user') || urlParams.get('user');
      if (simUser) {
        try {
          const res = await fetch('/api/simulator/switch-user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_key: simUser })
          });
          if (res.ok) {
            const data = await res.json();
            if (data.access_token) {
              sessionStorage.setItem('supabase_auth_token', data.access_token);
              localStorage.setItem('supabase_auth_token', data.access_token);
              currentCloudUser = data.user;
              window.currentCloudUser = data.user;
              return data.user;
            }
          }
        } catch (e) {
          console.warn("Errore auto-switch sim_user:", e);
        }
      }
      return null;
    }
    window.checkSimulatorParam = checkSimulatorParam;

    async function checkCloudAuthStatus() {
      const token = sessionStorage.getItem('supabase_auth_token') || localStorage.getItem('supabase_auth_token');
      const unauthBox = document.getElementById('authUnauthenticatedBox');
      const authBox = document.getElementById('authAuthenticatedBox');
      const headerBtn = document.getElementById('headerAccountBtn');
      const headerBadge = document.getElementById('headerAccountBadge');
      const sidebarBtn = document.getElementById('sidebarAccountBtn');
      const simLabel = document.getElementById('simulatorActiveUserLabel');

      if (!token) {
        currentCloudUser = null;
        window.currentCloudUser = null;
        if (unauthBox) unauthBox.classList.remove('hidden');
        if (authBox) authBox.classList.add('hidden');
        if (headerBtn) {
          headerBtn.classList.remove('bg-[#3C5A48]', 'text-white');
          headerBtn.classList.add('bg-white', 'text-[#3C5A48]');
          headerBtn.title = "Il mio Account & Profilo Cloud (Offline)";
        }
        if (headerBadge) headerBadge.classList.add('hidden');
        if (sidebarBtn) sidebarBtn.classList.remove('bg-[#3C5A48]', 'text-white');
        if (simLabel) simLabel.textContent = "Simula";
        return null;
      }

      try {
        const res = await fetch('/api/auth/cloud/me', { headers: authHeaders() });
        if (res.ok) {
          const user = await res.json();
          currentCloudUser = user;
          window.currentCloudUser = user;
          if (unauthBox) unauthBox.classList.add('hidden');
          if (authBox) authBox.classList.remove('hidden');
          
          const nameEl = document.getElementById('authProfileName');
          const emailEl = document.getElementById('authProfileEmail');
          const avatarEl = document.getElementById('authProfileAvatar');
          if (nameEl) nameEl.textContent = user.full_name || 'Utente';
          if (emailEl) emailEl.textContent = user.email || '';
          if (avatarEl) avatarEl.textContent = (user.full_name || user.email || 'U')[0].toUpperCase();

          if (headerBtn) {
            headerBtn.classList.add('bg-[#3C5A48]', 'text-white');
            headerBtn.classList.remove('bg-white', 'text-[#3C5A48]');
            headerBtn.title = `Il mio Account: ${user.full_name || user.email}`;
          }
          if (headerBadge) headerBadge.classList.remove('hidden');
          if (sidebarBtn) sidebarBtn.classList.add('bg-[#3C5A48]', 'text-white');
          if (simLabel) {
            const first = (user.full_name || user.email || 'Utente').split(' ')[0];
            simLabel.textContent = first;
          }
          return user;
        } else {
          localStorage.removeItem('supabase_auth_token');
          sessionStorage.removeItem('supabase_auth_token');
          currentCloudUser = null;
          window.currentCloudUser = null;
          if (unauthBox) unauthBox.classList.remove('hidden');
          if (authBox) authBox.classList.add('hidden');
          if (headerBtn) {
            headerBtn.classList.remove('bg-[#3C5A48]', 'text-white');
            headerBtn.classList.add('bg-white', 'text-[#3C5A48]');
            headerBtn.title = "Il mio Account & Profilo Cloud (Offline)";
          }
          if (headerBadge) headerBadge.classList.add('hidden');
          if (simLabel) simLabel.textContent = "Simula";
          return null;
        }
      } catch (err) {
        console.warn("Errore checkCloudAuthStatus:", err);
        if (simLabel) simLabel.textContent = "Simula";
        return null;
      }
    }
    window.checkCloudAuthStatus = checkCloudAuthStatus;

    // --- Sistema Aggiornamenti Over-The-Air (OTA) & Controllo Manuale ---
    window.checkAppUpdates = async function(isManual = true) {
      // 1. Se siamo nell'app Android con bridge nativo AndroidUpdater
      if (window.AndroidUpdater && typeof window.AndroidUpdater.checkNow === 'function') {
        window.AndroidUpdater.checkNow();
        return;
      }

      // 2. Se siamo in un browser desktop o mobile
      if (isManual && typeof showToast === 'function') {
        showToast("Verifica disponibilità aggiornamenti in corso...", "info", 2000);
      }

      try {
        const res = await fetch('https://raw.githubusercontent.com/themeig/DOVE-LO-AI-MESSO/main/android-release/version.json?t=' + Date.now(), { cache: 'no-store' });
        if (!res.ok) throw new Error("Errore recupero metadati aggiornamento");
        const remote = await res.json();
        
        const localRes = await fetch('/api/version');
        const localData = await localRes.json();
        const currentVer = localData.version || "2.6.1";

        if (remote.version_name && remote.version_name !== currentVer) {
          const notes = remote.release_notes ? ` Note: ${remote.release_notes}` : '';
          if (typeof showToast === 'function') {
            showToast(`✨ Nuova versione v${remote.version_name} disponibile!${notes}`, "success", 8000);
          } else {
            alert(`✨ Nuova versione v${remote.version_name} disponibile!${notes}`);
          }
        } else {
          if (isManual) {
            if (typeof showToast === 'function') {
              showToast(`✅ Sei già all'ultima versione disponibile (v${currentVer})`, "success", 3500);
            } else {
              alert(`✅ Sei già all'ultima versione disponibile (v${currentVer})`);
            }
          }
        }
      } catch (err) {
        if (isManual) {
          if (typeof showToast === 'function') {
            showToast("⚠️ Impossibile verificare gli aggiornamenti al momento.", "warning", 3500);
          } else {
            alert("⚠️ Impossibile verificare gli aggiornamenti al momento.");
          }
        }
      }
    };

    // --- Sincronizzazione Versione App Dinamica ---
    async function fetchAppVersion() {
      try {
        const res = await fetch('/api/version');
        if (res.ok) {
          const data = await res.json();
          if (data && data.version) {
            document.querySelectorAll('.app-version-badge').forEach(el => {
              el.textContent = 'v' + data.version;
              el.classList.add('cursor-pointer');
              el.title = 'Versione ' + data.version + ' (clicca per verificare aggiornamenti)';
              el.onclick = () => window.checkAppUpdates(true);
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
      if (typeof checkSimulatorParam === 'function') {
        await checkSimulatorParam();
      }
      let token = sessionStorage.getItem('vault_token') || localStorage.getItem('vault_token');
      try {
        const res = await fetch('/api/auth/status', {
          headers: authHeaders()
        });
        if (res.ok) {
          const data = await res.json();
          if (data.unlocked) {
            const effectiveToken = token || data.token;
            if (effectiveToken) {
              sessionStorage.setItem('vault_token', effectiveToken);
              localStorage.setItem('vault_token', effectiveToken);
            }
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
        localStorage.setItem('vault_token', data.token);
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
      localStorage.removeItem('vault_token');
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
      if (!file) return;

      if (pendingPhotoItemId) {
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
            ensureTodayDateDivider();
            appendAssistantBubble(
              `📸 **Foto memorizzata!** Ho salvato la foto della posizione per **${data.item_name}**.`,
              null,
              null,
              { item_name: data.item_name, image_url: data.image_url },
              null,
              null,
              null,
              getTime()
            );
          }
        } catch (err) {
          console.error('Errore caricamento foto:', err);
          alert('Impossibile salvare la foto: ' + err.message);
        }
      } else {
        // Scatto da fotocamera per documenti o chat
        if (typeof handleCameraMultiPhotoSelected === 'function') {
          handleCameraMultiPhotoSelected(event);
        } else if (window.MobileScanner && typeof window.MobileScanner.loadExternalImage === 'function') {
          window.MobileScanner.loadExternalImage(file);
        } else {
          processFilesUpload([file]);
        }
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

    // =========================================================================
    // SIMULATORE MULTI-UTENTE & TESTING CHAT CONDIVISA IN TEMPO REALE
    // =========================================================================
    function toggleSimulatorDropdown() {
      const menu = document.getElementById('simulatorDropdownMenu');
      if (menu) {
        menu.classList.toggle('hidden');
      }
    }
    window.toggleSimulatorDropdown = toggleSimulatorDropdown;

    function closeSimulatorDropdown() {
      const menu = document.getElementById('simulatorDropdownMenu');
      if (menu) {
        menu.classList.add('hidden');
      }
    }
    window.closeSimulatorDropdown = closeSimulatorDropdown;

    document.addEventListener('click', (e) => {
      const btn = document.getElementById('simulatorDropdownBtn');
      const menu = document.getElementById('simulatorDropdownMenu');
      if (btn && menu && !btn.contains(e.target) && !menu.contains(e.target)) {
        menu.classList.add('hidden');
      }
    });

    async function switchActiveSimulatorUser(userKey) {
      closeSimulatorDropdown();
      if (typeof closeAccountModal === 'function') closeAccountModal();
      try {
        const res = await fetch('/api/simulator/switch-user', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_key: userKey })
        });
        if (!res.ok) throw new Error("Errore durante il cambio utente");
        const data = await res.json();
        if (data.access_token) {
          sessionStorage.setItem('supabase_auth_token', data.access_token);
          localStorage.setItem('supabase_auth_token', data.access_token);
          currentCloudUser = data.user;
          window.currentCloudUser = data.user;

          // Aggiorna URL e ricarica per sessione pulita ed isolata
          const url = new URL(window.location.href);
          url.searchParams.set('sim_user', userKey);
          window.location.href = url.toString();
        }
      } catch (err) {
        console.error("Errore switchActiveSimulatorUser:", err);
        alert("Errore cambio utente simulato: " + err.message);
      }
    }
    window.switchActiveSimulatorUser = switchActiveSimulatorUser;

    async function launchSecondWindowSimulator(userKey = 'laura') {
      closeSimulatorDropdown();
      try {
        if (typeof showToast === 'function') {
          showToast(`Avvio seconda finestra desktop per ${userKey}...`, 'info');
        }
        const res = await fetch('/api/simulator/launch-window', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_key: userKey })
        });
        const data = await res.json();
        if (res.ok) {
          if (typeof showToast === 'function') {
            showToast(`Finestra avviata: ${data.message || 'Sessione aperta'}`, 'success');
          } else {
            alert(data.message || 'Finestra avviata');
          }
        } else {
          throw new Error(data.detail || 'Impossibile avviare finestra');
        }
      } catch (err) {
        console.error("Errore launchSecondWindowSimulator:", err);
        alert("Impossibile avviare seconda finestra: " + err.message);
      }
    }
    window.launchSecondWindowSimulator = launchSecondWindowSimulator;

    function openSplitScreenSimulator() {
      closeSimulatorDropdown();
      window.open('/simulator/split', '_blank');
    }
    window.openSplitScreenSimulator = openSplitScreenSimulator;
