/* Optional integration for the existing chatbot UI. Does not intercept requests.
   import { joinArena, arenaHeaders } from '/arena/assets/participant.js';
   await joinArena(nickname, backendOrigin); then merge arenaHeaders() into chat headers.
   Session storage is tab-local; never stores an admin credential. */
const key = 'sachet-arena-session';
export async function joinArena(nickname = '', backendOrigin = '', challengeId = 'open', reset = false) {
  const response = await fetch(backendOrigin + '/api/v1/redteam/session', {
    method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({nickname, challenge_id: challengeId, reset})
  });
  if (!response.ok) throw new Error('Could not join the arena');
  const session = await response.json();
  sessionStorage.setItem(key, session.session_token);
  return {participantName: session.participant_name, sessionId: session.session_id};
}
export async function leaveArena(backendOrigin = '') {
  try {
    await fetch(backendOrigin + '/api/v1/redteam/logout', { method: 'POST', credentials: 'include' });
  } catch {}
  sessionStorage.removeItem(key);
}
export function arenaHeaders() {
  const token = sessionStorage.getItem(key);
  return token ? {'X-Redteam-Session': token} : {};
}
