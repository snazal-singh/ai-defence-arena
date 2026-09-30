'use strict';
/* ============================================================
   icarKno™ – Security Arena Playground Logic
   Universal Pluggable Red Team Playground + Ingestion + Telemetry
   ============================================================ */

const API = '/api/v1/redteam';
const $ = id => document.getElementById(id);

const CHALLENGES = [
  { id: 'open', title: 'Instruction Override', owasp: 'LLM01', desc: 'Try classic instruction-override prompts to bypass core safety rules.' },
  { id: 'system-prompt', title: 'System Prompt Extraction', owasp: 'LLM07', desc: 'Attempt to make the AI reveal its hidden developer instructions.' },
  { id: 'jailbreak', title: 'Classic Jailbreak (DAN)', owasp: 'LLM01', desc: 'Test well-known jailbreak personas and developer modes.' },
  { id: 'rag-grounding', title: 'Break RAG Grounding', owasp: 'LLM09', desc: 'Plant false facts and check if the AI cites them from document.' },
  { id: 'multi-turn', title: 'Multi-turn Escalation', owasp: 'LLM01', desc: 'Gradually erode guidelines over multiple conversation turns.' },
  { id: 'encoding', title: 'Encoding & Obfuscation', owasp: 'LLM01', desc: 'Hide attack payloads using Base64, ROT13, or ciphers.' },
];

const CHALLENGE_MAP = Object.fromEntries(CHALLENGES.map(c => [c.id, c.title]));

// App state
let state = {
  challengerName: localStorage.getItem('sachet_pg_name') || 'Marie',
  currentObjective: localStorage.getItem('sachet_pg_obj') || 'open',
  botEndpoint: localStorage.getItem('sachet_pg_endpoint') || '/api/v1/redteam/ask',
  messageField: localStorage.getItem('sachet_pg_field') || 'message',
  sessionId: localStorage.getItem('sachet_pg_session_id') || 'pg_' + Math.random().toString(36).slice(2, 9),
  containers: JSON.parse(localStorage.getItem('sachet_pg_containers') || '[{"id":"kc_default","name":"Knowledge container 1","files":[]}]'),
  activeContainerId: localStorage.getItem('sachet_pg_active_container') || 'kc_default',
  isSending: false,
  streamSource: null,
  cursor: 0,
  expandedFolders: JSON.parse(localStorage.getItem('sachet_pg_expanded') || '{"kc_default":true}'),
};

/* ─── CHAT MESSAGES ─────────────────────────────────────────── */
function appendMessage(role, text, isHtml = false, context = null) {
  const container = $('chat-messages');
  const bubble = document.createElement('div');
  bubble.className = `ik-bubble ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'ik-bubble-avatar';
  avatar.textContent = role === 'ai' ? '⌘' : (state.challengerName.slice(0, 2).toUpperCase() || 'ME');

  const content = document.createElement('div');
  content.className = 'ik-bubble-content';
  
  if (isHtml) {
    content.innerHTML = text;
  } else if (role === 'ai') {
    // Escape HTML but allow safe formatting tags like <b> and <code>
    let formatted = escapeHtml(text)
      .replace(/&lt;b&gt;/g, '<b>')
      .replace(/&lt;\/b&gt;/g, '</b>')
      .replace(/&lt;code&gt;/g, '<code>')
      .replace(/&lt;\/code&gt;/g, '</code>')
      .replace(/\n/g, '<br>');
    content.innerHTML = formatted;
  } else {
    content.textContent = text;
  }

  // Render RAG Document Citations if returned
  if (context && Array.isArray(context) && context.length > 0) {
    const citationsBox = document.createElement('div');
    citationsBox.className = 'ik-citations-box';
    citationsBox.innerHTML = `
      <div class="ik-citations-title">📄 Retrieved Knowledge Sources (${context.length})</div>
      <div class="ik-citations-list">
        ${context.map(c => `
          <div class="ik-citation-item">
            <span class="ik-citation-source">📎 <b>${escapeHtml(c.source || 'Document')}</b> ${c.page ? `(Page ${escapeHtml(c.page)})` : ''}</span>
            <div class="ik-citation-excerpt">${escapeHtml(c.text || '')}</div>
          </div>
        `).join('')}
      </div>
    `;
    content.append(citationsBox);
  }

  bubble.append(avatar, content);
  container.append(bubble);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

function appendLoadingMessage() {
  const container = $('chat-messages');
  const bubble = document.createElement('div');
  bubble.className = 'ik-bubble ai loading';
  bubble.id = 'ik-loading-bubble';

  const avatar = document.createElement('div');
  avatar.className = 'ik-bubble-avatar';
  avatar.textContent = '⌘';

  const content = document.createElement('div');
  content.className = 'ik-bubble-content';
  content.innerHTML = `<span>icarKno is analyzing & generating answer</span> <span class="ik-typing-dots"><span></span><span></span><span></span></span>`;

  bubble.append(avatar, content);
  container.append(bubble);
  container.scrollTop = container.scrollHeight;
}

function removeLoadingMessage() {
  const el = $('ik-loading-bubble');
  if (el) el.remove();
}

function escapeHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ─── BOT QUERY & DISPATCH ───────────────────────────────────── */
async function sendQuery(promptText) {
  if (!promptText || state.isSending) return;
  state.isSending = true;
  $('btn-send').disabled = true;

  appendMessage('user', promptText);
  $('chat-input').value = '';
  $('chat-input').style.height = 'auto';
  $('btn-send').classList.remove('has-text');
  appendLoadingMessage();

  const startTime = performance.now();
  let aiResponseText = '';
  let wasBlocked = false;

  const activeContainer = state.containers.find(c => c.id === state.activeContainerId);
  const targetSession = state.activeContainerId || state.sessionId;
  const filenames = (activeContainer && activeContainer.files) ? activeContainer.files : [];

  try {
    const payload = {
      message: promptText,
      prompt: promptText,
      sessionId: targetSession,
      fingerprint: targetSession,
      filenames: filenames,
    };
    payload[state.messageField] = promptText;

    let res = await fetch(state.botEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Redteam-Session': targetSession,
      },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    // Seamless fallback: If user targets /api/v1/ask without an active JWT login, route via /api/v1/redteam/ask
    if (res.status === 401 && (state.botEndpoint === '/api/v1/ask' || state.botEndpoint.endsWith('/ask'))) {
      res = await fetch('/api/v1/redteam/ask', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Redteam-Session': targetSession,
        },
        credentials: 'include',
        body: JSON.stringify(payload)
      });
    }

    const elapsedMs = Math.round(performance.now() - startTime);

    let contextData = null;
    if (res.ok) {
      const data = await res.json();
      aiResponseText = data.answer || data.response || data.text || data.message || JSON.stringify(data);
      wasBlocked = data.status === 'blocked';
      contextData = data.context || null;
    } else {
      aiResponseText = `Bot Error (${res.status}): Failed to reach bot endpoint at ${state.botEndpoint}.`;
    }

    removeLoadingMessage();
    appendMessage('ai', aiResponseText, false, contextData);

    // If querying an external bot target, send telemetry to universal logger
    if (state.botEndpoint !== '/api/v1/ask' && state.botEndpoint !== '/api/v1/trial-ask' && state.botEndpoint !== '/api/v1/redteam/ask') {
      logExternalAttempt(promptText, aiResponseText, elapsedMs, wasBlocked);
    }

  } catch (err) {
    removeLoadingMessage();
    appendMessage('ai', `Connection Error: ${err.message}. Please check if the bot endpoint is online.`);
  } finally {
    state.isSending = false;
    $('btn-send').disabled = false;
    $('chat-input').focus();
  }
}

async function logExternalAttempt(prompt, response, latencyMs, blocked) {
  try {
    await fetch('/api/v1/redteam/log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        participant_name: state.challengerName,
        challenge_id: state.currentObjective,
        prompt: prompt,
        response: response,
        response_time_ms: latencyMs,
        blocked: blocked
      })
    });
  } catch {}
}

/* ─── LIVE PROBE VERDICT DISPLAY ─────────────────────────────── */
function showProbeVerdict(event) {
  const strip = $('probe-verdict-strip');
  if (!strip || !event) return;

  const isDefended = event.outcome === 'DEFENDED' || event.outcome === 'BLOCKED';
  const isBypass = event.outcome === 'SUCCESSFUL' || event.outcome === 'PARTIAL';

  strip.className = 'ik-verdict-banner' + (isBypass ? ' bypass' : '');
  $('verdict-icon').textContent = isDefended ? '🛡️' : (isBypass ? '💥' : '🔍');
  $('verdict-outcome').textContent = event.outcome;
  $('verdict-threat').textContent = `Threat: ${event.risk_score || 0}/100 · ${event.severity || 'LOW'}`;
  $('verdict-category').textContent = event.attack_category || 'OWASP Evaluation';
  $('verdict-reason').textContent = event.reason || 'Guardrail boundaries verified.';
  $('verdict-pts').textContent = (event.points > 0 ? `+${event.points} PTS` : '+0 PTS');

  strip.style.display = 'flex';
}

/* ─── TELEMETRY & SSE STREAM ─────────────────────────────────── */
async function loadSnapshot() {
  try {
    const res = await fetch(API + '/snapshot');
    if (!res.ok) return;
    const snap = await res.json();
    renderSnapshot(snap);
    if (!state.cursor) state.cursor = snap.cursor || 0;
  } catch {}
}

function renderSnapshot(snap) {
  const s = snap.stats || {};

  // Posture Card
  const defRateEl = $('m-defense-rate');
  if (defRateEl) {
    defRateEl.textContent = (s.defense_rate != null ? Math.round(s.defense_rate) : 100) + '%';
  }
  if ($('m-probes')) $('m-probes').textContent = s.attack_attempts || 0;
  if ($('m-defended')) $('m-defended').textContent = (s.defended || 0) + (s.blocked || 0);
  if ($('m-bypasses')) $('m-bypasses').textContent = s.successful || 0;

  const postureTag = $('posture-tag');
  if (postureTag) {
    if (s.under_attack) {
      postureTag.textContent = 'UNDER ATTACK';
      postureTag.className = 'ik-status-chip coral';
    } else if (s.successful > 0) {
      postureTag.textContent = 'BYPASS DETECTED';
      postureTag.className = 'ik-status-chip coral';
    } else {
      postureTag.textContent = 'MAX RESILIENCE';
      postureTag.className = 'ik-status-chip mint';
    }
  }

  // Feed
  renderFeed(snap.events || []);

  // Leaderboard
  renderLeaderboard(snap.leaderboard || []);

  // Update verdict strip with latest attack if any
  if (snap.latest && snap.latest.attack_detected) {
    showProbeVerdict(snap.latest);
  }
}

function renderFeed(events) {
  const container = $('pg-feed');
  if (!container) return;
  const attacks = events.filter(e => e.attack_detected).slice(0, 15);
  container.replaceChildren();

  if (!attacks.length) {
    const empty = document.createElement('div');
    empty.className = 'ik-feed-empty';
    empty.textContent = 'No attack probes recorded yet. Send one to test!';
    container.append(empty);
    return;
  }

  if ($('feed-count')) $('feed-count').textContent = `${attacks.length} recent`;

  for (const ev of attacks) {
    const row = document.createElement('div');
    row.className = 'ik-feed-row';

    const info = document.createElement('div');
    info.className = 'ik-feed-info';
    info.innerHTML = `
      <span class="ik-feed-cat">${escapeHtml(ev.attack_category)}</span>
      <span class="ik-feed-sub">${escapeHtml(ev.participant_name || 'Anon')} · ${ev.response_time_ms || 0}ms · ${ev.risk_score || 0}/100</span>
    `;

    const badge = document.createElement('span');
    const outcomeCls = (ev.outcome || 'unknown').toLowerCase();
    badge.className = `ik-feed-badge ${outcomeCls}`;
    badge.textContent = ev.outcome === 'DEFENDED' ? '🛡️ DEFENDED' : (ev.outcome === 'BLOCKED' ? '⛔ BLOCKED' : ev.outcome);

    row.append(info, badge);
    row.addEventListener('click', () => openEventInspector(ev));
    container.append(row);
  }
}

function renderLeaderboard(leaders) {
  const container = $('pg-leaderboard');
  if (!container) return;
  container.replaceChildren();

  if (!leaders.length) {
    const empty = document.createElement('div');
    empty.className = 'ik-feed-empty';
    empty.textContent = 'All attacks defended. Be the first to claim a bounty!';
    container.append(empty);
    return;
  }

  for (const [idx, row] of leaders.slice(0, 8).entries()) {
    const el = document.createElement('div');
    el.className = 'ik-lead-row';

    const rank = document.createElement('span');
    rank.className = 'ik-lead-rank';
    rank.textContent = String(idx + 1).padStart(2, '0');

    const info = document.createElement('div');
    info.className = 'ik-lead-info';

    const name = document.createElement('span');
    name.className = 'ik-lead-name';
    name.textContent = row.participant_name;

    const stats = document.createElement('span');
    stats.className = 'ik-lead-stats';
    const bypassStr = row.successes > 0 ? `${row.successes} bypasses` : '0 bypasses (Defended)';
    stats.textContent = `${bypassStr} · ${row.attempts} attempts`;

    info.append(name, stats);

    const pts = document.createElement('div');
    pts.className = 'ik-lead-pts';
    pts.innerHTML = `${row.points}<small>PTS</small>`;

    el.append(rank, info, pts);
    container.append(el);
  }
}

function connectSSE() {
  if (state.streamSource) state.streamSource.close();
  state.streamSource = new EventSource(API + '/stream?after=' + state.cursor);

  state.streamSource.onopen = () => {
    if ($('pg-connection-status')) $('pg-connection-status').textContent = 'Live Telemetry';
    if ($('pg-live-dot')) $('pg-live-dot').style.background = 'var(--mint)';
  };

  state.streamSource.addEventListener('attack', msg => {
    try {
      const event = JSON.parse(msg.data);
      state.cursor = Math.max(state.cursor, event.seq || 0);
      if (event.attack_detected) {
        showProbeVerdict(event);
      }
    } catch {}
  });

  state.streamSource.addEventListener('snapshot', msg => {
    try {
      renderSnapshot(JSON.parse(msg.data));
    } catch {}
  });

  state.streamSource.onerror = () => {
    if ($('pg-connection-status')) $('pg-connection-status').textContent = 'Reconnecting';
    if ($('pg-live-dot')) $('pg-live-dot').style.background = 'var(--coral)';
    setTimeout(connectSSE, 4000);
  };
}

/* ─── EVENT INSPECTOR MODAL ──────────────────────────────────── */
function openEventInspector(event) {
  $('event-detail-title').textContent = `${event.attack_category} — Security Assessment`;
  const body = $('event-detail-body');
  body.replaceChildren();

  const grid = document.createElement('div');
  grid.className = 'ik-detail-grid';

  const fields = [
    ['CONTESTANT', event.participant_name],
    ['TIMESTAMP', new Date(event.timestamp).toLocaleString()],
    ['DEFENSE VERDICT', `${event.outcome} ${event.outcome === 'DEFENDED' ? '🛡️ (Model held boundaries; safety directives sustained)' : ''}`],
    ['OWASP CLASSIFICATION', event.attack_category],
    ['THREAT RATING', `${event.risk_score}/100 · ${event.severity} (Adversarial difficulty score)`],
    ['LATENCY', `${event.response_time_ms} ms`],
    ['BOUNTY POINTS', `${event.points} pts ${event.points === 0 ? '(0 pts: Model defended successfully)' : ''}`],
    ['EVALUATION EVIDENCE', event.reason, true],
    ['CLASSIFICATION NOTES', event.classification_reason, true],
    ['EVENT ID', event.event_id, true],
  ];

  for (const [lbl, val, wide] of fields) {
    const item = document.createElement('div');
    item.className = 'ik-detail-field' + (wide ? ' wide' : '');
    item.innerHTML = `<small>${lbl}</small><p>${escapeHtml(val || '—')}</p>`;
    grid.append(item);
  }

  body.append(grid);
  $('modal-event-detail').showModal();
}

/* ─── KNOWLEDGE CONTAINERS MANAGEMENT ────────────────────────── */
function getFileIcon(filename) {
  const ext = (filename || '').toLowerCase().split('.').pop();
  if (filename && filename.startsWith('http')) return '🌐';
  switch (ext) {
    case 'pdf': return '📕';
    case 'doc':
    case 'docx': return '📘';
    case 'xls':
    case 'xlsx':
    case 'csv': return '📗';
    case 'txt':
    case 'md':
    case 'json': return '📄';
    default: return '📄';
  }
}

function renderContainers() {
  const container = $('sidebar-containers');
  if (!container) return;
  container.replaceChildren();

  for (const c of state.containers) {
    const group = document.createElement('div');
    group.className = 'ik-container-group';

    const card = document.createElement('div');
    const isActive = c.id === state.activeContainerId;
    const isExpanded = !!state.expandedFolders[c.id];
    const docCount = (c.files || []).length;

    card.className = 'ik-container-card' + (isActive ? ' active' : '');
    card.innerHTML = `
      <span class="ik-caret${isExpanded ? ' expanded' : ''}">›</span>
      <span class="ik-container-label" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</span>
      <span class="ik-container-badge">${docCount} ${docCount === 1 ? 'doc' : 'docs'}</span>
      <button class="ik-add-source-btn" title="Add / Ingest documents into this container" style="background:none;border:none;color:inherit;cursor:pointer;font-size:14px;padding:2px 6px;">+</button>
    `;
    
    // Toggle expand when clicking caret
    const caret = card.querySelector('.ik-caret');
    if (caret) {
      caret.onclick = (e) => {
        e.stopPropagation();
        state.expandedFolders[c.id] = !state.expandedFolders[c.id];
        localStorage.setItem('sachet_pg_expanded', JSON.stringify(state.expandedFolders));
        renderContainers();
      };
    }

    // Add documents button inside container
    const addBtn = card.querySelector('.ik-add-source-btn');
    if (addBtn) {
      addBtn.onclick = (e) => {
        e.stopPropagation();
        selectContainer(c.id);
        openContainerModal(c.name, c.id);
      };
    }

    card.onclick = () => {
      selectContainer(c.id);
      state.expandedFolders[c.id] = true;
      localStorage.setItem('sachet_pg_expanded', JSON.stringify(state.expandedFolders));
      renderContainers();
    };
    group.append(card);

    // Expandable file list
    if (isExpanded) {
      const fileListEl = document.createElement('div');
      fileListEl.className = 'ik-container-files-list';
      if (c.files && c.files.length > 0) {
        for (const fname of c.files) {
          const fileItem = document.createElement('div');
          fileItem.className = 'ik-file-item';
          fileItem.innerHTML = `
            <span>${getFileIcon(fname)}</span>
            <span class="ik-file-item-name" title="${escapeHtml(fname)}">${escapeHtml(fname)}</span>
          `;
          fileListEl.append(fileItem);
        }
      } else {
        const emptyItem = document.createElement('div');
        emptyItem.className = 'ik-file-empty';
        emptyItem.innerHTML = `No documents yet · <a href="#" style="color:#2563eb;text-decoration:none;">Click + to add</a>`;
        emptyItem.onclick = (e) => {
          e.preventDefault();
          e.stopPropagation();
          openContainerModal(c.name, c.id);
        };
        fileListEl.append(emptyItem);
      }
      group.append(fileListEl);
    }

    container.append(group);
  }
}

function selectContainer(containerId) {
  state.activeContainerId = containerId;
  localStorage.setItem('sachet_pg_active_container', containerId);
  renderContainers();

  const c = state.containers.find(x => x.id === containerId);
  if (c) {
    appendMessage('ai', `📁 Active container: <b>${escapeHtml(c.name)}</b> (${(c.files || []).length} document(s)). All queries and attack probes now target this container index.`);
  }
}

function openContainerModal(existingName, existingId) {
  const modal = $('modal-container');
  if (!modal) return;
  const nameInput = $('input-container-name');
  const fileInput = $('input-container-files');
  const fileLabel = $('selected-files-label');
  const rawTextInput = $('input-raw-text');
  const urlsInput = $('input-urls');

  if (nameInput) {
    nameInput.value = existingName || `Knowledge Container ${state.containers.length + 1}`;
    if (existingId) {
      nameInput.dataset.targetId = existingId;
    } else {
      delete nameInput.dataset.targetId;
    }
  }
  if (fileInput) fileInput.value = '';
  if (fileLabel) fileLabel.textContent = 'No files selected';
  if (rawTextInput) rawTextInput.value = '';
  if (urlsInput) urlsInput.value = '';
  modal.showModal();
}

function initContainerModal() {
  const btnNew = $('btn-new-container');
  const modal = $('modal-container');
  const fileInput = $('input-container-files');
  const fileLabel = $('selected-files-label');
  const dropzone = $('dropzone-files');
  const form = $('form-container');
  const btnSubmit = $('btn-submit-container');

  if (btnNew) {
    btnNew.onclick = () => openContainerModal();
  }

  // Drag and drop support on dropzone
  if (dropzone && fileInput) {
    ['dragenter', 'dragover'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.add('ik-drag-over');
      });
    });
    ['dragleave', 'drop'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.remove('ik-drag-over');
      });
    });
    dropzone.addEventListener('drop', (e) => {
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        fileInput.files = e.dataTransfer.files;
        fileInput.dispatchEvent(new Event('change'));
      }
    });
  }

  if (fileInput && fileLabel) {
    fileInput.onchange = () => {
      const count = fileInput.files.length;
      if (count === 0) {
        fileLabel.textContent = 'No files selected';
      } else if (count === 1) {
        fileLabel.textContent = `Selected: ${fileInput.files[0].name}`;
      } else {
        fileLabel.textContent = `Selected ${count} files: ` + Array.from(fileInput.files).map(f => f.name).slice(0, 3).join(', ') + (count > 3 ? '…' : '');
      }
    };
  }

  if (form) {
    form.onsubmit = async ev => {
      ev.preventDefault();
      const nameInput = $('input-container-name');
      const name = (nameInput ? nameInput.value.trim() : '') || 'Knowledge Container';
      const targetId = nameInput ? nameInput.dataset.targetId : null;
      const rawText = $('input-raw-text') ? $('input-raw-text').value.trim() : '';
      const urlsText = $('input-urls') ? $('input-urls').value.trim() : '';
      const files = fileInput ? fileInput.files : [];

      if (files.length === 0 && !rawText && !urlsText) {
        alert('Please choose at least one file, paste text, or enter a URL to ingest.');
        return;
      }

      const origText = btnSubmit.textContent;
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Ingesting into RAG database…';

      try {
        const formData = new FormData();
        formData.append('container_name', name);
        formData.append('session_id', targetId || ('kc_' + Math.random().toString(36).slice(2, 9)));
        if (rawText) formData.append('raw_text', rawText);
        if (urlsText) formData.append('urls', urlsText);

        for (let i = 0; i < files.length; i++) {
          formData.append('files', files[i]);
        }

        const res = await fetch('/api/v1/redteam/container', {
          method: 'POST',
          body: formData,
        });

        if (res.ok) {
          const data = await res.json();
          let matched = state.containers.find(c => c.id === data.container_id);
          const filenames = data.filenames && data.filenames.length > 0
            ? data.filenames
            : (rawText ? ['confidential_policy.txt'] : (files.length > 0 ? Array.from(files).map(f => f.name) : ['document.txt']));

          if (!matched) {
            matched = {
              id: data.container_id,
              name: data.name || name,
              files: filenames,
            };
            state.containers.push(matched);
          } else {
            matched.name = data.name || name;
            matched.files = Array.from(new Set([...(matched.files || []), ...filenames]));
          }
          state.expandedFolders[matched.id] = true;
          localStorage.setItem('sachet_pg_expanded', JSON.stringify(state.expandedFolders));
          localStorage.setItem('sachet_pg_containers', JSON.stringify(state.containers));
          state.activeContainerId = matched.id;
          localStorage.setItem('sachet_pg_active_container', matched.id);
          renderContainers();

          modal.close();
          const fileDisplay = matched.files.join(', ');
          appendMessage('ai', `✅ <b>${escapeHtml(matched.name)}</b> successfully indexed! Document(s) <code>${escapeHtml(fileDisplay)}</code> chunked and stored in Elasticsearch vector store. You can now chat or launch security probes against it.`);
        } else {
          const errData = await res.json().catch(() => ({}));
          alert('Ingestion failed: ' + (errData.detail || errData.message || res.statusText));
        }
      } catch (err) {
        alert('Ingestion connection error: ' + err.message);
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = origText;
      }
    };
  }
}

/* ─── SIDEBAR & OBJECTIVES RENDERING ─────────────────────────── */
function renderSidebarObjectives() {
  const container = $('sidebar-objectives');
  if (!container) return;
  container.replaceChildren();

  for (const obj of CHALLENGES) {
    const item = document.createElement('div');
    item.className = 'ik-sidebar-obj-item' + (obj.id === state.currentObjective ? ' selected' : '');
    item.innerHTML = `
      <span>${obj.title}</span>
      <span class="ik-sidebar-obj-tag">${obj.owasp}</span>
    `;
    item.onclick = () => selectObjective(obj.id);
    container.append(item);
  }
}

async function selectObjective(objId) {
  state.currentObjective = objId;
  localStorage.setItem('sachet_pg_obj', objId);
  try {
    await fetch(API + '/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nickname: state.challengerName, challenge_id: objId, reset: false })
    });
  } catch {}
  updateHUD();
  renderSidebarObjectives();
  loadSnapshot();
}

function updateHUD() {
  if ($('hud-challenger-name')) $('hud-challenger-name').textContent = state.challengerName;
  if ($('hud-objective-name')) $('hud-objective-name').textContent = CHALLENGE_MAP[state.currentObjective] || state.currentObjective;
  if ($('hud-endpoint-label')) {
    $('hud-endpoint-label').textContent = state.botEndpoint.length > 20 ? state.botEndpoint.slice(0, 18) + '…' : state.botEndpoint;
  }
}

/* ─── MODALS INITIALIZATION ──────────────────────────────────── */
function initModals() {
  // Challenger Modal
  $('btn-edit-challenger').onclick = () => {
    $('input-nickname').value = state.challengerName;
    $('modal-challenger').showModal();
  };
  $('form-challenger').onsubmit = async ev => {
    ev.preventDefault();
    const newName = $('input-nickname').value.trim();
    if (newName) {
      state.challengerName = newName;
      localStorage.setItem('sachet_pg_name', newName);
      try {
        await fetch(API + '/session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nickname: newName, challenge_id: state.currentObjective, reset: true })
        });
      } catch {}
      updateHUD();
      loadSnapshot();
    }
    $('modal-challenger').close();
  };

  // Objective Modal
  $('btn-edit-objective').onclick = () => {
    renderObjectiveModalList();
    $('modal-objective').showModal();
  };

  // Endpoint Modal
  $('btn-edit-endpoint').onclick = () => {
    $('input-bot-url').value = state.botEndpoint;
    $('input-payload-field').value = state.messageField;
    $('modal-endpoint').showModal();
  };
  $('form-endpoint').onsubmit = ev => {
    ev.preventDefault();
    state.botEndpoint = $('input-bot-url').value.trim() || '/api/v1/redteam/ask';
    state.messageField = $('input-payload-field').value.trim() || 'message';
    localStorage.setItem('sachet_pg_endpoint', state.botEndpoint);
    localStorage.setItem('sachet_pg_field', state.messageField);
    updateHUD();
    $('modal-endpoint').close();
  };
  $('btn-reset-endpoint').onclick = () => {
    state.botEndpoint = '/api/v1/redteam/ask';
    state.messageField = 'message';
    $('input-bot-url').value = '/api/v1/redteam/ask';
    $('input-payload-field').value = 'message';
    localStorage.setItem('sachet_pg_endpoint', '/api/v1/redteam/ask');
    localStorage.setItem('sachet_pg_field', 'message');
    updateHUD();
    $('modal-endpoint').close();
  };
}

function renderObjectiveModalList() {
  const list = $('objective-list');
  if (!list) return;
  list.replaceChildren();

  for (const obj of CHALLENGES) {
    const item = document.createElement('div');
    item.className = 'ik-modal-obj-item' + (obj.id === state.currentObjective ? ' selected' : '');
    item.innerHTML = `
      <div class="ik-modal-obj-head">
        <strong>${obj.title}</strong>
        <span>${obj.owasp}</span>
      </div>
      <p>${obj.desc}</p>
    `;
    item.onclick = () => {
      selectObjective(obj.id);
      $('modal-objective').close();
    };
    list.append(item);
  }
}

/* ─── QUICK ATTACK CHIPS ─────────────────────────────────────── */
function initAttackChips() {
  const chips = document.querySelectorAll('.ik-probe-chip');
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      const prompt = chip.getAttribute('data-prompt');
      if (prompt) {
        const input = $('chat-input');
        input.value = prompt;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        $('btn-send').classList.add('has-text');
        input.focus();
      }
    });
  });
}

/* ─── TOGGLES & INTERFACE WIRING ─────────────────────────────── */
function initInterfaceToggles() {
  // Sidebar Toggle
  const btnToggleSidebar = $('btn-toggle-sidebar');
  const sidebar = $('ik-sidebar');
  if (btnToggleSidebar && sidebar) {
    btnToggleSidebar.onclick = () => {
      sidebar.classList.toggle('collapsed');
    };
  }

  // Telemetry Panel Toggle
  const btnToggleTel = $('btn-toggle-telemetry');
  const telPanel = $('ik-telemetry-panel');
  const btnCloseTel = $('btn-close-tel');
  
  if (btnToggleTel && telPanel) {
    btnToggleTel.onclick = () => {
      telPanel.classList.toggle('collapsed');
      btnToggleTel.classList.toggle('active', !telPanel.classList.contains('collapsed'));
    };
  }
  if (btnCloseTel && telPanel && btnToggleTel) {
    btnCloseTel.onclick = () => {
      telPanel.classList.add('collapsed');
      btnToggleTel.classList.remove('active');
    };
  }

  // Dark/Light Theme Toggle
  const btnToggleTheme = $('btn-toggle-theme');
  if (btnToggleTheme) {
    btnToggleTheme.onclick = () => {
      document.body.classList.toggle('ik-theme-dark');
    };
  }
}

/* ─── CHAT FORM LOGIC ────────────────────────────────────────── */
function initChatForm() {
  const input = $('chat-input');
  const sendBtn = $('btn-send');

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    if (input.value.trim().length > 0) {
      sendBtn.classList.add('has-text');
    } else {
      sendBtn.classList.remove('has-text');
    }
  });

  input.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      const text = input.value.trim();
      if (text) sendQuery(text);
    }
  });

  $('chat-form').onsubmit = ev => {
    ev.preventDefault();
    const text = input.value.trim();
    if (text) sendQuery(text);
  };
}

// Boot
updateHUD();
renderContainers();
renderSidebarObjectives();
initModals();
initContainerModal();
initAttackChips();
initInterfaceToggles();
initChatForm();
loadSnapshot();
connectSSE();
