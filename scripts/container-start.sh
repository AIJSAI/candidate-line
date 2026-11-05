#!/bin/sh
# The container's entry point: the recruiter's cockpit on the loopback only (never a published port, reached
# through an SSM port-forward into the task, DR-023), then the line itself in the foreground on 0.0.0.0:8000
# behind the load balancer. If the line stops, the container stops, and the service starts a new task.
set -eu
uvicorn --factory candidate_line.traces.cockpit:app --host 127.0.0.1 --port 8001 --log-level warning &
exec uvicorn candidate_line.telephony.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'
