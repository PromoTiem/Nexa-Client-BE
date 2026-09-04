from locust import HttpUser, between, task


class NexaClientUser(HttpUser):
    """Basic load test skeleton for Nexa-Client-BE API endpoints."""

    wait_time = between(1, 3)

    def on_start(self):
        """Authenticate on start and store token for subsequent requests."""
        response = self.client.post(
            "/auth/login",
            json={
                "identity": self.environment.parsed_options.identity
                if hasattr(self.environment.parsed_options, "identity")
                else "",
                "password": self.environment.parsed_options.password
                if hasattr(self.environment.parsed_options, "password")
                else "",
            },
        )
        if response.status_code == 200:
            self.token = response.json().get("token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    @task(5)
    def health_check(self):
        """GET /health - public endpoint, high weight."""
        self.client.get("/health")

    @task(3)
    def list_sites(self):
        """GET /sites - list sites for authenticated user."""
        if self.token:
            self.client.get("/sites", headers=self.headers)

    @task(2)
    def list_templates(self):
        """GET /templates - list templates."""
        if self.token:
            self.client.get("/templates", headers=self.headers)

    @task(2)
    def list_styles(self):
        """GET /styles - list styles."""
        if self.token:
            self.client.get("/styles", headers=self.headers)

    @task(2)
    def list_blocks(self):
        """GET /blocks - list blocks."""
        if self.token:
            self.client.get("/blocks", headers=self.headers)

    @task(1)
    def get_profile(self):
        """GET /users/me - get current user profile."""
        if self.token:
            self.client.get("/users/me", headers=self.headers)

    @task(1)
    def refresh_token(self):
        """POST /auth/refresh - refresh authentication token."""
        if self.token:
            self.client.post("/auth/refresh", headers=self.headers)
