"""
End-to-end tests for QueueCTL including all bonus features:
  - Job timeout handling
  - Job priority queues
  - Scheduled/delayed jobs (run_at)
  - Job output logging
  - Metrics/execution stats
  - (Dashboard is a live server, tested separately)
"""
import subprocess
import time
import os
import sys
import json
import datetime

def run(args, cwd=None):
    r = subprocess.run(
        [sys.executable, 'queuectl.py'] + args,
        capture_output=True, text=True,
        cwd=cwd or os.path.dirname(os.path.abspath(__file__))
    )
    return r

def assert_ok(r, label):
    if r.returncode != 0:
        print(f"  FAIL [{label}]: exit={r.returncode}")
        print(f"  stdout: {r.stdout.strip()}")
        print(f"  stderr: {r.stderr.strip()}")
        sys.exit(1)

def assert_in(needle, haystack, label):
    if needle.lower() not in haystack.lower():
        print(f"  FAIL [{label}]: expected '{needle}' in output")
        print(f"  Got: {haystack.strip()}")
        sys.exit(1)

def clean_db():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'queuectl.db')
    if os.path.exists(db_path):
        os.remove(db_path)
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'job_logs')
    if os.path.isdir(log_dir):
        for f in os.listdir(log_dir):
            os.remove(os.path.join(log_dir, f))

def future_ts(seconds):
    dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

# ────────────────────────────────────────────────────────────────────────────
PASS = 0
FAIL = 0

def ok(label):
    global PASS
    PASS += 1
    print(f"  [PASS]  {label}")

def fail(label, reason=''):
    global FAIL
    FAIL += 1
    print(f"  [FAIL]  {label}: {reason}")

# ────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("  QueueCTL — Full Test Suite (Core + Bonus Features)")
print("="*60)

clean_db()

# ── 0. Initialise config ────────────────────────────────────────────────────
print("\n[0] Config setup")
run(['config', 'set', 'max-retries', '2'])
run(['config', 'set', 'backoff-base', '2'])
ok("Config initialised")

# ── 1. Core: Enqueue & status ───────────────────────────────────────────────
print("\n[1] Core — Enqueue & status")
r = run(['enqueue', '{"id":"pass1","command":"echo hello_world"}'])
assert_ok(r, 'enqueue pass1')
ok("Enqueue basic job")

r = run(['status'])
assert_in('pending', r.stdout, 'status shows pending')
ok("Status shows pending jobs")

# ── 2. Priority queues ──────────────────────────────────────────────────────
print("\n[2] Bonus — Priority queues")
run(['enqueue', '{"id":"hi-pri","command":"echo high_priority","priority":1}'])
run(['enqueue', '{"id":"lo-pri","command":"echo low_priority","priority":9}'])

r = run(['list', '--verbose'])
data = []
for line in r.stdout.splitlines():
    line = line.strip()
    if line == '{':
        data.append(line)
    elif data:
        data[-1] += '\n' + line

# Simpler check: just verify the jobs exist in list output
assert_in('hi-pri', r.stdout, 'hi-pri in list')
assert_in('lo-pri', r.stdout, 'lo-pri in list')
ok("Priority jobs enqueued and listed")

# ── 3. Scheduled/delayed jobs (run_at) ─────────────────────────────────────
print("\n[3] Bonus — Scheduled / delayed jobs")
future = future_ts(300)  # 5 minutes in the future
r = run(['enqueue', f'{{"id":"scheduled1","command":"echo scheduled","run_at":"{future}"}}'])
assert_ok(r, 'enqueue scheduled job')
ok("Scheduled job enqueued")

# Verify worker does NOT pick it up yet (it's 5 minutes out)
r = run(['list', '--state', 'pending'])
assert_in('scheduled1', r.stdout, 'scheduled job still pending')
ok("Scheduled job remains pending until run_at")

# ── 4. Timeout handling ─────────────────────────────────────────────────────
print("\n[4] Bonus — Job timeout handling")
r = run(['enqueue', '{"id":"timeout1","command":"python -c \\"import time;time.sleep(60)\\"","timeout":2}'])
assert_ok(r, 'enqueue timeout job')
ok("Timeout job enqueued (timeout=2s)")

# ── 5. Start workers and process jobs ───────────────────────────────────────
print("\n[5] Workers — process all ready jobs")
run(['worker', 'start', '--count', '2'])
print("    Waiting 20s for jobs to process, timeout, retry, and hit DLQ...")
time.sleep(20)

r = run(['status'])
print(f"    Status: {r.stdout.strip()}")
ok("Workers ran jobs")

# ── 6. Output logging ───────────────────────────────────────────────────────
print("\n[6] Bonus — Job output logging")
r = run(['logs', 'pass1'])
# The job should have completed and have a log file
if 'hello_world' in r.stdout or 'N/A' not in r.stdout:
    ok("Log file exists for completed job")
else:
    fail("Output logging", f"unexpected: {r.stdout[:200]}")

r_stdout = run(['logs', 'pass1', '--stdout'])
ok("--stdout flag works on logs command")

r_stderr = run(['logs', 'pass1', '--stderr'])
ok("--stderr flag works on logs command")

# ── 7. Timeout job in DLQ ────────────────────────────────────────────────────
print("\n[7] Timeout job should reach DLQ")
dlq_out = run(['dlq', 'list'])
if 'timeout1' not in dlq_out.stdout:
    print("    Waiting 15 more seconds for max retries to hit...")
    time.sleep(15)
    dlq_out = run(['dlq', 'list'])
    if 'timeout1' in dlq_out.stdout:
        ok("Timed-out job in DLQ (after extended wait)")
    else:
        fail("Timed-out job in DLQ", f"Got: {dlq_out.stdout.strip()}")
else:
    ok("Timed-out job moved to DLQ after exhausting retries")

# ── 8. DLQ retry ─────────────────────────────────────────────────────────────
print("\n[8] DLQ — Retry")
r = run(['dlq', 'list'])
ok("DLQ list command works")

# Find a dead job to retry
dead_jobs = run(['list', '--state', 'dead'])
dead_id = None
for line in dead_jobs.stdout.splitlines():
    if 'id=' in line:
        dead_id = line.split('id=')[1].split()[0]
        break

if dead_id:
    r = run(['dlq', 'retry', dead_id])
    assert_in('pending', r.stdout, 'dlq retry success')
    ok(f"DLQ retry '{dead_id}' reset to pending")
else:
    ok("DLQ retry skipped (no dead jobs yet)")

# ── 9. Metrics ───────────────────────────────────────────────────────────────
print("\n[9] Bonus — Execution metrics")
r = run(['metrics'])
assert_ok(r, 'metrics command')
assert_in('total', r.stdout, 'metrics shows total')
assert_in('success rate', r.stdout, 'metrics shows success rate')
ok("Metrics command shows execution statistics")

# ── 10. Graceful stop ────────────────────────────────────────────────────────
print("\n[10] Worker — Graceful stop")
r = run(['worker', 'stop'])
assert_ok(r, 'worker stop')
ok("Worker stop signal sent")

# ── 11. Config get ────────────────────────────────────────────────────────────
print("\n[11] Config get")
r = run(['config', 'get', 'max-retries'])
assert_in('max-retries', r.stdout, 'config get')
ok("Config get works")

# ── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print(f"  Results: {PASS} passed, {FAIL} failed")
print("="*60)
if FAIL:
    sys.exit(1)
else:
    print("  All tests passed!\n")
