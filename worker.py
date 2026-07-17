import time
import subprocess
import signal
import sys
import os
import datetime
import threading
import db

# Global flag for graceful shutdown (set by signal handler OR db config poll)
_shutdown_requested = False

def handle_shutdown(signum, frame):
    global _shutdown_requested
    print("\n[Worker] Shutdown signal received. Finishing current job before exiting...")
    _shutdown_requested = True

def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)

def fmt_time(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def calculate_next_run(base, attempts):
    """Exponential backoff: delay = base ^ attempts seconds."""
    delay = int(base) ** attempts
    return fmt_time(now_utc() + datetime.timedelta(seconds=delay))

# --- Job execution ----------------------------------------------------------

def process_job(job, worker_id):
    job_id   = job['id']
    command  = job['command']
    timeout  = job['timeout']  # None or int seconds
    priority = job['priority']

    print(f"[Worker {worker_id}] Picking up job '{job_id}' "
          f"(priority={priority}, timeout={'inf' if not timeout else f'{timeout}s'}): {command}")

    start = now_utc()
    stdout_data = ''
    stderr_data = ''
    exit_code   = None
    timed_out   = False

    try:
        # Use Popen instead of run() so we can forcibly kill the tree on timeout
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout_data, stderr_data = proc.communicate(
                timeout=timeout if timeout and timeout > 0 else None
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            # Kill the entire process tree (important on Windows)
            try:
                if sys.platform == 'win32':
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    import signal as _sig
                    import os as _os
                    _os.killpg(_os.getpgid(proc.pid), _sig.SIGKILL)
            except Exception:
                proc.kill()
            proc.wait()
            stdout_data, stderr_data = '', ''
            exit_code   = -1
            duration_ms = int((now_utc() - start).total_seconds() * 1000)
            timed_out   = True
            print(f"[Worker {worker_id}] Job '{job_id}' TIMED OUT after {timeout}s")
            _log_output(job_id, stdout_data, stderr_data, timed_out=True)
            _handle_failure(job, worker_id, exit_code, duration_ms,
                            stdout_data, stderr_data, timed_out=True)
            return
        stdout_data = stdout_data or ''
        stderr_data = stderr_data or ''
        duration_ms = int((now_utc() - start).total_seconds() * 1000)

        if exit_code != 0:
            raise subprocess.CalledProcessError(exit_code, command,
                                                stdout_data, stderr_data)

        print(f"[Worker {worker_id}] Job '{job_id}' completed in {duration_ms}ms")
        _log_output(job_id, stdout_data, stderr_data)

        db.finish_job(
            job_id, 'completed', job['attempts'],
            job['next_run_at'],
            stdout=stdout_data, stderr=stderr_data,
            exit_code=exit_code, duration_ms=duration_ms
        )

    except subprocess.CalledProcessError as e:
        duration_ms = int((now_utc() - start).total_seconds() * 1000)
        stdout_data = e.stdout or ''
        stderr_data = e.stderr or ''
        exit_code   = e.returncode
        print(f"[Worker {worker_id}] Job '{job_id}' FAILED "
              f"(exit={exit_code}) in {duration_ms}ms [x]")
        _log_output(job_id, stdout_data, stderr_data)
        _handle_failure(job, worker_id, exit_code, duration_ms,
                        stdout_data, stderr_data)

def _handle_failure(job, worker_id, exit_code, duration_ms,
                    stdout, stderr, timed_out=False):
    attempts    = job['attempts'] + 1
    max_retries = job['max_retries']
    job_id      = job['id']

    if attempts >= max_retries:
        print(f"[Worker {worker_id}] Job '{job_id}' exhausted {max_retries} retries -> DLQ")
        db.finish_job(job_id, 'dead', attempts, job['next_run_at'],
                      stdout=stdout, stderr=stderr,
                      exit_code=exit_code, duration_ms=duration_ms,
                      timed_out=timed_out)
    else:
        base = int(db.get_config('backoff-base', 2))
        next_run = calculate_next_run(base, attempts)
        print(f"[Worker {worker_id}] Job '{job_id}' will retry "
              f"(attempt {attempts}/{max_retries}) at {next_run}")
        db.finish_job(job_id, 'failed', attempts, next_run,
                      stdout=stdout, stderr=stderr,
                      exit_code=exit_code, duration_ms=duration_ms,
                      timed_out=timed_out)

# --- Output logging ----------------------------------------------------------

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'job_logs')

def _log_output(job_id, stdout, stderr, timed_out=False):
    """Write captured stdout/stderr to a log file for the job."""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{job_id}.log")
    ts = fmt_time(now_utc())
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"Timestamp : {ts}\n")
        if timed_out:
            f.write("Result    : TIMED OUT\n")
        f.write(f"STDOUT:\n{stdout or '(empty)'}\n")
        f.write(f"STDERR:\n{stderr or '(empty)'}\n")

# --- Worker loop -------------------------------------------------------------

def _should_shutdown():
    """Check DB config for a graceful stop signal (cross-process communication)."""
    return db.get_config('worker-shutdown', '0') == '1'

def start_worker(worker_id):
    global _shutdown_requested

    # Register OS-level signal handlers
    try:
        signal.signal(signal.SIGINT,  handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)
    except (OSError, ValueError):
        pass  # May not be main thread on some platforms

    db.init_db()
    print(f"[Worker {worker_id}] Started. PID={os.getpid()}")

    while not _shutdown_requested:
        # Also respect DB-driven stop signal
        if _should_shutdown():
            print(f"[Worker {worker_id}] DB stop signal detected. Exiting.")
            break

        db.update_worker_heartbeat(worker_id, 'Idle')
        job = db.dequeue_job()
        if job:
            db.update_worker_heartbeat(worker_id, 'Running', job['id'])
            process_job(job, worker_id)
            # Snapshot metrics after every job
            try:
                db.record_metrics()
            except Exception:
                pass
            db.update_worker_heartbeat(worker_id, 'Idle')
        else:
            time.sleep(1)

    print(f"[Worker {worker_id}] Shutdown complete.")
