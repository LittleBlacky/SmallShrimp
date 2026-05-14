---
id: cron-ops
name: cron-ops
description: Create, list, and delete scheduled cron jobs
---

# Cron Operations Skill

Use APScheduler to schedule periodic tasks.

## Create a Cron Job

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(your_function, 'interval', minutes=30)
scheduler.start()

# List Jobs

for job in scheduler.get_jobs():
    print(job.name, job.next_run_time)

# Delete a Job
scheduler.remove_job('job_name')
```
