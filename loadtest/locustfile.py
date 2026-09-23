from locust import HttpUser, task, between
import random
import time


class ObservabilityUser(HttpUser):

    wait_time = between(0.3, 0.7)

    # --------------------------------------------------
    # INCIDENT CONFIGURATION
    # --------------------------------------------------

    INCIDENTS = [
        "latency",
        "db_latency",
        "error",
        "404",
        "cpu",
        "memory",
    ]

    INCIDENT_DURATION = 180
    INCIDENT_INTERVAL = 60

    # Shared state across users
    current_incident = None
    incident_start = 0
    incident_until = 0

    recent_incidents = []

    COOLDOWN = 3

    # --------------------------------------------------
    # INCIDENT SELECTION
    # --------------------------------------------------

    @classmethod
    def start_random_incident(cls):

        available = [
            incident
            for incident in cls.INCIDENTS
            if incident not in cls.recent_incidents
        ]

        # Safety fallback
        if not available:
            cls.recent_incidents = []
            available = cls.INCIDENTS

        cls.current_incident = random.choice(available)

        cls.recent_incidents.append(cls.current_incident)

        # Don't allow the same incident for the
        # next 3 incident cycles
        if len(cls.recent_incidents) > cls.COOLDOWN:
            cls.recent_incidents.pop(0)

        now = time.time()

        cls.incident_start = now
        cls.incident_until = now + cls.INCIDENT_DURATION

        print(
            f"\n🚨 INCIDENT STARTED: "
            f"{cls.current_incident} "
            f"for {cls.INCIDENT_DURATION}s\n"
        )

    # --------------------------------------------------
    # INCIDENT SCHEDULER
    # --------------------------------------------------

    @classmethod
    def update_incident(cls):

        now = time.time()

        # --------------------------------------------------
        # Currently inside an incident
        # --------------------------------------------------

        if cls.current_incident:

            if now < cls.incident_until:
                return

            # Incident finished
            print(
                f"\n✅ INCIDENT ENDED: "
                f"{cls.current_incident}\n"
            )

            cls.current_incident = None

        # --------------------------------------------------
        # Wait until next minute
        # --------------------------------------------------

        # Start a new incident when the next minute begins
        if not hasattr(cls, "next_incident_time"):

            cls.next_incident_time = now

        if now >= cls.next_incident_time:

            cls.start_random_incident()

            # Schedule next incident one minute later
            cls.next_incident_time = (
                cls.next_incident_time
                + cls.INCIDENT_INTERVAL
            )

    # --------------------------------------------------
    # NORMAL TRAFFIC
    # --------------------------------------------------

    def normal_traffic(self):

        endpoint = random.choice([
            "/",
            "/health",
            "/ready",
            "/users",
            "/cache/test",
            "/external",
        ])

        self.client.get(endpoint)

    # --------------------------------------------------
    # INCIDENT TRAFFIC
    # --------------------------------------------------

    def incident_traffic(self, incident):

        if incident == "latency":

            self.client.get(
                "/work?delay=2"
            )

        elif incident == "db_latency":

            self.client.get(
                "/db-slow?seconds=2"
            )

        elif incident == "error":

            self.client.get(
                "/error"
            )

        elif incident == "404":

            self.client.get(
                "/does-not-exist"
            )

        elif incident == "cpu":

            self.client.get(
                "/cpu?seconds=2"
            )

        elif incident == "memory":

            self.client.get(
                "/memory?mb=50&seconds=2"
            )

    # --------------------------------------------------
    # MAIN TRAFFIC
    # --------------------------------------------------

    @task
    def traffic(self):

        self.update_incident()

        if self.current_incident:

            self.incident_traffic(
                self.current_incident
            )

        else:

            self.normal_traffic()
