// Apply saved theme immediately (before IIFE) to prevent flash
(function () {
    var saved = localStorage.getItem('contact_list_theme') || '';
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
})();

// Progressive enhancement — all handlers degrade gracefully without JS
(function () {
    'use strict';

    // =================================================================
    // Theme picker
    // =================================================================
    var THEME_KEY = 'contact_list_theme';
    var themeToggle = document.getElementById('theme-toggle');
    var themeDropdown = document.getElementById('theme-dropdown');

    function applyTheme(name) {
        if (name) {
            document.documentElement.setAttribute('data-theme', name);
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
        try { localStorage.setItem(THEME_KEY, name); } catch (e) {}
        // Update active state
        if (themeDropdown) {
            themeDropdown.querySelectorAll('.theme-option').forEach(function (btn) {
                btn.classList.toggle('active', btn.getAttribute('data-theme-choice') === name);
            });
        }
    }

    // Mark current theme as active on load
    var currentTheme = localStorage.getItem(THEME_KEY) || '';
    if (themeDropdown) {
        themeDropdown.querySelectorAll('.theme-option').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-theme-choice') === currentTheme);
            btn.addEventListener('click', function () {
                applyTheme(this.getAttribute('data-theme-choice'));
                themeDropdown.classList.remove('open');
            });
        });
    }

    if (themeToggle && themeDropdown) {
        themeToggle.addEventListener('click', function (e) {
            e.stopPropagation();
            themeDropdown.classList.toggle('open');
        });
        document.addEventListener('click', function (e) {
            if (!themeDropdown.contains(e.target) && e.target !== themeToggle) {
                themeDropdown.classList.remove('open');
            }
        });
    }

    // =================================================================
    // Flash message dismiss + auto-dismiss
    // =================================================================
    document.querySelectorAll('.flash').forEach(function (flash) {
        var btn = flash.querySelector('.flash-dismiss');
        if (btn) {
            btn.addEventListener('click', function () { flash.remove(); });
        }
        // Auto-dismiss after 6 seconds
        setTimeout(function () {
            flash.style.transition = 'opacity 0.4s ease';
            flash.style.opacity = '0';
            setTimeout(function () { flash.remove(); }, 400);
        }, 6000);
    });

    // =================================================================
    // Custom confirmation modal (replaces native confirm())
    // =================================================================
    var modal = document.getElementById('confirm-modal');
    var modalMsg = document.getElementById('confirm-message');
    var modalYes = document.getElementById('confirm-yes');
    var modalNo = document.getElementById('confirm-no');
    var pendingConfirm = null;

    function showModal(message) {
        return new Promise(function (resolve) {
            if (!modal || !modalMsg || !message) {
                resolve(confirm(message || 'Are you sure?')); // fallback
                return;
            }
            modalMsg.textContent = message;
            modal.hidden = false;
            pendingConfirm = resolve;
            modalYes.focus();
        });
    }

    if (modalYes) {
        modalYes.addEventListener('click', function () {
            modal.hidden = true;
            if (pendingConfirm) pendingConfirm(true);
            pendingConfirm = null;
        });
    }
    if (modalNo) {
        modalNo.addEventListener('click', function () {
            modal.hidden = true;
            if (pendingConfirm) pendingConfirm(false);
            pendingConfirm = null;
        });
    }
    if (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === modal) {
                modal.hidden = true;
                if (pendingConfirm) pendingConfirm(false);
                pendingConfirm = null;
            }
        });
    }

    // data-confirm attribute handler using custom modal
    document.querySelectorAll('[data-confirm]').forEach(function (el) {
        var confirming = false;
        el.addEventListener('click', function (e) {
            if (confirming) {
                confirming = false;
                return; // allow the native action
            }
            e.preventDefault();
            var msg = this.getAttribute('data-confirm');
            if (!msg) return;
            var self = this;
            showModal(msg).then(function (confirmed) {
                if (confirmed) {
                    confirming = true;
                    // For buttons inside forms, submit the form directly
                    if (self.type === 'submit' && self.form) {
                        self.form.submit();
                    } else {
                        self.click();
                    }
                }
            });
        });
    });

    // =================================================================
    // Keyboard shortcuts
    // =================================================================
    document.addEventListener('keydown', function (e) {
        // Don't capture when typing in inputs
        var tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') {
            if (e.key === 'Escape') { e.target.blur(); }
            return;
        }

        if (e.key === '/' || e.key === 's') {
            var searchInput = document.getElementById('search-input');
            if (searchInput) {
                e.preventDefault();
                searchInput.focus();
            }
        } else if (e.key === 'n') {
            // Navigate to new contact
            window.location.href = document.querySelector('a[href*="/contacts/new"]')?.href || '/contacts/new';
        } else if (e.key === 'Escape') {
            // Dismiss modal if open
            if (modal && !modal.hidden) {
                modal.hidden = true;
                if (pendingConfirm) pendingConfirm(false);
                pendingConfirm = null;
            }
            // Dismiss all flash messages
            document.querySelectorAll('.flash').forEach(function (f) { f.remove(); });
        }
    });

    // =================================================================
    // Mobile hamburger toggle
    // =================================================================
    var navToggle = document.querySelector('.nav-toggle');
    var navLinks = document.querySelector('.nav-links');
    if (navToggle && navLinks) {
        navToggle.addEventListener('click', function () {
            var open = navLinks.classList.toggle('open');
            navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
    }

    // =================================================================
    // Bulk selection
    // =================================================================
    var selectAll = document.getElementById('select-all');
    var bulkBar = document.getElementById('bulk-bar');
    var bulkCount = document.getElementById('bulk-count');
    var bulkClear = document.getElementById('bulk-clear');
    var rowSelects = document.querySelectorAll('.row-select');

    function updateBulkBar() {
        if (!bulkBar) return;
        var count = document.querySelectorAll('.row-select:checked').length;
        if (count > 0) {
            bulkBar.hidden = false;
            bulkCount.textContent = count;
        } else {
            bulkBar.hidden = true;
        }
    }

    if (selectAll) {
        selectAll.addEventListener('change', function () {
            rowSelects.forEach(function (cb) { cb.checked = selectAll.checked; });
            updateBulkBar();
        });
    }
    rowSelects.forEach(function (cb) {
        cb.addEventListener('change', function () {
            if (!cb.checked && selectAll) selectAll.checked = false;
            updateBulkBar();
        });
    });

    // Group-select checkboxes (duplicates page — select all in one table)
    document.querySelectorAll('.group-select').forEach(function (gs) {
        gs.addEventListener('change', function () {
            var table = gs.closest('table');
            if (!table) return;
            table.querySelectorAll('.row-select').forEach(function (cb) {
                cb.checked = gs.checked;
            });
            updateBulkBar();
        });
    });
    if (bulkClear) {
        bulkClear.addEventListener('click', function () {
            if (selectAll) selectAll.checked = false;
            rowSelects.forEach(function (cb) { cb.checked = false; });
            updateBulkBar();
        });
    }
    var bulkDeleteBtn = document.getElementById('bulk-delete-btn');
    var bulkForm = document.getElementById('bulk-form');
    // Prevent accidental Enter-key submission
    if (bulkForm) {
        bulkForm.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') e.preventDefault();
        });
    }
    if (bulkDeleteBtn && bulkForm) {
        bulkDeleteBtn.addEventListener('click', function () {
            var count = document.querySelectorAll('.row-select:checked').length;
            if (count === 0) return;
            showModal('Delete ' + count + ' selected contact' + (count !== 1 ? 's' : '') + '?').then(function (confirmed) {
                if (confirmed) {
                    // Use HTMLFormElement.prototype.submit to bypass the keydown preventDefault
                    HTMLFormElement.prototype.submit.call(bulkForm);
                }
            });
        });
    }

    // =================================================================
    // Recently viewed (localStorage)
    // =================================================================
    var recentContainer = document.getElementById('recently-viewed');
    var RECENT_KEY = 'contact_list_recent';
    var MAX_RECENT = 5;

    function getRecent() {
        try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); }
        catch (e) { return []; }
    }

    function saveRecent(list) {
        try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); }
        catch (e) { /* quota exceeded */ }
    }

    // Track current contact detail page
    var detailMatch = window.location.pathname.match(/^\/contacts\/(\d+)$/);
    if (detailMatch) {
        var contactId = detailMatch[1];
        var nameEl = document.querySelector('.detail-header h1');
        if (nameEl) {
            var recent = getRecent();
            // Remove existing entry for this contact
            recent = recent.filter(function (r) { return r.id !== contactId; });
            recent.unshift({ id: contactId, name: nameEl.textContent.trim(), href: window.location.pathname });
            if (recent.length > MAX_RECENT) recent = recent.slice(0, MAX_RECENT);
            saveRecent(recent);
        }
    }

    // Show recently viewed on list page
    if (recentContainer && window.location.pathname === '/contacts') {
        var recent = getRecent();
        if (recent.length > 0) {
            // Build with createElement/textContent (not innerHTML) so a contact
            // name containing HTML can never be re-parsed as markup.
            var titleEl = document.createElement('div');
            titleEl.className = 'recently-viewed-title';
            titleEl.textContent = 'Recently viewed';

            var listEl = document.createElement('div');
            listEl.className = 'recently-viewed-list';

            recent.forEach(function (r) {
                var initial = r.name.charAt(0).toUpperCase();
                var cls = /[A-Z]/.test(initial) ? 'avatar-' + initial : 'avatar-other';
                var link = document.createElement('a');
                link.setAttribute('href', r.href);
                link.className = 'recently-viewed-item';
                var avatar = document.createElement('span');
                avatar.className = 'avatar ' + cls;
                avatar.textContent = initial;
                link.appendChild(avatar);
                link.appendChild(document.createTextNode(' ' + r.name));
                listEl.appendChild(link);
            });

            recentContainer.replaceChildren(titleEl, listEl);
            recentContainer.hidden = false;
        }
    }

    // =================================================================
    // Dynamic custom field rows (with drag-and-drop)
    // =================================================================
    var container = document.getElementById('custom-fields');
    var addBtn = document.getElementById('add-field');
    if (!container || !addBtn) {
        return;
    }
    var MAX_CUSTOM_FIELDS = 50;
    var dragSrcRow = null;

    function makeDraggable(row) {
        row.setAttribute('draggable', 'true');
        row.addEventListener('dragstart', function (e) {
            dragSrcRow = this;
            this.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', '');
        });
        row.addEventListener('dragend', function () {
            this.classList.remove('dragging');
            container.querySelectorAll('.custom-field-row').forEach(function (r) {
                r.classList.remove('drag-over');
            });
            dragSrcRow = null;
        });
        row.addEventListener('dragover', function (e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (dragSrcRow && dragSrcRow !== this) {
                this.classList.add('drag-over');
            }
        });
        row.addEventListener('dragleave', function () {
            this.classList.remove('drag-over');
        });
        row.addEventListener('drop', function (e) {
            e.preventDefault();
            this.classList.remove('drag-over');
            if (!dragSrcRow || dragSrcRow === this) return;
            var rows = Array.from(container.querySelectorAll('.custom-field-row'));
            var srcIdx = rows.indexOf(dragSrcRow);
            var dstIdx = rows.indexOf(this);
            if (srcIdx < dstIdx) {
                container.insertBefore(dragSrcRow, this.nextElementSibling);
            } else {
                container.insertBefore(dragSrcRow, this);
            }
        });
    }

    function createRow(name, value) {
        var row = document.createElement('div');
        row.className = 'custom-field-row';

        var handle = document.createElement('span');
        handle.className = 'drag-handle';
        handle.textContent = '\u2817';
        handle.setAttribute('aria-label', 'Drag to reorder');
        handle.title = 'Drag to reorder';

        var nameInput = document.createElement('input');
        nameInput.name = 'cf_name';
        nameInput.type = 'text';
        nameInput.placeholder = 'Field name';
        nameInput.maxLength = 64;
        nameInput.required = true;
        nameInput.value = name || '';

        var valInput = document.createElement('input');
        valInput.name = 'cf_value';
        valInput.type = 'text';
        valInput.placeholder = 'Value';
        valInput.maxLength = 500;
        valInput.required = true;
        valInput.value = value || '';

        var upBtn = document.createElement('button');
        upBtn.type = 'button';
        upBtn.className = 'btn btn-small btn-secondary move-up';
        upBtn.textContent = '\u25B2';
        upBtn.setAttribute('aria-label', 'Move field up');

        var downBtn = document.createElement('button');
        downBtn.type = 'button';
        downBtn.className = 'btn btn-small btn-secondary move-down';
        downBtn.textContent = '\u25BC';
        downBtn.setAttribute('aria-label', 'Move field down');

        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-small btn-danger remove-field';
        removeBtn.textContent = 'Remove';
        removeBtn.setAttribute('aria-label', 'Remove this custom field');

        row.appendChild(handle);
        row.appendChild(nameInput);
        row.appendChild(valInput);
        row.appendChild(upBtn);
        row.appendChild(downBtn);
        row.appendChild(removeBtn);

        makeDraggable(row);
        return row;
    }

    // Enhance existing server-rendered rows with buttons and drag
    container.querySelectorAll('.custom-field-row').forEach(function (row) {
        var removeBtn = row.querySelector('.remove-field');
        if (removeBtn && !row.querySelector('.move-up')) {
            var upBtn = document.createElement('button');
            upBtn.type = 'button';
            upBtn.className = 'btn btn-small btn-secondary move-up';
            upBtn.textContent = '\u25B2';
            upBtn.setAttribute('aria-label', 'Move field up');

            var downBtn = document.createElement('button');
            downBtn.type = 'button';
            downBtn.className = 'btn btn-small btn-secondary move-down';
            downBtn.textContent = '\u25BC';
            downBtn.setAttribute('aria-label', 'Move field down');

            row.insertBefore(downBtn, removeBtn);
            row.insertBefore(upBtn, downBtn);
        }
        if (!row.querySelector('.drag-handle')) {
            var handle = document.createElement('span');
            handle.className = 'drag-handle';
            handle.textContent = '\u2817';
            handle.setAttribute('aria-label', 'Drag to reorder');
            handle.title = 'Drag to reorder';
            row.insertBefore(handle, row.firstChild);
        }
        makeDraggable(row);
    });

    addBtn.addEventListener('click', function () {
        if (container.querySelectorAll('.custom-field-row').length >= MAX_CUSTOM_FIELDS) {
            showModal('Maximum ' + MAX_CUSTOM_FIELDS + ' custom fields allowed.');
            return;
        }
        container.appendChild(createRow());
        var inputs = container.querySelectorAll('input[name="cf_name"]');
        inputs[inputs.length - 1].focus();
    });

    container.addEventListener('click', function (e) {
        var target = e.target;
        var row = target.closest('.custom-field-row');
        if (!row) return;

        if (target.classList.contains('remove-field')) {
            row.remove();
        } else if (target.classList.contains('move-up')) {
            var prev = row.previousElementSibling;
            if (prev && prev.classList.contains('custom-field-row')) {
                container.insertBefore(row, prev);
            }
        } else if (target.classList.contains('move-down')) {
            var next = row.nextElementSibling;
            if (next && next.classList.contains('custom-field-row')) {
                container.insertBefore(next, row);
            }
        }
    });
})();
