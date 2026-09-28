// =========================================================================
// MODULO 2: Navigazione, Slide Carousel, Touch Gestures 1:1 & Popstate
// =========================================================================
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
        if (typeof loadCalendarStatus === 'function') loadCalendarStatus();
        if (typeof updateSystemMenuStatusBadges === 'function') updateSystemMenuStatusBadges();
        if (typeof setSystemArea === 'function') setSystemArea(sessionStorage.getItem('dove_system_active_area') || 'all');
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

    function openPanelHub() {
      const hub = document.getElementById('panelHubContainer');
      const detail = document.getElementById('panelDetailContainer');
      if (hub) hub.classList.remove('hidden');
      if (detail) detail.classList.add('hidden');
      const main = document.querySelector('#dashboardView main');
      if (main) main.scrollTop = 0;
      loadDashboard('all');
    }
    window.openPanelHub = openPanelHub;

    function openPanelSection(section) {
      const hub = document.getElementById('panelHubContainer');
      const detail = document.getElementById('panelDetailContainer');
      const panoStats = document.getElementById('panoramicaStatsContainer');

      if (hub) hub.classList.add('hidden');
      if (detail) detail.classList.remove('hidden');

      const titleEl = document.getElementById('panelDetailSectionTitle');
      const iconEl = document.getElementById('panelDetailSectionIcon');
      const badgeEl = document.getElementById('panelDetailSectionBadge');

      const norm = (section || 'panoramica').toLowerCase().trim();

      if (norm === 'scadenze' || norm === 'deadlines' || norm === 'scadenzario' || norm === 'da_pagare') {
        if (panoStats) panoStats.classList.add('hidden');
        if (titleEl) titleEl.textContent = 'SCADENZE & TRIBUTI';
        if (iconEl) iconEl.className = 'fa-solid fa-calendar-days text-[#C84B31] text-xs';
        if (badgeEl) {
          badgeEl.textContent = 'SCADENZARIO';
          badgeEl.className = 'stamp-oli stamp-terracotta text-[9px] font-bold';
        }
        filterTable('scadenzario');
      } else if (norm === 'atti' || norm === 'documents' || norm === 'documenti') {
        if (panoStats) panoStats.classList.add('hidden');
        if (titleEl) titleEl.textContent = 'ATTI & DOCUMENTI';
        if (iconEl) iconEl.className = 'fa-solid fa-file-invoice text-[#3C5A48] text-xs';
        if (badgeEl) {
          badgeEl.textContent = 'ARCHIVIO ATTI';
          badgeEl.className = 'stamp-oli stamp-solid-sage text-[9px] font-bold';
        }
        filterTable('atti');
      } else if (norm === 'oggetti' || norm === 'items') {
        if (panoStats) panoStats.classList.add('hidden');
        if (titleEl) titleEl.textContent = 'OGGETTI FISICI & STANZE';
        if (iconEl) iconEl.className = 'fa-solid fa-boxes-stacked text-[#7A7568] text-xs';
        if (badgeEl) {
          badgeEl.textContent = 'INVENTARIO';
          badgeEl.className = 'stamp-oli text-[9px] font-bold';
        }
        filterTable('items');
      } else {
        // panoramica / all
        if (panoStats) panoStats.classList.remove('hidden');
        if (titleEl) titleEl.textContent = 'PANORAMICA & STATISTICHE';
        if (iconEl) iconEl.className = 'fa-solid fa-chart-pie text-[#3C5A48] text-xs';
        if (badgeEl) {
          badgeEl.textContent = 'STATISTICHE & REPORT';
          badgeEl.className = 'stamp-oli stamp-solid-sage text-[9px] font-bold';
        }
        filterTable('all');
      }

      const main = document.querySelector('#dashboardView main');
      if (main) main.scrollTop = 0;
    }
    window.openPanelSection = openPanelSection;

    function openDashboard(filter = null) {
      slideToScreen('dashboard', () => {
        if (filter && filter !== 'all') {
          openPanelSection(filter);
        } else {
          openPanelHub();
        }
      });
    }
    window.openDashboard = openDashboard;

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
        openDashboard(null);
      } else if (screen === 'chat') {
        closeToChat();
      } else if (screen === 'archive') {
        openDashboard('items');
      } else if (screen === 'settings' || screen === 'system') {
        openSystem();
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
        try {
          if (window.history.state && window.history.state.view === 'conversation') {
            window.history.replaceState({ screen: 'chat', view: 'sidebar' }, '');
          }
        } catch (_) {}
      }
      // Su desktop non fa nulla — entrambi i pannelli sono sempre visibili
    }
    window.showThreadsSidebar = showThreadsSidebar;

    function showConversation() {
      if (isMobileView) {
        _mobileShowConversation(true);
        try {
          if (!window.history.state || window.history.state.view !== 'conversation') {
            window.history.pushState({ screen: 'chat', view: 'conversation', threadId: currentThreadId }, '');
          }
        } catch (_) {}
        requestAnimationFrame(() => {
          scrollToBottom(false);
          setTimeout(() => scrollToBottom(false), 120);
          setTimeout(() => scrollToBottom(false), 300);
        });
      }
    }
    window.showConversation = showConversation;

    // --- Gestione Tasto Indietro Nativo Mobile (Android / Browser Popstate) ---
    function handleNativeBackPress() {
      // 1. Chiudi modali o drawer aperti se presenti
      const openModalIds = [
        'multiPhotoModal',
        'multiScanChoiceModal',
        'googleDriveModal',
        'newThreadModal',
        'documentDetailModal',
        'watchedFoldersModal',
        'deleteConfirmModal',
        'scannerPreviewModal',
        'systemModal',
        'whitePaperModal'
      ];
      for (const mId of openModalIds) {
        const el = document.getElementById(mId);
        if (el && !el.classList.contains('hidden')) {
          if (mId === 'multiPhotoModal' && typeof cancelMultiPhotoSession === 'function') {
            cancelMultiPhotoSession();
            return true;
          }
          if (mId === 'multiScanChoiceModal' && typeof cancelMultiScanChoice === 'function') {
            cancelMultiScanChoice();
            return true;
          }
          if (mId === 'googleDriveModal' && typeof closeGoogleDriveModal === 'function') {
            closeGoogleDriveModal();
            return true;
          }
          if (mId === 'newThreadModal' && typeof closeNewThreadModal === 'function') {
            closeNewThreadModal();
            return true;
          }
          if (mId === 'watchedFoldersModal' && typeof closeWatchedFoldersModal === 'function') {
            closeWatchedFoldersModal();
            return true;
          }
          el.classList.add('hidden');
          el.classList.remove('flex');
          return true;
        }
      }

      // 2. Se l'utente è all'interno della conversazione su mobile, torna all'elenco chat/canali
      if (isMobileView && currentActiveScreen === 'chat') {
        const conv = document.getElementById('conversationPanel');
        if (conv && conv.classList.contains('mobile-active')) {
          showThreadsSidebar();
          return true;
        }
      }

      // 2b. Se l'utente si trova in Sistema e ha una sezione aperta nel dettaglio, torna all'elenco sezioni principale
      if (currentActiveScreen === 'settings') {
        const detail = document.getElementById('systemSectionDetailView');
        if (detail && !detail.classList.contains('hidden')) {
          if (typeof closeSystemSection === 'function') {
            closeSystemSection();
          } else {
            detail.classList.add('hidden');
            const menu = document.getElementById('systemSectionsMenu');
            if (menu) menu.classList.remove('hidden');
          }
          return true;
        }
      }

      // 3. Se l'utente si trova su Dashboard o Sistema, torna alla sezione Conversa (Chat)
      if (currentActiveScreen !== 'chat') {
        closeToChat();
        return true;
      }

      // 4. Se si trova già nella lista chat principale (root), ritorna false per consentire l'uscita
      return false;
    }
    window.handleNativeBackPress = handleNativeBackPress;

    // Listener popstate per browser mobile
    window.addEventListener('popstate', (e) => {
      handleNativeBackPress();
    });

    // --- Gestione Gesture di Swipe Orizzontale Interattivo (1:1 Dragging) per Cambio Sezione Mobile ---
    function initMobileSwipeGestures() {
      let touchStartX = 0;
      let touchStartY = 0;
      let touchStartTime = 0;
      let isDragging = false;
      let gestureDirection = null; // null | 'horizontal' | 'vertical'
      let activeFromEl = null;
      let activeToEl = null;
      let targetScreen = null;
      let viewportWidth = window.innerWidth;

      const viewport = document.getElementById('appScreensViewport') || document.body;

      function resetDragState() {
        if (activeFromEl) {
          activeFromEl.style.transform = '';
          activeFromEl.style.transition = '';
          activeFromEl.style.zIndex = '';
          activeFromEl.style.willChange = '';
        }
        if (activeToEl) {
          activeToEl.classList.add('hidden');
          activeToEl.classList.remove('flex');
          activeToEl.style.transform = '';
          activeToEl.style.transition = '';
          activeToEl.style.zIndex = '';
          activeToEl.style.willChange = '';
        }
        activeFromEl = null;
        activeToEl = null;
        targetScreen = null;
        isDragging = false;
        gestureDirection = null;
      }

      viewport.addEventListener('touchstart', (e) => {
        if (e.touches.length !== 1) {
          resetDragState();
          return;
        }

        // Attivo su mobile / tablet o viewport ristretto
        if (!isMobileView && window.innerWidth > 850) {
          return;
        }

        if (isTransitioningScreens) {
          return;
        }

        const target = e.target;
        // Non iniziare lo swipe su controlli di testo interattivi o bottoni form
        if (target.closest('input, textarea, select, #chatForm, #inputContainer, #threadsSearchInput, .modal-card, #multiPhotoModal, #multiScanChoiceModal')) {
          return;
        }

        // Ignora se un modale è aperto
        const openModal = document.querySelector('#googleDriveModal:not(.hidden), #newThreadModal:not(.hidden), #watchedFoldersModal:not(.hidden), #multiPhotoModal:not(.hidden), #multiScanChoiceModal:not(.hidden)');
        if (openModal) {
          return;
        }

        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        touchStartTime = Date.now();
        isDragging = false;
        gestureDirection = null;
        viewportWidth = viewport.clientWidth || window.innerWidth || 360;
      }, { passive: true });

      viewport.addEventListener('touchmove', (e) => {
        if (e.touches.length !== 1 || isTransitioningScreens) return;

        const currentX = e.touches[0].clientX;
        const currentY = e.touches[0].clientY;
        const dx = currentX - touchStartX;
        const dy = currentY - touchStartY;

        // Se la direzione non è ancora stata determinata:
        if (gestureDirection === null) {
          const absDx = Math.abs(dx);
          const absDy = Math.abs(dy);

          // Attendi un movimento iniziale minimo di 6px per capire l'intento dell'utente
          if (absDx < 6 && absDy < 6) return;

          if (absDx > absDy * 1.1) {
            gestureDirection = 'horizontal';
            isDragging = true;
          } else {
            gestureDirection = 'vertical';
            isDragging = false;
            return;
          }
        }

        // Se il gesto è stato classificato come scroll verticale, lascia scorrere la pagina/messaggi nativamente
        if (gestureDirection !== 'horizontal' || !isDragging) return;

        // Blocca lo scroll verticale mentre si trascina l'interfaccia orizzontalmente
        if (e.cancelable) e.preventDefault();

        const normalizedCurrent = (currentActiveScreen === 'system') ? 'settings' : currentActiveScreen;
        let nextTarget = null;

        if (dx > 0) {
          // Trascina verso destra -> (scopre la schermata a sinistra)
          if (normalizedCurrent === 'settings') nextTarget = 'chat';
          else if (normalizedCurrent === 'chat') nextTarget = 'dashboard';
          else nextTarget = null; // A sinistra della dashboard non c'è nulla
        } else if (dx < 0) {
          // Trascina verso sinistra <- (scopre la schermata a destra)
          if (normalizedCurrent === 'dashboard') nextTarget = 'chat';
          else if (normalizedCurrent === 'chat') nextTarget = 'settings';
          else nextTarget = null; // A destra di settings non c'è nulla
        }

        const fromEl = getScreenElement(normalizedCurrent);
        if (!fromEl) return;
        activeFromEl = fromEl;

        // Gestione fine corsa (resistenza elastica se non ci sono ulteriori schermate in quella direzione)
        if (!nextTarget) {
          if (activeToEl) {
            activeToEl.classList.add('hidden');
            activeToEl.classList.remove('flex');
            activeToEl.style.transform = '';
            activeToEl = null;
          }
          const elasticDx = dx * 0.22;
          fromEl.style.transition = 'none';
          fromEl.style.transform = `translate3d(${elasticDx}px, 0, 0)`;
          targetScreen = null;
          return;
        }

        const toEl = getScreenElement(nextTarget);
        if (!toEl) return;

        // Se è cambiato il target rispetto alla mossa precedente (es. inversione repentina del dito)
        if (activeToEl && activeToEl !== toEl) {
          activeToEl.classList.add('hidden');
          activeToEl.classList.remove('flex');
          activeToEl.style.transform = '';
          activeToEl = null;
        }

        if (activeToEl !== toEl) {
          activeToEl = toEl;
          targetScreen = nextTarget;
          toEl.classList.remove('hidden');
          toEl.classList.add('flex');
          toEl.style.transition = 'none';
          toEl.style.zIndex = '15';
          fromEl.style.zIndex = '20';
          toEl.style.willChange = 'transform';
          fromEl.style.willChange = 'transform';

          if (nextTarget === 'dashboard') renderDashboardView();
        }

        // Calcola e applica la traslazione graduale 1:1 in tempo reale con accelerazione hardware GPU
        fromEl.style.transition = 'none';
        fromEl.style.transform = `translate3d(${dx}px, 0, 0)`;

        const toX = (dx > 0) ? (-viewportWidth + dx) : (viewportWidth + dx);
        toEl.style.transition = 'none';
        toEl.style.transform = `translate3d(${toX}px, 0, 0)`;
      }, { passive: false });

      function handleDragEnd(e) {
        if (!isDragging || !activeFromEl) {
          resetDragState();
          return;
        }

        const changedTouch = (e.changedTouches && e.changedTouches[0]) || null;
        const currentX = changedTouch ? changedTouch.clientX : touchStartX;
        const dx = currentX - touchStartX;
        const elapsed = Math.max(1, Date.now() - touchStartTime);
        const velocity = dx / elapsed; // px/ms

        isDragging = false;
        gestureDirection = null;

        const threshold = viewportWidth * 0.18; // Superato il 18% della larghezza o scatto rapido
        const commit = targetScreen && (
          (dx > 0 && (dx > threshold || (dx > 25 && velocity > 0.3))) ||
          (dx < 0 && (dx < -threshold || (dx < -25 && velocity < -0.3)))
        );

        if (commit && activeToEl) {
          isTransitioningScreens = true;
          const animDuration = 240;
          const easing = `transform ${animDuration}ms cubic-bezier(0.25, 1, 0.5, 1)`;

          activeFromEl.style.transition = easing;
          activeToEl.style.transition = easing;

          const fromEnd = (dx > 0) ? viewportWidth : -viewportWidth;
          activeFromEl.style.transform = `translate3d(${fromEnd}px, 0, 0)`;
          activeToEl.style.transform = 'translate3d(0, 0, 0)';

          const committedTarget = targetScreen;
          const fromElToHide = activeFromEl;
          const toElToShow = activeToEl;

          setTimeout(() => {
            fromElToHide.classList.add('hidden');
            fromElToHide.classList.remove('flex');
            fromElToHide.style.transform = '';
            fromElToHide.style.transition = '';
            fromElToHide.style.zIndex = '';
            fromElToHide.style.willChange = '';

            toElToShow.style.transform = '';
            toElToShow.style.transition = '';
            toElToShow.style.zIndex = '';
            toElToShow.style.willChange = '';

            currentActiveScreen = committedTarget;
            updateAllBottomNavs(committedTarget);
            isTransitioningScreens = false;

            activeFromEl = null;
            activeToEl = null;
            targetScreen = null;

            // Caricamento dati e inizializzazione della schermata di destinazione
            if (committedTarget === 'dashboard') {
              renderDashboardView();
              loadDashboard(currentFilter);
            } else if (committedTarget === 'settings') {
              loadAiModelSetting();
              loadOpenRouterCredits();
              loadGoogleDriveStatus();
              loadWatchedFolders();
              if (typeof loadCalendarStatus === 'function') loadCalendarStatus();
              if (typeof updateSystemMenuStatusBadges === 'function') updateSystemMenuStatusBadges();
              if (typeof setSystemArea === 'function') setSystemArea(sessionStorage.getItem('dove_system_active_area') || 'all');
            } else if (committedTarget === 'chat') {
              if (isMobileView) {
                if (conversationPanel.classList.contains('mobile-active')) {
                  _mobileShowConversation(false);
                } else {
                  _mobileShowSidebar(false);
                }
              }
            }
          }, animDuration + 10);
        } else {
          // Rimbalzo / Annullamento: ripristina fluidamente la schermata iniziale
          const animDuration = 200;
          const easing = `transform ${animDuration}ms cubic-bezier(0.25, 1, 0.5, 1)`;

          if (activeFromEl) {
            activeFromEl.style.transition = easing;
            activeFromEl.style.transform = 'translate3d(0, 0, 0)';
          }
          if (activeToEl) {
            activeToEl.style.transition = easing;
            const returnX = (dx > 0) ? -viewportWidth : viewportWidth;
            activeToEl.style.transform = `translate3d(${returnX}px, 0, 0)`;
          }

          const fromElToRestore = activeFromEl;
          const toElToHide = activeToEl;

          setTimeout(() => {
            if (toElToHide) {
              toElToHide.classList.add('hidden');
              toElToHide.classList.remove('flex');
              toElToHide.style.transform = '';
              toElToHide.style.transition = '';
              toElToHide.style.zIndex = '';
              toElToHide.style.willChange = '';
            }
            if (fromElToRestore) {
              fromElToRestore.style.transform = '';
              fromElToRestore.style.transition = '';
              fromElToRestore.style.zIndex = '';
              fromElToRestore.style.willChange = '';
            }
            activeFromEl = null;
            activeToEl = null;
            targetScreen = null;
            isTransitioningScreens = false;
          }, animDuration + 10);
        }
      }

      viewport.addEventListener('touchend', handleDragEnd, { passive: true });
      viewport.addEventListener('touchcancel', handleDragEnd, { passive: true });
    }
    window.initMobileSwipeGestures = initMobileSwipeGestures;

    // Listener resize e orientamento — ricalcola layout
    let resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(applyLayout, 80);
    });
    window.addEventListener('orientationchange', () => {
      setTimeout(applyLayout, 200);
    });

