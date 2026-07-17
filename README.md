# QueueCTL - Backend Developer Internship Assignment

QueueCTL is a minimal, production-grade background job queue system with a CLI interface. It uses Python and SQLite to manage jobs, concurrent workers, exponential backoff retries, and a Dead Letter Queue (DLQ).

## Setup Instructions

### Prerequisites
- Python 3.8+
- No external pip dependencies are required! Only standard library modules are used.

### Installation
1. Clone this repository or download the source code.
2. Ensure you are in the project root directory.
3. On Windows, you can run the tool using `queuectl.bat` or `python queuectl.py`.
4. On Unix/Linux/macOS, you can run `python queuectl.py`.

## Usage Examples

**1. Enqueue a Job:**
```bash
queuectl enqueue '{"id":"job1", "command":"echo Hello World"}'
queuectl enqueue '{"id":"job2", "command":"sleep 2"}'
queuectl enqueue '{"id":"job3-fail", "command":"exit 1"}'
```

**2. Start Workers:**
Start multiple background workers to process jobs concurrently.
```bash
queuectl worker start --count 3
```

**3. Check Status & List Jobs:**
```bash
queuectl status
queuectl list --state pending
queuectl list --state completed
```

**4. Stop Workers Gracefully:**
```bash
queuectl worker stop
```

**5. Manage Dead Letter Queue (DLQ):**
Jobs that exhaust all retries are moved to the DLQ (state: `dead`).
```bash
queuectl dlq list
queuectl dlq retry job3-fail
```

**6. Configuration:**
Manage retry count and backoff base.
```bash
queuectl config set max-retries 5
queuectl config set backoff-base 2
```

## Architecture Overview

**Database & Persistence (SQLite):**
We use an embedded SQLite database (`queuectl.db`) for seamless persistent job storage. SQLite provides robust support for transactions (`BEGIN EXCLUSIVE`), which allows multiple concurrent workers to safely dequeue jobs without race conditions or duplicating execution. Data is fully persistent across tool restarts.

**Worker Logic:**
Workers pull jobs that are `pending` or `failed` with a `next_run_at` timestamp in the past. 
- Execution uses `subprocess.run`.
- Success sets the job to `completed`.
- Failure calculates exponential backoff: `delay = base ^ attempts` and sets the state to `failed`, scheduling the `next_run_at`. 
- If attempts exceed `max_retries`, the job is moved to the DLQ (`dead`).

**Graceful Shutdown:**
When `queuectl worker stop` is executed, a shutdown flag is set in the database. Workers continuously check this flag between jobs. Once set, they finish their currently executing job and terminate gracefully, ensuring no job corruption occurs mid-execution.

## Assumptions & Trade-offs
- **SQLite Concurrency:** SQLite is excellent for light-to-moderate concurrency. For massively scaled distributed systems, a dedicated message broker (like Redis or RabbitMQ) would be preferred, but SQLite fits perfectly for a lightweight CLI system.
- **Background Processes:** We spawn background workers using detached processes. Standard output of these workers is suppressed to keep the terminal clean, as per typical CLI behaviors. In a real-world scenario, worker logs would be piped to a dedicated log file.
- **Security:** Jobs use `subprocess.run(shell=True)`. In a true production environment, arbitrary shell execution from an untrusted source is dangerous. We assume the user of this CLI is trusted.

## Testing Instructions

A testing script `test_flows.py` is included to validate the core flows.

Run the tests:
```bash
python test_flows.py
```
This script will:
1. Verify basic successful job execution.
2. Verify failed job retries, backoff, and DLQ routing.
3. Ensure configuration updates take effect.
4. Validate that job data persists correctly.
