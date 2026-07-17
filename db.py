import sqlite3
import json
import datetime
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'queuectl.db')

def get_connection():
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Create jobs table with all bonus feature columns
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            command     TEXT NOT NULL,
            state       TEXT NOT NULL,
            attempts    INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            priority    INTEGER DEFAULT 5,
            timeout     INTEGER DEFAULT NULL,
            run_at      TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            next_run_at TEXT NOT NULL,
            started_at  TEXT DEFAULT NULL,
            finished_at TEXT DEFAULT NULL,
            duration_ms INTEGER DEFAULT NULL,
            stdout      TEXT DEFAULT NULL,
            stderr      TEXT DEFAULT NULL,
            exit_code   INTEGER DEFAULT NULL,
            timed_out   INTEGER DEFAULT 0
        )
    ''')

    # Migrate existing tables -- add any missing columns silently
    _add_column_if_missing(cursor, 'jobs', 'priority',    'INTEGER DEFAULT 5')
    _add_column_if_missing(cursor, 'jobs', 'timeout',     'INTEGER DEFAULT NULL')
    _add_column_if_missing(cursor, 'jobs', 'run_at',      'TEXT')
    _add_column_if_missing(cursor, 'jobs', 'started_at',  'TEXT DEFAULT NULL')
    _add_column_if_missing(cursor, 'jobs', 'finished_at', 'TEXT DEFAULT NULL')
    _add_column_if_missing(cursor, 'jobs', 'duration_ms', 'INTEGER DEFAULT NULL')
    _add_column_if_missing(cursor, 'jobs', 'stdout',      'TEXT DEFAULT NULL')
    _add_column_if_missing(cursor, 'jobs', 'stderr',      'TEXT DEFAULT NULL')
    _add_column_if_missing(cursor, 'jobs', 'exit_code',   'INTEGER DEFAULT NULL')
    _add_column_if_missing(cursor, 'jobs', 'timed_out',   'INTEGER DEFAULT 0')

    # Create config table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Create metrics table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at  TEXT NOT NULL,
            total_jobs   INTEGER DEFAULT 0,
            pending      INTEGER DEFAULT 0,
            processing   INTEGER DEFAULT 0,
            completed    INTEGER DEFAULT 0,
            failed       INTEGER DEFAULT 0,
            dead         INTEGER DEFAULT 0,
            avg_duration_ms INTEGER DEFAULT NULL
        )
    ''')

    # Create workers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            current_job_id TEXT,
            last_heartbeat TEXT NOT NULL
        )
    ''')

    # Default config values
    defaults = [
        ('max-retries',  '3'),
        ('backoff-base', '2'),
        ('worker-shutdown', '0'),
        ('default-timeout', '0'),
        ('default-priority', '5'),
    ]
    for key, val in defaults:
        cursor.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (key, val))

    conn.close()

def _add_column_if_missing(cursor, table, column, col_def):
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [row['name'] for row in cursor.fetchall()]
    if column not in cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")

# --- Helpers ----------------------------------------------------------------

def get_current_time():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def get_config(key, default_value=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default_value

def set_config(key, value):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (key, str(value)))
    conn.close()

def update_worker_heartbeat(worker_id, status, current_job_id=None):
    conn = get_connection()
    cursor = conn.cursor()
    now = get_current_time()
    cursor.execute('''
        INSERT OR REPLACE INTO workers (id, status, current_job_id, last_heartbeat)
        VALUES (?, ?, ?, ?)
    ''', (worker_id, status, current_job_id, now))
    conn.close()

def get_workers():
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
    cursor.execute('SELECT * FROM workers WHERE last_heartbeat >= ? ORDER BY id', (cutoff,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# --- Job CRUD ----------------------------------------------------------------

def enqueue_job(job_id, command, priority=None, timeout=None, run_at=None):
    now = get_current_time()
    max_retries = int(get_config('max-retries', 3))
    if priority is None:
        priority = int(get_config('default-priority', 5))
    if timeout is None:
        t = int(get_config('default-timeout', 0))
        timeout = t if t > 0 else None
    if run_at is None:
        run_at = now

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO jobs
            (id, command, state, attempts, max_retries, priority, timeout,
             run_at, created_at, updated_at, next_run_at)
        VALUES (?, ?, 'pending', 0, ?, ?, ?, ?, ?, ?, ?)
    ''', (job_id, command, max_retries, priority, timeout, run_at, now, now, run_at))
    conn.close()
    return get_job(job_id)

def get_job(job_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM jobs WHERE id = ?', (job_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def dequeue_job():
    """Atomically claim the highest-priority job that is ready to run."""
    conn = get_connection()
    cursor = conn.cursor()
    now = get_current_time()

    cursor.execute('BEGIN EXCLUSIVE')
    try:
        cursor.execute('''
            SELECT id FROM jobs
            WHERE (state = 'pending' AND run_at <= ?)
               OR (state = 'failed'  AND next_run_at <= ?)
            ORDER BY priority ASC, next_run_at ASC, created_at ASC
            LIMIT 1
        ''', (now, now))

        row = cursor.fetchone()
        if not row:
            cursor.execute('COMMIT')
            conn.close()
            return None

        job_id = row['id']
        cursor.execute('''
            UPDATE jobs
            SET state = 'processing', updated_at = ?, started_at = ?
            WHERE id = ?
        ''', (now, now, job_id))
        cursor.execute('COMMIT')

        cursor.execute('SELECT * FROM jobs WHERE id = ?', (job_id,))
        job = cursor.fetchone()
        conn.close()
        return dict(job)
    except sqlite3.Error as e:
        cursor.execute('ROLLBACK')
        conn.close()
        raise e

def finish_job(job_id, state, attempts, next_run_at,
               stdout=None, stderr=None, exit_code=None,
               duration_ms=None, timed_out=False):
    conn = get_connection()
    cursor = conn.cursor()
    now = get_current_time()
    cursor.execute('''
        UPDATE jobs
        SET state=?, attempts=?, updated_at=?, next_run_at=?,
            finished_at=?, stdout=?, stderr=?, exit_code=?,
            duration_ms=?, timed_out=?
        WHERE id=?
    ''', (state, attempts, now, next_run_at,
          now, stdout, stderr, exit_code,
          duration_ms, 1 if timed_out else 0, job_id))
    conn.close()

def list_jobs(state=None, priority=None, limit=None):
    conn = get_connection()
    cursor = conn.cursor()
    sql  = 'SELECT * FROM jobs WHERE 1=1'
    params = []
    if state:
        sql += ' AND state = ?'; params.append(state)
    if priority is not None:
        sql += ' AND priority = ?'; params.append(priority)
    sql += ' ORDER BY priority ASC, created_at ASC'
    if limit:
        sql += ' LIMIT ?'; params.append(limit)
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_status():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT state, COUNT(*) AS cnt FROM jobs GROUP BY state')
    rows = cursor.fetchall()
    conn.close()
    return {r['state']: r['cnt'] for r in rows}

def retry_dlq_job(job_id):
    conn = get_connection()
    cursor = conn.cursor()
    now = get_current_time()
    cursor.execute('BEGIN EXCLUSIVE')
    try:
        cursor.execute('SELECT state FROM jobs WHERE id = ?', (job_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute('ROLLBACK'); conn.close()
            return False, "Job not found."
        if row['state'] != 'dead':
            cursor.execute('ROLLBACK'); conn.close()
            return False, "Job is not in the dead letter queue."
        cursor.execute('''
            UPDATE jobs
            SET state='pending', attempts=0, updated_at=?,
                next_run_at=?, run_at=?, timed_out=0
            WHERE id=?
        ''', (now, now, now, job_id))
        cursor.execute('COMMIT')
        conn.close()
        return True, "Job successfully reset to pending."
    except sqlite3.Error as e:
        cursor.execute('ROLLBACK'); conn.close()
        return False, str(e)

# --- Metrics -----------------------------------------------------------------

def retry_all_dlq_jobs():
    conn = get_connection()
    cursor = conn.cursor()
    now = get_current_time()
    cursor.execute('BEGIN EXCLUSIVE')
    try:
        cursor.execute("SELECT id FROM jobs WHERE state = 'dead'")
        rows = cursor.fetchall()
        count = len(rows)
        if count == 0:
            cursor.execute('ROLLBACK'); conn.close()
            return True, 0, "No dead jobs found."
        
        cursor.execute('''
            UPDATE jobs
            SET state='pending', attempts=0, updated_at=?,
                next_run_at=?, run_at=?, timed_out=0
            WHERE state='dead'
        ''', (now, now, now))
        cursor.execute('COMMIT')
        conn.close()
        return True, count, f"Successfully reset {count} dead job(s) to pending."
    except sqlite3.Error as e:
        cursor.execute('ROLLBACK'); conn.close()
        return False, 0, str(e)

def record_metrics():
    conn = get_connection()
    cursor = conn.cursor()
    now = get_current_time()

    cursor.execute('SELECT state, COUNT(*) AS cnt FROM jobs GROUP BY state')
    counts = {r['state']: r['cnt'] for r in cursor.fetchall()}

    cursor.execute('''
        SELECT AVG(duration_ms) AS avg_ms FROM jobs
        WHERE state = 'completed' AND duration_ms IS NOT NULL
    ''')
    avg_row = cursor.fetchone()
    avg_ms = int(avg_row['avg_ms']) if avg_row and avg_row['avg_ms'] else None

    total = sum(counts.values())
    cursor.execute('''
        INSERT INTO metrics
            (recorded_at, total_jobs, pending, processing, completed, failed, dead, avg_duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (now, total,
          counts.get('pending', 0),
          counts.get('processing', 0),
          counts.get('completed', 0),
          counts.get('failed', 0),
          counts.get('dead', 0),
          avg_ms))
    conn.close()

def get_metrics_summary():
    conn = get_connection()
    cursor = conn.cursor()

    # Overall stats
    cursor.execute('''
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN state='completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN state='dead'      THEN 1 ELSE 0 END) AS dead,
            SUM(CASE WHEN state='failed'    THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN timed_out=1       THEN 1 ELSE 0 END) AS timed_out,
            AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) AS avg_duration_ms,
            MIN(duration_ms) AS min_duration_ms,
            MAX(duration_ms) AS max_duration_ms
        FROM jobs
    ''')
    row = cursor.fetchone()
    summary = dict(row)

    # Per-priority breakdown
    cursor.execute('''
        SELECT priority, COUNT(*) AS cnt,
               SUM(CASE WHEN state='completed' THEN 1 ELSE 0 END) AS completed
        FROM jobs GROUP BY priority ORDER BY priority
    ''')
    summary['by_priority'] = [dict(r) for r in cursor.fetchall()]

    # Recent history (last 20 metric snapshots)
    cursor.execute('''
        SELECT * FROM metrics ORDER BY recorded_at DESC LIMIT 20
    ''')
    summary['history'] = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return summary

def get_all_jobs_for_dashboard():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM jobs ORDER BY priority ASC, created_at DESC LIMIT 200')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
