/* =============================================================
   EBMS — Application Shell JavaScript
   Sidebar collapse + mobile drawer, topbar dropdowns, toasts,
   dark-mode toggle, modal helpers. No external dependencies.
   ============================================================= */
(function () {
  'use strict';

  /* ---------- Toast notifications ---------- */
  var TOAST_ICONS = {
    success: 'bi-check-circle-fill',
    error: 'bi-exclamation-octagon-fill',
    warning: 'bi-exclamation-triangle-fill',
    info: 'bi-info-circle-fill'
  };

  function ensureToastStack() {
    var stack = document.getElementById('ebmsToastStack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'ebmsToastStack';
      stack.className = 'ebms-toast-stack';
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    return stack;
  }

  function showToast(message, category, title) {
    var type = category || 'info';
    var stack = ensureToastStack();
    var toast = document.createElement('div');
    toast.className = 'ebms-toast ' + type;
    toast.setAttribute('role', 'status');

    var icon = TOAST_ICONS[type] || TOAST_ICONS.info;
    var heading = title ||
      (type === 'success' ? 'Success' :
        type === 'error' ? 'Something went wrong' :
          type === 'warning' ? 'Please check' : 'Notice');

    toast.innerHTML =
      '<span class="toast-icon"><i class="bi ' + icon + '"></i></span>' +
      '<div class="ebms-toast-body">' +
      '<span class="ebms-toast-title"></span>' +
      '<span class="toast-message"></span>' +
      '</div>' +
      '<button type="button" class="ebms-toast-close" aria-label="Dismiss"><i class="bi bi-x-lg"></i></button>';

    toast.querySelector('.ebms-toast-title').textContent = heading;
    toast.querySelector('.toast-message').textContent = message;

    var closeBtn = toast.querySelector('.ebms-toast-close');
    closeBtn.addEventListener('click', function () {
      dismissToast(toast);
    });

    stack.appendChild(toast);

    // Auto-dismiss after 6 seconds
    setTimeout(function () {
      dismissToast(toast);
    }, 6000);
  }

  function dismissToast(toast) {
    toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-6px)';
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 260);
  }

  /* ---------- Cancellable document uploads ---------- */
  function initCancellableUploads() {
    var forms = document.querySelectorAll('form[data-cancellable-upload]');
    Array.prototype.forEach.call(forms, function (form) {
      var submitButton = form.querySelector('button[type="submit"]');
      var fileInputs = form.querySelectorAll('input[type="file"]');
      if (!submitButton) return;

      var progress = document.createElement('progress');
      progress.className = 'w-100 mt-2';
      progress.max = 100;
      progress.value = 0;
      progress.hidden = true;
      progress.setAttribute('aria-label', 'Upload progress');

      submitButton.parentNode.appendChild(progress);

      Array.prototype.forEach.call(fileInputs, function (fileInput) {
        var removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'btn btn-sm btn-outline-secondary mt-1';
        removeButton.innerHTML = '<i class="bi bi-x-circle me-1"></i>Remove selected file';
        removeButton.hidden = true;
        fileInput.parentNode.appendChild(removeButton);

        fileInput.addEventListener('change', function () {
          removeButton.hidden = !fileInput.files.length;
        });
        removeButton.addEventListener('click', function () {
          fileInput.value = '';
          removeButton.hidden = true;
        });
      });

      var request = null;
      var originalLabel = submitButton.innerHTML;

      function resetUploadState() {
        submitButton.disabled = false;
        submitButton.innerHTML = originalLabel;
        progress.hidden = true;
        progress.value = 0;
        request = null;
      }

      form.addEventListener('submit', function (event) {
        var submitter = event.submitter || submitButton;

        if (submitter && submitter.name) {
          return;
        }

        event.preventDefault();
        if (request) return;

        request = new XMLHttpRequest();
        request.open('POST', form.action, true);
        request.upload.addEventListener('progress', function (progressEvent) {
          if (!progressEvent.lengthComputable) return;
          progress.value = Math.round((progressEvent.loaded / progressEvent.total) * 100);
        });
        request.addEventListener('load', function () {
          var successStatus = request.status >= 200 && request.status < 400;
          var redirectStatus = request.status >= 300 && request.status < 400;
          var redirectLocation = request.responseURL || request.getResponseHeader('Location') || form.action;

          if (successStatus || redirectStatus) {
            try {
              window.location.assign(redirectLocation || form.action);
            } catch (error) {
              window.location.href = form.action;
            }
            return;
          }

          resetUploadState();
          showToast('The upload could not be completed. Please try again.', 'error');
        });
        request.addEventListener('error', function () {
          resetUploadState();
          showToast('A network error interrupted the upload.', 'error');
        });

        var formData = new FormData(form);
        if (submitter && submitter.name) {
          formData.append(submitter.name, submitter.value);
        }

        submitButton.disabled = true;
        submitButton.innerHTML = '<i class="bi bi-cloud-arrow-up me-1"></i>Uploading...';
        progress.hidden = false;
        request.send(formData);
      });
    });
  }

  /* Render any flashed messages (data-ebms-flash elements) as toasts */
  function renderFlashedMessages() {
    var srcs = document.querySelectorAll('[data-ebms-flash]');
    Array.prototype.forEach.call(srcs, function (el) {
      var message = el.textContent.trim();
      var category = el.getAttribute('data-ebms-flash') || 'info';
      if (message) showToast(message, category);
      if (el.parentNode) el.parentNode.removeChild(el);
    });
  }

  /* ---------- Sidebar ---------- */
  function initSidebar() {
    var sidebar = document.querySelector('.ebms-sidebar');
    var toggle = document.querySelector('.ebms-sidebar-toggle');
    var main = document.querySelector('.ebms-main');
    var backdrop = document.querySelector('.ebms-sidebar-backdrop');
    if (!sidebar) return;

    var STORAGE_KEY = 'ebms.sidebarCollapsed';

    function setCollapsed(collapsed, save) {
      sidebar.classList.toggle('collapsed', collapsed);
      if (main) main.classList.toggle('collapsed', collapsed);
      if (save) {
        try {
          localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
        } catch (e) { /* ignore */ }
      }
    }

    if (toggle) {
      toggle.addEventListener('click', function () {
        var isMobile = window.innerWidth <= 768;
        if (isMobile) {
          sidebar.classList.toggle('open');
          if (backdrop) backdrop.classList.toggle('show', sidebar.classList.contains('open'));
        } else {
          var wasCollapsed = sidebar.classList.contains('collapsed');
          setCollapsed(!wasCollapsed, true);
        }
      });
    }

    if (backdrop) {
      backdrop.addEventListener('click', function () {
        sidebar.classList.remove('open');
        backdrop.classList.remove('show');
      });
    }

    // Restore persisted state on desktop
    if (window.innerWidth > 768) {
      var saved = '0';
      try {
        saved = localStorage.getItem(STORAGE_KEY) || '0';
      } catch (e) { /* ignore */ }
      setCollapsed(saved === '1', false);
    }
  }
/* ---------- Topbar dropdowns ---------- */
  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function renderPreviewItem(it) {
    var href = (typeof it.thread_id !== 'undefined' && it.thread_id !== null)
      ? '/messages/thread/' + it.thread_id
      : (it.url || '#');
    var unread = it.unread
      ? '<span class="ebms-preview-dot"></span>' : '';
    var icon = it.is_outbound ? 'bi-send'
      : (typeof it.thread_id !== 'undefined' && it.thread_id !== null ? 'bi-chat-text' : 'bi-bell');
    var title = it.is_outbound ? 'You' : (it.sender || 'System');
    return '<a class="ebms-dropdown-preview-item" href="' + href + '">' + unread +
      '<span class="ebms-preview-icon"><i class="bi ' + icon + '"></i></span>' +
      '<span class="ebms-preview-body">' +
        '<span class="ebms-preview-title">' + escapeHtml(title) + '</span>' +
        '<span class="ebms-preview-text">' + escapeHtml(it.subject || '') +
          (it.snippet ? ' — ' + escapeHtml(it.snippet) : '') + '</span>' +
        '<span class="ebms-preview-time">' + escapeHtml(it.created_fmt || '') + '</span>' +
      '</span></a>';
  }

  function loadMenuPreview(menu) {
    var url = menu.getAttribute('data-preview-url');
    if (!url) return;
    var list = menu.querySelector('.ebms-preview-list');
    if (!list) return;
    list.innerHTML = '<div class="ebms-dropdown-loading">Loading…</div>';
    fetch(url, { headers: { 'Accept': 'application/json' } })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data || !data.items || !data.items.length) {
          list.innerHTML = '<div class="ebms-dropdown-empty">Nothing here yet.</div>';
          return;
        }
        list.innerHTML = data.items.map(renderPreviewItem).join('');
      })
      .catch(function () {
        list.innerHTML = '<div class="ebms-dropdown-empty">Could not load.</div>';
      });
  }

  function initDropdowns() {
    var triggers = document.querySelectorAll('[data-dropdown-target]');
    var openMenu = null;

    function closeAll() {
      if (openMenu) {
        openMenu.classList.remove('show');
        var trigger = document.querySelector('[data-dropdown-target="' + openMenu.id + '"]');
        if (trigger) trigger.classList.remove('active');
      }
      openMenu = null;
    }

    Array.prototype.forEach.call(triggers, function (trigger) {
      trigger.addEventListener('click', function (e) {
        e.stopPropagation();
        var id = trigger.getAttribute('data-dropdown-target');
        var menu = document.getElementById(id);
        if (!menu) return;

        var isOpen = menu.classList.contains('show');
        closeAll();
        if (!isOpen) {
          menu.classList.add('show');
          positionDropdown(trigger, menu);
          trigger.classList.add('active');
          openMenu = menu;
          loadMenuPreview(menu);
        }
      });
    });

    document.addEventListener('click', function () {
      closeAll();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeAll();
    });
  }

  function positionDropdown(trigger, menu) {
    var rect = trigger.getBoundingClientRect();
    var left = rect.right - menu.offsetWidth;
    var top = rect.bottom + 8;
    if (left < 8) left = 8;
    if (top + menu.offsetHeight > window.innerHeight - 8) {
      top = rect.top - menu.offsetHeight - 8;
    }
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }

  /* ---------- Dark mode ---------- */
  var darkPreference = null;

  function updateThemeIcon() {
    var btn = document.getElementById('ebmsThemeToggle');
    if (!btn) return;
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    btn.innerHTML = isDark
      ? '<i class="bi bi-sun" aria-hidden="true"></i>'
      : '<i class="bi bi-moon-stars" aria-hidden="true"></i>';
  }

  function initThemeToggle() {
    var btn = document.getElementById('ebmsThemeToggle');
    if (!btn) return;

    btn.addEventListener('click', function () {
      var html = document.documentElement;
      var current = html.getAttribute('data-theme') || 'light';
      var next = current === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', next);
      darkPreference = next;
      try {
        localStorage.setItem('ebms.theme', next);
      } catch (e) { /* ignore */ }
      updateThemeIcon();
    });
  }

  /* ---------- Bootstrap-compatible modals (no dependency) ---------- */
  function initModals() {
    // If Bootstrap is already present, defer to it.
    if (window.bootstrap && window.bootstrap.Modal) return;

    var activeModal = null;
    var backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.addEventListener('click', function () {
      if (activeModal) closeModal(activeModal);
    });

    function openModal(modal) {
      if (activeModal && activeModal !== modal) closeModal(activeModal);
      document.body.appendChild(modal);
      document.body.appendChild(backdrop);
      modal.style.position = 'fixed';
      modal.style.inset = '0';
      modal.style.zIndex = '1401';
      modal.style.maxWidth = 'none';
      modal.style.maxHeight = 'none';
      modal.style.padding = '1.5rem';
      modal.style.background = 'transparent';
      modal.style.display = 'flex';
      modal.style.alignItems = 'center';
      modal.style.justifyContent = 'center';
      var dialog = modal.querySelector('.modal-dialog');
      if (dialog) {
        dialog.style.width = '100%';
        dialog.style.maxWidth = '520px';
        dialog.style.maxHeight = 'calc(100vh - 3rem)';
        dialog.style.margin = '0';
      }
      var content = modal.querySelector('.modal-content');
      if (content) {
        content.style.maxHeight = 'calc(100vh - 3rem)';
        content.style.overflowY = 'auto';
      }
      modal.classList.add('show');
      backdrop.classList.add('show');
      document.body.style.overflow = 'hidden';
      activeModal = modal;
    }

    function closeModal(modal) {
      modal.classList.remove('show');
      modal.style.display = 'none';
      backdrop.classList.remove('show');
      document.body.style.overflow = '';
      if (activeModal === modal) activeModal = null;
    }

    Array.prototype.forEach.call(
      document.querySelectorAll('[data-bs-toggle="modal"][data-bs-target]'),
      function (trigger) {
        trigger.addEventListener('click', function () {
          var target = document.querySelector(trigger.getAttribute('data-bs-target'));
          if (target) openModal(target);
        });
      }
    );

    Array.prototype.forEach.call(
      document.querySelectorAll('[data-bs-dismiss="modal"]'),
      function (el) {
        el.addEventListener('click', function () {
          var modal = el.closest('.modal') || el.closest('.ebms-modal');
          if (modal) closeModal(modal);
        });
      }
    );

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && activeModal) closeModal(activeModal);
    });
  }

  /* ---------- Unread counts (notifications + messages) ---------- */
  function initUnreadCounts() {
    function apply(id, count) {
      var el = document.getElementById(id);
      if (!el) return;
      if (count > 0) {
        el.textContent = count > 99 ? '99+' : String(count);
        el.style.display = 'inline-flex';
      } else {
        el.style.display = 'none';
      }
    }

    function fetchCount(url, elementId) {
      fetch(url, { headers: { 'Accept': 'application/json' } })
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (data) {
          if (data && typeof data.count !== 'undefined') {
            apply(elementId, data.count);
            if (elementId === 'notificationsCount') apply('sidebarNotificationsCount', data.count);
            if (elementId === 'messagesCount') apply('sidebarMessagesCount', data.count);
          }
        })
        .catch(function () { /* silent — badge simply stays hidden */ });
    }

    function refresh() {
      fetchCount('/notifications/unread-count', 'notificationsCount');
      fetchCount('/messages/unread-count', 'messagesCount');
    }

    refresh();
    // Near-real-time badge updates without a full page refresh
    window.setInterval(refresh, 20000);
  }

  /* ---------- Init ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    initSidebar();
    initDropdowns();
    initThemeToggle();
    updateThemeIcon();
    initModals();
    renderFlashedMessages();
    initUnreadCounts();
    initCancellableUploads();

    // Expose helpers for inline onclick handlers used by templates
    window.EBMS = {
      showToast: showToast,
      toast: showToast
    };
  });
})();
