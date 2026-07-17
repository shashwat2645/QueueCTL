"""
Helper script to make running QueueCTL easy from Windows CMD/PowerShell.
Usage: python run.py enqueue job1 "echo Hello World"
       python run.py enqueue job2 "echo High Priority" --priority 1
       python run.py enqueue job3 "python -c \"import time;time.sleep(99)\"" --timeout 3
       python run.py worker start --count 2
       python run.py worker stop
       python run.py status
       python run.py list
       python run.py metrics
       python run.py dashboard
       python run.py logs job1
       python run.py dlq list
       python run.py dlq retry job1
"""
import sys
import subprocess
import json
import os

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    # Special handling for enqueue to avoid JSON quoting hell on Windows
    if cmd == 'enqueue':
        if len(sys.argv) < 4:
            print("Usage: python run.py enqueue <id> <command> [--priority N] [--timeout N] [--run_at ISO]")
            sys.exit(1)

        job_id  = sys.argv[2]
        command = sys.argv[3]

        job = {"id": job_id, "command": command}

        # Parse optional flags
        i = 4
        while i < len(sys.argv):
            flag = sys.argv[i]
            if flag == '--priority' and i + 1 < len(sys.argv):
                job['priority'] = int(sys.argv[i + 1]); i += 2
            elif flag == '--timeout' and i + 1 < len(sys.argv):
                job['timeout'] = int(sys.argv[i + 1]); i += 2
            elif flag == '--run_at' and i + 1 < len(sys.argv):
                job['run_at'] = sys.argv[i + 1]; i += 2
            else:
                i += 1

        json_str = json.dumps(job)
        subprocess.run([sys.executable, 'queuectl.py', 'enqueue', json_str])

    else:
        # Pass everything else straight through to queuectl.py
        subprocess.run([sys.executable, 'queuectl.py'] + sys.argv[1:])

if __name__ == '__main__':
    main()
