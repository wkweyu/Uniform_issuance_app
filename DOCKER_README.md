Docker development setup
========================

This project includes Docker and docker-compose configuration for local development.

Quick start (local development with the included MySQL service):

1. Copy the `.env.example` to `.env` and edit values (do not commit `.env`):

```bash
cp .env.example .env
# edit .env to set DB_USER/DB_PASSWORD/DB_NAME if desired
```

2. Build and start services:

```bash
docker-compose build
docker-compose up -d
```

3. Tail logs:

```bash
docker-compose logs -f web
```

4. Stop and remove:

```bash
docker-compose down
```

Notes
- The `web` service mounts the project directory into the container for fast iteration.
- The `db` service provides a local MySQL instance for development; you can point `DB_HOST` to a cloud DB instead.
- For production deploy the same image to a managed container service (Render, Cloud Run, etc.) and configure secrets there.
