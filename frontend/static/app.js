'use strict';

const app = (() => {
  let sessionId = null;
  let eventSource = null;
  let pendingChangeId = null;
  let buttonsEnabled = false;
  let currentPassNumber = 0;
  let currentPassTotal = 0;
  let currentPassAccepted = 0;
  let sessions = [];

  // ── DOM helpers ────────────────────────────────────────────────────────────
  const $ = id => document.getElementById(id);

  function show(id) { $(id).classList.remove('hidden'); }
  function hide(id) { $(id).classList.add('hidden'); }
  function text(id, val) { $(id).textContent = val; }
  function html(id, val) { $(id).innerHTML = val; }

  // ── Session panel activation ───────────────────────────────────────────────
  function activateSessionPanel(sid, filename, status) {
    sessionId = sid;
    hide('welcome-panel');
    show('session-panel');
    text('session-filename', filename);
    text('session-status-badge', status);
  }

  // ── File upload ────────────────────────────────────────────────────────────
  async function uploadFile(file) {
    if (!file) return;
    const statusEl = $('upload-status');
    statusEl.classList.remove('hidden');
    statusEl.textContent = `Uploading ${file.name}…`;

    const form = new FormData();
    form.append('file', file);

    try {
      const res = await fetch('/sessions', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      statusEl.textContent = 'Upload complete. Starting agent…';

      activateSessionPanel(data.session_id, data.filename, data.status);
      await loadSessionList();
      openStream(data.session_id);
    } catch (err) {
      statusEl.textContent = `Upload failed: ${err.message}`;
    }
  }

  // ── Drag & drop ────────────────────────────────────────────────────────────
  function initDragDrop() {
    const zone = $('drop-zone');
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('border-indigo-500'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('border-indigo-500'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('border-indigo-500');
      const file = e.dataTransfer.files[0];
      if (file) uploadFile(file);
    });
  }

  // ── SSE stream ─────────────────────────────────────────────────────────────
  function openStream(sid) {
    if (eventSource) eventSource.close();

    const url = `/sessions/${sid}/stream`;
    eventSource = new EventSource(url);

    const handlers = {
      status:        onStatus,
      voice:         onVoice,
      pass_start:    onPassStart,
      change:        onChange,
      decision:      onDecision,
      pass_complete: onPassComplete,
      audit_start:   onAuditStart,
      complete:      onComplete,
      error:         onError,
    };

    for (const [evt, fn] of Object.entries(handlers)) {
      eventSource.addEventListener(evt, e => fn(JSON.parse(e.data)));
    }

    eventSource.onerror = () => {
      // SSE reconnects automatically; nothing to do here
    };
  }

  // ── Event handlers ─────────────────────────────────────────────────────────
  function onStatus({ phase, message }) {
    text('session-status-badge', phase);
    showStatus(message || phase);
  }

  function onVoice(fp) {
    hideStatus();
    show('voice-card');
    text('voice-summary', fp.raw_summary || '');

    const stats = [
      ['Avg sentence length', `${fp.avg_sentence_length?.toFixed(1) ?? '—'} words`],
      ['Short sentences', `${((fp.short_sentence_ratio ?? 0) * 100).toFixed(0)}%`],
      ['Long sentences', `${((fp.long_sentence_ratio ?? 0) * 100).toFixed(0)}%`],
      ['Vocabulary richness', `${((fp.vocabulary_richness ?? 0) * 100).toFixed(0)}%`],
      ['Dialogue ratio', `${((fp.dialogue_ratio ?? 0) * 100).toFixed(0)}%`],
      ['POV', (fp.pov_pronouns ?? []).join(', ') || '—'],
    ];
    html('voice-stats', stats.map(([k, v]) =>
      `<div class="bg-gray-50 rounded p-2"><div class="text-xs text-gray-400">${k}</div><div class="font-medium text-sm">${v}</div></div>`
    ).join(''));

    if (fp.signature_phrases?.length) {
      html('voice-phrases',
        `<div class="text-xs text-gray-400 mb-1">Signature phrases</div>` +
        fp.signature_phrases.map(p =>
          `<span class="inline-block bg-indigo-50 text-indigo-700 text-xs px-2 py-0.5 rounded mr-1 mb-1">${escHtml(p)}</span>`
        ).join('')
      );
    }
  }

  function onPassStart({ pass, name, total_passes }) {
    currentPassNumber = pass;
    currentPassTotal = 0;
    currentPassAccepted = 0;
    text('session-status-badge', `Pass ${pass}: ${name}`);
    showStatus(`Pass ${pass} of ${total_passes}: ${name}…`);
    show('progress-bar-wrap');
    text('progress-label', `Pass ${pass}/${total_passes}`);
    setProgress(0, 0, 0);
    hide('pass-complete-card');
  }

  function onChange(change) {
    hideStatus();
    hide('waiting-card');
    hide('pass-complete-card');

    pendingChangeId = change.change_id;
    currentPassTotal = change.total_in_pass ?? currentPassTotal;
    const idx = change.index_in_pass ?? 0;

    // Pass badge
    const passLabel = change.pass_number === 4 ? 'Audit' : `Pass ${change.pass_number}`;
    text('change-pass-badge', passLabel);
    text('change-principle-badge', change.craft_principle || '');
    text('change-index-label', `${idx + 1} / ${currentPassTotal}`);
    text('change-rationale', change.rationale || '');

    // Before / After
    html('change-before', escHtml(change.original || ''));
    html('change-after', change.inline_diff_html || escHtml(change.proposed || ''));

    // Voice alert
    if (change.voice_alert) {
      show('voice-alert-badge');
      $('change-card').classList.add('voice-alert-card');
    } else {
      hide('voice-alert-badge');
      $('change-card').classList.remove('voice-alert-card');
    }

    setProgress(idx, currentPassTotal, currentPassAccepted);

    show('change-card');
    enableButtons(true);
    $('change-card').classList.remove('fade-in');
    void $('change-card').offsetWidth;
    $('change-card').classList.add('fade-in');
  }

  function onDecision({ change_id, status }) {
    if (status === 'accepted') currentPassAccepted++;
    enableButtons(false);
    hide('change-card');
    show('waiting-card');
  }

  function onPassComplete({ pass, name, pass_summary, accepted, total }) {
    hide('waiting-card');
    hide('change-card');

    text('pass-complete-title', `Pass ${pass} complete — ${name}`);
    text('pass-complete-summary', pass_summary || '');
    text('pass-complete-stats', `${accepted} of ${total} changes accepted`);
    show('pass-complete-card');

    setProgress(total, total, accepted);
    showStatus(`Starting Pass ${pass + 1}…`);
  }

  function onAuditStart({ message }) {
    text('session-status-badge', 'Audit');
    showStatus(message || 'Running humanizer audit…');
    text('progress-label', 'Audit');
    setProgress(0, 0, 0);
  }

  function onComplete({ final_text, stats }) {
    if (eventSource) eventSource.close();
    hide('waiting-card');
    hide('change-card');
    hide('status-msg');
    hide('progress-bar-wrap');

    text('session-status-badge', 'complete');
    text('complete-stats',
      `${stats.total_accepted ?? 0} of ${stats.total_changes_proposed ?? 0} changes accepted`
    );
    show('complete-card');
    show('download-btn');
    loadSessionList();
  }

  function onError({ message }) {
    hideStatus();
    showStatus(`Error: ${message}`);
  }

  // ── Decisions ──────────────────────────────────────────────────────────────
  async function decide(status) {
    if (!buttonsEnabled || !pendingChangeId) return;
    enableButtons(false);
    try {
      await fetch(`/sessions/${sessionId}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ change_id: pendingChangeId, status }),
      });
    } catch (err) {
      console.error('Decision failed', err);
    }
  }

  async function skipPass() {
    try {
      await fetch(`/sessions/${sessionId}/skip_pass`, { method: 'POST' });
    } catch (err) {
      console.error('Skip pass failed', err);
    }
  }

  // ── Download ───────────────────────────────────────────────────────────────
  function downloadResult() {
    if (!sessionId) return;
    const a = document.createElement('a');
    a.href = `/sessions/${sessionId}/download`;
    a.click();
  }

  // ── Session list ───────────────────────────────────────────────────────────
  async function loadSessionList() {
    try {
      const res = await fetch('/sessions');
      sessions = await res.json();
      renderSessionList();
    } catch (_) {}
  }

  function renderSessionList() {
    const ul = $('session-list');
    ul.innerHTML = '';
    for (const s of sessions) {
      const li = document.createElement('li');
      const isActive = s.session_id === sessionId;
      li.className = `flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer text-sm transition-colors ${isActive ? 'bg-indigo-50 text-indigo-700' : 'hover:bg-gray-100 text-gray-700'}`;
      li.innerHTML = `
        <span class="w-2 h-2 rounded-full flex-shrink-0 ${statusColor(s.status)}"></span>
        <span class="truncate flex-1" title="${escHtml(s.filename)}">${escHtml(s.filename)}</span>
        <button class="text-gray-300 hover:text-red-400 transition-colors text-xs" onclick="app.removeSession('${s.session_id}', event)">✕</button>
      `;
      li.addEventListener('click', () => loadExistingSession(s.session_id));
      ul.appendChild(li);
    }
  }

  async function loadExistingSession(sid) {
    if (sid === sessionId) return;
    try {
      const res = await fetch(`/sessions/${sid}`);
      const data = await res.json();
      activateSessionPanel(data.session_id, data.filename, data.status);
      renderSessionList();

      // Reset UI state
      hide('voice-card');
      hide('change-card');
      hide('waiting-card');
      hide('pass-complete-card');
      hide('complete-card');
      hide('download-btn');
      hide('progress-bar-wrap');
      hideStatus();

      if (data.status === 'complete') {
        text('complete-stats', '');
        show('complete-card');
        show('download-btn');
      } else if (data.status !== 'uploaded') {
        openStream(sid);
      }
    } catch (err) {
      console.error('Load session failed', err);
    }
  }

  async function removeSession(sid, e) {
    e.stopPropagation();
    if (!confirm('Delete this session?')) return;
    await fetch(`/sessions/${sid}`, { method: 'DELETE' });
    if (sid === sessionId) {
      sessionId = null;
      show('welcome-panel');
      hide('session-panel');
    }
    await loadSessionList();
  }

  // ── Voice fingerprint toggle ───────────────────────────────────────────────
  function toggleVoice() {
    const body = $('voice-body');
    const chevron = $('voice-chevron');
    body.classList.toggle('hidden');
    chevron.style.transform = body.classList.contains('hidden') ? '' : 'rotate(180deg)';
  }

  // ── UI helpers ─────────────────────────────────────────────────────────────
  function showStatus(msg) {
    text('status-msg-text', msg);
    show('status-msg');
    $('status-msg').classList.add('flex');
  }

  function hideStatus() {
    hide('status-msg');
    $('status-msg').classList.remove('flex');
  }

  function setProgress(done, total, accepted) {
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    $('progress-bar').style.width = `${pct}%`;
    text('progress-count', total > 0 ? `${done}/${total}` : '');
  }

  function enableButtons(enabled) {
    buttonsEnabled = enabled;
    $('accept-btn').disabled = !enabled;
    $('reject-btn').disabled = !enabled;
  }

  function statusColor(status) {
    const map = {
      uploaded: 'bg-gray-400',
      analyzing: 'bg-blue-400',
      pass1: 'bg-indigo-400',
      pass2: 'bg-purple-400',
      pass3: 'bg-pink-400',
      audit: 'bg-amber-400',
      complete: 'bg-green-500',
    };
    return map[status] || 'bg-gray-300';
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    initDragDrop();
    loadSessionList();
  });

  return {
    uploadFile,
    decide,
    skipPass,
    downloadResult,
    loadSessionList,
    removeSession,
    toggleVoice,
  };
})();
