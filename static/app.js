/* hoerbox-feeder front-end: everyday-language status, drag & drop, polling. */
const hoerbox = (function () {
    let selectedChannel = null;
    let pollTimers = [];

    function q(sel) { return document.querySelector(sel); }
    function qa(sel) { return Array.from(document.querySelectorAll(sel)); }
    // Translated strings embedded server-side (see templates/base.html) --
    // falls back to the key itself if a key is somehow missing, same as
    // the Python-side t() helper, so a typo shows up as visible junk text
    // instead of a silent blank. Params use the same {name} placeholder
    // syntax as i18n.t() on the Python side.
    function i18n(key, params) {
        let text = (window.HOERBOX_I18N && window.HOERBOX_I18N[key]) || key;
        if (params) {
            for (const name in params) {
                text = text.split('{' + name + '}').join(params[name]);
            }
        }
        return text;
    }

    // Wrap a title in the language-appropriate quotation marks -- German
    // „low-high", English "curly" -- mirrors app/i18n.py's quote() helper
    // so titles look right regardless of window.HOERBOX_LANG.
    function quote(text) {
        return window.HOERBOX_LANG === 'en' ? '“' + text + '”' : '„' + text + '“';
    }

    // The channel button's display label (a color name, or "Taste N" in the
    // numbered skin — see channel_label() server-side) shown alongside a
    // title so a status/error line makes sense without page context — e.g.
    // in a phone notification or after scrolling away from the color grid.
    function selectedChannelName() {
        const btn = q('.color-btn[data-channel="' + selectedChannel + '"]');
        const nameEl = btn && btn.querySelector('.name');
        return nameEl ? nameEl.textContent : null;
    }

    function titleWithChannel(title) {
        if (!title) return null;
        const channel = selectedChannelName();
        return quote(title) + (channel ? ' (' + channel + ')' : '');
    }

    // ---- Index page --------------------------------------------------------
    function initIndex() {
        const grid = q('#color-grid');
        const addBtn = q('#add-btn');
        const urlInput = q('#url');

        const failedClose = q('#failed-notice-close');
        if (failedClose) {
            failedClose.addEventListener('click', () => {
                q('#failed-notice').hidden = true;
            });
        }
        const unreviewedClose = q('#unreviewed-notice-close');
        if (unreviewedClose) {
            unreviewedClose.addEventListener('click', () => {
                q('#unreviewed-notice').hidden = true;
            });
        }

        // The Start-page notice is a single summary with three bulk actions
        // covering every flagged item at once — individual handling happens
        // per-title in the channel view (reached via /bearbeiten), not here.
        const retryAllBtn = q('#retry-all-btn');
        if (retryAllBtn) retryAllBtn.addEventListener('click', retryAllProblems);
        const findAltAllBtn = q('#find-alt-all-btn');
        if (findAltAllBtn) findAltAllBtn.addEventListener('click', findAlternativeAllProblems);
        const deleteAllBtn = q('#delete-all-btn');
        if (deleteAllBtn) deleteAllBtn.addEventListener('click', deleteAllProblems);

        qa('.color-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                qa('.color-btn').forEach(b => b.classList.remove('selected'));
                btn.classList.add('selected');
                selectedChannel = parseInt(btn.dataset.channel, 10);
                updateAddState();
            });
        });

        urlInput.addEventListener('input', updateAddState);
        addBtn.addEventListener('click', () => submitAdd(false));

        // Clipboard-Button
        const pasteBtn = q('#paste-btn');
        if (pasteBtn) {
            pasteBtn.addEventListener('click', async () => {
                try {
                    const text = await navigator.clipboard.readText();
                    if (text && text.trim()) {
                        urlInput.value = text.trim();
                        updateAddState();
                        urlInput.focus();
                    }
                } catch (e) {
                    // Clipboard-Zugriff verweigert (z.B. kein HTTPS) → Textfeld fokussieren
                    urlInput.focus();
                    urlInput.select();
                }
            });
        }

        const clearBtn = q('#clear-url-btn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                urlInput.value = '';
                updateAddState();
                urlInput.focus();
            });
        }

        function updateAddState() {
            addBtn.disabled = !(urlInput.value.trim() && selectedChannel !== null);
        }

        // Restore ongoing jobs from previous session
        restoreJobsFromStorage();
    }

    async function submitAdd(confirmEvict, evictMode) {
        const url = q('#url').value.trim();
        const statusBox = q('#status');
        const statusText = q('#status-text');
        const progWrap = q('#progress-wrap');
        const retryBtn = q('#retry-btn');

        clearTimers();
        statusBox.hidden = false;
        retryBtn.hidden = true;
        const deleteBtn = q('#delete-btn');
        if (deleteBtn) deleteBtn.hidden = true;
        const statusDetailEl = q('#status-detail');
        if (statusDetailEl) statusDetailEl.hidden = true;
        progWrap.hidden = true;
        statusText.textContent = i18n('js.status.preparing');
        q('#add-btn').disabled = true;

        let res;
        try {
            res = await fetch('/api/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: url, channel: selectedChannel,
                    confirm_evict: !!confirmEvict,
                    evict_mode: evictMode || 'library'
                })
            }).then(r => r.json());
        } catch (e) {
            showError(i18n('js.status.no_connection'), retryBtn, statusText);
            return;
        }

        if (!res.ok) {
            showError(res.message || i18n('js.status.failed'), retryBtn, statusText);
            return;
        }

        if (res.needs_confirmation) {
            showEvictDialog(res.message, (mode) => {
                if (mode) {
                    submitAdd(true, mode);
                } else {
                    // Abbruch: kein Download, keine Änderung.
                    statusBox.hidden = true;
                    resetAddBtn();
                }
            });
            return;
        }

        if (res.duplicate) {
            statusText.textContent = res.message;
            resetAddBtn();
            return;
        }

        if (res.job_ids && res.job_ids.length) {
            // Shows immediately (e.g. "„Füenf – Ein Fest für König Gugubo“:
            // 26 Folgen werden jetzt geladen." for a series add) —
            // otherwise the first poll tick 1.5s later would overwrite it
            // before anyone reads it.
            statusText.textContent = res.message || i18n('js.status.preparing');
            saveJobsToStorage(res.job_ids, 'running', res.series_title);
            pollJobs(res.job_ids, statusText, progWrap, retryBtn, res.series_title);
        } else {
            statusText.textContent = res.message || i18n('js.status.on_player_tomorrow');
            resetAddBtn();
        }
    }

    function pollJobs(jobIds, statusText, progWrap, retryBtn, initialSeriesTitle) {
        progWrap.hidden = false;
        const total = jobIds.length;
        // Mutable, not just the passed-in parameter: if the server response
        // (or a restored localStorage entry) didn't carry a title — e.g. an
        // extractor left the playlist's own title empty — the first status
        // tick's item_title backfills something real instead of the batch
        // staying labelled with the bare, uninformative word "Serie" for its
        // whole run.
        let seriesTitle = initialSeriesTitle || null;
        // Per-job current state, re-derived from every poll tick rather than
        // accumulated with one-way counters — a job can legitimately move
        // active -> backoff -> active again (manual retry) -> done, and the
        // rendered summary always reflects the latest known snapshot instead
        // of a historical count that only ever went up.
        const stateByJob = new Map(jobIds.map(id => [id, 'active']));
        const cancelBtn = q('#cancel-btn');
        const statusDetailEl = q('#status-detail');
        // Which single episode the (single-threaded) worker is actually
        // processing right now, distinct from seriesTitle/the aggregate
        // count above it — line 1 says how far the whole batch has gotten,
        // this is what's happening at this exact moment.
        let currentDetail = null;

        // Show cancel button for ongoing jobs
        if (cancelBtn) {
            cancelBtn.hidden = false;
            cancelBtn.onclick = () => cancelAllJobs(jobIds);
        }

        function counts() {
            const c = { active: 0, backoff: 0, done: 0, failed: 0, cancelled: 0 };
            for (const st of stateByJob.values()) c[st]++;
            return c;
        }

        function renderBatchProgress() {
            const c = counts();
            const label = seriesTitle ? titleWithChannel(seriesTitle) : i18n('js.status.series_label_fallback');
            let msg = i18n('js.status.batch_progress', { label: label, done: c.done, total: total });
            // A job stuck in backoff (erroring, waiting to retry within its
            // ~2h/3-attempt window — see worker.handle_failure) used to be
            // indistinguishable from one still normally downloading, both
            // client-side and in the job_status API response itself. Naming
            // it here is the actual fix for a batch that silently looked
            // frozen while most of its episodes were quietly failing.
            if (c.backoff > 0) {
                msg += ', ' + i18n('js.status.waiting_retry', { n: c.backoff });
            }
            if (c.failed > 0) {
                msg += ', ' + i18n('js.status.finally_unavailable', { n: c.failed });
            }
            statusText.textContent = msg;
            if (statusDetailEl) {
                if (currentDetail && currentDetail.text) {
                    statusDetailEl.textContent = i18n('js.status.current_label') + ' '
                        + (currentDetail.title ? quote(currentDetail.title) + ' – ' : '')
                        + currentDetail.text;
                    statusDetailEl.hidden = false;
                } else {
                    statusDetailEl.hidden = true;
                }
            }
            const finished = c.done + c.failed + c.cancelled;
            q('#progress-bar').style.width = Math.round((finished / total) * 100) + '%';
        }

        function finishBatch() {
            const c = counts();
            if (cancelBtn) cancelBtn.hidden = true;
            if (statusDetailEl) statusDetailEl.hidden = true;
            resetAddBtn();
            saveJobsToStorage(jobIds, 'done');
            if (c.cancelled >= total) {
                statusText.textContent = i18n('js.status.cancelled');
                return;
            }
            q('#progress-bar').style.width = '100%';
            if (c.failed > 0) {
                const label = seriesTitle ? titleWithChannel(seriesTitle) : i18n('js.status.series_label_fallback');
                const failedText = c.failed === 1
                    ? i18n('js.status.failed_episode_one', { n: c.failed })
                    : i18n('js.status.failed_episode_many', { n: c.failed });
                statusText.textContent = i18n('js.status.batch_done_with_failures',
                    { label: label, done: c.done, total: total, failedText: failedText });
            } else {
                statusText.textContent = i18n('js.status.on_player_tomorrow');
            }
        }

        function isBatchDone() {
            const c = counts();
            return c.done + c.failed + c.cancelled >= total;
        }

        jobIds.forEach(id => {
            const timer = setInterval(async () => {
                let s;
                try {
                    s = await fetch('/api/job/' + id + '/status').then(r => r.json());
                } catch (e) { return; }

                if (total === 1) {
                    // Backfill a title the same way the batch branch below
                    // does, so a single add's progress/error line also names
                    // what it's about instead of a bare percentage/reason.
                    if (!seriesTitle && s.item_title) seriesTitle = s.item_title;
                    const prefix = seriesTitle ? titleWithChannel(seriesTitle) + ': ' : '';
                    // job_status() now surfaces the real error text (via
                    // s.text) even while status stays 'queued' during
                    // backoff, so this simple assignment already shows the
                    // actual problem instead of a generic "wird geladen" the
                    // whole time it's retrying.
                    if (s.status === 'done') {
                        clearInterval(timer);
                        q('#progress-bar').style.width = '100%';
                        statusText.textContent = i18n('js.status.on_player_tomorrow');
                        if (cancelBtn) cancelBtn.hidden = true;
                        resetAddBtn();
                        saveJobsToStorage(jobIds, 'done');
                    } else if (s.status === 'failed') {
                        clearInterval(timer);
                        if (cancelBtn) cancelBtn.hidden = true;
                        showError(prefix + i18n('js.status.failed_with_reason', { text: s.text }), retryBtn, statusText, s.item_id, id);
                    } else if (s.status === 'cancelled') {
                        clearInterval(timer);
                        statusText.textContent = i18n('js.status.cancelled');
                        if (cancelBtn) cancelBtn.hidden = true;
                        resetAddBtn();
                    } else {
                        statusText.textContent = prefix + s.text;
                        q('#progress-bar').style.width = (s.progress || 0) + '%';
                    }
                    return;
                }

                // total > 1 only ever happens for a series/playlist add (see
                // add_content) — always re-render from the current snapshot
                // of every job's state instead of showError()-ing on a
                // single failure, which used to clear every pollTimer (not
                // just the failed job's) and could freeze the whole batch's
                // display on a stale "X von Y fertig" the moment a still-
                // running job's already-in-flight status check landed after.
                if (!seriesTitle && s.item_title) {
                    seriesTitle = s.item_title;
                }
                if (s.status === 'done') {
                    stateByJob.set(id, 'done');
                    clearInterval(timer);
                } else if (s.status === 'cancelled') {
                    stateByJob.set(id, 'cancelled');
                    clearInterval(timer);
                } else if (s.status === 'failed') {
                    stateByJob.set(id, 'failed');
                    clearInterval(timer);
                } else if (s.status === 'queued' && s.is_backoff) {
                    stateByJob.set(id, 'backoff');
                    // Keep polling: it may still recover (manual retry
                    // elsewhere) or eventually exhaust into 'failed'.
                } else if (s.status === 'running') {
                    stateByJob.set(id, 'active');
                    // The worker is single-threaded — at most one job is
                    // ever actually 'running' at a time — so this is
                    // unambiguously "what's happening right now" for the
                    // whole batch, not just this one job.
                    currentDetail = { title: s.item_title, text: s.text };
                } else {
                    // Freshly queued, not yet started — no detail to show.
                    stateByJob.set(id, 'active');
                }

                if (isBatchDone()) {
                    finishBatch();
                } else {
                    renderBatchProgress();
                }
            }, 1500);
            pollTimers.push(timer);
        });
    }

    async function cancelAllJobs(jobIds) {
        if (!confirm(i18n('js.confirm.cancel_job'))) return;
        clearTimers();
        for (const id of jobIds) {
            try {
                await fetch('/api/job/' + id, { method: 'DELETE' });
            } catch (e) { /* ignore */ }
        }
        const cancelBtn = q('#cancel-btn');
        if (cancelBtn) cancelBtn.hidden = true;
        q('#status-text').textContent = i18n('js.status.cancelled');
        resetAddBtn();
        clearJobsFromStorage(jobIds);
    }

    function showEvictDialog(message, onChoice, hideDelete) {
        const dialog = q('#evict-dialog');
        const libraryBtn = q('#evict-library-btn');
        const deleteBtn = q('#evict-delete-btn');
        const cancelBtn = q('#evict-cancel-btn');
        q('#evict-message').textContent = message;
        deleteBtn.hidden = !!hideDelete;
        dialog.hidden = false;

        function cleanup() {
            dialog.hidden = true;
            deleteBtn.hidden = false;
            libraryBtn.onclick = null;
            deleteBtn.onclick = null;
            cancelBtn.onclick = null;
        }
        libraryBtn.onclick = () => { cleanup(); onChoice('library'); };
        deleteBtn.onclick = () => {
            if (!confirm(i18n('js.confirm.delete_forever'))) return;
            cleanup();
            onChoice('delete');
        };
        cancelBtn.onclick = () => { cleanup(); onChoice(null); };
    }

    function showError(msg, retryBtn, statusText, itemId, jobId) {
        clearTimers();
        statusText.textContent = msg;
        retryBtn.hidden = false;
        const deleteBtn = q('#delete-btn');
        if (itemId) {
            // Item/Job already exist — resubmitting the form would just hit the
            // duplicate-URL check and silently do nothing. Retry the same item instead.
            retryBtn.onclick = async () => {
                retryBtn.disabled = true;
                try {
                    await fetch('/api/item/' + itemId + '/retry', { method: 'POST' });
                } catch (e) { /* ignore */ }
                retryBtn.hidden = true;
                retryBtn.disabled = false;
                if (deleteBtn) deleteBtn.hidden = true;
                const progWrap = q('#progress-wrap');
                pollJobs([jobId], statusText, progWrap, retryBtn);
            };
            // The automatic retry+alternative-source pipeline (see
            // worker.handle_failure) has already run its course by the time
            // a single add reaches this terminal state — this is the "inform
            // the user, offer Wiederholen/Löschen" prompt for that moment.
            if (deleteBtn) {
                deleteBtn.hidden = false;
                deleteBtn.onclick = async () => {
                    if (!confirm(i18n('js.confirm.delete_entry'))) return;
                    deleteBtn.disabled = true;
                    try {
                        await fetch('/api/item/' + itemId, { method: 'DELETE' });
                    } catch (e) { /* ignore */ }
                    deleteBtn.hidden = true;
                    deleteBtn.disabled = false;
                    retryBtn.hidden = true;
                    statusText.textContent = i18n('js.status.entry_deleted');
                    clearJobsFromStorage([jobId]);
                    resetAddBtn();
                };
            }
        } else {
            // Failure happened before any item/job was created (e.g. analyze()
            // failed) — resubmitting the whole form is the correct retry, and
            // there's nothing to delete yet.
            retryBtn.onclick = () => submitAdd(false);
            if (deleteBtn) deleteBtn.hidden = true;
        }
        resetAddBtn();
    }

    function resetAddBtn() {
        const addBtn = q('#add-btn');
        if (addBtn) addBtn.disabled = false;
    }

    function clearTimers() {
        pollTimers.forEach(t => clearInterval(t));
        pollTimers = [];
    }

    // ---- Persistent status (localStorage) ----------------------------------
    function saveJobsToStorage(jobIds, status, seriesTitle) {
        try {
            localStorage.setItem('hoerbox_jobs', JSON.stringify({
                ids: jobIds, status: status, channel: selectedChannel, seriesTitle: seriesTitle || null
            }));
        } catch (e) { /* ignore */ }
    }

    function clearJobsFromStorage(jobIds) {
        try {
            const stored = localStorage.getItem('hoerbox_jobs');
            if (stored) {
                const data = JSON.parse(stored);
                if (JSON.stringify(data.ids) === JSON.stringify(jobIds)) {
                    localStorage.removeItem('hoerbox_jobs');
                }
            }
        } catch (e) { /* ignore */ }
    }

    function restoreJobsFromStorage() {
        try {
            const stored = localStorage.getItem('hoerbox_jobs');
            if (!stored) return;
            const data = JSON.parse(stored);
            if (data.status === 'done') {
                localStorage.removeItem('hoerbox_jobs');
                return;
            }
            // Resume polling
            const statusBox = q('#status');
            const statusText = q('#status-text');
            const progWrap = q('#progress-wrap');
            const retryBtn = q('#retry-btn');

            if (statusBox && statusText && progWrap) {
                selectedChannel = data.channel;
                statusBox.hidden = false;
                pollJobs(data.ids, statusText, progWrap, retryBtn, data.seriesTitle);
            }
        } catch (e) { /* ignore */ }
    }

    // ---- Channel page ------------------------------------------------------
    function initChannel(channelId) {
        const list = q('#item-list');
        if (list && window.Sortable) {
            Sortable.create(list, {
                handle: '.outer-handle',
                animation: 150,
                onEnd: () => saveBlockOrder(channelId)
            });
        }

        qa('.block-toggle').forEach(btn => {
            btn.addEventListener('click', () => toggleBlock(btn));
        });

        // Blocks render expanded by default (server-side) — the inner
        // Sortable is normally only created lazily on first expand-click,
        // so wire it up here too for whatever's already open on page load.
        qa('.sub-item-list').forEach(inner => {
            if (!inner.hidden && !inner.dataset.sortableInit && window.Sortable) {
                Sortable.create(inner, {
                    handle: '.inner-handle',
                    animation: 150,
                    onEnd: () => saveSubOrder(inner.dataset.subId)
                });
                inner.dataset.sortableInit = '1';
            }
        });

        qa('.del-btn').forEach(btn => {
            btn.addEventListener('click', () => deleteItem(btn.dataset.id));
        });

        qa('.retry-now-btn').forEach(btn => {
            btn.addEventListener('click', () => retryItem(btn.dataset.id));
        });
        qa('.find-alt-btn').forEach(btn => {
            btn.addEventListener('click', () => findAlternative(btn.dataset.id));
        });
        qa('.search-alt-btn').forEach(btn => {
            btn.addEventListener('click', () => toggleAltSearchPanel(btn.dataset.id));
        });
        qa('.confirm-alt-btn').forEach(btn => {
            btn.addEventListener('click', () => confirmAlternative(btn.dataset.id));
        });
        qa('.play-btn').forEach(btn => {
            btn.addEventListener('click', () => togglePlayback(btn, btn.dataset.url));
        });
        qa('.alt-search-go-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const panel = q('.alt-search-panel[data-id="' + btn.dataset.id + '"]');
                const input = panel && panel.querySelector('.alt-search-input');
                runAltSearch(btn.dataset.id, input ? input.value.trim() : '');
            });
        });
        // Result cards are rendered after a search, long after this wiring
        // pass ran -- delegate from the list container instead of binding
        // per-button.
        if (list) {
            list.addEventListener('click', (e) => {
                const pickBtn = e.target.closest('.alt-candidate-pick-btn');
                if (pickBtn) pickAlternative(pickBtn.dataset.id, pickBtn.dataset.url);
            });
        }

        qa('.item-to-library').forEach(btn => {
            btn.addEventListener('click', () => parkItem(btn.dataset.id));
        });
        qa('.block-to-library').forEach(btn => {
            btn.addEventListener('click', () => parkBlock(btn.dataset.subId));
        });
        qa('.item-move-btn').forEach(btn => {
            btn.addEventListener('click', () => moveItem(btn));
        });
        qa('.block-move-btn').forEach(btn => {
            btn.addEventListener('click', () => moveBlock(btn));
        });
        qa('.block-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => deleteBlock(btn.dataset.subId));
        });
        qa('.block-rename-btn').forEach(btn => {
            btn.addEventListener('click', () => renameBlock(btn.dataset.subId));
        });

        const abo = q('#abo-toggle');
        if (abo) {
            abo.addEventListener('change', () => toggleAbo(channelId, abo.checked));
        }

        const delAllBtn = q('.delete-all-btn');
        if (delAllBtn) {
            delAllBtn.addEventListener('click', () => deleteAllFiles(delAllBtn.dataset.channel));
        }

        const parkAllBtn = q('.park-all-btn');
        if (parkAllBtn) {
            parkAllBtn.addEventListener('click', () => parkAllToLibrary(parkAllBtn.dataset.channel));
        }
    }

    function toggleBlock(btn) {
        const li = btn.closest('.block');
        const inner = li.querySelector('.sub-item-list');
        const expand = inner.hidden;
        inner.hidden = !expand;
        btn.setAttribute('aria-expanded', String(expand));
        btn.textContent = expand ? '▾' : '▸';
        if (expand && !inner.dataset.sortableInit && window.Sortable) {
            Sortable.create(inner, {
                handle: '.inner-handle',
                animation: 150,
                onEnd: () => saveSubOrder(inner.dataset.subId)
            });
            inner.dataset.sortableInit = '1';
        }
    }

    async function saveBlockOrder(channelId) {
        const order = qa('#item-list > .item').map(li => {
            if (li.classList.contains('block')) {
                return { type: 'block', subscription_id: parseInt(li.dataset.subId, 10) };
            }
            return { type: 'single', item_id: parseInt(li.dataset.id, 10) };
        });
        try {
            const res = await fetch('/api/kanal/' + channelId + '/reorder-blocks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ order: order })
            }).then(r => r.json());
            toast(res.message || i18n('js.status.order_saved'));
        } catch (e) {
            toast(i18n('js.toast.could_not_save'));
        }
    }

    async function saveSubOrder(subId) {
        const order = qa('.sub-item-list[data-sub-id="' + subId + '"] .sub-item')
            .map(li => parseInt(li.dataset.id, 10));
        try {
            const res = await fetch('/api/subscription/' + subId + '/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ order: order })
            }).then(r => r.json());
            toast(res.message || i18n('js.status.order_saved'));
        } catch (e) {
            toast(i18n('js.toast.could_not_save'));
        }
    }

    async function retryItem(itemId) {
        try {
            const res = await fetch('/api/item/' + itemId + '/retry', { method: 'POST' }).then(r => r.json());
            toast(res.message);
            if (res.ok) location.reload();
        } catch (e) {
            toast(i18n('js.toast.could_not_retry'));
        }
    }

    async function findAlternative(itemId) {
        try {
            const res = await fetch('/api/item/' + itemId + '/find-alternative', { method: 'POST' }).then(r => r.json());
            toast(res.message);
            if (res.ok) location.reload();
        } catch (e) {
            toast(i18n('js.toast.could_not_find_alt'));
        }
    }

    // ---- Play/Stop fürs ganze Stück -----------------------------------------
    // Nur ein Titel spielt gleichzeitig -- ein neuer Start stoppt den laufenden.
    let activeAudio = null;
    let activeBtn = null;

    function stopPlayback() {
        if (activeAudio) {
            activeAudio.pause();
            activeAudio = null;
        }
        if (activeBtn) {
            activeBtn.textContent = '▶';
            activeBtn = null;
        }
    }

    function togglePlayback(btn, url) {
        const wasThisOne = activeBtn === btn;
        stopPlayback();
        if (wasThisOne) return; // zweiter Klick auf denselben Button stoppt nur

        const audio = new Audio(url);
        audio.addEventListener('ended', stopPlayback);
        audio.play().catch(() => {
            toast(i18n('js.toast.could_not_play'));
            stopPlayback();
        });
        activeAudio = audio;
        activeBtn = btn;
        btn.textContent = '⏸';
    }

    // Löschen/Verschieben entfernt nur den DOM-Knoten -- die Audio-Wiedergabe
    // läuft unabhängig davon weiter, wenn sie nicht explizit gestoppt wird.
    function removeRow(el) {
        if (!el) return;
        if (activeBtn && el.contains(activeBtn)) stopPlayback();
        el.remove();
    }

    // ---- Manual "Selbst suchen" search-and-pick panel ----------------------
    function toggleAltSearchPanel(itemId) {
        const panel = q('.alt-search-panel[data-id="' + itemId + '"]');
        if (panel) panel.hidden = !panel.hidden;
    }

    function renderAltCandidate(itemId, c) {
        const card = document.createElement('div');
        card.className = 'alt-candidate';
        if (c.thumbnail_url) {
            const img = document.createElement('img');
            img.src = c.thumbnail_url;
            img.alt = '';
            card.appendChild(img);
        }
        const info = document.createElement('div');
        info.className = 'alt-candidate-info';
        const title = document.createElement('div');
        title.className = 'alt-candidate-title';
        title.textContent = c.title;
        info.appendChild(title);
        const meta = document.createElement('div');
        meta.className = 'alt-candidate-meta';
        const mins = c.duration_seconds ? Math.round(c.duration_seconds / 60) + ' ' + i18n('js.candidate.minutes') : '';
        meta.textContent = [c.uploader, mins].filter(Boolean).join(' · ');
        info.appendChild(meta);
        card.appendChild(info);
        const pickBtn = document.createElement('button');
        pickBtn.type = 'button';
        pickBtn.className = 'alt-candidate-pick-btn';
        pickBtn.dataset.id = itemId;
        pickBtn.dataset.url = c.url;
        pickBtn.textContent = i18n('js.candidate.pick');
        card.appendChild(pickBtn);
        return card;
    }

    async function runAltSearch(itemId, query) {
        const resultsEl = q('.alt-search-results[data-id="' + itemId + '"]');
        if (!resultsEl || !query) return;
        resultsEl.innerHTML = '<p class="alt-search-empty">' + i18n('js.toast.search_running') + '</p>';
        let res;
        try {
            res = await fetch('/api/item/' + itemId + '/search-alternative', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: query })
            }).then(r => r.json());
        } catch (e) {
            resultsEl.innerHTML = '<p class="alt-search-empty">' + i18n('js.toast.search_failed') + '</p>';
            return;
        }
        resultsEl.innerHTML = '';
        if (!res.ok || !res.candidates || !res.candidates.length) {
            const p = document.createElement('p');
            p.className = 'alt-search-empty';
            p.textContent = (res && res.message) || i18n('js.toast.no_results');
            resultsEl.appendChild(p);
            return;
        }
        res.candidates.forEach(c => resultsEl.appendChild(renderAltCandidate(itemId, c)));
    }

    async function pickAlternative(itemId, url) {
        try {
            const res = await fetch('/api/item/' + itemId + '/pick-alternative', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            }).then(r => r.json());
            toast(res.message);
            if (res.ok) location.reload();
        } catch (e) {
            toast(i18n('js.toast.could_not_apply'));
        }
    }

    async function confirmAlternative(itemId) {
        try {
            const res = await fetch('/api/item/' + itemId + '/confirm-alternative', { method: 'POST' }).then(r => r.json());
            toast(res.message);
            if (res.ok) location.reload();
        } catch (e) {
            toast(i18n('js.toast.could_not_confirm'));
        }
    }

    // ---- Start page: bulk actions on every currently flagged item ---------
    async function retryAllProblems() {
        try {
            const res = await fetch('/api/problems/retry-all', { method: 'POST' }).then(r => r.json());
            toast(res.message);
            if (res.ok) location.reload();
        } catch (e) {
            toast(i18n('js.toast.could_not_retry'));
        }
    }

    async function findAlternativeAllProblems() {
        try {
            const res = await fetch('/api/problems/find-alternative-all', { method: 'POST' }).then(r => r.json());
            toast(res.message);
            if (res.ok) location.reload();
        } catch (e) {
            toast(i18n('js.toast.could_not_find_alt'));
        }
    }

    async function deleteAllProblems() {
        if (!confirm(i18n('js.confirm.delete_all_problems'))) return;
        try {
            const res = await fetch('/api/problems/delete-all', { method: 'DELETE' }).then(r => r.json());
            toast(res.message);
            if (res.ok) location.reload();
        } catch (e) {
            toast(i18n('js.toast.could_not_delete'));
        }
    }

    async function parkItem(itemId) {
        if (!confirm(i18n('js.confirm.park_item'))) return;
        try {
            const res = await fetch('/api/item/' + itemId + '/park', { method: 'POST' }).then(r => r.json());
            toast(res.message);
            if (res.ok) {
                const li = document.querySelector('.item.single[data-id="' + itemId + '"]');
                removeRow(li);
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_move'));
        }
    }

    async function parkBlock(subId) {
        if (!confirm(i18n('js.confirm.park_block'))) return;
        try {
            const res = await fetch('/api/subscription/' + subId + '/park', { method: 'POST' }).then(r => r.json());
            toast(res.message);
            if (res.ok) {
                const li = document.querySelector('.item.block[data-sub-id="' + subId + '"]');
                removeRow(li);
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_move'));
        }
    }

    async function deleteBlock(subId) {
        if (!confirm(i18n('js.confirm.delete_block'))) return;
        try {
            const res = await fetch('/api/subscription/' + subId, { method: 'DELETE' }).then(r => r.json());
            toast(res.message);
            if (res.ok) {
                const li = document.querySelector('.item.block[data-sub-id="' + subId + '"]');
                removeRow(li);
                const card = document.querySelector('.library-card [data-sub-id="' + subId + '"]');
                if (card) setTimeout(() => location.reload(), 800);
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_delete'));
        }
    }

    async function renameBlock(subId) {
        const li = document.querySelector('.item.block[data-sub-id="' + subId + '"]');
        const titleEl = li ? li.querySelector('.item-title') : null;
        const next = prompt(i18n('js.prompt.rename_title'), titleEl ? titleEl.textContent : '');
        if (next === null) return;  // cancelled
        const title = next.trim();
        if (!title) return;
        try {
            const res = await fetch('/api/subscription/' + subId + '/rename', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: title })
            }).then(r => r.json());
            toast(res.message);
            if (res.ok && titleEl) {
                titleEl.textContent = res.title;
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_save'));
        }
    }

    async function moveItem(btn) {
        const select = document.querySelector('.item-channel-select[data-id="' + btn.dataset.id + '"]');
        const channelId = select.value;
        if (!channelId) { toast(i18n('js.toast.pick_channel_first')); return; }
        try {
            const res = await fetch('/api/item/' + btn.dataset.id + '/assign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: parseInt(channelId, 10) })
            }).then(r => r.json());
            toast(res.message);
            if (res.ok) {
                const li = document.querySelector('.item.single[data-id="' + btn.dataset.id + '"]');
                removeRow(li);
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_move'));
        }
    }

    async function moveBlock(btn) {
        const select = document.querySelector('.block-channel-select[data-sub-id="' + btn.dataset.subId + '"]');
        const channelId = select.value;
        if (!channelId) { toast(i18n('js.toast.pick_channel_first')); return; }
        try {
            const res = await fetch('/api/subscription/' + btn.dataset.subId + '/assign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: parseInt(channelId, 10) })
            }).then(r => r.json());
            toast(res.message);
            if (res.ok) {
                const li = document.querySelector('.item.block[data-sub-id="' + btn.dataset.subId + '"]');
                removeRow(li);
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_move'));
        }
    }

    async function deleteItem(itemId) {
        if (!confirm(i18n('js.confirm.delete_entry'))) return;
        try {
            const res = await fetch('/api/item/' + itemId, { method: 'DELETE' }).then(r => r.json());
            if (res.ok) {
                const li = document.querySelector('.item[data-id="' + itemId + '"]');
                removeRow(li);
                toast(i18n('js.status.entry_deleted'));
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_delete'));
        }
    }

    // ---- Bibliothek page ----------------------------------------------------
    function initBibliothek() {
        qa('.del-btn').forEach(btn => {
            btn.addEventListener('click', () => deleteItem(btn.dataset.id));
        });
        qa('.lib-item-move-btn').forEach(btn => {
            btn.addEventListener('click', () => libMoveItem(btn));
        });
        qa('.lib-block-move-btn').forEach(btn => {
            btn.addEventListener('click', () => libMoveBlock(btn));
        });
        qa('.block-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => deleteBlock(btn.dataset.subId));
        });
        qa('.lib-block-toggle').forEach(btn => {
            btn.addEventListener('click', () => toggleLibraryBlock(btn));
        });
        qa('.play-btn').forEach(btn => {
            btn.addEventListener('click', () => togglePlayback(btn, btn.dataset.url));
        });
    }

    function toggleLibraryBlock(btn) {
        const card = btn.closest('.library-card');
        const inner = card.querySelector('.library-sub-list');
        const expand = inner.hidden;
        inner.hidden = !expand;
        btn.setAttribute('aria-expanded', String(expand));
        btn.textContent = expand ? '▾' : '▸';
    }

    async function libMoveItem(btn) {
        const select = document.querySelector('.lib-item-channel-select[data-id="' + btn.dataset.id + '"]');
        const channelId = select.value;
        if (!channelId) { toast(i18n('js.toast.pick_channel_first')); return; }
        try {
            const res = await fetch('/api/item/' + btn.dataset.id + '/assign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: parseInt(channelId, 10) })
            }).then(r => r.json());
            toast(res.message);
            if (res.ok) setTimeout(() => location.reload(), 800);
        } catch (e) {
            toast(i18n('js.toast.could_not_move'));
        }
    }

    async function libMoveBlock(btn) {
        const select = document.querySelector('.lib-block-channel-select[data-sub-id="' + btn.dataset.subId + '"]');
        const channelId = select.value;
        if (!channelId) { toast(i18n('js.toast.pick_channel_first')); return; }
        try {
            const res = await fetch('/api/subscription/' + btn.dataset.subId + '/assign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: parseInt(channelId, 10) })
            }).then(r => r.json());
            toast(res.message);
            if (res.ok) setTimeout(() => location.reload(), 800);
        } catch (e) {
            toast(i18n('js.toast.could_not_move'));
        }
    }

    async function toggleAbo(channelId, enabled) {
        try {
            const res = await fetch('/api/kanal/' + channelId + '/abo-toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: enabled })
            }).then(r => r.json());
            toast(res.message);
        } catch (e) {
            toast(i18n('js.toast.could_not_change'));
        }
    }

    function toast(msg) {
        const el = q('#toast');
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        setTimeout(() => { el.hidden = true; }, 2500);
    }

    // ---- Belegung page -----------------------------------------------------
    function initBelegung() {
        qa('.del-file-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const channel = btn.dataset.channel;
                const filename = btn.dataset.filename;
                deleteFile(channel, filename, btn);
            });
        });

        qa('.delete-all-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const channel = btn.dataset.channel;
                deleteAllFiles(channel);
            });
        });

        qa('.play-btn').forEach(btn => {
            btn.addEventListener('click', () => togglePlayback(btn, btn.dataset.url));
        });
    }

    async function deleteFile(channelId, filename, btn) {
        if (!confirm(i18n('js.confirm.delete_file', { filename: filename }))) return;
        try {
            const res = await fetch(`/api/audio/${channelId}/${encodeURIComponent(filename)}`, {
                method: 'DELETE'
            }).then(r => r.json());
            if (res.ok) {
                const li = btn.closest('.file-item');
                removeRow(li);
                toast(i18n('js.status.file_deleted'));
                // Reload to update counts
                setTimeout(() => location.reload(), 1000);
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_delete'));
        }
    }

    async function parkAllToLibrary(channelId) {
        if (!confirm(i18n('js.confirm.park_all_channel'))) return;
        try {
            const res = await fetch(`/api/kanal/${channelId}/park`, { method: 'POST' }).then(r => r.json());
            toast(res.message);
            if (res.ok) setTimeout(() => location.reload(), 1000);
        } catch (e) {
            toast(i18n('js.toast.could_not_move'));
        }
    }

    async function deleteAllFiles(channelId) {
        if (!confirm(i18n('js.confirm.delete_all_files'))) return;
        try {
            const res = await fetch(`/api/audio/${channelId}`, { method: 'DELETE' }).then(r => r.json());
            if (res.ok) {
                if (activeBtn && activeBtn.dataset.url && activeBtn.dataset.url.startsWith(`/audio/${channelId}/`)) {
                    stopPlayback();
                }
                toast(res.message);
                setTimeout(() => location.reload(), 1000);
            }
        } catch (e) {
            toast(i18n('js.toast.could_not_delete'));
        }
    }

    // ---- Setup page: Knopf aktiv/inaktiv --------------------------------
    function initSetup() {
        qa('.channel-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const channelId = btn.dataset.channel;
                const isActive = btn.dataset.active === '1';
                toggleChannelActive(channelId, !isActive);
            });
        });
    }

    async function toggleChannelActive(channelId, active, moveToLibrary) {
        const res = await fetch('/api/kanal/' + channelId + '/set-active', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active: active, move_to_library: !!moveToLibrary })
        }).then(r => r.json());
        if (res.needs_confirmation) {
            showEvictDialog(res.message, mode => {
                if (mode === 'library') toggleChannelActive(channelId, false, true);
            }, true);
            return;
        }
        location.reload();
    }

    return { initIndex, initChannel, initBelegung, initBibliothek, initSetup };
})();
