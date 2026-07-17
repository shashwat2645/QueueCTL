import argparse
import json
import sys
import os
import subprocess
import db
import worker

# --- Enqueue -----------------------------------------------------------------

def cmd_enqueue(args):
    try:
        job_data = json.loads(args.job_json)
    except json.JSONDecodeError:
        print("Error: Invalid JSON provided.")
        sys.exit(1)

    if 'id' not in job_data or 'command' not in job_data:
        print("Error: JSON must contain 'id' and 'command' fields.")
        sys.exit(1)

    db.init_db()

    if db.get_job(job_data['id']):
        print(f"Error: Job with id '{job_data['id']}' already exists.")
        sys.exit(1)

    # Optional bonus-feature fields from JSON
    priority = job_data.get('priority', None)
    timeout  = job_data.get('timeout',  None)
    run_at   = job_data.get('run_at',   None)

    # Validate priority
    if priority is not None:
        try:
            priority = int(priority)
            if not (1 <= priority <= 10):
                raise ValueError
        except (ValueError, TypeError):
            print("Error: 'priority' must be an integer between 1 (highest) and 10 (lowest).")
            sys.exit(1)

    # Validate timeout
    if timeout is not None:
        try:
            timeout = int(timeout)
            if timeout < 0:
                raise ValueError
        except (ValueError, TypeError):
            print("Error: 'timeout' must be a non-negative integer (seconds). Use 0 for no timeout.")
            sys.exit(1)
        timeout = timeout if timeout > 0 else None

    job = db.enqueue_job(
        job_data['id'], job_data['command'],
        priority=priority, timeout=timeout, run_at=run_at
    )
    print(f"Enqueued job: {job['id']} "
          f"(priority={job['priority']}, "
          f"run_at={job['run_at']}, "
          f"timeout={job['timeout'] or 'inf'}s)")

# --- Worker -------------------------------------------------------------------

def cmd_worker_start(args):
    db.init_db()
    db.set_config('worker-shutdown', '0')
    count = args.count
    print(f"Starting {count} worker(s)...")

    script_path = os.path.abspath(__file__)

    for i in range(count):
        creationflags = 0
        kwargs = {}
        if sys.platform == 'win32':
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs['start_new_session'] = True

        subprocess.Popen(
            [sys.executable, script_path, '_run_worker', str(i + 1)],
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs
        )

    print(f"Successfully started {count} background worker(s).")

def cmd_worker_stop(args):
    db.init_db()
    db.set_config('worker-shutdown', '1')
    print("Stop signal sent. Workers will finish their current jobs and exit gracefully.")

# --- Status -------------------------------------------------------------------

def cmd_status(args):
    db.init_db()
    status = db.get_status()
    print("-" * 32)
    print("  Job Status Summary")
    print("-" * 32)
    if not status:
        print("  No jobs found.")
    else:
        for state, count in status.items():
            icon = {
                'pending':    '[~]',
                'processing': '[>]',
                'completed':  '[+]',
                'failed':     '[!]',
                'dead':       '[x]',
            }.get(state, '[ ]')
            print(f"  {icon}  {state.capitalize():<12} {count}")
    print("-" * 32)

# --- List ---------------------------------------------------------------------

def cmd_list(args):
    db.init_db()
    state    = getattr(args, 'state',    None)
    priority = getattr(args, 'priority', None)
    limit    = getattr(args, 'limit',    None)
    verbose  = getattr(args, 'verbose',  False)

    jobs = db.list_jobs(state=state, priority=priority, limit=limit)
    if not jobs:
        print("No jobs found.")
        return

    for job in jobs:
        if verbose:
            print(json.dumps(job, indent=2))
        else:
            # Compact one-liner
            print(
                f"[{job['state'].upper():<10}] "
                f"id={job['id']:<20} "
                f"pri={job['priority']} "
                f"attempts={job['attempts']}/{job['max_retries']} "
                f"run_at={job['run_at']} "
                f"cmd={job['command']}"
            )

# --- Logs ---------------------------------------------------------------------

def cmd_logs(args):
    db.init_db()
    job = db.get_job(args.job_id)
    if not job:
        print(f"Error: Job '{args.job_id}' not found.")
        sys.exit(1)

    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'job_logs', f"{args.job_id}.log"
    )

    print(f"--- Job: {job['id']} --- State: {job['state']} ---")
    print(f"Command  : {job['command']}")
    print(f"Attempts : {job['attempts']} / {job['max_retries']}")
    print(f"Duration : {job['duration_ms']}ms" if job['duration_ms'] else "Duration : N/A")
    print(f"Timed out: {'Yes' if job['timed_out'] else 'No'}")

    if args.stdout:
        print("\n-- STDOUT --")
        print(job['stdout'] or "(empty)")
    if args.stderr:
        print("\n-- STDERR --")
        print(job['stderr'] or "(empty)")

    if not args.stdout and not args.stderr:
        if os.path.exists(log_path):
            print(f"\n-- Full log ({log_path}) --")
            with open(log_path, encoding='utf-8') as f:
                print(f.read())
        else:
            print("\n(No log file yet -- job may not have run)")

# --- Metrics ------------------------------------------------------------------

def cmd_metrics(args):
    db.init_db()
    m = db.get_metrics_summary()
    total     = m.get('total') or 0
    completed = m.get('completed') or 0
    dead      = m.get('dead') or 0
    failed    = m.get('failed') or 0
    timed_out = m.get('timed_out') or 0
    avg_ms    = m.get('avg_duration_ms')
    min_ms    = m.get('min_duration_ms')
    max_ms    = m.get('max_duration_ms')

    success_rate = (completed / total * 100) if total else 0.0

    print("-" * 40)
    print("  Execution Metrics")
    print("-" * 40)
    print(f"  Total jobs      : {total}")
    print(f"  Completed       : {completed}")
    print(f"  Failed (DLQ)    : {dead}")
    print(f"  Awaiting retry  : {failed}")
    print(f"  Timed out       : {timed_out}")
    print(f"  Success rate    : {success_rate:.1f}%")
    print("-" * 40)
    print(f"  Avg duration    : {avg_ms:.0f}ms" if avg_ms else "  Avg duration    : N/A")
    print(f"  Min duration    : {min_ms}ms"      if min_ms else "  Min duration    : N/A")
    print(f"  Max duration    : {max_ms}ms"      if max_ms else "  Max duration    : N/A")
    print("-" * 40)

    if m.get('by_priority'):
        print("  By Priority:")
        for bp in m['by_priority']:
            print(f"    Priority {bp['priority']}: {bp['cnt']} jobs, "
                  f"{bp['completed']} completed")
        print("-" * 40)

# --- DLQ ----------------------------------------------------------------------

def cmd_dlq_list(args):
    db.init_db()
    jobs = db.list_jobs(state='dead')
    if not jobs:
        print("Dead Letter Queue is empty.")
        return
    print(f"Dead Letter Queue ({len(jobs)} job(s)):")
    for job in jobs:
        print(f"  id={job['id']} attempts={job['attempts']} timed_out={bool(job['timed_out'])} cmd={job['command']}")

def cmd_dlq_retry(args):
    db.init_db()
    success, msg = db.retry_dlq_job(args.job_id)
    if success:
        print(f"[OK] Job '{args.job_id}' reset to pending and queued for retry.")
    else:
        print(f"Error: {msg}")

def cmd_dlq_retry_all(args):
    db.init_db()
    success, count, msg = db.retry_all_dlq_jobs()
    if success:
        if count > 0:
            print(f"[OK] {msg}")
        else:
            print(msg)
    else:
        print(f"Error: {msg}")

# --- Config -------------------------------------------------------------------

def cmd_config_set(args):
    db.init_db()
    db.set_config(args.key, args.value)
    print(f"Config '{args.key}' set to '{args.value}'")

def cmd_config_get(args):
    db.init_db()
    value = db.get_config(args.key)
    if value is None:
        print(f"Config key '{args.key}' not found.")
    else:
        print(f"{args.key} = {value}")

# --- Dashboard ----------------------------------------------------------------

def cmd_dashboard(args):
    """Launch the web dashboard (a tiny built-in HTTP server)."""
    import http.server
    import socketserver
    import threading
    import webbrowser

    db.init_db()
    port = args.port
    dashboard_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard')

    class DashboardHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            pass  # suppress access logs

        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/':
                self.serve_file('index.html', 'text/html')
            elif path == '/style.css':
                self.serve_file('style.css', 'text/css')
            elif path == '/app.js':
                self.serve_file('app.js', 'application/javascript')

            elif path == '/api/jobs':
                jobs = db.get_all_jobs_for_dashboard()
                self._json(jobs)

            elif path == '/api/metrics':
                m = db.get_metrics_summary()
                self._json(m)

            elif path == '/api/status':
                s = db.get_status()
                # Also include active workers count in status
                workers = db.get_workers()
                s['workers'] = len(workers)
                
                # We need pending_jobs, processing_jobs, failed_jobs, dead_jobs to match the frontend expectations
                s['pending_jobs'] = s.get('pending', 0)
                s['processing_jobs'] = s.get('processing', 0)
                s['failed_jobs'] = s.get('failed', 0)
                s['dead_jobs'] = s.get('dead', 0)
                s['completed_jobs'] = s.get('completed', 0)
                
                self._json(s)

            elif path == '/api/workers':
                workers = db.get_workers()
                self._json(workers)

            elif path == '/api/config':
                cfg = {
                    'max_retries': db.get_config('max-retries', '3'),
                    'backoff_base': db.get_config('backoff-base', '2'),
                    'default_priority': db.get_config('default-priority', '5'),
                    'default_timeout': db.get_config('default-timeout', '0'),
                }
                self._json(cfg)

            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)

            if self.path == '/api/dlq/retry':
                try:
                    data    = json.loads(body)
                    job_id  = data['job_id']
                    ok, msg = db.retry_dlq_job(job_id)
                    self._json({'ok': ok, 'message': msg})
                except Exception as e:
                    self._json({'ok': False, 'message': str(e)})
            else:
                self.send_response(404)
                self.end_headers()

        def _json(self, obj):
            payload = json.dumps(obj, default=str).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)

        def serve_file(self, filename, content_type):
            filepath = os.path.join(dashboard_dir, filename)
            try:
                with open(filepath, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")

    class ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        pass

    with ThreadingServer(('', port), DashboardHandler) as httpd:
        url = f"http://localhost:{port}"
        print(f"[OK] Dashboard running at {url}")
        print("   Press Ctrl+C to stop.")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")

def cmd_run_worker(args):
    db.init_db()
    worker.start_worker(args.worker_id)

# --- Main CLI -----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="QueueCTL - Background Job Queue System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Enqueue a simple job:
    queuectl enqueue '{"id":"job1","command":"echo hi"}'

  Enqueue with priority (1=highest) and timeout:
    queuectl enqueue '{"id":"job2","command":"sleep 10","priority":1,"timeout":5}'

  Schedule a job for later (ISO-8601 UTC):
    queuectl enqueue '{"id":"job3","command":"echo later","run_at":"2025-12-01T00:00:00Z"}'

  Start 3 workers:
    queuectl worker start --count 3

  Open web dashboard:
    queuectl dashboard
"""
    )
    sub = parser.add_subparsers(dest="command")

    # enqueue
    p = sub.add_parser("enqueue", help="Add a job to the queue")
    p.add_argument("job_json", help='JSON with required "id" and "command", optional "priority","timeout","run_at"')
    p.set_defaults(func=cmd_enqueue)

    # worker
    pw = sub.add_parser("worker", help="Manage workers")
    ws = pw.add_subparsers(dest="worker_command")
    p_start = ws.add_parser("start", help="Start background workers")
    p_start.add_argument("--count", type=int, default=1, help="Number of workers")
    p_start.set_defaults(func=cmd_worker_start)
    p_stop = ws.add_parser("stop", help="Gracefully stop all workers")
    p_stop.set_defaults(func=cmd_worker_stop)

    # status
    p = sub.add_parser("status", help="Show job state summary")
    p.set_defaults(func=cmd_status)

    # list
    p = sub.add_parser("list", help="List jobs")
    p.add_argument("--state",    help="Filter by state")
    p.add_argument("--priority", type=int, help="Filter by priority")
    p.add_argument("--limit",    type=int, help="Max rows to return")
    p.add_argument("--verbose",  action="store_true", help="Show full JSON per job")
    p.set_defaults(func=cmd_list)

    # logs
    p = sub.add_parser("logs", help="View output logs for a job")
    p.add_argument("job_id",          help="Job ID")
    p.add_argument("--stdout",        action="store_true", help="Show only stdout")
    p.add_argument("--stderr",        action="store_true", help="Show only stderr")
    p.set_defaults(func=cmd_logs)

    # metrics
    p = sub.add_parser("metrics", help="Show execution statistics")
    p.set_defaults(func=cmd_metrics)

    # dlq
    pd = sub.add_parser("dlq", help="Manage Dead Letter Queue")
    ds = pd.add_subparsers(dest="dlq_command")
    p = ds.add_parser("list", help="List DLQ jobs")
    p.set_defaults(func=cmd_dlq_list)
    p = ds.add_parser("retry", help="Retry a DLQ job")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_dlq_retry)
    p = ds.add_parser("retry-all", help="Retry all DLQ jobs")
    p.set_defaults(func=cmd_dlq_retry_all)

    # config
    pc = sub.add_parser("config", help="Manage configuration")
    cs = pc.add_subparsers(dest="config_command")
    p = cs.add_parser("set", help="Set a config value")
    p.add_argument("key");  p.add_argument("value")
    p.set_defaults(func=cmd_config_set)
    p = cs.add_parser("get", help="Get a config value")
    p.add_argument("key")
    p.set_defaults(func=cmd_config_get)

    # dashboard
    p = sub.add_parser("dashboard", help="Launch the web dashboard")
    p.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    p.set_defaults(func=cmd_dashboard)

    # internal
    p = sub.add_parser("_run_worker", help=argparse.SUPPRESS)
    p.add_argument("worker_id", type=int)
    p.set_defaults(func=cmd_run_worker)

    if len(sys.argv) == 1:
        print("Welcome to QueueCTL!")
        print("\nHere is a guided example to test the system in order:\n")
        print("1. Start background workers (they will wait for jobs):")
        print("   python queuectl.py worker start --count 2\n")
        print("2. Enqueue some test jobs:")
        print("   python queuectl.py enqueue \"{\\\"id\\\":\\\"job-1\\\", \\\"command\\\":\\\"echo Hello\\\"}\"")
        print("   python queuectl.py enqueue \"{\\\"id\\\":\\\"job-fail\\\", \\\"command\\\":\\\"exit 1\\\"}\"\n")
        print("3. Check the status of your jobs:")
        print("   python queuectl.py status")
        print("   python queuectl.py list\n")
        print("4. View the Dead Letter Queue (DLQ) for failed jobs:")
        print("   python queuectl.py dlq list\n")
        print("5. Retry all dead jobs:")
        print("   python queuectl.py dlq retry-all\n")
        print("6. Stop the workers gracefully:")
        print("   python queuectl.py worker stop\n")
        print("Run 'python queuectl.py --help' for the full list of commands.")
        sys.exit(0)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
