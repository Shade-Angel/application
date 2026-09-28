import itertools
import os
import random
import time

from locust import HttpUser, constant_pacing, task
from locust.shape import LoadTestShape

PACER = float(os.getenv("REQUEST_PACING_S", "1.0"))
LOCUST_HOST = os.getenv("LOCUST_HOST", "http://localhost:8001")

_ids = itertools.count(int(time.time() * 1000))


class AISOrders(HttpUser):
    host = LOCUST_HOST
    wait_time = constant_pacing(PACER)

    @task(8)
    def create_order(self) -> None:
        order_id = next(_ids)
        self.client.post(
            "/api/orders",
            json={
                "id": order_id,
                "parent_id": None,
                "amount": random.randint(5_000, 900_000),
                "client_msp": random.choice(["yes", "no"]),
                "executor_msp": random.choice(["yes", "no"]),
                "order_type": random.choice(["ORDER_1", "ORDER_2", "ORDER_3"]),
                "subject": random.choice(["subject-a", "subject-b", "subject-c"]),
                "vip": random.random() < 0.1,
                "text": "Locust load profile",
                "status": "processed",
            },
            name="AIS order webhook",
        )
class AcceptanceShape(LoadTestShape):
    """Profile A runs 30 minutes at ~1.1 rps; B adds a 100-user 60s burst."""

    def tick(self) -> tuple[int, float] | None:
        profile = os.getenv("LOAD_PROFILE", "A").upper()
        elapsed = self.get_run_time()
        if profile == "A":
            if elapsed > 30 * 60:
                return None
            return (1, 1)
        phase = elapsed % 600
        if elapsed > 1200:
            return None
        if 300 <= phase < 360:
            return (100, 100)
        return (1, 1)
