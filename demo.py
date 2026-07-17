"""
QueueCTL - Live Demo Script
Run this while screen recording to showcase all features.
Usage: python demo.py
"""
import subprocess
import sys
import time
import os

# ── Colors for Windows CMD (ANSI) ────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
PURPLE = "\033[95m"
BLUE   = "\033[94m"
WHITE  = "\033[97m"
DIM    = "\033[2m"

def enable_ansi():
    """Enable ANSI colors in Windows CMD."""
    if sys.platform == 'win32':
        os.system('')

def clear():
    os.system('cls' if sys.platform == 'win32' else 'clear')

def banner(title, color=CYAN):
    w = 60
    print(color + BOLD)
    print("=" * w)
    print(f"  {title}")
    print("=" * w)
    print(RESET)

def step(num, title):
    print(f"\n{YELLOW}{BOLD}[STEP {num}]{RESET} {WHITE}{BOLD}{title}{RESET}")
    print(DIM + "-" * 50 + RESET)
    time.sleep(0.5)

def info(msg):
    print(f"{BLUE}  >> {msg}{RESET}")
    time.sleep(0.3)

def run(args, show_cmd=True):
    cmd = ['python', 'queuectl.py'] + args
    if show_cmd:
        print(f"\n{GREEN}  $ python queuectl.py {' '.join(args)}{RESET}")
        time.sleep(0.4)
    result = subprocess.run(cmd, capture_output=True, text=True,
                            cwd=os.path.dirname(os.path.abspath(__file__)))
    output = result.stdout.strip()
    if output:
        for line in output.splitlines():
            print(f"  {DIM}{line}{RESET}")
    if result.returncode != 0 and result.stderr:
        print(f"  {RED}{result.stderr.strip()}{RESET}")
    time.sleep(0.3)
    return result

def pause(msg="", secs=1.5):
    if msg:
        print(f"\n  {PURPLE}[{msg}]{RESET}")
    time.sleep(secs)

# ─────────────────────────────────────────────────────────────────────────────

enable_ansi()

# ── Reset environment ─────────────────────────────────────────────────────────
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'queuectl.db')
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'job_logs')
if os.path.exists(db_path):
    os.remove(db_path)
if os.path.isdir(log_dir):
    for f in os.listdir(log_dir):
        try: os.remove(os.path.join(log_dir, f))
        except: pass

# ── INTRO ─────────────────────────────────────────────────────────────────────
clear()
banner("QueueCTL - Background Job Queue System", CYAN)
print(f"""
  {WHITE}A CLI-based background job queue with:{RESET}
  {GREEN}  *  Persistent SQLite storage{RESET}
  {GREEN}  *  Concurrent workers with race-condition-safe dequeue{RESET}
  {GREEN}  *  Exponential backoff retries{RESET}
  {GREEN}  *  Dead Letter Queue (DLQ){RESET}
  {GREEN}  *  Job priority queues        [BONUS]{RESET}
  {GREEN}  *  Job timeout handling       [BONUS]{RESET}
  {GREEN}  *  Scheduled / delayed jobs   [BONUS]{RESET}
  {GREEN}  *  Job output logging         [BONUS]{RESET}
  {GREEN}  *  Execution metrics          [BONUS]{RESET}
  {GREEN}  *  Live web dashboard         [BONUS]{RESET}

  {DIM}No external dependencies -- Python stdlib only{RESET}
""")
pause("Starting demo in 3 seconds...", 3)

# ── STEP 1: Config ────────────────────────────────────────────────────────────
clear()
banner("STEP 1 - Configuration")
step(1, "Set max retries and backoff base")
info("max-retries=3 means a job is retried 3 times before going to DLQ")
info("backoff-base=2 means delays are 2^1=2s, 2^2=4s, 2^3=8s ...")
run(['config', 'set', 'max-retries', '3'])
run(['config', 'set', 'backoff-base', '2'])
run(['config', 'get', 'max-retries'])
pause("Config saved!", 2)

# ── STEP 2: Enqueue Jobs ──────────────────────────────────────────────────────
clear()
banner("STEP 2 - Enqueue Jobs")

step(2, "Enqueue a simple job")
info('Basic job -- just an id and command')
run(['enqueue', '{"id":"greet","command":"echo Hello from QueueCTL!"}'])
pause("", 1)

step(2, "Enqueue a HIGH PRIORITY job (priority=1)")
info('Priority 1 = highest. Workers always pick this up first.')
run(['enqueue', '{"id":"urgent","command":"echo URGENT job processed first","priority":1}'])
pause("", 1)

step(2, "Enqueue a LOW PRIORITY job (priority=9)")
run(['enqueue', '{"id":"low","command":"echo low priority job","priority":9}'])
pause("", 1)

step(2, "Enqueue a job WITH TIMEOUT (2 seconds)")
info('This job sleeps 60s but will be killed after 2s -- then retried -- then DLQ')
run(['enqueue', '{"id":"timeout-job","command":"python -c \\"import time;time.sleep(60)\\"","timeout":2,"priority":3}'])
pause("", 1)

step(2, "Enqueue a FAILING job (to demonstrate DLQ)")
run(['enqueue', '{"id":"failing","command":"exit 1","priority":5}'])
pause("", 1)

step(2, "Enqueue a SCHEDULED job (runs 2 minutes from now)")
info('This job will sit in pending until its run_at timestamp is reached')
import datetime
future = (datetime.datetime.now(datetime.timezone.utc) +
          datetime.timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
run(['enqueue', f'{{"id":"scheduled","command":"echo I was scheduled!","run_at":"{future}"}}'])
pause("All jobs enqueued!", 2)

# ── STEP 3: Status Before Workers ────────────────────────────────────────────
clear()
banner("STEP 3 - Status (Before Workers Start)")
step(3, "Check job status -- all should be PENDING")
run(['status'])
pause("", 1)
step(3, "List all jobs sorted by priority")
run(['list'])
pause("Notice priority order: urgent(1), timeout-job(3), failing(5), greet(5), low(9), scheduled(5)", 3)

# ── STEP 4: Start Workers ─────────────────────────────────────────────────────
clear()
banner("STEP 4 - Start Workers")
step(4, "Start 3 concurrent background workers")
info("Workers run in background -- they poll for jobs every second")
info("SQLite EXCLUSIVE transactions prevent race conditions between workers")
run(['worker', 'start', '--count', '3'])
pause("Workers are now running in the background!", 2)

# Wait for normal jobs to complete
print(f"\n  {YELLOW}Waiting 5 seconds for normal jobs to process...{RESET}")
time.sleep(5)

# ── STEP 5: Status After Normal Jobs ─────────────────────────────────────────
clear()
banner("STEP 5 - Progress Check")
step(5, "Check status -- fast jobs should be done")
run(['status'])
pause("", 1)
step(5, "List all jobs")
run(['list'])
pause("Notice: greet, urgent, low are COMPLETED. timeout-job and failing are retrying...", 3)

# Wait for retries + DLQ
print(f"\n  {YELLOW}Waiting 20 seconds for retries and DLQ transitions...{RESET}")
print(f"  {DIM}(timeout-job: 3 retries x 2s timeout each + backoff){RESET}")
time.sleep(20)

# ── STEP 6: DLQ Demo ─────────────────────────────────────────────────────────
clear()
banner("STEP 6 - Dead Letter Queue (DLQ)")
step(6, "Final status -- failing jobs should be in DLQ")
run(['status'])
pause("", 1)
step(6, "View Dead Letter Queue")
run(['dlq', 'list'])
pause("Jobs exhausted all retries and are now in the DLQ (state=dead)", 2)

step(6, "Retry a dead job from DLQ")
info("We can rescue any dead job and re-queue it")
run(['dlq', 'retry', 'failing'])
run(['dlq', 'retry', 'timeout-job'])
pause("", 1)
run(['status'])
pause("Dead jobs are back as PENDING -- workers will pick them up again!", 2)

# ── STEP 7: Logs ─────────────────────────────────────────────────────────────
clear()
banner("STEP 7 - Job Output Logging")
step(7, "Every job's output is captured and stored")
info("Stored in DB + written to job_logs/<job-id>.log")
run(['logs', 'greet'])
pause("", 1)
step(7, "View just stdout of a job")
run(['logs', 'greet', '--stdout'])
pause("", 1)
step(7, "View just stderr of a job")
run(['logs', 'greet', '--stderr'])
pause("Full output captured for every job!", 2)

# ── STEP 8: Metrics ──────────────────────────────────────────────────────────
clear()
banner("STEP 8 - Execution Metrics")
step(8, "View execution statistics")
run(['metrics'])
pause("Success rate, duration stats, per-priority breakdown -- all tracked!", 3)

# ── STEP 9: Scheduled Job ────────────────────────────────────────────────────
clear()
banner("STEP 9 - Scheduled Job")
step(9, "The scheduled job is still PENDING (run_at is 2 min from start)")
run(['list', '--state', 'pending'])
info("Workers see it but skip it because run_at > NOW")
info("It will automatically run when the clock reaches its run_at timestamp")
pause("Delayed/scheduled jobs work without any extra setup!", 2)

# ── STEP 10: Stop Workers ────────────────────────────────────────────────────
clear()
banner("STEP 10 - Graceful Shutdown")
step(10, "Stop all workers gracefully")
info("Workers finish their current job, then exit cleanly")
run(['worker', 'stop'])
pause("", 1)
run(['status'])
pause("Workers stopped. State is fully persisted in SQLite.", 2)

# ── STEP 11: Dashboard ───────────────────────────────────────────────────────
clear()
banner("STEP 11 - Web Dashboard")
step(11, "Launch the live web dashboard")
info("Serves a real-time HTML dashboard at http://localhost:8765")
info("Auto-refreshes every 5 seconds")
info("Features: state cards, bar chart, metrics, job table, DLQ retry button")
print(f"\n  {GREEN}  $ python queuectl.py dashboard{RESET}")
print(f"  {DIM}  Dashboard running at http://localhost:8765{RESET}")
print(f"  {DIM}  Open your browser and go to: http://localhost:8765{RESET}")
pause("", 2)

# ── OUTRO ─────────────────────────────────────────────────────────────────────
clear()
banner("Demo Complete!", GREEN)
print(f"""
  {WHITE}{BOLD}QueueCTL Features Demonstrated:{RESET}

  {GREEN}[CORE]{RESET}
  {GREEN}  *  Job enqueueing with persistence{RESET}
  {GREEN}  *  Concurrent workers (race-condition-safe){RESET}
  {GREEN}  *  Exponential backoff retries{RESET}
  {GREEN}  *  Dead Letter Queue + retry{RESET}
  {GREEN}  *  Configuration management{RESET}

  {CYAN}[BONUS]{RESET}
  {CYAN}  *  Priority queues (urgent ran first!){RESET}
  {CYAN}  *  Timeout handling (killed + retried + DLQ){RESET}
  {CYAN}  *  Scheduled / delayed jobs (run_at){RESET}
  {CYAN}  *  Job output logging (stdout/stderr){RESET}
  {CYAN}  *  Execution metrics (success rate, duration){RESET}
  {CYAN}  *  Live web dashboard at http://localhost:8765{RESET}

  {DIM}Zero external dependencies -- Python stdlib only{RESET}
  {DIM}Run: python demo.py to replay this demo{RESET}
""")
print("=" * 60 + "\n")

# Launch dashboard at the end
print(f"  {YELLOW}Launching dashboard now... Open http://localhost:8765{RESET}\n")
time.sleep(1)
subprocess.run([sys.executable, 'queuectl.py', 'dashboard'],
               cwd=os.path.dirname(os.path.abspath(__file__)))
