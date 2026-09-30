import { joinArena, leaveArena } from './participant.js';

const form     = document.getElementById('join-form');
const button   = document.getElementById('join-button');
const status   = document.getElementById('join-status');
const make     = (tag, text) => { const el = document.createElement(tag); if (text != null) el.textContent = text; return el; };

let selected = 'open';
let joined   = false;
let currentParticipantName = '';

async function loadChallenges() {
  button.disabled = true;
  try {
    const resp = await fetch('/api/v1/redteam/challenges');
    if (!resp.ok) throw Error('Unavailable');
    const data = await resp.json();
    const container = document.getElementById('missions');
    container.replaceChildren();

    for (const ch of data.challenges) {
      const card = document.createElement('label');
      card.className = 'mission' + (ch.available ? '' : ' mission-unavailable');

      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'challenge';
      radio.value = ch.id;
      radio.checked = ch.id === selected;
      radio.disabled = !ch.available;
      radio.addEventListener('change', () => { selected = ch.id; });

      // Top line: title + level badge
      const topRow = document.createElement('div');
      topRow.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;';
      const title = make('strong', ch.title + (ch.available ? '' : ' · organiser setup required'));
      const levelEl = make('span', ch.level?.split(' ')[0] ?? 'STARTER');
      const levelClass = (ch.level ?? '').toLowerCase().replace(/[^a-z]/g, '').replace('objective', 'expert').replace('ctf', 'expert');
      levelEl.className = 'guide-level ' + (levelClass || 'starter');
      topRow.append(title, levelEl);

      // OWASP reference
      const owaspEl = make('div', ch.owasp ?? '');
      owaspEl.className = 'mission-owasp';

      // Objective
      const obj = make('p', ch.objective ?? '');

      card.append(radio, topRow, owaspEl, obj);

      // Hints section
      if (ch.hints && ch.hints.length) {
        const hintsWrap = document.createElement('div');
        hintsWrap.className = 'mission-hints';
        hintsWrap.append(make('small', 'EXAMPLE PROMPTS — CLICK TO COPY'));
        const ul = document.createElement('ul');
        for (const hint of ch.hints.slice(0, 3)) {
          const li = make('li', hint);
          li.style.cursor = 'pointer';
          li.title = 'Click to copy to clipboard';
          li.addEventListener('click', e => {
            e.preventDefault();
            navigator.clipboard?.writeText(hint).then(() => {
              li.style.color = 'var(--mint)';
              setTimeout(() => (li.style.color = ''), 1400);
            });
          });
          ul.append(li);
        }
        hintsWrap.append(ul);
        card.append(hintsWrap);
      }

      // Win condition
      if (ch.win_condition) {
        const winEl = document.createElement('div');
        winEl.className = 'mission-win';
        const winLabel = make('strong', 'WIN CONDITION');
        winEl.append(winLabel, document.createTextNode(ch.win_condition));
        card.append(winEl);
      }

      // Verification note
      if (ch.verification) {
        const note = make('p', 'How outcomes are assessed: ' + ch.verification);
        note.style.cssText = 'font-size:9px;color:var(--muted);margin-top:8px;line-height:1.6;';
        card.append(note);
      }

      container.append(card);
    }
    button.disabled = false;
  } catch {
    document.getElementById('missions').textContent =
      'Challenges are unavailable. Reload when the backend reconnects.';
  }
}

async function refreshProgress() {
  try {
    const resp = await fetch('/api/v1/redteam/me', { cache: 'no-store' });
    if (!resp.ok) return;
    const player = await resp.json();
    if (!player || !player.participant_name) return;
    joined = true;
    currentParticipantName = player.participant_name;

    const badge = document.getElementById('player-status-badge');
    const badgeName = document.getElementById('player-status-name');
    if (badge && badgeName) {
      badge.style.display = 'flex';
      badgeName.textContent = currentParticipantName;
    }
    const nickInput = document.getElementById('nickname');
    if (nickInput && !nickInput.value) {
      nickInput.placeholder = currentParticipantName;
    }

    button.textContent = 'Update objective →';
    document.getElementById('progress').hidden = false;
    document.getElementById('progress-stats').textContent =
      `${player.participant_name} · ${player.points} pts · ${player.attempts} attacks · ${player.successes} confirmed bypasses`;

    document.getElementById('progress-events').replaceChildren(
      ...player.events.slice(0, 6).map(ev => {
        const outcomeLabel = ev.outcome === 'DEFENDED' ? '🛡️ DEFENDED (Model Held)'
          : ev.outcome === 'BLOCKED' ? '⛔ BLOCKED (Guardrail)'
          : ev.outcome === 'SUCCESSFUL' ? '💥 CONFIRMED BYPASS'
          : ev.outcome === 'PARTIAL' ? '⚠️ PARTIAL'
          : ev.outcome === 'NOT_APPLICABLE' ? 'BENIGN'
          : ev.outcome;
        const row = make('p', `${ev.attack_category} — ${outcomeLabel} · +${ev.points} pts`);
        row.append(make('small', ev.reason ?? ''));
        return row;
      })
    );
  } catch { /* Keep last known progress */ }
}

document.getElementById('switch-player-btn')?.addEventListener('click', async () => {
  await leaveArena();
  currentParticipantName = '';
  const badge = document.getElementById('player-status-badge');
  if (badge) badge.style.display = 'none';
  document.getElementById('progress').hidden = true;
  const nickInput = document.getElementById('nickname');
  if (nickInput) {
    nickInput.value = '';
    nickInput.placeholder = 'e.g. CuriousHuman42';
    nickInput.focus();
  }
  button.textContent = 'Join the challenge →';
  status.textContent = 'Session reset. Enter a new challenger name and click Join!';
  joined = false;
});

form.addEventListener('submit', async ev => {
  ev.preventDefault();
  button.disabled = true;
  status.textContent = 'Joining the arena…';
  try {
    const enteredName = (document.getElementById('nickname').value || '').trim();
    // If user entered a specific name and it differs from active session, start as a new identity
    const shouldReset = Boolean(enteredName && currentParticipantName && enteredName.toLowerCase() !== currentParticipantName.toLowerCase());
    const player = await joinArena(enteredName, '', selected, shouldReset);
    const missionCard = document.querySelector(`input[name="challenge"][value="${selected}"]`)?.closest('.mission');
    const missionTitle = missionCard?.querySelector('strong')?.textContent?.split('·')[0]?.trim() || selected;
    status.textContent =
      `Target objective set to "${missionTitle}" for ${player.participantName}! Open the chatbot below to test your attack prompts. (Note: Only adversarial attack probes count toward attempts on the leaderboard; normal document questions are excluded).`;
    button.textContent = 'Update objective →';
    joined = true;
    await refreshProgress();
  } catch {
    status.textContent = 'Could not join. Wait a moment and try again.';
  } finally {
    button.disabled = false;
  }
});

loadChallenges();
refreshProgress();
setInterval(() => { if (joined && !document.hidden) refreshProgress(); }, 6000);
window.addEventListener('focus', refreshProgress);
