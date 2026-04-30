const API = "/api";
const state = {
  token: localStorage.getItem("token"),
  user: null,
  projects: [],
  selectedProject: null,
  members: [],
  tasks: [],
  dashboard: null,
};

const $ = (selector) => document.querySelector(selector);

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "Request failed");
  return payload;
}

function fmtDate(value) {
  if (!value) return "";
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message, tone = "error") {
  const node = $("#toast");
  if (!node) return;
  node.textContent = message;
  node.className = `toast ${tone}`;
  setTimeout(() => (node.className = "toast"), 3200);
}

function authView(mode = "login") {
  const isSignup = mode === "signup";
  $("#app").innerHTML = `
    <main class="auth-shell">
      <section class="auth-panel">
        <div>
          <p class="eyebrow">Collaborative task management</p>
          <h1>TeamFlow</h1>
          <p class="lede">Create projects, assign work, and keep every team member focused on the tasks they own.</p>
        </div>
        <form id="authForm" class="form-card">
          <h2>${isSignup ? "Create account" : "Welcome back"}</h2>
          ${isSignup ? `<label>Name<input name="name" autocomplete="name" required /></label>` : ""}
          <label>Email<input name="email" type="email" autocomplete="email" required /></label>
          <label>Password<input name="password" type="password" autocomplete="${isSignup ? "new-password" : "current-password"}" minlength="8" required /></label>
          <button class="primary" type="submit">${isSignup ? "Sign up" : "Log in"}</button>
          <button class="link-button" type="button" id="switchMode">
            ${isSignup ? "Already have an account? Log in" : "Need an account? Sign up"}
          </button>
        </form>
      </section>
      <div id="toast" class="toast"></div>
    </main>
  `;
  $("#switchMode").addEventListener("click", () => authView(isSignup ? "login" : "signup"));
  $("#authForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const payload = await request(isSignup ? "/auth/signup" : "/auth/login", {
        method: "POST",
        body: JSON.stringify(data),
      });
      state.token = payload.token;
      state.user = payload.user;
      localStorage.setItem("token", state.token);
      await boot();
    } catch (error) {
      toast(error.message);
    }
  });
}

async function boot() {
  if (!state.token) return authView();
  try {
    const me = await request("/me");
    state.user = me.user;
    await loadProjects();
    renderApp();
  } catch {
    localStorage.removeItem("token");
    state.token = null;
    authView();
  }
}

async function loadProjects() {
  const payload = await request("/projects");
  state.projects = payload.projects;
  if (!state.selectedProject && state.projects.length) state.selectedProject = state.projects[0].id;
  if (state.selectedProject) await loadProject(state.selectedProject);
  await loadDashboard();
}

async function loadProject(projectId) {
  const [detail, tasks] = await Promise.all([
    request(`/projects/${projectId}`),
    request(`/projects/${projectId}/tasks`),
  ]);
  state.selectedProject = projectId;
  state.members = detail.members;
  state.tasks = tasks.tasks;
  const existing = state.projects.find((project) => project.id === projectId);
  state.currentProject = { ...(existing || {}), ...detail.project };
}

async function loadDashboard() {
  state.dashboard = await request(state.selectedProject ? `/dashboard?project_id=${state.selectedProject}` : "/dashboard");
}

function renderApp() {
  $("#app").innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <span class="brand-mark">TF</span>
          <div>
            <strong>TeamFlow</strong>
            <small>${escapeHtml(state.user.name)}</small>
          </div>
        </div>
        <form id="projectForm" class="project-form">
          <input name="name" placeholder="New project" required />
          <input name="description" placeholder="Description" />
          <button title="Create project" class="icon-button" type="submit">+</button>
        </form>
        <nav class="project-list">
          ${state.projects.map(projectCard).join("") || `<p class="empty">Create your first project to start assigning tasks.</p>`}
        </nav>
        <button id="logout" class="ghost">Log out</button>
      </aside>
      <main class="workspace">
        ${state.selectedProject ? workspaceView() : emptyWorkspace()}
      </main>
      <div id="toast" class="toast"></div>
    </div>
  `;
  wireEvents();
}

function projectCard(project) {
  const active = project.id === state.selectedProject ? "active" : "";
  const done = Number(project.done_count || 0);
  const total = Number(project.task_count || 0);
  return `
    <button class="project-card ${active}" data-project="${project.id}">
      <span>
        <strong>${escapeHtml(project.name)}</strong>
        <small>${project.role} - ${done}/${total} done</small>
      </span>
    </button>
  `;
}

function emptyWorkspace() {
  return `
    <section class="starter">
      <div class="starter-hero">
        <p class="eyebrow">Start workspace</p>
        <h1>Plan the work before the work gets noisy.</h1>
        <p>Create a project from the left panel. You become the Admin, then you can add members, assign tasks, and track progress from this dashboard.</p>
      </div>
      <div class="starter-grid">
        <article>
          <strong>1</strong>
          <span>Create a project</span>
          <p>Add a name and short description in the sidebar form.</p>
        </article>
        <article>
          <strong>2</strong>
          <span>Invite teammates</span>
          <p>Add registered users by email and choose Admin or Member access.</p>
        </article>
        <article>
          <strong>3</strong>
          <span>Assign tasks</span>
          <p>Use due dates, priorities, assignees, and status updates to keep work visible.</p>
        </article>
      </div>
      <section class="starter-preview">
        <div><span>Total tasks</span><strong>0</strong></div>
        <div><span>Completion</span><strong>0%</strong></div>
        <div><span>Overdue</span><strong>0</strong></div>
        <div><span>Workload</span><strong>Ready</strong></div>
      </section>
    </section>
  `;
}

function workspaceView() {
  const isAdmin = state.currentProject?.role === "Admin";
  return `
    <header class="topbar">
      <div>
        <p class="eyebrow">${state.currentProject.role}</p>
        <h1>${escapeHtml(state.currentProject.name)}</h1>
        <p>${escapeHtml(state.currentProject.description || "No description yet.")}</p>
      </div>
    </header>
    ${dashboardView()}
    <section class="content-grid">
      <div class="panel task-panel">
        <div class="panel-head">
          <h2>Tasks</h2>
          <div class="status-tabs">
            <button class="tab active" data-filter="All">All</button>
            <button class="tab" data-filter="To Do">To Do</button>
            <button class="tab" data-filter="In Progress">In Progress</button>
            <button class="tab" data-filter="Done">Done</button>
          </div>
        </div>
        ${isAdmin ? taskForm() : ""}
        <div id="taskList" class="task-list">${state.tasks.map(taskCard).join("") || `<p class="empty">No tasks visible yet.</p>`}</div>
      </div>
      <aside class="panel members-panel">
        <div class="panel-head">
          <h2>Members</h2>
          <span>${state.members.length}</span>
        </div>
        ${isAdmin ? memberForm() : ""}
        <div class="members">${state.members.map(memberRow).join("")}</div>
      </aside>
    </section>
  `;
}

function dashboardView() {
  const dash = state.dashboard || { total_tasks: 0, by_status: {}, by_priority: {}, per_user: {}, overdue: 0, recent: [] };
  const done = dash.by_status.Done || 0;
  const todo = dash.by_status["To Do"] || 0;
  const progress = dash.by_status["In Progress"] || 0;
  const completion = dash.completion_rate || 0;
  const statusTotal = Math.max(1, dash.total_tasks || 0);
  return `
    <section class="metrics">
      <article><span>Total tasks</span><strong>${dash.total_tasks}</strong></article>
      <article><span>Active</span><strong>${dash.active_tasks || 0}</strong></article>
      <article><span>Due this week</span><strong>${dash.due_soon || 0}</strong></article>
      <article><span>High priority</span><strong>${dash.high_priority_open || 0}</strong></article>
      <article class="${dash.overdue ? "danger" : ""}"><span>Overdue</span><strong>${dash.overdue}</strong></article>
    </section>
    <section class="analytics-grid">
      <article class="analytics-card progress-card">
        <div>
          <h2>Completion</h2>
          <p>${done} of ${dash.total_tasks} tasks are done</p>
        </div>
        <div class="progress-ring" style="--value:${completion}"><strong>${completion}%</strong></div>
      </article>
      <article class="analytics-card">
        <h2>Status breakdown</h2>
        <div class="stacked-bar" aria-label="Task status breakdown">
          <span class="todo" style="width:${(todo / statusTotal) * 100}%"></span>
          <span class="doing" style="width:${(progress / statusTotal) * 100}%"></span>
          <span class="done" style="width:${(done / statusTotal) * 100}%"></span>
        </div>
        <div class="legend">
          <span><i class="todo"></i>To Do ${todo}</span>
          <span><i class="doing"></i>In Progress ${progress}</span>
          <span><i class="done"></i>Done ${done}</span>
        </div>
      </article>
      <article class="analytics-card">
        <h2>Priority mix</h2>
        <div class="priority-grid">
          ${["Urgent", "High", "Medium", "Low"].map((priority) => priorityTile(priority, dash.by_priority?.[priority] || 0)).join("")}
        </div>
      </article>
      <article class="analytics-card">
        <h2>Next focus</h2>
        ${dash.next_due ? nextDueCard(dash.next_due) : `<p class="empty">No open task is due yet.</p>`}
        <p class="insight">${dash.unassigned || 0} unassigned task${dash.unassigned === 1 ? "" : "s"} need ownership.</p>
      </article>
    </section>
    <section class="dashboard-panels">
      <section class="workload">
        <h2>Tasks per user</h2>
        <div class="bars">
          ${Object.entries(dash.per_user || {}).map(([name, count]) => workloadBar(name, count, dash.total_tasks)).join("") || `<p class="empty">No workload data yet.</p>`}
        </div>
      </section>
      <section class="workload recent-panel">
        <h2>Recently updated</h2>
        <div class="recent-list">
          ${(dash.recent || []).map(recentTask).join("") || `<p class="empty">No recent task activity yet.</p>`}
        </div>
      </section>
    </section>
  `;
}

function priorityTile(priority, count) {
  return `
    <div class="priority-tile ${priority.toLowerCase()}">
      <span>${priority}</span>
      <strong>${count}</strong>
    </div>
  `;
}

function nextDueCard(task) {
  return `
    <div class="next-due">
      <strong>${escapeHtml(task.title)}</strong>
      <span>${escapeHtml(task.assignee_name || "Unassigned")} - ${fmtDate(task.due_date)}</span>
      <small>${task.priority} priority in ${escapeHtml(task.project_name)}</small>
    </div>
  `;
}

function recentTask(task) {
  return `
    <div class="recent-task">
      <span>
        <strong>${escapeHtml(task.title)}</strong>
        <small>${escapeHtml(task.project_name)} - ${escapeHtml(task.assignee_name || "Unassigned")}</small>
      </span>
      <span class="chip">${task.status}</span>
    </div>
  `;
}

function workloadBar(name, count, total) {
  const width = total ? Math.max(8, (count / total) * 100) : 0;
  return `
    <div class="bar-row">
      <span>${escapeHtml(name)}</span>
      <div class="bar-track"><div style="width:${width}%"></div></div>
      <strong>${count}</strong>
    </div>
  `;
}

function taskForm() {
  return `
    <form id="taskForm" class="task-form">
      <input name="title" placeholder="Task title" required />
      <input name="description" placeholder="Description" />
      <input name="due_date" type="date" required />
      <select name="priority">
        <option>Medium</option><option>Low</option><option>High</option><option>Urgent</option>
      </select>
      <select name="assigned_to">
        <option value="">Unassigned</option>
        ${state.members.map((member) => `<option value="${member.id}">${escapeHtml(member.name)}</option>`).join("")}
      </select>
      <button class="primary" type="submit">Add task</button>
    </form>
  `;
}

function taskCard(task) {
  const overdue = task.status !== "Done" && task.due_date < new Date().toISOString().slice(0, 10);
  return `
    <article class="task-card" data-status="${task.status}">
      <div>
        <h3>${escapeHtml(task.title)}</h3>
        <p>${escapeHtml(task.description || "No description")}</p>
        <div class="chips">
          <span class="chip priority-${task.priority.toLowerCase()}">${task.priority}</span>
          <span class="chip ${overdue ? "overdue" : ""}">${fmtDate(task.due_date)}</span>
          <span class="chip">${escapeHtml(task.assignee_name || "Unassigned")}</span>
        </div>
      </div>
      <div class="task-actions">
        <select class="status-select" data-task="${task.id}">
          ${["To Do", "In Progress", "Done"].map((status) => `<option ${status === task.status ? "selected" : ""}>${status}</option>`).join("")}
        </select>
        ${state.currentProject.role === "Admin" ? `<button class="icon-button danger-button" title="Delete task" data-delete-task="${task.id}">x</button>` : ""}
      </div>
    </article>
  `;
}

function memberForm() {
  return `
    <form id="memberForm" class="member-form">
      <input name="email" type="email" placeholder="user@email.com" required />
      <select name="role"><option>Member</option><option>Admin</option></select>
      <button class="primary" type="submit">Add</button>
    </form>
  `;
}

function memberRow(member) {
  const removable = state.currentProject.role === "Admin" && member.id !== state.user.id;
  return `
    <div class="member-row">
      <span>
        <strong>${escapeHtml(member.name)}</strong>
        <small>${escapeHtml(member.email)}</small>
      </span>
      <span class="role-pill">${member.role}</span>
      ${removable ? `<button class="icon-button" title="Remove member" data-remove-member="${member.id}">x</button>` : ""}
    </div>
  `;
}

function wireEvents() {
  $("#logout")?.addEventListener("click", () => {
    localStorage.removeItem("token");
    state.token = null;
    authView();
  });

  $("#projectForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await request("/projects", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
      await loadProjects();
      renderApp();
      toast("Project created", "success");
    } catch (error) {
      toast(error.message);
    }
  });

  document.querySelectorAll("[data-project]").forEach((button) => {
    button.addEventListener("click", async () => {
      await loadProject(Number(button.dataset.project));
      await loadDashboard();
      renderApp();
    });
  });

  $("#taskForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await request(`/projects/${state.selectedProject}/tasks`, { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
      await loadProject(state.selectedProject);
      await loadDashboard();
      renderApp();
      toast("Task added", "success");
    } catch (error) {
      toast(error.message);
    }
  });

  $("#memberForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await request(`/projects/${state.selectedProject}/members`, { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
      await loadProject(state.selectedProject);
      renderApp();
      toast("Member updated", "success");
    } catch (error) {
      toast(error.message);
    }
  });

  document.querySelectorAll(".status-select").forEach((select) => {
    select.addEventListener("change", async () => {
      try {
        await request(`/tasks/${select.dataset.task}`, { method: "PATCH", body: JSON.stringify({ status: select.value }) });
        await loadProject(state.selectedProject);
        await loadDashboard();
        renderApp();
      } catch (error) {
        toast(error.message);
      }
    });
  });

  document.querySelectorAll("[data-delete-task]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await request(`/tasks/${button.dataset.deleteTask}`, { method: "DELETE" });
        await loadProject(state.selectedProject);
        await loadDashboard();
        renderApp();
      } catch (error) {
        toast(error.message);
      }
    });
  });

  document.querySelectorAll("[data-remove-member]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await request(`/projects/${state.selectedProject}/members/${button.dataset.removeMember}`, { method: "DELETE" });
        await loadProject(state.selectedProject);
        renderApp();
      } catch (error) {
        toast(error.message);
      }
    });
  });

  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
      button.classList.add("active");
      const filter = button.dataset.filter;
      document.querySelectorAll(".task-card").forEach((card) => {
        card.hidden = filter !== "All" && card.dataset.status !== filter;
      });
    });
  });
}

boot();
