#!/usr/bin/env python3
"""
KEDA Redis Queue Scaling Test Script

This script tests KEDA scaling by:
1. Adding tasks to the Redis queue
2. Monitoring queue length
3. Monitoring pod scaling behavior
4. Providing real-time feedback

Usage:
    python test_keda_scaling.py --add-tasks 15
    python test_keda_scaling.py --monitor-only
    python test_keda_scaling.py --clear-queue
"""

import redis
import subprocess
import time
import json
import argparse
from datetime import datetime
from typing import Dict, List, Any

class KEDAScalingTester:
    def __init__(self, redis_host='redis-redis-chart', redis_port=6379, redis_db=0,
                 namespace='backend', queue_name='celery'):
        """Initialize the KEDA scaling tester."""
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.namespace = namespace
        self.queue_name = queue_name
        self.redis_client = None

    def connect_redis(self) -> bool:
        """Connect to Redis server."""
        try:
            # For local testing (outside cluster)
            try:
                self.redis_client = redis.Redis(
                    host=self.redis_host,
                    port=self.redis_port,
                    db=self.redis_db,
                    decode_responses=True
                )
                self.redis_client.ping()
                print(f"✅ Connected to Redis at {self.redis_host}:{self.redis_port}/{self.redis_db}")
                return True
            except:
                # If direct connection fails, try through kubectl port-forward
                print("⚠️  Direct Redis connection failed, trying kubectl exec...")
                return self._test_redis_via_kubectl()
        except Exception as e:
            print(f"❌ Failed to connect to Redis: {e}")
            return False

    def _test_redis_via_kubectl(self) -> bool:
        """Test Redis connection via kubectl exec."""
        try:
            cmd = [
                'kubectl', 'exec', '-n', self.namespace,
                'deployment/backend', '--', 'python3', '-c',
                f"import redis; r=redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db}); print('Connected:', r.ping())"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and 'Connected: True' in result.stdout:
                print("✅ Redis connection verified via kubectl")
                return True
            else:
                print(f"❌ Redis connection failed: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ kubectl exec failed: {e}")
            return False

    def get_queue_length(self) -> int:
        """Get current queue length."""
        if self.redis_client:
            try:
                return self.redis_client.llen(self.queue_name)
            except:
                pass

        # Fallback to kubectl exec
        try:
            cmd = [
                'kubectl', 'exec', '-n', self.namespace,
                'deployment/backend', '--', 'python3', '-c',
                f"import redis; r=redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db}); print(r.llen('{self.queue_name}'))"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return int(result.stdout.strip().split('\n')[-1])
        except Exception as e:
            print(f"⚠️  Could not get queue length: {e}")
        return 0

    def add_tasks_to_queue(self, num_tasks: int) -> bool:
        """Add tasks to the Redis queue."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.redis_client:
            try:
                for i in range(num_tasks):
                    task_data = f"test_task_{timestamp}_{i+1}"
                    self.redis_client.lpush(self.queue_name, task_data)
                print(f"✅ Added {num_tasks} tasks to queue via direct connection")
                return True
            except:
                pass

        # Fallback to kubectl exec
        try:
            tasks_str = ', '.join([f'"test_task_{timestamp}_{i+1}"' for i in range(num_tasks)])
            cmd = [
                'kubectl', 'exec', '-n', self.namespace,
                'deployment/backend', '--', 'python3', '-c',
                f"import redis; r=redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db}); [r.lpush('{self.queue_name}', task) for task in [{tasks_str}]]; print('Added {num_tasks} tasks')"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"✅ Added {num_tasks} tasks to queue via kubectl")
                return True
            else:
                print(f"❌ Failed to add tasks: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ Failed to add tasks via kubectl: {e}")
            return False

    def clear_queue(self) -> bool:
        """Clear all tasks from the queue."""
        if self.redis_client:
            try:
                cleared = self.redis_client.delete(self.queue_name)
                print(f"✅ Cleared queue via direct connection (removed {cleared} keys)")
                return True
            except:
                pass

        # Fallback to kubectl exec
        try:
            cmd = [
                'kubectl', 'exec', '-n', self.namespace,
                'deployment/backend', '--', 'python3', '-c',
                f"import redis; r=redis.Redis(host='{self.redis_host}', port={self.redis_port}, db={self.redis_db}); print('Cleared:', r.delete('{self.queue_name}'))"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print("✅ Queue cleared via kubectl")
                return True
            else:
                print(f"❌ Failed to clear queue: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ Failed to clear queue via kubectl: {e}")
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

    def get_keda_status(self) -> Dict[str, Any]:
        """Get KEDA ScaledObject status."""
        try:
            cmd = ['kubectl', 'get', 'scaledobjects', '-n', self.namespace, '-o', 'json']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data['items']:
                    scaled_obj = data['items'][0]
                    return {
                        'name': scaled_obj['metadata']['name'],
                        'ready': scaled_obj['status'].get('conditions', [{}])[0].get('status', 'Unknown'),
                        'active': scaled_obj['status'].get('scaleTargetGVKR', {}).get('kind', 'Unknown'),
                        'current_replicas': scaled_obj['status'].get('externalMetricNames', []),
                        'triggers': len(scaled_obj['spec'].get('triggers', []))
                    }
        except Exception as e:
            print(f"⚠️  Could not get KEDA status: {e}")
        return {'name': 'Unknown', 'ready': 'Unknown', 'active': 'Unknown', 'triggers': 0}

    def monitor_scaling(self, duration_minutes: int = 5, check_interval: int = 15):
        """Monitor scaling behavior for a specified duration."""
        print(f"\n🔍 Monitoring KEDA scaling for {duration_minutes} minutes...")
        print(f"📊 Checking every {check_interval} seconds")
        print("=" * 80)

        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)

        # Print header
        print(f"{'Time':<12} {'Queue':<8} {'Pods':<6} {'KEDA Status':<15} {'Action'}")
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

            print(f"{current_time:<12} {queue_length:<8} {pod_count:<6} {keda_ready:<15} {action}")

            time.sleep(check_interval)

        print("=" * 80)
        print("✅ Monitoring completed")

    def run_scaling_test(self, num_tasks: int, monitor_duration: int = 5):
        """Run a complete scaling test."""
        print("🚀 KEDA Redis Queue Scaling Test")
        print("=" * 50)

        # Step 1: Connect to Redis
        if not self.connect_redis():
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
    parser.add_argument('--duration', type=int, default=5,
                       help='Monitoring duration in minutes (default: 5)')
    parser.add_argument('--namespace', default='backend',
                       help='Kubernetes namespace (default: backend)')
    parser.add_argument('--redis-host', default='redis-redis-chart',
                       help='Redis host (default: redis-redis-chart)')

    args = parser.parse_args()

    tester = KEDAScalingTester(
        redis_host=args.redis_host,
        namespace=args.namespace
    )

    if args.clear_queue:
        print("🧹 Clearing Redis queue...")
        if tester.connect_redis():
            tester.clear_queue()
            print(f"✅ Queue cleared. Current length: {tester.get_queue_length()}")
        else:
            print("❌ Could not connect to Redis")

    elif args.monitor_only:
        print("🔍 Monitoring KEDA scaling status...")
        if tester.connect_redis():
            tester.monitor_scaling(duration_minutes=args.duration)
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

if __name__ == "__main__":
    main()