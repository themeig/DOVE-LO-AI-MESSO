// =========================================================================
// MODULO 5: Chat Engine, Vocale Whisper, Markdown, Schede Widget & Upload
// =========================================================================
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
        ensureTodayDateDivider();
        appendAssistantBubble("⏹️ *Generazione/elaborazione interrotta dall'utente.*", null, null, null, null, null, null, getTime());
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
          <div class="flex items-center gap-2.5">
            <div class="typing-dots shrink-0">
              <span></span><span></span><span></span>
            </div>
            ${statusText ? `<span id="typingStatusText" class="text-xs font-medium text-slate-700 select-none">${escapeHtml(statusText)}</span>` : `<span id="typingStatusText" class="text-xs font-medium text-slate-700 select-none hidden"></span>`}
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

    function appendUserBubble(text, quoted = null, timeStr = null) {
      const userBubble = document.createElement('div');
      userBubble.className = 'flex flex-col items-end';
      const isOli = getActiveTheme() === 'olivetti';
      const actualTime = (timeStr && typeof timeStr === 'string' && timeStr.trim()) ? timeStr.trim() : getTime();

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
        <span class="text-[9px] font-mono-code text-[#7A7568] mb-1 user-bubble-stamp" title="Inviato alle ${actualTime}">UTENTE • ${actualTime}</span>
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
            <span class="text-[10px] text-gray-500 font-mono-code" title="Inviato alle ${actualTime}">${actualTime}</span>
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

    function appendUserAudioBubble(audioUrl, duration = 0, quoted = null, transcription = null, timeStr = null) {
      const userBubble = document.createElement('div');
      userBubble.className = 'flex flex-col items-end user-voice-bubble-wrapper';
      const isOli = getActiveTheme() === 'olivetti';
      const actualTime = (timeStr && typeof timeStr === 'string' && timeStr.trim()) ? timeStr.trim() : getTime();

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
        <span class="text-[9px] font-mono-code text-[#7A7568] mb-1 user-bubble-stamp" title="Inviato alle ${actualTime}">UTENTE • ${actualTime}</span>
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
            <span class="text-[10px] text-gray-500 font-mono-code" title="Inviato alle ${actualTime}">${actualTime}</span>
            <i class="fa-solid fa-check-double text-[11px] text-[#53bdeb] wa-ticks-icon"></i>
          </div>
        </div>
      `;
      chatFeed.appendChild(userBubble);
      scrollBottom();
      return userBubble;
    }

    function appendUserFileBubble(fileName, fileSize, previewUrl = null, isImage = false, isPdf = false, downloadUrl = null, docId = null, timeStr = null) {
      const userBubble = document.createElement('div');
      userBubble.className = 'flex flex-col items-end';
      const isOli = getActiveTheme() === 'olivetti';
      const actualTime = (timeStr && typeof timeStr === 'string' && timeStr.trim()) ? timeStr.trim() : getTime();

      const dlUrl = downloadUrl || previewUrl || '#';
      const lowerName = (fileName || '').toLowerCase();
      const isOffice = lowerName.endsWith('.docx') || lowerName.endsWith('.doc') || lowerName.endsWith('.xlsx') || lowerName.endsWith('.xls') || lowerName.endsWith('.csv') || lowerName.endsWith('.tsv');
      const isZip = lowerName.endsWith('.zip') || lowerName.endsWith('.rar') || lowerName.endsWith('.7z') || lowerName.endsWith('.tar') || lowerName.endsWith('.gz');

      let previewContent = '';
      if (isImage && previewUrl) {
        previewContent = `
          <div class="cursor-pointer group mb-1" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', 'image', '${dlUrl}', ${docId || 'null'})">
            <div class="relative overflow-hidden ${isOli ? 'rounded-xs' : 'rounded-lg'} bg-black/5 max-h-52 flex items-center justify-center border border-[#E3DDD1]">
              <img src="${previewUrl}" class="w-full h-auto object-cover max-h-52 ${isOli ? 'rounded-xs' : 'rounded-lg'} group-hover:scale-[1.02] transition duration-200" alt="Anteprima">
              <div class="absolute inset-0 bg-black/25 opacity-0 group-hover:opacity-100 transition flex items-center justify-center text-white gap-1.5 text-xs font-semibold backdrop-blur-2xs">
                <i class="fa-solid fa-magnifying-glass-plus text-lg drop-shadow"></i> Ingrandisci Foto
              </div>
              <div class="absolute top-1.5 left-1.5 pointer-events-none">
                <span class="stamp-oli stamp-solid-sage text-[8px]"><i class="fa-solid fa-camera text-[8px]"></i> FOTO / SCANSIONE</span>
              </div>
            </div>
            <div class="flex items-center justify-between px-1 pt-1.5 gap-2 border-t border-[#E3DDD1] mt-1.5">
              <div class="flex items-center gap-1.5 min-w-0">
                <span class="truncate max-w-[140px] text-[11px] font-bold font-mono-code text-[#222220]">${escapeHtml(fileName)}</span>
                <span class="text-[10px] text-gray-500 font-mono-code shrink-0">${formatFileSize(fileSize)}</span>
              </div>
              <div class="flex items-center gap-1.5 shrink-0" onclick="event.stopPropagation()">
                <button type="button" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', 'image', '${dlUrl}', ${docId || 'null'})" class="bg-[#3C5A48] hover:bg-[#2F4738] text-white text-[10px] font-bold px-2.5 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space cursor-pointer shadow-xs" title="Visualizza anteprima">
                  <i class="fa-regular fa-eye text-xs"></i> <span>Vedi</span>
                </button>
                ${dlUrl && dlUrl !== '#' ? `
                <a href="${dlUrl}" download="${escapeHtml(fileName)}" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space shadow-xs" title="Scarica file">
                  <i class="fa-solid fa-download text-xs text-[#3C5A48]"></i>
                </a>` : ''}
              </div>
            </div>
          </div>
        `;
      } else if (isPdf && previewUrl) {
        const boxClass = isOli 
          ? 'bg-[#FAF8F2] p-2.5 rounded-xs flex items-center justify-between gap-3 mb-1 border border-[#E3DDD1]' 
          : 'bg-[#d4f2c5] p-2.5 rounded-lg flex items-center justify-between gap-3 mb-1 border border-emerald-200/70';
        const iconBoxClass = isOli 
          ? 'w-8 h-8 rounded-xs bg-[#FAECE8] text-[#C84B31] flex items-center justify-center shrink-0 shadow-xs border border-[#E3DDD1]' 
          : 'w-9 h-9 rounded-lg bg-red-100 text-red-600 flex items-center justify-center shrink-0 shadow-2xs';

        previewContent = `
          <div class="${boxClass} cursor-pointer group/pdf" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', 'application/pdf', '${dlUrl}', ${docId || 'null'})">
            <div class="flex items-center gap-2.5 min-w-0">
              <div class="${iconBoxClass}">
                <i class="fa-solid fa-file-pdf text-lg"></i>
              </div>
              <div class="text-xs min-w-0">
                <p class="font-bold text-[#222220] truncate max-w-[140px] ${isOli ? 'font-space' : ''}">${escapeHtml(fileName)}</p>
                <div class="flex items-center gap-1 mt-0.5">
                  <span class="stamp-oli stamp-terracotta text-[8px]">PDF</span>
                  <span class="text-[10px] text-[#7A7568] font-mono-code">${formatFileSize(fileSize)}</span>
                </div>
              </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0" onclick="event.stopPropagation()">
              <button type="button" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', 'application/pdf', '${dlUrl}', ${docId || 'null'})" class="bg-[#3C5A48] hover:bg-[#2F4738] text-white text-[10px] font-bold px-2.5 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space cursor-pointer shadow-xs" title="Visualizza documento PDF">
                <i class="fa-regular fa-eye text-xs"></i> <span>Vedi</span>
              </button>
              ${dlUrl && dlUrl !== '#' ? `
              <a href="${dlUrl}" download="${escapeHtml(fileName)}" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space shadow-xs" title="Scarica file">
                <i class="fa-solid fa-download text-xs text-[#3C5A48]"></i>
              </a>` : ''}
            </div>
          </div>
        `;
      } else if (previewUrl) {
        let iconHtml = '<i class="fa-solid fa-file-lines text-lg text-slate-600"></i>';
        let bgStyle = isOli ? 'bg-[#FAF8F2] text-[#3C5A48]' : 'bg-slate-100 text-slate-600';
        let badgeText = 'FILE';

        if (lowerName.endsWith('.docx') || lowerName.endsWith('.doc')) {
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

        previewContent = `
          <div class="${boxClass} cursor-pointer group/doc" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', '${badgeText.toLowerCase()}', '${dlUrl}', ${docId || 'null'})">
            <div class="flex items-center gap-2.5 min-w-0">
              <div class="${iconBoxClass}">
                ${iconHtml}
              </div>
              <div class="text-xs min-w-0">
                <p class="font-bold text-[#222220] truncate max-w-[140px] ${isOli ? 'font-space' : ''}">${escapeHtml(fileName)}</p>
                <p class="text-[10px] text-[#7A7568] font-mono-code">${formatFileSize(fileSize)} • ${badgeText}</p>
              </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0" onclick="event.stopPropagation()">
              <button type="button" onclick="openMediaModal('${previewUrl}', '${escapeHtml(fileName).replace(/'/g, "\\'")}', '${badgeText.toLowerCase()}', '${dlUrl}', ${docId || 'null'})" class="bg-[#3C5A48] hover:bg-[#2F4738] text-white text-[10px] font-bold px-2.5 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space cursor-pointer shadow-xs" title="Visualizza documento">
                <i class="fa-regular fa-eye text-xs"></i> <span>Vedi</span>
              </button>
              ${dlUrl && dlUrl !== '#' ? `
              <a href="${dlUrl}" download="${escapeHtml(fileName)}" class="bg-white hover:bg-[#FAF8F2] text-[#3C5A48] border border-[#3C5A48] text-[10px] font-bold px-2 py-1 rounded-xs transition active:scale-95 flex items-center gap-1 font-space shadow-xs" title="Scarica file">
                <i class="fa-solid fa-download text-xs text-[#3C5A48]"></i>
              </a>` : ''}
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
        <span class="text-[9px] font-mono-code text-[#7A7568] mb-1 user-bubble-stamp" title="Inviato alle ${actualTime}">UTENTE • ${actualTime}</span>
        <div class="wa-bubble-out p-2 max-w-[85%] text-sm text-gray-800 select-text group/msg">
          ${previewContent}
          <div class="flex justify-end items-center gap-1.5 mt-0.5 select-none">
            <button type="button" onclick="replyToMessage(this, 'user', 'File: ${escapeHtml(fileName).replace(/'/g, "\\'")}')" class="copy-msg-btn hover:text-[#075E54] text-slate-500 text-[11px] p-0.5 rounded transition cursor-pointer" title="Rispondi / Quota">
              <i class="fa-solid fa-reply"></i>
            </button>
            <button type="button" onclick="copyTextToClipboard('${escapeHtml(fileName).replace(/'/g, "\\'")}', this)" class="copy-msg-btn hover:text-slate-900 text-slate-500 text-[11px] p-0.5 rounded transition cursor-pointer" title="Copia nome file">
              <i class="fa-regular fa-copy"></i>
            </button>
            <span class="text-[10px] text-gray-500 font-mono-code" title="Inviato alle ${actualTime}">${actualTime}</span>
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

    function appendAssistantBubble(text, documents = null, confirmation = null, itemPhoto = null, storeItem = null, proposal = null, routedModel = null, timeStr = null) {
      const aiBubble = document.createElement('div');
      aiBubble.className = 'flex flex-col items-start max-w-[90%]';
      const actualTime = (timeStr && typeof timeStr === 'string' && timeStr.trim()) ? timeStr.trim() : getTime();
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
                      ${docItem.due_date ? `
                        <a href="${getGoogleCalendarDirectLink(docItem)}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 stamp-oli text-[9px] hover:bg-[#2B4C7E] hover:text-white transition" title="Aggiungi scadenza su Google Calendar">
                          <i class="fa-brands fa-google text-[10px]"></i> <span>Cal ↗</span>
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
        <span class="text-[9px] font-mono-code text-[#3C5A48] font-bold mb-1 ai-bubble-stamp" title="Inviato alle ${actualTime}">ASSISTENTE • ${actualTime}</span>
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
            <span class="text-[10px] text-gray-400 font-mono-code" title="Inviato alle ${actualTime}">${actualTime}</span>
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

      if (!window.currentCloudUser && !localStorage.getItem('supabase_auth_token') && !sessionStorage.getItem('supabase_auth_token')) {
        if (typeof showToast === 'function') {
          showToast("⚠️ Accedi al tuo account per inviare messaggi o consultare il registro.", "warning", 3000);
        }
        if (typeof openAccountModal === 'function') openAccountModal('profile', true);
        return;
      }

      const targetThreadId = currentThreadId; // Memorizza la chat di destinazione
      const quotedToSend = currentQuotedMessage;
      cancelQuoteReply(); // Chiudi subito la barra preview della citazione

      ensureTodayDateDivider();
      appendUserBubble(text, quotedToSend, getTime());
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
          th.last_message_iso = (data && data.created_at) ? data.created_at : new Date().toISOString();
          th.message_count = (th.message_count || 0) + 2;
          renderThreadsList();
        }

        // Se l'utente è ancora su questa chat, inietta subito la bolla di risposta
        if (currentThreadId === targetThreadId) {
          ensureTodayDateDivider();
          const routedModel = data.routed_model || (data.data && data.data.routed_model) || null;
          const asstTime = (data && data.created_at) ? formatMessageTime(data.created_at) : getTime();
          appendAssistantBubble(data.reply, data.documents, data.confirmation, itemPhoto, storeItem, proposal, routedModel, asstTime);
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
          ensureTodayDateDivider();
          appendAssistantBubble("⚠️ Errore di connessione: impossibile contattare il server.", null, null, null, null, null, null, getTime());
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
      multiPhotoTargetThreadId = currentThreadId || 'general';
      const isMobileNative = window.AndroidNativeVoice || /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
      const cameraInput = document.getElementById('cameraMultiPhotoInput');
      if (isMobileNative && cameraInput) {
        cameraInput.value = '';
        cameraInput.click();
      } else if (cameraInput && !navigator.mediaDevices?.getUserMedia) {
        cameraInput.value = '';
        cameraInput.click();
      } else if (isMobileNative) {
        const itemPhotoInput = document.getElementById('itemPhotoInput');
        if (itemPhotoInput) {
          itemPhotoInput.value = '';
          itemPhotoInput.click();
        } else if (realFileInput) {
          realFileInput.click();
        }
      } else {
        openWebcamCaptureModal();
      }
    }

    function triggerScanner() {
      if (attachmentMenu) attachmentMenu.classList.add('hidden');
      const targetThread = currentThreadId || 'general';
      if (window.AndroidDocumentScanner && typeof window.AndroidDocumentScanner.launchScanner === 'function') {
        window.AndroidDocumentScanner.launchScanner(targetThread);
      } else if (window.MobileScanner && typeof window.MobileScanner.openScanner === 'function') {
        window.MobileScanner.openScanner(targetThread);
      } else {
        triggerCameraInput();
      }
    }
    window.triggerScanner = triggerScanner;
    window.triggerCameraInput = triggerCameraInput;
    window.triggerFileInput = triggerFileInput;
    window.triggerFolderInput = triggerFolderInput;

    function formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    async function processFilesUpload(fileList) {
      if (!fileList || fileList.length === 0) return;

      if (!window.currentCloudUser && !localStorage.getItem('supabase_auth_token') && !sessionStorage.getItem('supabase_auth_token')) {
        if (typeof showToast === 'function') {
          showToast("⚠️ Accedi al tuo account per caricare documenti nel Caveau.", "warning", 3000);
        }
        if (typeof openAccountModal === 'function') openAccountModal('profile', true);
        return;
      }

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
        const fileNameLower = (file.name || '').toLowerCase();
        const isImage = file.type.startsWith('image/') || /\.(jpe?g|png|webp|gif|bmp|svg)$/i.test(fileNameLower);
        const isPdf = file.type === 'application/pdf' || fileNameLower.endsWith('.pdf');
        const blobUrl = URL.createObjectURL(file);

        if (currentThreadId === targetThreadId) {
          ensureTodayDateDivider();
          appendUserFileBubble(file.name, file.size, blobUrl, isImage, isPdf, blobUrl, null, getTime());
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
            th.last_message_iso = new Date().toISOString();
            th.message_count = (th.message_count || 0) + 2;
            renderThreadsList();
          }

          if (currentThreadId === targetThreadId) {
            ensureTodayDateDivider();
            appendAssistantBubble(data.chat_reply || "📄 Documento salvato e catalogato!", [docItem], null, null, null, null, data.routed_model || 'google/gemini-2.5-flash-lite', getTime());
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
            ensureTodayDateDivider();
            appendAssistantBubble("⚠️ Errore durante il caricamento del documento.", null, null, null, null, null, null, getTime());
          } else {
            const th = threadsCache.find(t => t.id === targetThreadId);
            showToast(`⚠️ Errore caricamento in "${th?.name || targetThreadId}"`, 'error', 4000);
          }
        }
      } else {
        // Upload Multiplo o Cartella con avanzamento a blocchi paralleli reali
        const totalCount = validFiles.length;
        const totalSize = validFiles.reduce((acc, f) => acc + (f.size || 0), 0);
        const userSummaryText = `📁 Caricamento di ${totalCount} file... (${formatBytes(totalSize)})`;
        if (currentThreadId === targetThreadId) {
          ensureTodayDateDivider();
          appendUserBubble(userSummaryText, null, getTime());
        }

        // Elaborazione CONCORRENTE REALE (fino a 8 worker simultanei)
        // con avanzamento visibile in tempo reale DOCUMENTO PER DOCUMENTO!
        const CONCURRENCY = Math.min(8, totalCount);

        setGenerationActive(true, `Avvio elaborazione parallela di ${totalCount} file...`, 0, targetThreadId);
        const taskController = activeThreadTasks[targetThreadId]?.abortController;

        try {
          const allUploadedDocs = [];
          const allDocumentIds = [];
          const errors = [];
          let completedCount = 0;
          let fileIndex = 0;

          const uploadWorker = async () => {
            while (fileIndex < totalCount) {
              if (taskController?.signal?.aborted) break;
              const currentIdx = fileIndex++;
              const file = validFiles[currentIdx];

              const formData = new FormData();
              formData.append('file', file);
              formData.append('thread_id', targetThreadId);
              formData.append('save_chat_message', 'false');

              try {
                const res = await fetch('/api/documents/upload', {
                  method: 'POST',
                  headers: authHeaders(),
                  body: formData,
                  signal: taskController ? taskController.signal : undefined
                });

                if (res.ok) {
                  const data = await res.json();
                  const docItem = {
                    id: data.document_id || data.id,
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
                  };
                  allUploadedDocs.push(docItem);
                  if (docItem.id) allDocumentIds.push(docItem.id);
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
                updateTypingIndicator(
                  `⚡ [${completedCount}/${totalCount}] Analizzato: ${file.name}`,
                  realPct,
                  targetThreadId
                );
              }
            }
          };

          // Avvia gli 8 worker paralleli simultaneamente
          const workers = [];
          for (let w = 0; w < CONCURRENCY; w++) {
            workers.push(uploadWorker());
          }
          await Promise.all(workers);

          // Registra l'unico messaggio finale aggregato nella chat sul database
          let finalReplyText = '';
          if (allDocumentIds.length > 0 && !taskController?.signal?.aborted) {
            try {
              const recRes = await fetch('/api/documents/batch-record-chat', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({
                  document_ids: allDocumentIds,
                  thread_id: targetThreadId,
                  total_files_count: totalCount
                })
              });
              if (recRes.ok) {
                const recData = await recRes.json();
                finalReplyText = recData.chat_reply || '';
              }
            } catch (e) {
              console.warn('Errore salvataggio chat aggregata sul server:', e);
            }
          }

          if (taskController?.signal?.aborted) {
            setGenerationActive(false, '', null, targetThreadId);
            return;
          }

          updateTypingIndicator('Completato!', 100, targetThreadId);
          await new Promise(r => setTimeout(r, 300));
          setGenerationActive(false, '', null, targetThreadId);

          const th = threadsCache.find(t => t.id === targetThreadId);
          if (th) {
            th.last_message = `${allUploadedDocs.length} file elaborati`;
            th.last_message_time = getTime();
            th.last_message_iso = new Date().toISOString();
            th.message_count = (th.message_count || 0) + allUploadedDocs.length * 2;
            renderThreadsList();
          }

          let replyText = finalReplyText || `📁 **${allUploadedDocs.length} di ${totalCount}** file archiviati e catalogati nel caveau con successo!`;
          if (errors.length > 0) {
            replyText += `\n⚠️ *Attenzione: ${errors.length} file non sono stati elaborati.*`;
          }

          if (currentThreadId === targetThreadId) {
            ensureTodayDateDivider();
            if (allUploadedDocs.length > 0) {
              appendAssistantBubble(replyText, allUploadedDocs, null, null, null, null, 'google/gemini-2.5-flash-lite', getTime());
            } else {
              appendAssistantBubble('⚠️ Nessun file è stato elaborato con successo. Verifica i formati o la connessione.', null, null, null, null, null, null, getTime());
            }
            scrollBottom();
          } else {
            const targetName = th ? th.name : 'altra chat';
            showToast(`📁 Elaborazione completata in "${targetName}": ${allUploadedDocs.length}/${totalCount} file`, 'success', 5000);
          }
          loadDashboard(currentFilter);
        } catch (err) {
          if (err.name === 'AbortError' || err.message?.includes('aborted')) {
            setGenerationActive(false, '', null, targetThreadId);
            return;
          }
          setGenerationActive(false, '', null, targetThreadId);
          console.error('Errore durante il caricamento batch:', err);
          if (currentThreadId === targetThreadId) {
            ensureTodayDateDivider();
            appendAssistantBubble('⚠️ Errore imprevisto durante il caricamento multiplo dei documenti.', null, null, null, null, null, null, getTime());
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

    // =========================================================================
    // NATIVE DOCUMENT SCANNER HANDLERS (Google Drive Document Scanner)
    // =========================================================================
    let _multiScanPendingCount = 0;
    let _multiScanPendingPdf = false;
    let _multiScanTargetThreadId = 'general';

    function readScannedPageFile(pageIndex) {
      if (!window.AndroidDocumentScanner) return null;
      const totalChunks = window.AndroidDocumentScanner.getPageTotalChunks ? window.AndroidDocumentScanner.getPageTotalChunks(pageIndex) : (pageIndex === 0 ? window.AndroidDocumentScanner.getTotalChunks() : 0);
      const filename = (window.AndroidDocumentScanner.getPageFilename && window.AndroidDocumentScanner.getPageFilename(pageIndex)) || `scansione_doc${pageIndex + 1}_${Date.now()}.jpg`;
      const mimeType = (window.AndroidDocumentScanner.getPageMimeType && window.AndroidDocumentScanner.getPageMimeType(pageIndex)) || 'image/jpeg';
      const byteArrays = [];
      for (let i = 0; i < totalChunks; i++) {
        const chunkB64 = window.AndroidDocumentScanner.getPageChunk ? window.AndroidDocumentScanner.getPageChunk(pageIndex, i) : (pageIndex === 0 ? window.AndroidDocumentScanner.getChunk(i) : "");
        if (!chunkB64) continue;
        const byteChars = atob(chunkB64);
        const chunkBytes = new Uint8Array(byteChars.length);
        for (let j = 0; j < byteChars.length; j++) {
          chunkBytes[j] = byteChars.charCodeAt(j);
        }
        byteArrays.push(chunkBytes);
      }
      if (byteArrays.length === 0) return null;
      const blob = new Blob(byteArrays, { type: mimeType });
      return new File([blob], filename, { type: mimeType });
    }

    function readScannedPdfFile() {
      if (!window.AndroidDocumentScanner) return null;
      const totalChunks = window.AndroidDocumentScanner.getPdfTotalChunks ? window.AndroidDocumentScanner.getPdfTotalChunks() : window.AndroidDocumentScanner.getTotalChunks();
      const filename = (window.AndroidDocumentScanner.getPdfFilename && window.AndroidDocumentScanner.getPdfFilename()) || `scansione_completa_${Date.now()}.pdf`;
      const byteArrays = [];
      for (let i = 0; i < totalChunks; i++) {
        const chunkB64 = window.AndroidDocumentScanner.getPdfChunk ? window.AndroidDocumentScanner.getPdfChunk(i) : window.AndroidDocumentScanner.getChunk(i);
        if (!chunkB64) continue;
        const byteChars = atob(chunkB64);
        const chunkBytes = new Uint8Array(byteChars.length);
        for (let j = 0; j < byteChars.length; j++) {
          chunkBytes[j] = byteChars.charCodeAt(j);
        }
        byteArrays.push(chunkBytes);
      }
      if (byteArrays.length === 0) return null;
      const blob = new Blob(byteArrays, { type: 'application/pdf' });
      return new File([blob], filename, { type: 'application/pdf' });
    }

    window.onNativeScanResult = async function(pageCount, hasPdf, threadId) {
      try {
        if (!window.AndroidDocumentScanner) return;
        _multiScanTargetThreadId = threadId || currentThreadId || 'general';
        if (threadId && typeof switchThread === 'function' && threadId !== currentThreadId) {
          switchThread(threadId);
        }

        // Se è stata scansionata solo 1 singola pagina: carica direttamente in modo trasparente
        if (pageCount <= 1) {
          const file = readScannedPageFile(0) || (hasPdf ? readScannedPdfFile() : null);
          if (file) {
            if (window.AndroidDocumentScanner.clearLastScan) window.AndroidDocumentScanner.clearLastScan();
            showToast("📄 Acquisizione scansione Google completata!", "success");
            await processFilesUpload([file]);
          }
          return;
        }

        // Se sono state scansionate 2 o più pagine/documenti: apri la modale di scelta Olivetti
        openMultiScanChoiceModal(pageCount, hasPdf, _multiScanTargetThreadId);
      } catch (err) {
        console.error("Errore onNativeScanResult:", err);
        showToast("⚠️ Impossibile elaborare i documenti scansionati.", "error");
      }
    };

    function openMultiScanChoiceModal(pageCount, hasPdf, threadId) {
      _multiScanPendingCount = pageCount;
      _multiScanPendingPdf = hasPdf;
      _multiScanTargetThreadId = threadId || currentThreadId || 'general';

      const modal = document.getElementById('multiScanChoiceModal');
      const titleEl = document.getElementById('multiScanModalTitle');
      const descEl = document.getElementById('multiScanModalDesc');
      const badgeEl = document.getElementById('multiScanSeparateBadge');
      const pdfBtn = document.getElementById('btnMultiScanPdf');

      if (titleEl) titleEl.textContent = `Acquisiti ${pageCount} Documenti`;
      if (descEl) descEl.textContent = `Lo scanner di Google ha acquisito con successo ${pageCount} pagine. Come desideri archiviarle nel caveau per l'analisi dell'assistente?`;
      if (badgeEl) badgeEl.textContent = `${pageCount} FILE`;
      if (pdfBtn) {
        if (hasPdf) pdfBtn.classList.remove('hidden');
        else pdfBtn.classList.add('hidden');
      }

      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
      }
    }

    function closeMultiScanChoiceModal() {
      const modal = document.getElementById('multiScanChoiceModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function cancelMultiScanChoice() {
      closeMultiScanChoiceModal();
      if (window.AndroidDocumentScanner && window.AndroidDocumentScanner.clearLastScan) {
        window.AndroidDocumentScanner.clearLastScan();
      }
      showToast("Scansione annullata.", "info");
    }

    async function submitMultiScanChoice(mode) {
      closeMultiScanChoiceModal();
      try {
        if (!window.AndroidDocumentScanner) return;

        if (mode === 'pdf' && _multiScanPendingPdf) {
          showToast(`📄 Creazione e analisi documento multipagina in corso...`, 'info', 3000);
          const pdfFile = readScannedPdfFile();
          if (window.AndroidDocumentScanner.clearLastScan) window.AndroidDocumentScanner.clearLastScan();
          if (pdfFile) {
            await processFilesUpload([pdfFile]);
          }
        } else {
          // Modalità 'separate': carica ogni documento come file separato per massima comprensione e categorizzazione
          showToast(`📁 Acquisizione di ${_multiScanPendingCount} documenti separati...`, 'info', 3000);
          const filesArray = [];
          for (let i = 0; i < _multiScanPendingCount; i++) {
            const f = readScannedPageFile(i);
            if (f) filesArray.push(f);
          }
          if (window.AndroidDocumentScanner.clearLastScan) window.AndroidDocumentScanner.clearLastScan();
          if (filesArray.length > 0) {
            await processFilesUpload(filesArray);
          }
        }
      } catch (err) {
        console.error("Errore submitMultiScanChoice:", err);
        showToast("⚠️ Errore caricamento scansioni.", "error");
      }
    }

    window.openMultiScanChoiceModal = openMultiScanChoiceModal;
    window.closeMultiScanChoiceModal = closeMultiScanChoiceModal;
    window.cancelMultiScanChoice = cancelMultiScanChoice;
    window.submitMultiScanChoice = submitMultiScanChoice;

    window.onNativeScanReady = async function(filename, mimeType, fileSize, threadId) {
      if (window.AndroidDocumentScanner && typeof window.AndroidDocumentScanner.getPageCount === 'function') {
        const count = window.AndroidDocumentScanner.getPageCount();
        const hasPdf = window.AndroidDocumentScanner.hasPdf ? window.AndroidDocumentScanner.hasPdf() : false;
        await window.onNativeScanResult(count, hasPdf, threadId);
        return;
      }
      try {
        if (!window.AndroidDocumentScanner) return;
        const totalChunks = window.AndroidDocumentScanner.getTotalChunks ? window.AndroidDocumentScanner.getTotalChunks() : 0;
        const byteArrays = [];
        for (let i = 0; i < totalChunks; i++) {
          const chunkB64 = window.AndroidDocumentScanner.getChunk(i);
          if (!chunkB64) continue;
          const byteChars = atob(chunkB64);
          const chunkBytes = new Uint8Array(byteChars.length);
          for (let j = 0; j < byteChars.length; j++) {
            chunkBytes[j] = byteChars.charCodeAt(j);
          }
          byteArrays.push(chunkBytes);
        }
        if (window.AndroidDocumentScanner.clearLastScan) {
          window.AndroidDocumentScanner.clearLastScan();
        }

        const cleanMime = mimeType || (filename.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'image/jpeg');
        const blob = new Blob(byteArrays, { type: cleanMime });
        const cleanName = filename || (`scansione_${Date.now()}.${cleanMime === 'application/pdf' ? 'pdf' : 'jpg'}`);
        const file = new File([blob], cleanName, { type: cleanMime });

        if (threadId && typeof switchThread === 'function' && threadId !== currentThreadId) {
          switchThread(threadId);
        }

        showToast("📄 Acquisizione scansione Google completata!", "success");
        await processFilesUpload([file]);
      } catch (err) {
        console.error("Errore onNativeScanReady:", err);
        showToast("⚠️ Impossibile caricare il documento scansionato.", "error");
      }
    };

    window.onNativeScanError = function(errMsg) {
      console.warn("Native scanner error:", errMsg);
      showToast("⚠️ " + (errMsg || "Errore durante la scansione del documento."), "error");
    };

    window.onNativeScanCancelled = function() {
      // Scansione annullata dall'utente
    };

    // =========================================================================
    // GESTIONE MULTI-FOTO CONTINUA DA CELLULARE SENZA BORDI (Olivetti Style)
    // =========================================================================
    let multiPhotosSession = [];
    let multiPhotoTargetThreadId = null;

    function openMultiPhotoModal() {
      const modal = document.getElementById('multiPhotoModal');
      if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
      }
    }

    function closeMultiPhotoModal() {
      const modal = document.getElementById('multiPhotoModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function cancelMultiPhotoSession() {
      multiPhotosSession.forEach(p => {
        if (p.previewUrl) URL.revokeObjectURL(p.previewUrl);
      });
      multiPhotosSession = [];
      closeMultiPhotoModal();
      showToast("Acquisizione foto annullata.", "info");
    }

    function renderMultiPhotoModal() {
      const count = multiPhotosSession.length;
      const countBadge = document.getElementById('multiPhotoCountBadge');
      const separateBadge = document.getElementById('multiPhotoSeparateCountBadge');
      const grid = document.getElementById('multiPhotoGrid');
      const singleAction = document.getElementById('multiPhotoSingleAction');
      const multipleActions = document.getElementById('multiPhotoMultipleActions');

      if (countBadge) countBadge.textContent = count;
      if (separateBadge) separateBadge.textContent = `${count} FILE`;

      if (grid) {
        grid.innerHTML = '';
        multiPhotosSession.forEach((item, index) => {
          const card = document.createElement('div');
          card.className = "relative rounded-xs border border-[#D8D2C4] bg-[#FAF8F2] overflow-hidden group shadow-xs";
          card.innerHTML = `
            <img src="${item.previewUrl}" alt="Foto ${index + 1}" class="w-full h-24 object-cover">
            <span class="stamp-oli absolute top-1 left-1 text-[8px] bg-white/95 text-[#222220] py-0.5 px-1 font-mono-code font-bold shadow-xs">
              PAG. ${index + 1}
            </span>
            <button type="button" onclick="removeMultiPhoto(${index})" title="Elimina foto" class="absolute top-1 right-1 w-6 h-6 rounded-xs bg-white/95 text-[#C84B31] hover:bg-[#C84B31] hover:text-white flex items-center justify-center text-xs shadow-xs transition cursor-pointer">
              <i class="fa-solid fa-trash-can"></i>
            </button>
          `;
          grid.appendChild(card);
        });
      }

      if (count <= 1) {
        if (singleAction) singleAction.classList.remove('hidden');
        if (multipleActions) multipleActions.classList.add('hidden');
      } else {
        if (singleAction) singleAction.classList.add('hidden');
        if (multipleActions) multipleActions.classList.remove('hidden');
      }
    }

    function removeMultiPhoto(index) {
      if (index >= 0 && index < multiPhotosSession.length) {
        const removed = multiPhotosSession.splice(index, 1)[0];
        if (removed && removed.previewUrl) URL.revokeObjectURL(removed.previewUrl);
        if (multiPhotosSession.length === 0) {
          closeMultiPhotoModal();
        } else {
          renderMultiPhotoModal();
        }
      }
    }

    function triggerAnotherCameraShot() {
      const input = document.getElementById('cameraMultiPhotoInput');
      if (input) {
        input.value = '';
        input.click();
      }
    }

    function triggerGalleryMultiAdd() {
      const input = document.getElementById('galleryMultiPhotoInput');
      if (input) {
        input.value = '';
        input.click();
      }
    }

    function handleCameraMultiPhotoSelected(event) {
      const files = event.target.files;
      if (!files || files.length === 0) return;
      multiPhotoTargetThreadId = currentThreadId || 'general';
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        multiPhotosSession.push({
          file: f,
          previewUrl: URL.createObjectURL(f),
          name: f.name || `foto_${Date.now()}_${i + 1}.jpg`
        });
      }
      renderMultiPhotoModal();
      openMultiPhotoModal();
    }

    function handleGalleryMultiPhotosSelected(event) {
      const files = event.target.files;
      if (!files || files.length === 0) return;
      multiPhotoTargetThreadId = currentThreadId || 'general';
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        multiPhotosSession.push({
          file: f,
          previewUrl: URL.createObjectURL(f),
          name: f.name || `foto_${Date.now()}_${i + 1}.jpg`
        });
      }
      renderMultiPhotoModal();
      openMultiPhotoModal();
    }

    async function submitMultiPhotosToAI(mode) {
      if (multiPhotosSession.length === 0) {
        closeMultiPhotoModal();
        return;
      }
      if (multiPhotosSession.length === 1 || mode === 'single') {
        const item = multiPhotosSession[0];
        const fileToUpload = item.file;
        multiPhotosSession.forEach(p => { if (p.previewUrl) URL.revokeObjectURL(p.previewUrl); });
        multiPhotosSession = [];
        closeMultiPhotoModal();
        await processFilesUpload([fileToUpload]);
      } else {
        await submitMultiPhotosSeparately();
      }
    }

    async function submitMultiPhotosSeparately() {
      if (multiPhotosSession.length === 0) {
        closeMultiPhotoModal();
        return;
      }
      const filesToUpload = multiPhotosSession.map(p => p.file);
      multiPhotosSession.forEach(p => { if (p.previewUrl) URL.revokeObjectURL(p.previewUrl); });
      multiPhotosSession = [];
      closeMultiPhotoModal();
      showToast(`📁 Acquisizione di ${filesToUpload.length} foto per catalogazione separata...`, 'info', 3000);
      await processFilesUpload(filesToUpload);
    }

    async function submitMultiPhotosAsPdf() {
      if (multiPhotosSession.length === 0) {
        closeMultiPhotoModal();
        return;
      }
      const filesToUpload = multiPhotosSession.map(p => p.file);
      const targetThreadId = multiPhotoTargetThreadId || currentThreadId || 'general';
      multiPhotosSession.forEach(p => { if (p.previewUrl) URL.revokeObjectURL(p.previewUrl); });
      multiPhotosSession = [];
      closeMultiPhotoModal();

      if (currentThreadId && currentThreadId !== targetThreadId && typeof switchThread === 'function') {
        switchThread(targetThreadId);
      }

      const totalCount = filesToUpload.length;
      if (currentThreadId === targetThreadId) {
        ensureTodayDateDivider();
        appendUserBubble(`📸 Documento multipagina: ${totalCount} foto unite in unico PDF`, null, getTime());
      }
      setGenerationActive(true, `Compilazione ed analisi AI documento multipagina (${totalCount} foto)...`, null, targetThreadId);

      const formData = new FormData();
      filesToUpload.forEach(f => formData.append('files', f));
      formData.append('thread_id', targetThreadId);

      try {
        const res = await fetch('/api/documents/upload-multipage-photos', {
          method: 'POST',
          headers: authHeaders(),
          body: formData
        });
        setGenerationActive(false, "", null, targetThreadId);
        if (!res.ok) throw new Error("Errore durante l'elaborazione del documento multipagina");
        const data = await res.json();

        const docItem = {
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
          file_type: data.file_type || 'application/pdf'
        };

        const th = threadsCache.find(t => t.id === targetThreadId);
        if (th) {
          th.last_message = data.chat_reply ? cleanSidebarPreview(data.chat_reply) : `Acquisito documento multipagina`;
          th.last_message_time = getTime();
          th.last_message_iso = new Date().toISOString();
          th.message_count = (th.message_count || 0) + 2;
          renderThreadsList();
        }

        if (currentThreadId === targetThreadId) {
          ensureTodayDateDivider();
          appendAssistantBubble(data.chat_reply || "📄 Documento multipagina salvato e protocollato!", [docItem], null, null, null, null, data.routed_model || 'google/gemini-2.5-flash-lite', getTime());
          scrollBottom();
        } else {
          showToast(`📄 Documento multipagina protocollato in "${th?.name || targetThreadId}"`, 'success', 4500);
        }
        loadDashboard(currentFilter);
      } catch (err) {
        setGenerationActive(false, "", null, targetThreadId);
        console.error("Errore upload-multipage-photos:", err);
        showToast("⚠️ Impossibile salvare il documento multipagina.", "error");
        if (currentThreadId === targetThreadId) {
          ensureTodayDateDivider();
          appendAssistantBubble("⚠️ Errore durante l'unione e analisi del documento multipagina.", null, null, null, null, null, null, getTime());
        }
      }
    }

    window.handleCameraMultiPhotoSelected = handleCameraMultiPhotoSelected;
    window.handleGalleryMultiPhotosSelected = handleGalleryMultiPhotosSelected;
    window.triggerAnotherCameraShot = triggerAnotherCameraShot;
    window.triggerGalleryMultiAdd = triggerGalleryMultiAdd;
    window.removeMultiPhoto = removeMultiPhoto;
    window.cancelMultiPhotoSession = cancelMultiPhotoSession;
    window.submitMultiPhotosToAI = submitMultiPhotosToAI;
    window.submitMultiPhotosSeparately = submitMultiPhotosSeparately;
    window.submitMultiPhotosAsPdf = submitMultiPhotosAsPdf;
    window.openMultiPhotoModal = openMultiPhotoModal;
    window.closeMultiPhotoModal = closeMultiPhotoModal;

    // =========================================================================
    // MODALE WEBCAM / VIDEOCAMERA DESKTOP (Scatto Foto Live)
    // =========================================================================
    let webcamStream = null;
    let currentCameraDeviceId = null;
    let availableVideoDevices = [];

    async function openWebcamCaptureModal() {
      if (attachmentMenu) attachmentMenu.classList.add('hidden');

      const modal = document.getElementById('webcamModal');
      if (!modal) {
        // Fallback se il modal non è presente nel DOM
        const itemPhotoInput = document.getElementById('itemPhotoInput');
        if (itemPhotoInput) itemPhotoInput.click();
        else if (realFileInput) realFileInput.click();
        return;
      }

      const errorBox = document.getElementById('webcamErrorBox');
      if (errorBox) errorBox.classList.add('hidden');
      const video = document.getElementById('webcamVideo');
      const canvas = document.getElementById('webcamCanvas');
      const liveControls = document.getElementById('webcamLiveControls');
      const previewControls = document.getElementById('webcamPreviewControls');
      const crosshair = document.getElementById('webcamCrosshair');
      const statusText = document.getElementById('webcamStatusText');

      if (video) video.classList.remove('hidden');
      if (canvas) canvas.classList.add('hidden');
      if (liveControls) liveControls.classList.remove('hidden');
      if (previewControls) previewControls.classList.add('hidden');
      if (crosshair) crosshair.classList.remove('hidden');
      if (statusText) statusText.textContent = 'Inquadra e premi "Scatta Foto"';

      modal.classList.remove('hidden');
      modal.classList.add('flex');

      await startWebcamStream();
    }

    async function startWebcamStream(deviceId = null) {
      stopWebcamStream();

      const video = document.getElementById('webcamVideo');
      const errorBox = document.getElementById('webcamErrorBox');
      const errorMsg = document.getElementById('webcamErrorMessage');
      const btnSwitch = document.getElementById('btnSwitchWebcam');

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        if (errorBox) errorBox.classList.remove('hidden');
        if (errorMsg) errorMsg.textContent = 'Il tuo browser non supporta l\'accesso diretto alla videocamera.';
        return;
      }

      try {
        const constraints = {
          video: deviceId 
            ? { deviceId: { exact: deviceId }, width: { ideal: 1920 }, height: { ideal: 1080 } }
            : { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
          audio: false
        };

        webcamStream = await navigator.mediaDevices.getUserMedia(constraints);
        if (video) {
          video.srcObject = webcamStream;
          await video.play();
        }

        // Elenca dispositivi video per attivare/disattivare il tasto switch camera
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          availableVideoDevices = devices.filter(d => d.kind === 'videoinput');
          if (btnSwitch) {
            btnSwitch.classList.toggle('hidden', availableVideoDevices.length < 2);
          }
        } catch (_) {}

      } catch (err) {
        console.warn("Errore accesso videocamera:", err);
        if (errorBox) errorBox.classList.remove('hidden');
        if (errorMsg) {
          if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
            errorMsg.textContent = 'Accesso alla videocamera negato dal browser. Consenti l\'accesso nei permessi della pagina o seleziona un file.';
          } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
            errorMsg.textContent = 'Nessuna videocamera o webcam rilevata sul dispositivo.';
          } else {
            errorMsg.textContent = 'Impossibile avviare la videocamera: ' + (err.message || 'Errore dispositivo');
          }
        }
      }
    }

    async function switchWebcamDevice() {
      if (availableVideoDevices.length < 2) return;
      const currentIdx = availableVideoDevices.findIndex(d => d.deviceId === currentCameraDeviceId);
      const nextIdx = (currentIdx + 1) % availableVideoDevices.length;
      currentCameraDeviceId = availableVideoDevices[nextIdx].deviceId;
      await startWebcamStream(currentCameraDeviceId);
    }

    function captureWebcamPhoto() {
      const video = document.getElementById('webcamVideo');
      const canvas = document.getElementById('webcamCanvas');
      const liveControls = document.getElementById('webcamLiveControls');
      const previewControls = document.getElementById('webcamPreviewControls');
      const crosshair = document.getElementById('webcamCrosshair');
      const statusText = document.getElementById('webcamStatusText');

      if (!video || !canvas || !video.videoWidth) return;

      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      video.classList.add('hidden');
      canvas.classList.remove('hidden');
      if (crosshair) crosshair.classList.add('hidden');
      if (liveControls) liveControls.classList.add('hidden');
      if (previewControls) previewControls.classList.remove('hidden');
      if (statusText) statusText.textContent = 'Foto scattata! Conferma o rifai lo scatto.';
    }

    function retakeWebcamPhoto() {
      const video = document.getElementById('webcamVideo');
      const canvas = document.getElementById('webcamCanvas');
      const liveControls = document.getElementById('webcamLiveControls');
      const previewControls = document.getElementById('webcamPreviewControls');
      const crosshair = document.getElementById('webcamCrosshair');
      const statusText = document.getElementById('webcamStatusText');

      if (canvas) canvas.classList.add('hidden');
      if (video) video.classList.remove('hidden');
      if (crosshair) crosshair.classList.remove('hidden');
      if (liveControls) liveControls.classList.remove('hidden');
      if (previewControls) previewControls.classList.add('hidden');
      if (statusText) statusText.textContent = 'Inquadra e premi "Scatta Foto"';
    }

    function useCapturedWebcamPhoto() {
      const canvas = document.getElementById('webcamCanvas');
      if (!canvas) return;

      canvas.toBlob(async (blob) => {
        if (!blob) return;
        const filename = `foto_${Date.now()}.jpg`;
        const file = new File([blob], filename, { type: 'image/jpeg' });

        closeWebcamModal();

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
            showToast('Impossibile salvare la foto: ' + err.message, 'error');
          }
        } else {
          await processFilesUpload([file]);
        }
      }, 'image/jpeg', 0.92);
    }

    function stopWebcamStream() {
      if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
      }
      const video = document.getElementById('webcamVideo');
      if (video) video.srcObject = null;
    }

    function closeWebcamModal() {
      stopWebcamStream();
      const modal = document.getElementById('webcamModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
    }

    function fallbackToFilePicker() {
      closeWebcamModal();
      const itemPhotoInput = document.getElementById('itemPhotoInput');
      if (itemPhotoInput) itemPhotoInput.click();
      else if (realFileInput) realFileInput.click();
    }

    window.openWebcamCaptureModal = openWebcamCaptureModal;
    window.startWebcamStream = startWebcamStream;
    window.switchWebcamDevice = switchWebcamDevice;
    window.captureWebcamPhoto = captureWebcamPhoto;
    window.retakeWebcamPhoto = retakeWebcamPhoto;
    window.useCapturedWebcamPhoto = useCapturedWebcamPhoto;
    window.stopWebcamStream = stopWebcamStream;
    window.closeWebcamModal = closeWebcamModal;
    window.fallbackToFilePicker = fallbackToFilePicker;

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

    // --- Registratore Vocale Reale (Nativo Android APK, Web Audio & Fallback) ---
    let voiceMediaStream = null;
    let voiceMediaRecorder = null;
    let voiceSpeechRecognition = null;
    let voiceLiveTranscription = '';
    let voiceAudioChunks = [];
    let voiceTimerInterval = null;
    let voiceRecordStartTime = null;
    let isNativeVoiceActive = false;

    function showVoiceRecordingUI() {
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

    function hideVoiceRecordingUI() {
      clearInterval(voiceTimerInterval);
      voiceTimerInterval = null;

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

    async function startVoiceRecording() {
      // 1. Canale Nativo Android APK (hardware mic diretto, bypassa restrizioni WebRTC su LAN HTTP)
      if (window.AndroidNativeVoice && typeof window.AndroidNativeVoice.isSupported === 'function' && window.AndroidNativeVoice.isSupported()) {
        try {
          const started = window.AndroidNativeVoice.startRecording();
          if (started) {
            isNativeVoiceActive = true;
            voiceLiveTranscription = '';
            voiceRecordStartTime = Date.now();
            showVoiceRecordingUI();
            return;
          }
        } catch (e) {
          console.warn("Errore avvio registrazione nativa Android:", e);
        }
      }

      // 2. Controllo disponibilità microfono WebRTC nel browser
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        // Fallback per browser mobile su HTTP (es. Chrome su Pixel 9 che non espone getUserMedia su HTTP non cifrato)
        const voiceFileInput = document.getElementById('voiceAudioInput');
        if (voiceFileInput) {
          showToast("🎙️ Avvio registratore vocale del telefono...", "info", 3000);
          voiceFileInput.click();
          return;
        }
        showToast("⚠️ Il microfono via browser richiede HTTPS o l'app Android 'Dove lo AI messo'.", "error", 5000);
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
      showVoiceRecordingUI();
    }

    function cancelVoiceRecording() {
      if (isNativeVoiceActive) {
        isNativeVoiceActive = false;
        if (window.AndroidNativeVoice && typeof window.AndroidNativeVoice.cancelRecording === 'function') {
          try { window.AndroidNativeVoice.cancelRecording(); } catch (e) {}
        }
      }
      cleanupVoiceRecording();
      voiceAudioChunks = [];
      showToast("Registrazione vocale annullata", "info");
    }

    function cleanupVoiceRecording() {
      if (isNativeVoiceActive) {
        isNativeVoiceActive = false;
        if (window.AndroidNativeVoice && typeof window.AndroidNativeVoice.cancelRecording === 'function') {
          try { window.AndroidNativeVoice.cancelRecording(); } catch (e) {}
        }
      }

      hideVoiceRecordingUI();

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
    }

    async function sendVoiceAudioToAssistant(base64Audio, audioFormat, durationSec, transcriptionText, targetThreadId, quotedToSend, userVoiceBubbleEl) {
      setGenerationActive(true, "L'assistente sta ascoltando il tuo messaggio vocale...", null, targetThreadId);
      const taskSignal = activeThreadTasks[targetThreadId]?.abortController?.signal;

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            message: transcriptionText || "",
            audio_base64: base64Audio,
            audio_format: audioFormat || "wav",
            audio_duration: durationSec,
            thread_id: targetThreadId,
            quoted_message: quotedToSend ? { sender: quotedToSend.senderName, text: quotedToSend.text } : null
          }),
          signal: taskSignal
        });

        setGenerationActive(false, "", null, targetThreadId);
        if (!res.ok) throw new Error('Errore nella risposta del server');
        const data = await res.json();

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

        const asstTime = (data && data.created_at) ? formatMessageTime(data.created_at) : getTime();
        const th = threadsCache.find(t => t.id === targetThreadId);
        if (th) {
          th.last_message = data.reply ? cleanSidebarPreview(data.reply) : "Messaggio vocale";
          th.last_message_time = getTime();
          th.last_message_iso = (data && data.created_at) ? data.created_at : new Date().toISOString();
          th.message_count = (th.message_count || 0) + 2;
          renderThreadsList();
        }

        if (currentThreadId === targetThreadId) {
          ensureTodayDateDivider();
          const routedModel = data.routed_model || (data.data && data.data.routed_model) || null;
          appendAssistantBubble(data.reply, data.documents, data.confirmation, itemPhoto, storeItem, null, routedModel, asstTime);
          scrollBottom();
        } else {
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
          ensureTodayDateDivider();
          appendAssistantBubble("⚠️ Errore durante l'ascolto o l'elaborazione del messaggio vocale.", null, null, null, null, null, null, getTime());
          scrollBottom();
        }
      }
    }

    async function stopAndSendVoiceRecording() {
      if (isNativeVoiceActive) {
        isNativeVoiceActive = false;
        hideVoiceRecordingUI();
        if (window.AndroidNativeVoice && typeof window.AndroidNativeVoice.stopRecording === 'function') {
          window.AndroidNativeVoice.stopRecording();
        }
        return;
      }

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
      hideVoiceRecordingUI();

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
      ensureTodayDateDivider();
      const userVoiceBubbleEl = appendUserAudioBubble(localAudioUrl, durationSec, quotedToSend, voiceLiveTranscription || null, getTime());
      await sendVoiceAudioToAssistant(base64Audio, "wav", durationSec, voiceLiveTranscription || "", targetThreadId, quotedToSend, userVoiceBubbleEl);
    }

    window.onNativeVoiceRecorded = async function(base64Audio, durationSec, format) {
      const cleanFmt = format || 'm4a';
      const mimeType = cleanFmt === 'm4a' ? 'audio/mp4' : (cleanFmt === 'wav' ? 'audio/wav' : 'audio/webm');
      let localAudioUrl = '';
      try {
        const byteCharacters = atob(base64Audio);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const audioBlob = new Blob([byteArray], { type: mimeType });
        localAudioUrl = URL.createObjectURL(audioBlob);
      } catch (e) {
        localAudioUrl = `data:${mimeType};base64,${base64Audio}`;
      }

      const targetThreadId = currentThreadId;
      const quotedToSend = currentQuotedMessage;
      cancelQuoteReply();

      ensureTodayDateDivider();
      const userVoiceBubbleEl = appendUserAudioBubble(localAudioUrl, durationSec, quotedToSend, null, getTime());
      await sendVoiceAudioToAssistant(base64Audio, cleanFmt, durationSec, "", targetThreadId, quotedToSend, userVoiceBubbleEl);
    };

    window.onNativeVoiceError = function(errMsg) {
      hideVoiceRecordingUI();
      showToast("⚠️ " + (errMsg || "Errore nella registrazione vocale nativa."), "error");
    };

    window.handleVoiceAudioFileSelected = async function(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      event.target.value = '';

      const ext = file.name.split('.').pop().toLowerCase() || 'm4a';
      const cleanFmt = (ext === 'mp3' || ext === 'wav' || ext === 'm4a' || ext === 'ogg' || ext === 'aac') ? ext : 'm4a';
      const localAudioUrl = URL.createObjectURL(file);
      const targetThreadId = currentThreadId;
      const quotedToSend = currentQuotedMessage;
      cancelQuoteReply();

      let durationSec = 1;
      try {
        const tempAudio = new Audio(localAudioUrl);
        await new Promise((resolve) => {
          tempAudio.onloadedmetadata = () => {
            durationSec = Math.round(tempAudio.duration) || 1;
            resolve();
          };
          tempAudio.onerror = () => resolve();
          setTimeout(resolve, 800);
        });
      } catch (e) {}

      const base64Audio = await blobToBase64(file);
      ensureTodayDateDivider();
      const userVoiceBubbleEl = appendUserAudioBubble(localAudioUrl, durationSec, quotedToSend, null, getTime());
      await sendVoiceAudioToAssistant(base64Audio, cleanFmt, durationSec, "", targetThreadId, quotedToSend, userVoiceBubbleEl);
    };

    window.startVoiceRecording = startVoiceRecording;
    window.stopAndSendVoiceRecording = stopAndSendVoiceRecording;
    window.cancelVoiceRecording = cancelVoiceRecording;
    window.handleVoiceAudioFileSelected = handleVoiceAudioFileSelected;

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

