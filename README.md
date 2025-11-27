# LMPW - Notes API

A FastAPI-based Notes API that syncs markdown notes from GitHub, supports payments via Stripe, and delivers content as markdown, PDF, or ZIP files.

## Features

- **User Authentication**: JWT-based authentication with registration and login
- **Notes Management**: Sync notes from a GitHub repository
- **Multiple Formats**: Download notes as Markdown, PDF, or ZIP
- **Payment Integration**: Stripe integration for paid content
- **Webhooks**: GitHub webhook support for automatic sync
- **Email Delivery**: Optional email delivery of purchased content

## Quick Start

### Prerequisites

- Python 3.12+
- MongoDB instance (local or MongoDB Atlas)
- (Optional) GitHub repository with markdown notes
- (Optional) Stripe account for payments

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/TheStatsProject/LMPW.git
   cd LMPW
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. Run the application:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/health/db` | GET | Database health check |
| `/register` | POST | Register new user |
| `/login` | POST | Login and get JWT token |
| `/me` | GET | Get current user info |
| `/notes` | GET | List all notes |
| `/note/{slug}` | GET | Get note content |
| `/note/{slug}/preview` | GET | Get note preview |
| `/note/{slug}/download_zip` | POST | Download note as ZIP |
| `/note/{slug}/pdf` | GET | Download note as PDF |
| `/github/webhook` | POST | GitHub webhook for sync |
| `/stripe/webhook` | POST | Stripe payment webhook |
| `/admin/sync` | POST | Manual sync trigger |

## Deployment

### Docker with Docker Compose (Recommended)

The easiest way to deploy:

1. Copy the environment file and configure it:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your MongoDB Atlas credentials:
   ```bash
   # Get your connection string from MongoDB Atlas:
   # https://cloud.mongodb.com -> Your Cluster -> Connect -> Drivers
   MONGO_URL=mongodb://YOUR_USERNAME:YOUR_PASSWORD@atlas-sql-687f19d2678c807903e45f78-zalniw.g.query.mongodb.net/LMBD?ssl=true&authSource=admin
   SESSION_SECRET_KEY=your-secure-random-secret-key
   ```

3. Start the application:
   ```bash
   docker-compose up -d
   ```

4. Access the application:
   - API Documentation: http://localhost:8000/docs
   - Health Check: http://localhost:8000/health

5. View logs:
   ```bash
   docker-compose logs -f
   ```

6. Stop the application:
   ```bash
   docker-compose down
   ```

### Docker (Manual)

```bash
docker build -t lmpw .
docker run -p 8000:8000 --env-file .env lmpw
```

### Heroku

```bash
heroku create your-app-name
heroku config:set MONGO_URL="mongodb+srv://..."
heroku config:set SESSION_SECRET_KEY="your-secret-key"
# Set other environment variables as needed
git push heroku main
```

### Railway / Render / Fly.io

These platforms will automatically detect the Dockerfile or Procfile and deploy accordingly. Make sure to set all required environment variables.

## Configuration

See `.env.example` for all available configuration options.

### Required Environment Variables

- `MONGO_URL`: MongoDB connection string
- `SESSION_SECRET_KEY`: Secret key for JWT tokens

### Optional Environment Variables

- `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_TOKEN`: For GitHub sync
- `GITHUB_AUTO_SYNC`: Set to `true`, `1`, or `yes` to enable automatic sync of notes from GitHub on application startup. Requires valid `GITHUB_OWNER` and `GITHUB_REPO` values (not placeholder defaults). Disabled by default to avoid noisy errors during initial setup.
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`: For payments
- `EMAIL_HOST`, `EMAIL_USER`, `EMAIL_PASS`: For email delivery

## License

MIT