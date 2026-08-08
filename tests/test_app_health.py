import app as application


class HealthyConnection:
    def __init__(self):
        self.closed = False
        self.queries = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query):
        self.queries.append(query)

    def fetchone(self):
        return {'ok': 1}

    def close(self):
        self.closed = True


def test_health_check_reports_database_readiness(client, monkeypatch):
    connection = HealthyConnection()
    monkeypatch.setattr(application, 'get_db_connection', lambda: connection)

    response = client.get('/health')

    assert response.status_code == 200
    assert response.get_json()['status'] == 'healthy'
    assert connection.queries == ['SELECT 1 AS ok']
    assert connection.closed is True


def test_health_check_hides_database_errors(client, monkeypatch):
    monkeypatch.setattr(application, 'get_db_connection', lambda: (_ for _ in ()).throw(RuntimeError('database password leaked')))

    response = client.get('/health')

    assert response.status_code == 503
    assert response.get_json()['status'] == 'unhealthy'
    assert 'error' not in response.get_json()
    assert b'database password leaked' not in response.data