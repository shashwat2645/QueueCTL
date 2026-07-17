import time
import random
import uuid
import db

def generate_traffic():
    print("Starting background traffic generator for demo...")
    print("Press Ctrl+C to stop.")
    
    # Initialize DB connection just in case
    db.init_db()

    job_types = [
        # (weight, command_generator, priority, timeout)
        # 60% chance of a medium task (8 to 12 seconds)
        (60, lambda: f'python -c "import time; time.sleep({random.randint(8, 12)}); print(\'Medium task done\')"', 5, 0),
        # 10% chance of a fast running task (2 to 5 seconds)
        (10, lambda: f'python -c "import time; time.sleep({random.randint(2, 5)}); print(\'Short task done\')"', 6, 0),
        # 15% chance of a task that fails randomly after 2-4s
        (15, lambda: f'python -c "import sys; import time; time.sleep({random.randint(2, 4)}); sys.stderr.write(\'Random network failure\'); sys.exit(1)"', 4, 0),
        # 15% chance of a task that will timeout (sleeps 15s, times out in 10s)
        (15, lambda: 'python -c "import time; time.sleep(15)"', 3, 10),
    ]

    # Generate between 45 and 50 tasks
    total_tasks_to_generate = random.randint(45, 50)
    print(f"Generator configured to stop automatically after {total_tasks_to_generate} tasks.")

    tasks_generated = 0
    generated_job_ids = []
    
    try:
        while tasks_generated < total_tasks_to_generate:
            # Pick a random job type based on weights
            r = random.uniform(0, 100)
            cumulative = 0
            selected_job = job_types[0]
            for weight, cmd_gen, prio, to in job_types:
                cumulative += weight
                if r <= cumulative:
                    selected_job = (cmd_gen, prio, to)
                    break
            
            cmd_gen, prio, to = selected_job
            cmd = cmd_gen()
            job_id = f"demo-{uuid.uuid4().hex[:6]}"
            
            # Use db directly to enqueue fast
            db.enqueue_job(job_id, cmd, priority=prio, timeout=to)
            generated_job_ids.append(job_id)
            tasks_generated += 1
            print(f"[{tasks_generated}/{total_tasks_to_generate}] Enqueued {job_id}: {cmd[:40]}...")

            # Sleep between 0.5s and 2s to simulate organic traffic
            time.sleep(random.uniform(0.5, 2.0))
            
        print(f"\nTraffic generation complete! Waiting for workers to finish processing these {tasks_generated} tasks...")
        
        # Wait for all generated jobs to finish
        import sqlite3
        while True:
            conn = db.get_connection()
            c = conn.cursor()
            placeholders = ','.join(['?'] * len(generated_job_ids))
            c.execute(f"SELECT state, COUNT(*) FROM jobs WHERE id IN ({placeholders}) GROUP BY state", generated_job_ids)
            rows = c.fetchall()
            conn.close()
            
            states = {r['state']: r['COUNT(*)'] for r in rows}
            pending = states.get('pending', 0)
            processing = states.get('processing', 0)
            
            if pending == 0 and processing == 0:
                print("\n" + "="*50)
                print("🏁 ALL TASKS PROCESSED! FINAL REPORT 🏁")
                print("="*50)
                print(f"✅ Completed successfully: {states.get('completed', 0)}")
                print(f"⚠️  Failed (Retrying):      {states.get('failed', 0)}")
                print(f"❌ Cannot be completed:    {states.get('dead', 0)} (Dead Letter Queue)")
                print("="*50)
                break
                
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\nTraffic generator stopped.")

if __name__ == '__main__':
    generate_traffic()
