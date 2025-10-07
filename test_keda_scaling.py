#!/usr/bin/env python3
"""
KEDA Redis Queue Scaling Test Script

This script tests KEDA scaling by:
1. Adding tasks to the Redis queue
2. Monitoring queue length
3. Monitoring pod scaling behavior

Usage:
    python test_keda_scaling.py --add-tasks 15
    python test_keda_scaling.py --monitor-only
    python test_keda_scaling.py --clear-queue
"""

import subprocess
import time
import json
import argparse
from datetime import datetime

class KEDAScalingTester:
    def __init__(self, redis_host='redis-redis-chart', redis_port=6379, redis_db=0,
                 namespace='backend', queue_name='celery'):
        """Initialize the KEDA scaling tester."""
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.namespace = namespace
        self.queue_name = queue_name

    def get_backend_pod(self):
        """Get the first available backend pod name."""
        try:
            cmd = ['kubectl', 'get', 'pods', '-n', self.namespace, '-l', 'app=backend', '-o', 'json']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                pods_data = json.loads(result.stdout)
                running_pods = [pod for pod in pods_data['items']
                              if pod['status']['phase'] == 'Running']
                if running_pods:
                    return running_pods[0]['metadata']['name']
        except Exception as e:
            print(f"⚠️  Could not get backend pod: {e}")
        return None

    def execute_redis_command(self, command: str):
        """Execute a Redis command via kubectl exec."""
        pod_name = self.get_backend_pod()
        if not pod_name:
            print("❌ No running backend pod found")
            return None

        try:
            cmd = [
                'kubectl', 'exec', '-n', self.namespace,
                pod_name, '--', 'python3', '-c', command
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                print(f"❌ Command failed: {result.stderr}")
                return None
        except Exception as e:
            print(f"❌ Failed to execute command: {e}")
            return None

    def test_redis_connection(self) -> bool:
        """Test Redis connection."""
        command = f"""
import redis
try:
    r = redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db})
    print('Connected:', r.ping())
except Exception as e:
    print('Connection failed:', e)
"""
        result = self.execute_redis_command(command)
        if result and 'Connected: True' in result:
            print("✅ Redis connection verified")
            return True
        else:
            print(f"❌ Redis connection failed: {result}")
            return False

    def get_queue_length(self) -> int:
        """Get current queue length."""
        command = f"""
import redis
try:
    r = redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db})
    print(r.llen('{self.queue_name}'))
except Exception as e:
    print('0')
"""
        result = self.execute_redis_command(command)
        try:
            return int(result.split('\n')[-1]) if result else 0
        except:
            return 0

    def add_tasks_to_queue(self, num_tasks: int) -> bool:
        """Add properly formatted Celery messages with complete Kombu envelope."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        command = f"""
import redis
import json
import uuid
import base64
try:
    r = redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db})
    
    num_tasks = {num_tasks}
    timestamp = "{timestamp}"
    
    # Use real city names for successful weather API calls
    real_cities = [
        "London", "New York", "Tokyo", "Paris", "Berlin",
        "Madrid", "Rome", "Amsterdam", "Sydney", "Toronto",
        "Mumbai", "Dubai", "Singapore", "Barcelona", "Vienna",
        "Prague", "Stockholm", "Oslo", "Copenhagen", "Helsinki"
    ]
    
    for i in range(num_tasks):
        task_id = str(uuid.uuid4())
        city_name = real_cities[i % len(real_cities)]
        
        # Create Celery task body (what gets executed)
        task_body = [
            [city_name],  # args
            {{}},         # kwargs
            {{           # embed options
                "callbacks": None,
                "errbacks": None,
                "chain": None,
                "chord": None
            }}
        ]
        
        # Encode task body as base64 (standard Celery format)
        body_json = json.dumps(task_body)
        encoded_body = base64.b64encode(body_json.encode('utf-8')).decode('utf-8')
        
        # Create complete Kombu message envelope
        kombu_message = {{
            "body": encoded_body,
            "content-encoding": "utf-8", 
            "content-type": "application/json",
            "headers": {{
                "lang": "py",
                "task": "app.fetch_weather_data",
                "id": task_id,
                "shadow": None,
                "eta": None,
                "expires": None,
                "group": None,
                "group_index": None,
                "retries": 0,
                "timelimit": [None, None],
                "root_id": task_id,
                "parent_id": None,
                "argsrepr": f"('{{city_name}}',)",
                "kwargsrepr": "{{}}",
                "origin": "test-script@keda-test"
            }},
            "properties": {{
                "correlation_id": task_id,
                "reply_to": None,
                "delivery_mode": 2,
                "delivery_info": {{
                    "exchange": "",
                    "routing_key": "celery"
                }},
                "priority": 0,
                "body_encoding": "base64",
                "delivery_tag": None
            }}
        }}
        
        # Serialize complete message and add to queue
        message_json = json.dumps(kombu_message)
        r.lpush('{self.queue_name}', message_json)
    
    print(f'Added {{num_tasks}} complete Celery messages to queue')
except Exception as e:
    print('Failed:', str(e))
    import traceback
    traceback.print_exc()
"""
        result = self.execute_redis_command(command)
        if result and f'Added {num_tasks} complete Celery messages' in result:
            print(f"✅ Added {num_tasks} complete Celery messages for KEDA scaling")
            return True
        else:
            print(f"❌ Failed to add tasks: {result}")
            return False

    def clear_queue(self) -> bool:
        """Clear all tasks from the queue."""
        command = f"""
import redis
try:
    r = redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db})
    num_cleared = r.delete('{self.queue_name}')
    print(f'Cleared {{num_cleared}} queue(s)')
except Exception as e:
    print('Failed:', e)
"""
        result = self.execute_redis_command(command)
        if result and 'Cleared' in result:
            print("✅ Queue cleared")
            return True
        else:
            print(f"❌ Failed to clear queue: {result}")
            return False

    def simulate_task_processing(self, num_tasks: int = 5) -> bool:
        """Simulate task processing by removing tasks from queue."""
        command = f"""
import redis
import time
try:
    r = redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db})
    
    processed = 0
    for i in range({num_tasks}):
        task = r.rpop('{self.queue_name}')
        if task:
            processed += 1
            print(f'Processed task {{i+1}}: {{task.decode()[:50]}}...')
            time.sleep(1)  # Simulate processing time
        else:
            break
    
    print(f'Processed {{processed}} tasks from queue')
except Exception as e:
    print('Failed:', str(e))
"""
        result = self.execute_redis_command(command)
        if result and 'Processed' in result:
            print(f"✅ Simulated processing of tasks")
            return True
        else:
            print(f"❌ Failed to process tasks: {result}")
            return False

    def get_pod_count(self) -> int:
        """Get current number of backend pods."""
        try:
            cmd = ['kubectl', 'get', 'pods', '-n', self.namespace, '-l', 'app=backend', '-o', 'json']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                pods_data = json.loads(result.stdout)
                running_pods = [pod for pod in pods_data['items']
                              if pod['status']['phase'] == 'Running']
                return len(running_pods)
        except Exception as e:
            print(f"⚠️  Could not get pod count: {e}")
        return 0

    def get_keda_status(self):
        """Get KEDA ScaledObject status."""
        try:
            cmd = ['kubectl', 'get', 'scaledobjects', '-n', self.namespace, '-o', 'json']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data['items']:
                    scaled_obj = data['items'][0]
                    # Get status from conditions
                    conditions = scaled_obj.get('status', {}).get('conditions', [])
                    ready_status = 'Unknown'
                    for condition in conditions:
                        if condition.get('type') == 'Ready':
                            ready_status = condition.get('status', 'Unknown')
                            break

                    return {
                        'name': scaled_obj['metadata']['name'],
                        'ready': ready_status,
                        'triggers': len(scaled_obj['spec'].get('triggers', []))
                    }
        except Exception as e:
            print(f"⚠️  Could not get KEDA status: {e}")
        return {'name': 'Unknown', 'ready': 'Unknown', 'triggers': 0}

    def monitor_scaling(self, duration_minutes: int = 5, check_interval: int = 15):
        """Monitor scaling behavior."""
        print(f"\n🔍 Monitoring KEDA scaling for {duration_minutes} minutes...")
        print(f"📊 Checking every {check_interval} seconds")
        print("=" * 80)

        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)

        # Print header
        print(f"{'Time':<12} {'Queue':<8} {'Pods':<6} {'KEDA Ready':<12} {'Action'}")
        print("-" * 80)

        while time.time() < end_time:
            current_time = datetime.now().strftime("%H:%M:%S")
            queue_length = self.get_queue_length()
            pod_count = self.get_pod_count()
            keda_status = self.get_keda_status()

            # Determine expected action
            if queue_length > 5 and pod_count == 1:
                action = "Should scale UP"
            elif queue_length <= 5 and pod_count > 1:
                action = "Should scale DOWN"
            elif queue_length > 5 and pod_count > 1:
                action = "Scaled correctly"
            else:
                action = "No scaling needed"

            keda_ready = keda_status.get('ready', 'Unknown')

            print(f"{current_time:<12} {queue_length:<8} {pod_count:<6} {keda_ready:<12} {action}")

            time.sleep(check_interval)

        print("=" * 80)
        print("✅ Monitoring completed")

    def run_scaling_test(self, num_tasks: int, monitor_duration: int = 5):
        """Run a complete scaling test."""
        print("🚀 KEDA Redis Queue Scaling Test")
        print("=" * 50)

        # Step 1: Test Redis connection
        if not self.test_redis_connection():
            print("❌ Cannot connect to Redis. Exiting.")
            return False

        # Step 2: Check initial state
        initial_queue = self.get_queue_length()
        initial_pods = self.get_pod_count()
        keda_status = self.get_keda_status()

        print(f"\n📊 Initial State:")
        print(f"   Queue Length: {initial_queue}")
        print(f"   Pod Count: {initial_pods}")
        print(f"   KEDA Ready: {keda_status.get('ready', 'Unknown')}")
        print(f"   KEDA Triggers: {keda_status.get('triggers', 0)}")

        # Step 3: Add tasks to trigger scaling
        print(f"\n📝 Adding {num_tasks} tasks to trigger scaling...")
        if not self.add_tasks_to_queue(num_tasks):
            print("❌ Failed to add tasks. Exiting.")
            return False

        # Step 4: Show new queue length
        new_queue_length = self.get_queue_length()
        print(f"   New Queue Length: {new_queue_length}")

        if new_queue_length > 5:
            print(f"✅ Queue length ({new_queue_length}) exceeds threshold (5)")
            print("   🎯 KEDA should scale up to 2 replicas")
        else:
            print(f"⚠️  Queue length ({new_queue_length}) below threshold (5)")

        # Step 5: Monitor scaling behavior
        print(f"\n🔍 Monitoring scaling behavior...")
        self.monitor_scaling(duration_minutes=monitor_duration)

        return True

def main():
    parser = argparse.ArgumentParser(description='Test KEDA Redis Queue Scaling')
    parser.add_argument('--add-tasks', type=int, metavar='N',
                       help='Add N tasks to the queue and monitor scaling')
    parser.add_argument('--monitor-only', action='store_true',
                       help='Only monitor current scaling status')
    parser.add_argument('--clear-queue', action='store_true',
                       help='Clear all tasks from the queue')
    parser.add_argument('--simulate-processing', type=int, metavar='N',
                       help='Simulate processing N tasks from the queue')
    parser.add_argument('--duration', type=int, default=5,
                       help='Monitoring duration in minutes (default: 5)')
    parser.add_argument('--namespace', default='backend',
                       help='Kubernetes namespace (default: backend)')
    parser.add_argument('--redis-host', default='redis-redis-chart.backend.svc.cluster.local',
                       help='Redis host (default: redis-redis-chart.backend.svc.cluster.local)')

    args = parser.parse_args()

    tester = KEDAScalingTester(
        redis_host=args.redis_host,
        namespace=args.namespace
    )

    if args.clear_queue:
        print("🧹 Clearing Redis queue...")
        if tester.test_redis_connection():
            tester.clear_queue()
            print(f"✅ Queue cleared. Current length: {tester.get_queue_length()}")
        else:
            print("❌ Could not connect to Redis")

    elif args.monitor_only:
        print("🔍 Monitoring KEDA scaling status...")
        if tester.test_redis_connection():
            tester.monitor_scaling(duration_minutes=args.duration)
        else:
            print("❌ Could not connect to Redis")

    elif args.simulate_processing:
        print(f"🔄 Simulating processing of {args.simulate_processing} tasks...")
        if tester.test_redis_connection():
            print(f"   Initial queue length: {tester.get_queue_length()}")
            tester.simulate_task_processing(args.simulate_processing)
            print(f"   Final queue length: {tester.get_queue_length()}")
        else:
            print("❌ Could not connect to Redis")

    elif args.add_tasks:
        tester.run_scaling_test(args.add_tasks, args.duration)

    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python test_keda_scaling.py --add-tasks 15")
        print("  python test_keda_scaling.py --monitor-only --duration 10")
        print("  python test_keda_scaling.py --clear-queue")
        print("  python test_keda_scaling.py --simulate-processing 5")

if __name__ == "__main__":
    main()