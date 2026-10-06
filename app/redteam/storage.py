"""Separate SQLite WAL store; atomic scores, stable cursor, metadata-only records."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .scoring import ScoringService


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class TelemetryStore:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        path = Path(config.database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=5)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS arena_sessions (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                nickname TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS arena_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                session_id TEXT NOT NULL, created REAL NOT NULL, simulated INTEGER NOT NULL,
                prompt_hash TEXT NOT NULL, category TEXT NOT NULL, attack INTEGER NOT NULL,
                outcome TEXT NOT NULL, points INTEGER NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS arena_mode_seq ON arena_events(simulated, seq);
            CREATE INDEX IF NOT EXISTS arena_score ON arena_events(session_id, simulated, created);
            CREATE INDEX IF NOT EXISTS arena_duplicate ON arena_events(session_id, simulated, prompt_hash);
            CREATE TABLE IF NOT EXISTS arena_prompts (
                participant_name TEXT PRIMARY KEY, prompt TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS arena_contestants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                created REAL NOT NULL,
                total_score INTEGER DEFAULT 0,
                attempts INTEGER DEFAULT 0,
                evaluation_mode TEXT DEFAULT 'human',
                evaluator_notes TEXT,
                evaluations_json TEXT);
        ''')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(arena_sessions)')}
        if 'challenge_id' not in columns:
            self.db.execute("ALTER TABLE arena_sessions ADD COLUMN challenge_id TEXT NOT NULL DEFAULT 'open'")
            self.db.commit()
        self.scoring = ScoringService(config.scores)

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield self.db

    def create_session(self, nickname='', challenge_id='open'):
        session_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        # Nicknames are intentionally constrained, rendered as text, never HTML.
        nickname = re.sub(r'[^\w .-]', '', nickname, flags=re.UNICODE).strip()[:24]
        nickname = nickname or 'Player ' + session_id[:6].upper()
        with self.transaction() as db:
            db.execute('INSERT INTO arena_sessions(id,token_hash,nickname,created,challenge_id) VALUES (?,?,?,?,?)',
                       (session_id, hashlib.sha256(token.encode()).hexdigest(), nickname, time.time(), challenge_id))
        return {'session_id': session_id, 'participant_name': nickname, 'session_token': token, 'challenge_id': challenge_id}

    def session(self, token):
        if not token or len(token) > 128:
            return None
        with self.lock:
            row = self.db.execute('SELECT id,nickname,challenge_id FROM arena_sessions WHERE token_hash=?',
                                  (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return {'session_id': row['id'], 'participant_name': row['nickname'], 'challenge_id': row['challenge_id']} if row else None

    def set_challenge(self, session_id, challenge_id):
        with self.transaction() as db:
            db.execute('UPDATE arena_sessions SET challenge_id=? WHERE id=?', (challenge_id, session_id))

    def latest_named_session(self, max_age_seconds=7200):
        with self.lock:
            row = self.db.execute('''SELECT id,nickname,challenge_id FROM arena_sessions 
                                     WHERE nickname NOT LIKE 'Player %' AND nickname != 'Connection check' 
                                     AND created > ? ORDER BY created DESC LIMIT 1''',
                                  (time.time() - max_age_seconds,)).fetchone()
            if row:
                return {'session_id': row['id'], 'participant_name': row['nickname'], 'challenge_id': row['challenge_id']}
            return None

    def record_participant_prompt(self, participant_name: str, prompt: str, points: int = 0):
        if not participant_name or not prompt:
            return
        participant_name = participant_name.strip()[:32]
        clean_prompt = prompt.strip()[:500]
        with self.transaction() as db:
            db.execute('''
                INSERT INTO arena_prompts (participant_name, prompt, points, updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(participant_name) DO UPDATE SET
                    prompt = CASE WHEN excluded.points >= arena_prompts.points THEN excluded.prompt ELSE arena_prompts.prompt END,
                    points = MAX(arena_prompts.points, excluded.points),
                    updated = excluded.updated
            ''', (participant_name, clean_prompt, points, time.time()))

    def register_contestant(self, name: str, email: str = '', phone: str = '', session_id: str = ''):
        name = (name or '').strip()[:64]
        email = (email or '').strip()[:128]
        phone = (phone or '').strip()[:32]
        session_id = session_id or str(uuid.uuid4())
        with self.transaction() as db:
            db.execute('''
                INSERT INTO arena_contestants (session_id, name, email, phone, created)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, name, email, phone, time.time()))
        return {'status': 'registered', 'session_id': session_id, 'name': name, 'email': email, 'phone': phone}

    def record_human_evaluation(self, name: str, session_id: str, score: int, notes: str = '', evaluations: list = None):
        name = (name or '').strip()[:64]
        score = max(0, int(score or 0))
        notes = (notes or '').strip()[:500]
        eval_json = json.dumps(evaluations or [])
        with self.transaction() as db:
            # Update contestant record if exists
            db.execute('''
                UPDATE arena_contestants
                SET total_score = ?, evaluator_notes = ?, evaluations_json = ?, evaluation_mode = 'human'
                WHERE name = ? OR session_id = ?
            ''', (score, notes, eval_json, name, session_id))
            
            # Also update arena_prompts so live leaderboard shows the official human evaluated score
            best_prompt = 'Human Evaluated Red Team Run'
            if evaluations and len(evaluations) > 0:
                best_prompt = evaluations[0].get('prompt', best_prompt)
            db.execute('''
                INSERT INTO arena_prompts (participant_name, prompt, points, updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(participant_name) DO UPDATE SET
                    prompt = excluded.prompt,
                    points = excluded.points,
                    updated = excluded.updated
            ''', (name, best_prompt, score, time.time()))
        return {'status': 'saved', 'name': name, 'score': score}

    def list_contestants(self, limit: int = 100):
        with self.lock:
            rows = self.db.execute('''
                SELECT id, session_id, name, email, phone, created, total_score, attempts, evaluation_mode, evaluator_notes
                FROM arena_contestants
                ORDER BY created DESC LIMIT ?
            ''', (limit,)).fetchall()
        return [dict(r) for r in rows]

    def participant(self, session_id):
        with self.lock:
            row = self.db.execute('''SELECT COUNT(*) queries,COALESCE(SUM(points),0) points,
                COALESCE(SUM(attack),0) attempts,COALESCE(SUM(outcome='SUCCESSFUL'),0) successes
                FROM arena_events WHERE session_id=? AND simulated=?''', (session_id, self.config.demo)).fetchone()
            rows = self.db.execute('SELECT seq,payload FROM arena_events WHERE session_id=? AND simulated=? ORDER BY seq DESC LIMIT 8',
                                   (session_id, self.config.demo)).fetchall()
        return dict(row, events=[dict(json.loads(r['payload']), seq=r['seq']) for r in rows])

    def save(self, event, prompt_hash):
        with self.transaction() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload,seq FROM arena_events WHERE event_id=?', (event['event_id'],)).fetchone()
            if existing:
                return dict(json.loads(existing['payload']), seq=existing['seq'])
            args = (event['session_id'], event['simulated'])
            duplicate = db.execute('SELECT 1 FROM arena_events WHERE session_id=? AND simulated=? AND prompt_hash=? LIMIT 1', (*args, prompt_hash)).fetchone()
            novel = not db.execute('SELECT 1 FROM arena_events WHERE session_id=? AND simulated=? AND category=? AND attack=1 LIMIT 1', (*args, event['attack_category'])).fetchone()
            earned = db.execute('SELECT COALESCE(SUM(points),0) FROM arena_events WHERE session_id=? AND simulated=? AND created>?', (*args, time.time() - 3600)).fetchone()[0]
            event['points'] = self.scoring.points(event, bool(duplicate), novel, earned)
            event['duplicate_prompt'] = bool(duplicate)
            cursor = db.execute('INSERT INTO arena_events(event_id,session_id,created,simulated,prompt_hash,category,attack,outcome,points,payload) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (event['event_id'], event['session_id'], time.time(), event['simulated'], prompt_hash,
                 event['attack_category'], event['attack_detected'], event['outcome'], event['points'], json.dumps(event)))
            return dict(event, seq=cursor.lastrowid)

    def events(self, after=0, limit=100, newest=False):
        with self.lock:
            rows = self.db.execute('SELECT seq,payload FROM arena_events WHERE simulated=? AND seq>? ORDER BY seq ' + ('DESC' if newest else 'ASC') + ' LIMIT ?',
                                   (self.config.demo, after, limit)).fetchall()
        return [dict(json.loads(row['payload']), seq=row['seq']) for row in rows]

    def detail(self, event_id):
        with self.lock:
            row = self.db.execute('SELECT seq,payload FROM arena_events WHERE event_id=? AND simulated=?', (event_id, self.config.demo)).fetchone()
        return dict(json.loads(row['payload']), seq=row['seq']) if row else None

    def snapshot(self):
        # A single read transaction gives metrics and cursor a consistent boundary.
        with self.transaction() as db:
            db.execute('BEGIN')
            mode = (self.config.demo,)
            total = db.execute('''SELECT COUNT(*) queries, COALESCE(SUM(attack),0) attacks,
                COALESCE(SUM(points),0) points, COUNT(DISTINCT session_id) participants,
                AVG(json_extract(payload,'$.response_time_ms')) latency,
                COALESCE(SUM(attack AND json_extract(payload,'$.risk_score')>=70),0) high_risk,
                AVG(CASE WHEN attack THEN json_extract(payload,'$.risk_score') END) risk,
                MAX(seq) cursor FROM arena_events WHERE simulated=?''', mode).fetchone()
            outcomes = dict(db.execute('SELECT outcome,COUNT(*) FROM arena_events WHERE simulated=? AND attack=1 GROUP BY outcome', mode).fetchall())
            distribution = [{'category': r[0], 'count': r[1], 'successful': r[2]} for r in db.execute("SELECT category,COUNT(*),SUM(outcome='SUCCESSFUL') FROM arena_events WHERE simulated=? AND attack=1 GROUP BY category ORDER BY COUNT(*) DESC", mode)]
            severity = dict(db.execute("SELECT json_extract(payload,'$.severity'),COUNT(*) FROM arena_events WHERE simulated=? AND attack=1 GROUP BY 1", mode).fetchall())
            # Leaderboard queries arena_prompts for all exhibition contestants (including human evaluations)
            leaderboard = [dict(r) for r in db.execute("""
                SELECT 
                    COALESCE(e.session_id, c.session_id, 'arena') session_id,
                    p.participant_name,
                    p.prompt,
                    'open' challenge_id,
                    p.points points,
                    COALESCE(e.attempts, c.attempts, 1) attempts,
                    COALESCE(e.successes, 0) successes,
                    0 legacy_points
                FROM arena_prompts p
                LEFT JOIN arena_contestants c ON c.name = p.participant_name
                LEFT JOIN (
                    SELECT 
                        json_extract(payload, '$.participant_name') as part_name,
                        MAX(session_id) as session_id,
                        SUM(attack) as attempts,
                        SUM(outcome = 'SUCCESSFUL') as successes
                    FROM arena_events
                    WHERE simulated = ?
                    GROUP BY json_extract(payload, '$.participant_name')
                ) e ON e.part_name = p.participant_name
                ORDER BY p.points DESC, p.updated DESC
                LIMIT 25
            """, mode)]
            if not leaderboard:
                leaderboard = [dict(r) for r in db.execute("""SELECT session_id, json_extract(payload,'$.participant_name') participant_name,
                    COALESCE((SELECT prompt FROM arena_prompts WHERE arena_prompts.participant_name = json_extract(arena_events.payload,'$.participant_name')), 'Adversarial probe') prompt,
                    COALESCE((SELECT challenge_id FROM arena_sessions WHERE arena_sessions.nickname = json_extract(arena_events.payload,'$.participant_name') ORDER BY created DESC LIMIT 1), 'open') challenge_id,
                    SUM(points) points, SUM(attack) attempts, SUM(outcome='SUCCESSFUL') successes, SUM(CASE WHEN json_extract(payload,'$.scoring_version') IS NULL THEN points ELSE 0 END) legacy_points FROM arena_events WHERE simulated=?
                    GROUP BY json_extract(payload,'$.participant_name') HAVING (SUM(points)>0 OR SUM(attack)>0) ORDER BY successes DESC,points DESC,attempts DESC,MIN(seq) ASC LIMIT 15""", mode)]
            active = db.execute('SELECT COUNT(DISTINCT session_id) FROM arena_events WHERE simulated=? AND created>?', (*mode, time.time()-300)).fetchone()[0]
            recent_attack = db.execute('SELECT MAX(created) FROM arena_events WHERE simulated=? AND attack=1', mode).fetchone()[0]
            timeline = [dict(r) for r in db.execute("SELECT CAST(created/60 AS INTEGER)*60 minute,outcome,COUNT(*) count FROM arena_events WHERE simulated=? AND attack=1 AND created>? GROUP BY minute,outcome ORDER BY minute", (*mode, time.time()-1800))]
            latest = db.execute('SELECT payload,seq FROM arena_events WHERE simulated=? AND attack=1 ORDER BY seq DESC LIMIT 1', mode).fetchone()
            events = self.events(limit=60, newest=True)
            # A chain is consecutive adversarial submissions within an arena session.
            longest = db.execute('''WITH grouped AS (
                SELECT session_id,attack,SUM(CASE WHEN attack=0 THEN 1 ELSE 0 END)
                OVER (PARTITION BY session_id ORDER BY seq) grp
                FROM arena_events WHERE simulated=?), chains AS (
                SELECT COUNT(*) n FROM grouped WHERE attack=1 GROUP BY session_id,grp)
                SELECT COALESCE(MAX(n),0) FROM chains''', mode).fetchone()[0]
            fastest = db.execute("SELECT MIN(json_extract(payload,'$.timings.classification_ms')) FROM arena_events WHERE simulated=? AND attack=1", mode).fetchone()[0]
        attacks = total['attacks']
        defended = outcomes.get('BLOCKED', 0) + outcomes.get('DEFENDED', 0)
        assessed = defended + outcomes.get('SUCCESSFUL', 0) + outcomes.get('PARTIAL', 0)
        eligible = [d for d in distribution if d['count'] >= 5]
        hardest = max(eligible, key=lambda d: d['successful']/d['count'], default=None)
        return {'cursor': total['cursor'] or 0, 'simulated': self.config.demo, 'events': events,
                'latest': dict(json.loads(latest['payload']), seq=latest['seq']) if latest else None,
                'stats': {'total_queries': total['queries'], 'attack_attempts': attacks,
                          'blocked': outcomes.get('BLOCKED', 0), 'successful': outcomes.get('SUCCESSFUL', 0),
                          'defended': outcomes.get('DEFENDED', 0), 'unknown': outcomes.get('UNKNOWN', 0),
                          'partial': outcomes.get('PARTIAL', 0),
                          'defense_rate': round(100 * defended / assessed, 1) if assessed else None,
                          'confirmed_defense_share': round(100 * defended / attacks, 1) if attacks else None,
                          'evaluation_coverage': round(100 * assessed / attacks, 1) if attacks else None,
                          'assessed_attacks': assessed,
                          'attack_success_rate': round(100 * outcomes.get('SUCCESSFUL', 0) / assessed, 1) if assessed else None,
                          'sample_warning': assessed < 20,
                          'average_response_ms': round(total['latency']) if total['latency'] is not None else None,
                          'high_risk': total['high_risk'], 'active_participants': active,
                          'unique_participants': total['participants'], 'points': total['points'],
                          'average_risk': round(total['risk'], 1) if total['risk'] is not None else None,
                          'longest_chain': longest, 'fastest_detection_ms': fastest,
                          'most_common': distribution[0]['category'] if attacks >= 5 else None,
                          'hardest_category': hardest['category'] if hardest and hardest['successful'] else None,
                          'most_successful_category': max(eligible, key=lambda d:d['successful'])['category'] if any(d['successful'] for d in eligible) else None,
                          'under_attack': bool(recent_attack and time.time()-recent_attack < 20)},
                'distribution': distribution, 'severity': severity, 'timeline': timeline, 'leaderboard': leaderboard}

    def clear_leaderboard(self):
        with self.transaction() as db:
            db.execute("DELETE FROM arena_events")
            db.execute("DELETE FROM arena_sessions")
            db.execute("DELETE FROM arena_prompts")
            db.execute("DELETE FROM arena_contestants")
            try:
                db.execute("VACUUM")
            except Exception:
                pass
        return {"status": "cleared"}

    def delete_participant(self, name: str):
        if not name:
            return {"status": "ignored"}
        name_clean = name.strip()
        with self.transaction() as db:
            db.execute("DELETE FROM arena_prompts WHERE participant_name = ?", (name_clean,))
            db.execute("DELETE FROM arena_contestants WHERE name = ?", (name_clean,))
            db.execute("DELETE FROM arena_events WHERE json_extract(payload, '$.participant_name') = ?", (name_clean,))
        return {"status": "deleted", "participant_name": name_clean}

    def close(self):
        with self.lock:
            self.db.close()
