# TeamFlow Task Management Web Application

TeamFlow is a full-stack collaborative task manager for teams. Users can sign up, create projects, invite members, assign tasks, update progress, and view dashboard metrics.

## Features

- Secure signup and login with signed JWT-style bearer tokens
- PBKDF2 password hashing with per-user salts
- SQLite database with related Users, Projects, Project Members, and Tasks tables
- Project Admin and Member role enforcement
- Admin project member management
- Admin task creation, assignment, updates, and deletion
- Member access limited to assigned tasks
- Dashboard cards for total tasks, status counts, workload per user, and overdue tasks
- RESTful JSON API and responsive frontend served by one deployable service

## Tech Stack

- Backend: Python standard library HTTP server
- Database: SQLite
- Frontend: HTML, CSS, JavaScript
- Deployment target: Railway

## Local Run

```bash
python app.py
```

Then open `http://localhost:8000`.

If you want a custom port:

```bash
PORT=3000 python app.py
```

On Windows PowerShell:

```powershell
$env:PORT="3000"; python app.py
```

## Environment Variables

| Variable | Required | Example | Purpose |
| --- | --- | --- | --- |
| `JWT_SECRET` | Yes in production | `a-long-random-secret` | Signs auth tokens |
| `DATABASE_PATH` | No | `/data/team_tasks.db` | SQLite file location |
| `PORT` | Railway provides this | `8000` | HTTP server port |

## REST API

### Auth

- `POST /api/auth/signup`
- `POST /api/auth/login`
- `GET /api/me`

### Projects

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/:id`
- `POST /api/projects/:id/members`
- `DELETE /api/projects/:id/members/:userId`

### Tasks

- `GET /api/projects/:id/tasks`
- `POST /api/projects/:id/tasks`
- `PATCH /api/tasks/:id`
- `DELETE /api/tasks/:id`

### Dashboard

- `GET /api/dashboard`
- `GET /api/dashboard?project_id=:id`

## Railway Deployment

1. Push this folder to a GitHub repository.
2. Create a new Railway project from the GitHub repository.
3. Set the start command to:

   ```bash
   python app.py
   ```

4. Add environment variables:

   ```text
   JWT_SECRET=<generate-a-long-random-secret>
   DATABASE_PATH=/data/team_tasks.db
   ```

5. Add a Railway volume mounted at `/data` so the SQLite database persists between deploys.
6. Deploy. Railway will inject the public URL and `PORT`; the backend and frontend are served from the same app, so no separate CORS or frontend API URL setup is needed.

## Default Roles

- The user who creates a project becomes its `Admin`.
- Admins can add or remove members, create tasks, assign tasks, update any task, and delete tasks.
- Members can view their projects and update the status of tasks assigned to them.
