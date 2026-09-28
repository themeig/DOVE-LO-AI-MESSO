// =========================================================================
// MODULO 4: Google Drive Cloud Sync & Google Calendar Auto-Sync
// =========================================================================
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

      const googleConnBox = document.getElementById('googleConnectedSettings');
      const googleDiscBox = document.getElementById('googleDisconnectedBanner');
      const sysEmailEl = document.getElementById('systemGoogleConnectedEmail');
      const toggleDrive = document.getElementById('toggleDriveSync');

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
          window.currentDriveConnected = true;
          updateHeaderCloudIndicators(true, null);
          if (typeof updateSystemMenuStatusBadges === 'function') updateSystemMenuStatusBadges();
          if (connectedEl) connectedEl.classList.remove('hidden');
          if (disconnectedEl) disconnectedEl.classList.add('hidden');
          if (emailEl) emailEl.textContent = data.user_email || 'Account Google';

          if (googleConnBox) googleConnBox.classList.remove('hidden');
          if (googleDiscBox) googleDiscBox.classList.add('hidden');
          if (sysEmailEl) sysEmailEl.textContent = data.user_email || 'Account Google';

          const targetMode = data.storage_mode || 'dual';
          const radio = document.querySelector(`input[name="driveStorageMode"][value="${targetMode}"]`);
          if (radio) radio.checked = true;

          if (toggleDrive) {
            toggleDrive.checked = (data.drive_enabled !== false && targetMode !== 'local_only');
          }

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
          window.currentDriveConnected = false;
          updateHeaderCloudIndicators(false, null);
          if (typeof updateSystemMenuStatusBadges === 'function') updateSystemMenuStatusBadges();
          if (connectedEl) connectedEl.classList.add('hidden');
          if (disconnectedEl) disconnectedEl.classList.remove('hidden');
          if (googleConnBox) googleConnBox.classList.add('hidden');
          if (googleDiscBox) googleDiscBox.classList.remove('hidden');
          if (toggleDrive) toggleDrive.checked = false;

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
        window.currentDriveConnected = false;
        updateHeaderCloudIndicators(false, null);
        if (typeof updateSystemMenuStatusBadges === 'function') updateSystemMenuStatusBadges();
        if (loadingEl) loadingEl.classList.add('hidden');
        if (disconnectedEl) disconnectedEl.classList.remove('hidden');
        if (googleConnBox) googleConnBox.classList.add('hidden');
        if (googleDiscBox) googleDiscBox.classList.remove('hidden');
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
        showToast("⚠️ Impossibile avviare il collegamento con Google", "error");
      }
    }

    async function disconnectGoogleDrive() {
      await confirmDisconnectGoogle();
    }

    async function confirmDisconnectGoogle() {
      if (!confirm("Sei sicuro di voler scollegare il tuo account Google? Google Drive e Google Calendar verranno disconnessi.")) {
        return;
      }
      try {
        const res = await fetch('/api/drive/disconnect', {
          method: 'POST',
          headers: authHeaders()
        });
        if (!res.ok) throw new Error("Errore durante la disconnessione");
        window.currentDriveConnected = false;
        window.currentCalendarConnected = false;
        await loadGoogleDriveStatus();
        if (typeof loadCalendarStatus === 'function') await loadCalendarStatus();
        updateHeaderCloudIndicators(false, false);
        if (typeof updateSystemMenuStatusBadges === 'function') updateSystemMenuStatusBadges();
        showToast("Account Google scollegato con successo", "info");
      } catch (err) {
        console.error("Errore confirmDisconnectGoogle:", err);
        showToast("⚠️ Errore durante lo scollegamento dell'account Google", "error");
      }
    }
    window.confirmDisconnectGoogle = confirmDisconnectGoogle;

    async function toggleDriveSyncEnabled(enabled) {
      try {
        const res = await fetch('/api/drive/settings', {
          method: 'PATCH',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ drive_enabled: enabled })
        });
        if (!res.ok) throw new Error("Errore aggiornamento impostazioni Google Drive");
        const data = await res.json();
        if (googleDriveStatusCache) {
          googleDriveStatusCache.drive_enabled = data.drive_enabled;
          googleDriveStatusCache.storage_mode = data.storage_mode;
        }
        await loadGoogleDriveStatus();
        showToast(enabled ? "Backup Google Drive attivato" : "Backup Google Drive disattivato", "info");
      } catch (err) {
        console.error("Errore toggleDriveSyncEnabled:", err);
        showToast("⚠️ Impossibile aggiornare impostazione Drive", "error");
        await loadGoogleDriveStatus();
      }
    }
    window.toggleDriveSyncEnabled = toggleDriveSyncEnabled;

    async function toggleCalendarSyncEnabled(enabled) {
      try {
        const res = await fetch('/api/calendar/settings', {
          method: 'PATCH',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ calendar_enabled: enabled })
        });
        if (!res.ok) throw new Error("Errore aggiornamento impostazioni Google Calendar");
        await loadCalendarStatus();
        showToast(enabled ? "Sincronizzazione Google Calendar attivata" : "Sincronizzazione Google Calendar disattivata", "info");
      } catch (err) {
        console.error("Errore toggleCalendarSyncEnabled:", err);
        showToast("⚠️ Impossibile aggiornare impostazione Calendar", "error");
        await loadCalendarStatus();
      }
    }
    window.toggleCalendarSyncEnabled = toggleCalendarSyncEnabled;

    async function updateCalendarTarget(target) {
      try {
        const res = await fetch('/api/calendar/settings', {
          method: 'PATCH',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ calendar_target: target })
        });
        if (!res.ok) throw new Error("Errore aggiornamento destinazione calendario");
        const label = (target === 'primary') ? 'Calendario Principale' : 'Calendario Dedicato (Dove Lo AI Messo)';
        showToast(`Destinazione scadenze: ${label}`, "success");
        await loadCalendarStatus();
      } catch (err) {
        console.error("Errore updateCalendarTarget:", err);
        showToast("⚠️ Impossibile aggiornare la destinazione del calendario", "error");
        await loadCalendarStatus();
      }
    }
    window.updateCalendarTarget = updateCalendarTarget;

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
        if (typeof loadCalendarStatus === 'function') loadCalendarStatus();
        showToast(`🟢 Account Google collegato con successo!`, 'success');
      }
    });

