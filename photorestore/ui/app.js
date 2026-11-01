"use strict";
const $ = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const bytes = (n) => {
  if (!n) return "0 B";
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), 4);
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${["B", "KB", "MB", "GB", "TB"][i]}`;
};
const number = (n) => Number(n || 0).toLocaleString();
const date = (s) => (s ? new Date(s).toLocaleString() : "—");
let token = null,
  state = null,
  page = "dashboard",
  offset = 0,
  filter = "",
  search = "",
  pollBusy = false,
  formBusy = false,
  activityTime = 0,
  renderVersion = 0,
  recoveryKey = null,
  canStartOver = false;
const titles = {
  dashboard: "Dashboard",
  setup: "Setup",
  queue: "Queue",
  history: "History & reports",
  settings: "Settings",
  accounts: "Accounts",
  logs: "Logs & diagnostics",
  help: "Help",
};
const icons = {
  dashboard: "▦",
  setup: "⊕",
  queue: "≡",
  history: "◷",
  settings: "⚙",
  accounts: "♙",
  logs: "⌘",
  help: "?",
};
const statusNames = {
  pending: "Ready",
  preparing: "Preparing",
  uploading: "Uploading",
  uploaded: "Browser confirmed",
  verified: "Verified by you",
  failed: "Failed",
  rejected: "Rejected",
  skipped: "Skipped",
  review: "Needs review",
  restoration_review: "Restore details",
};
function pill(status) {
  return `<span class="pill ${["uploaded", "verified"].includes(status) ? "good" : ["review", "restoration_review", "needs_review", "partial", "no_uploads"].includes(status) ? "warn" : ["failed", "rejected"].includes(status) ? "bad" : ""}">${esc(statusNames[status] || ({needs_review:"Review required",partial:"More items ready",no_uploads:"No uploads confirmed"})[status] || status)}</span>`;
}
function notice(title, message = "", error = false) {
  $("#notice").className = error ? "error" : "";
  $("#notice").innerHTML =
    `<button class="quiet small" data-action="dismiss" aria-label="Dismiss notification">✕</button><strong>${esc(title)}</strong>${esc(message)}`;
  $("#notice").hidden = false;
}
async function api(action, params = {}) {
  const r = await window.pywebview.api.request(action, params, token);
  if (!r.ok) {
    if (r.error.code === "GPP-102") {
      token = null;
      state = null;
      await authScreen();
    }
    notice(`${r.error.code} · ${r.error.title}`, r.error.message, true);
    throw new Error(r.error.code);
  }
  return r.data;
}
async function confirmAction(title, text, ok = "Continue") {
  $("#modal-title").textContent = title;
  $("#modal-content").textContent = text;
  $("#modal-ok").textContent = ok;
  $("#modal").showModal();
  return new Promise((resolve) =>
    $("#modal").addEventListener(
      "close",
      () => resolve($("#modal").returnValue === "ok"),
      { once: true },
    ),
  );
}
function details(title, data) {
  $("#modal-title").textContent = title;
  $("#modal-content").replaceChildren(
    Object.assign(document.createElement("pre"), {
      textContent: JSON.stringify(data, null, 2),
    }),
  );
  $("#modal-ok").textContent = "Close";
  $("#modal").showModal();
}
async function authScreen() {
  renderVersion++;
  const b = await window.pywebview.api.request("bootstrap", {}, null);
  const first = !b.data.has_accounts;
  canStartOver = b.data.can_start_over;
  $("#app").innerHTML =
    `<div class="auth-page"><div class="auth-card"><div class="brand"><div class="mark">↑</div>Takeout Restore</div><h1>${first ? "A fresh start for your memories." : "Welcome back."}</h1><p>${first ? "Create your local administrator account to get started." : "Sign in to your local account to continue your restore."}</p><form id="auth-form" data-register="${first}"><div class="field"><label for="username">Username</label><input id="username" name="username" autocomplete="username" minlength="3" maxlength="48" required autofocus></div><div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="${first ? "new-password" : "current-password"}" ${first ? 'minlength="12"' : ""} maxlength="256" required>${first ? "<small>At least 12 characters. A memorable passphrase works well.</small>" : ""}</div><button type="submit">${first ? "Create account" : "Sign in"}</button></form>${!first ? `<div class="actions mt18">${actionButton("forgot-password", "Forgot password?", true)}${canStartOver ? actionButton("start-over", "Start over on this Mac", true) : ""}</div>` : ""}<p class="auth-footer">This is your local app account. You’ll sign in to Google separately in a Google browser window. Your Google password never enters this app.</p></div></div>`;
}
function showRecovery(code) {
  if (!code) return;
  recoveryKey = code;
  $("#recovery-code").textContent = code;
  $("#recovery-modal").showModal();
}
$("#recovery-modal").addEventListener("close", () => {
  recoveryKey = null;
  $("#recovery-code").textContent = "";
});
function recoveryScreen() {
  $("#app").innerHTML = `<div class="auth-page"><div class="auth-card"><h1>Reset your password</h1><p>Use the recovery key saved when you signed in. Your history and saved Google session will be preserved.</p><form id="recovery-form"><div class="field"><label for="recovery-user">Username</label><input id="recovery-user" name="username" autocomplete="username" maxlength="48" required></div><div class="field"><label for="recovery-key">Recovery key</label><input id="recovery-key" name="recovery_key" autocomplete="off" spellcheck="false" maxlength="200" required></div><div class="field"><label for="recovery-password">New password</label><input id="recovery-password" name="password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></div><button type="submit">Reset password</button></form><div class="actions mt18">${actionButton("back-auth", "Back to sign in", true)}</div><p class="tiny muted mt18">No recovery key? Another app administrator can reset your password. On macOS, Start over removes all local app accounts after device verification. Source files and Google Photos remain.</p></div></div>`;
}
async function passwordPrompt(title, message) {
  $("#modal-title").textContent = title;
  $("#modal-content").innerHTML = `<p>${esc(message)}</p><label for="confirm-password">Current app password</label><input id="confirm-password" type="password" autocomplete="current-password" maxlength="256" required>`;
  $("#modal-ok").textContent = "Continue";
  $("#modal").showModal();
  const accepted = await new Promise(resolve => $("#modal").addEventListener("close", () => resolve($("#modal").returnValue === "ok"), {once:true}));
  const password = $("#confirm-password").value;
  $("#confirm-password").value = "";
  return accepted ? password : null;
}
function shell() {
  const u = state.user;
  $("#app").innerHTML =
    `<div class="layout"><aside class="sidebar"><div class="brand"><div class="mark">↑</div>Takeout Restore</div><div class="nav-section">Your library</div><nav class="nav" aria-label="Main navigation">${Object.keys(
      titles,
    )
      .map(
        (p, i) =>
          `${i === 4 ? '<div class="nav-section">Manage</div>' : ""}<button data-page="${p}" class="${page === p ? "active" : ""}" ${page === p ? 'aria-current="page"' : ""}><span class="nav-icon" aria-hidden="true">${icons[p]}</span>${titles[p]}</button>`,
      )
      .join(
        "",
      )}</nav><div class="sidebar-bottom"><label class="inline tiny"><input id="advanced-toggle" type="checkbox" ${state.settings.advanced ? "checked" : ""} ${state.job.active ? "disabled" : ""}>Advanced view</label><div class="profile-card"><div class="avatar">${esc(u.username.slice(0, 2).toUpperCase())}</div><div><div class="profile-name tiny">${esc(u.username)}</div><span class="muted tiny">${u.role === "admin" ? "Administrator" : "Standard account"}</span></div></div><button class="quiet tiny" data-action="logout" ${state.job.active ? "disabled" : ""}>Lock & sign out</button></div></aside><main class="main"><div class="topline"><span>Workspace / ${titles[page]}</span><span class="local"><span class="dot"></span>Local & private</span></div><section id="content"></section><footer class="footer"><span>Takeout Restore · Preview 0.1.5</span><span>Your originals stay untouched</span></footer></main></div>`;
}
function header(title, subtitle, actions = "") {
  return `<header class="pagehead"><div><h1>${title}</h1><p>${subtitle}</p></div><div class="actions">${actions}</div></header>`;
}
function empty(title, text, action = "") {
  return `<div class="empty"><div class="empty-icon">▤</div><h2>${title}</h2><p>${text}</p>${action}</div>`;
}
const actionButton = (action, label, secondary = false, disabled = false) =>
  `<button data-action="${action}" class="${secondary ? "secondary" : ""}" ${disabled ? "disabled" : ""}>${label}</button>`;
function jobCard() {
  const j = state.job;
  return j.active
    ? `<div class="card"><div class="job"><strong>${esc(j.phase)}</strong>${j.awaiting_google_confirmation ? actionButton("confirm_google", "I’ve signed in — Continue") : ""}${actionButton("pause", "Pause safely", true)}</div><div class="progress" role="progressbar" aria-label="Operation in progress"></div><p class="tiny muted">${j.phase === "Downloading browser" ? `${j.count}% downloaded` : `${number(j.count)} items processed in this operation`} · Pausing finishes the current submitted upload.</p></div>`
    : j.outcome === "needs_review" && !j.error
      ? `<div class="banner"><strong>Review required</strong>${number(j.processed_count)} uploads confirmed in this run. Unresolved items remain in Queue; finishing an operation does not confirm those uploads.</div>`
    : j.error
      ? `<div class="banner"><strong>${esc(j.error.code + " · " + j.error.title)}</strong>${esc(j.error.message)}</div>`
      : "";
}
function dashboard() {
  const c = state.counts,
    total = Object.values(c).reduce((a, b) => a + b, 0),
    complete =
      (c.uploaded || 0) + (c.verified || 0) + (c.restoration_review || 0),
    review =
      (c.review || 0) +
      (c.restoration_review || 0) +
      (c.failed || 0) +
      (c.rejected || 0);
  return (
    header(
      "Bring your memories home.",
      "Restore your Google Takeout photos and videos, one carefully tracked step at a time.",
      actionButton("go-setup", total ? "Review setup" : "Get started", true),
    ) +
    jobCard() +
    `<div class="stats">${[
      ["In this workspace", total, bytes(state.bytes) + " of source media"],
      ["Ready to upload", c.pending || 0, "Waiting in your queue"],
      ["Upload confirmed", complete, "Browser or user confirmation"],
      ["Needs attention", review, "Review before continuing"],
    ]
      .map(
        ([l, n, t]) =>
          `<div class="card stat"><div class="stat-label">${l}</div><div class="stat-number">${number(n)}</div><div class="stat-note">${t}</div></div>`,
      )
      .join(
        "",
      )}</div>${!total ? `<div class="card hero"><div><div class="eyebrow">Start with your Takeout</div><h2 class="mt9">A familiar place for every photo.</h2><p>Select your extracted Takeout folder. We’ll find the photos, match their metadata and build a queue you can review before anything is uploaded.</p>${actionButton("go-setup", "Set up your restore")}</div><div class="hero-icon">↥</div></div>` : ""}<div class="grid2"><div class="card"><h2>Your restore</h2><div class="detail-row"><span>Source folder</span><span class="path">${esc(state.source || "Not selected")}</span></div><div class="detail-row"><span>Browser component</span><span>${state.browser_ready ? "Ready" : "Not installed"}</span></div><div class="detail-row"><span>Google session</span><span>${state.google_connected ? "Saved securely" : "Not connected"}</span></div><div class="actions mt20">${actionButton("upload", "Start upload", false, state.job.active || !state.google_connected || !c.pending)}${actionButton("go-queue", "View queue", true)}</div></div><div class="card"><h2>Designed to be cautious</h2><div class="detail-row"><span>Original files</span><span>Never edited</span></div><div class="detail-row"><span>Duplicate detection</span><span>${state.settings.duplicates === "hash" ? "Content fingerprint" : esc(state.settings.duplicates)}</span></div><div class="detail-row"><span>Interrupted uploads</span><span>Held for review</span></div><p class="tiny muted mt18">Google’s website can change. A browser confirmation is recorded evidence, not a guarantee of every cloud metadata field.</p></div></div>`
  );
}
function setup() {
  const busy = state.job.active;
  return (
    header(
      "Set up your restore.",
      "Everything you need, without editing files or using a terminal.",
    ) +
    jobCard() +
    `<div class="card"><ol class="steps">${[
      [
        "Choose your Takeout folder",
        state.source ||
          "Extract your Takeout ZIP files into a folder first. Choose the Google Photos folder inside it.",
        "pick_source",
        "Choose folder",
        false,
      ],
      [
        "Scan and review",
        "Read metadata and content fingerprints. Large backups can take time; progress is saved as files are scanned.",
        "scan",
        "Scan folder",
        !state.source,
      ],
      [
        "Install the browser component",
        state.browser_ready
          ? `${state.browser_name || "Browser"} is ready. Installed Google Chrome is preferred; the downloaded browser is a fallback.`
          : "Downloaded once from the browser vendor. The signed release supplies its SHA-256 checksum. Internet access is required.",
        "install_browser",
        state.browser_ready ? "Installed" : "Download browser",
        state.browser_ready,
      ],
      [
        "Connect to Google Photos",
        "Sign in manually in the dedicated Chrome window. When Google Photos opens, click “I’ve signed in — Continue” in this app. The app then attaches using the original pipeline’s CDP flow.",
        "connect_google",
        state.google_connected ? "Reconnect" : "Open Chrome sign-in",
        !state.browser_ready,
      ],
      [
        "Check the connection",
        "Checks your Google account and upload controls without uploading a test file.",
        "test_google",
        "Run check",
        !state.google_connected,
      ],
      [
        "Try a small sample",
        "Upload up to five ready items, then check their dates and playback in Google Photos.",
        "upload_sample",
        "Upload sample",
        !state.google_connected || !state.counts.pending,
      ],
    ]
      .map(
        ([t, d, a, l, disabled], i) =>
          `<li class="step"><span class="step-number">${i + 1}</span><div><h3>${t}</h3><p class="path">${esc(d)}</p></div>${actionButton(a, l, true, busy || disabled)}</li>`,
      )
      .join(
        "",
      )}</ol></div><div class="banner"><strong>What can be restored automatically?</strong>Supported file dates, location and descriptions are embedded into staged copies. Album membership, favorites, archive state and paired-photo relationships are recorded for review; this preview does not apply those Google-only features. Originals and existing Google items are never deleted.</div><div class="actions">${actionButton("go-queue", "Review the queue")}${actionButton("go-settings", "Choose restoration rules", true)}</div>`
  );
}
async function queue() {
  const data = await api("queue", { status: filter, search, offset });
  return (
    header(
      "Your upload queue.",
      "Review each item, understand issues, and resume when you’re ready.",
      actionButton(
        "upload",
        "Start upload",
        false,
        state.job.active || !state.google_connected || !state.counts.pending,
      ),
    ) +
    jobCard() +
    `<div class="toolbar"><input id="queue-search" type="search" placeholder="Search filenames…" aria-label="Search filenames" value="${esc(search)}"><select id="queue-filter" aria-label="Filter status"><option value="">All statuses</option>${Object.entries(
      statusNames,
    )
      .map(
        ([v, n]) =>
          `<option value="${v}" ${v === filter ? "selected" : ""}>${n}</option>`,
      )
      .join(
        "",
      )}</select>${actionButton("search", "Apply", true)}<span class="muted tiny">${number(data.total)} items</span></div>${data.items.length ? `<div class="table-wrap"><table><thead><tr><th>File</th><th>Size</th><th>Status</th><th>${state.settings.advanced ? "Actions" : "Details"}</th></tr></thead><tbody>${data.items.map((r) => `<tr><td><div class="filename" title="${esc(r.name)}"><span class="filetype">${esc(r.name.split(".").pop().slice(0, 4))}</span>${esc(r.name)}</div>${r.code ? `<div class="tiny muted">${esc(r.code)}</div>` : ""}</td><td>${bytes(r.size)}</td><td>${pill(r.status)}</td><td><div class="actions"><button class="quiet small" data-detail="${r.id}">Details</button>${state.settings.advanced && !state.job.active ? `${["failed", "skipped", "rejected", "review"].includes(r.status) ? `<button class="secondary small" data-item="${r.id}" data-op="retry" data-state="${r.status}">Retry</button>` : ""}${["pending", "failed", "rejected"].includes(r.status) ? `<button class="quiet small" data-item="${r.id}" data-op="skip">Skip</button>` : ""}${["review", "restoration_review", "uploaded"].includes(r.status) ? `<button class="secondary small" data-item="${r.id}" data-op="verify">Verified</button>` : ""}` : ""}</div></td></tr>`).join("")}</tbody></table></div><div class="pagination"><span>Showing ${offset + 1}–${offset + data.items.length} of ${number(data.total)}</span><div class="actions">${actionButton("prev", "Previous", true, !offset)}${actionButton("next", "Next", true, offset + 100 >= data.total)}</div></div>` : empty("Your queue is clear.", "Scan a folder to add items, or change your filters.", actionButton("go-setup", "Open setup", true))}${!state.settings.advanced ? '<p class="tiny muted mt18">Enable Advanced view to retry, skip or manually verify items. These actions affect your local records only.</p>' : ""}`
  );
}
async function history() {
  const rows = await api("history");
  return (
    header(
      "Every restore has a record.",
      "Operation history and a detailed, portable report of your library.",
      actionButton("report", "Export report", true, state.job.active),
    ) +
    `<div class="banner">Reports contain filenames, album names and restoration intent. Diagnostic bundles in Logs omit those details.</div>${rows.length ? `<div class="table-wrap"><table><thead><tr><th>Operation</th><th>Started</th><th>Outcome</th><th>Items</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(r.kind.replaceAll("_", " "))}</td><td>${esc(date(r.started))}</td><td>${pill(["upload", "upload_sample"].includes(r.kind) && r.status === "finished" && r.count === 0 ? "no_uploads" : r.status)}${r.code ? ` <span class="tiny muted">${esc(r.code)}</span>` : ""}</td><td>${number(r.count)}</td></tr>`).join("")}</tbody></table></div>` : empty("No operations yet.", "Your scans, connection checks and uploads will appear here.")}`
  );
}
const choices = {
  edited: [
    "Edited copies",
    {
      both: "Keep original and edited copies",
      skip: "Skip edited copies",
      only_edited: "Prefer edited copies when present",
    },
    "Affects newly scanned or unsubmitted items.",
  ],
  duplicates: [
    "Duplicates",
    {
      hash: "Skip identical content (recommended)",
      name_size: "Skip matching names and sizes",
      all: "Upload all source paths",
    },
    "Checks this local account’s records, not your existing Google library.",
  ],
  pairs: [
    "Live & motion photos",
    {
      together: "Keep pairs adjacent in the queue",
      separate: "Treat as separate files",
    },
    "Native Google pairing is not guaranteed; reported for review.",
  ],
  albums: [
    "Takeout albums",
    {
      recreate: "Preserve recreation tasks for review",
      ignore: "Ignore albums",
    },
    "Album metadata is saved in your report; automated recreation is not available in this preview.",
  ],
  favorites: [
    "Favorites",
    {
      carry: "Preserve favorite intent for review",
      ignore: "Ignore favorites",
    },
    "Google-only state requires review after upload.",
  ],
  archive: [
    "Archived items",
    {
      carry: "Preserve archive intent for review",
      ignore: "Ignore archive state",
    },
    "Google-only state requires review after upload.",
  ],
  descriptions: [
    "Descriptions",
    {
      carry: "Embed in supported staged files",
      ignore: "Keep original embedded description",
    },
    "Google may not display embedded descriptions as its own caption.",
  ],
  oversize: [
    "Files above Google limits",
    { skip: "Skip and report (recommended)", try: "Try uploading anyway" },
    "200 MB / 200 megapixels per photo; 10 GB per video.",
  ],
};
function settings() {
  const s = state.settings;
  return (
    header(
      "Make it work your way.",
      "Safe defaults for everyday use. More control when you need it.",
    ) +
    `<form id="settings-form"><div class="card"><h2>Restoration preferences</h2><p class="muted tiny">Rescan after changing scan rules. Existing upload evidence is preserved.</p><div class="fields">${Object.entries(
      choices,
    )
      .map(
        ([k, [label, options, help]]) =>
          `<div class="field"><label for="s-${k}">${label}</label><select id="s-${k}" name="${k}">${Object.entries(
            options,
          )
            .map(
              ([v, t]) =>
                `<option value="${v}" ${s[k] === v ? "selected" : ""}>${t}</option>`,
            )
            .join("")}</select><small>${help}</small></div>`,
      )
      .join(
        "",
      )}</div></div><div class="card"><h2>Privacy & resources</h2><div class="fields">${[
      ["auto_lock_minutes", "Lock after inactivity (minutes)", 1, 240],
      ...(s.advanced
        ? [
            ["scratch_gb", "Maximum working space (GB)", 1, 1024],
            ["retry_limit", "Attempts before manual intervention", 1, 10],
            [
              "upload_timeout_minutes",
              "Upload timeout per item (minutes)",
              5,
              1440,
            ],
          ]
        : []),
    ]
      .map(
        ([k, t, min, max]) =>
          `<div class="field"><label for="s-${k}">${t}</label><input type="number" name="${k}" id="s-${k}" min="${min}" max="${max}" value="${s[k]}" required></div>`,
      )
      .join(
        "",
      )}</div><p class="muted tiny mt16">An inactivity lock requests a safe pause. App accounts share the current operating-system account; use separate OS accounts and disk encryption for protection against other local programs.</p></div><button type="submit" ${state.job.active ? "disabled" : ""}>Save preferences</button></form>` + maintenanceSettings()
  );
}
function maintenanceSettings() {
  const admin = state.user.role === "admin", busy = state.job.active;
  return `<div class="card mt20"><h2>Reset &amp; removal</h2><div class="maintenance-actions"><div><h3>Reset to default settings</h3><p class="tiny muted">Restore preferences for your local account. Keep accounts, Google sign-in, source selection, queue and history.</p>${actionButton("reset-settings", "Reset to default settings", true, busy)}</div><div><h3>Clear all data</h3><p class="tiny muted">Permanently remove every local app account, setting, queue, record, log, browser download and saved Google session on this device. Start again with a new account.</p>${actionButton("clear-data", "Clear all data", true, busy || !admin)}</div><div><h3>Uninstall</h3><p class="tiny muted">On macOS, remove all local app data, move the installed app from Applications to Bin and close it. On Windows or Linux, clear data here, then remove the app using your system’s app manager.</p>${actionButton("uninstall", "Uninstall", true, busy || !admin)}</div></div><p class="tiny muted mt18">Clear all data and Uninstall require an app administrator and device verification on macOS (your administrator app password elsewhere). Your Takeout source files, exported reports, and Google Photos library stay intact.</p></div>`;
}
async function accounts() {
  const users = state.user.role === "admin" ? await api("users") : [];
  return (
    header(
      "Your account, your workspace.",
      "Each local user has separate settings, Google sign-in, queue and history.",
    ) +
    `<div class="grid2"><div class="card"><h2>${esc(state.user.username)}</h2><div class="detail-row"><span>Access</span><span>${state.user.role === "admin" ? "Administrator" : "Standard user"}</span></div><div class="detail-row"><span>Google session</span><span>${state.google_connected ? "Encrypted at rest" : "Not connected"}</span></div><p class="tiny muted mt15">A workspace stays bound to its first Google account, even after disconnection. Create another local user for another Google account.</p>${actionButton("disconnect_google", "Disconnect Google", true, state.job.active || !state.google_connected)}</div><form class="card" id="password-form"><h2>Change password</h2><div class="field"><label for="old-password">Current password</label><input id="old-password" name="old" type="password" autocomplete="current-password" required></div><div class="field"><label for="new-password">New password</label><input id="new-password" name="new" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></div><button type="submit" class="mt12" ${state.job.active ? "disabled" : ""}>Update password</button></form></div><div class="card"><h2>Password recovery</h2><p class="tiny muted">Generate a new recovery key to reset a forgotten password without losing your history or saved Google sign-in. The previous recovery key will stop working.</p>${actionButton("regenerate-recovery", "Generate replacement recovery key", true, state.job.active)}</div>${state.user.role === "admin" ? `<div class="card"><h2>Users on this device</h2><div class="table-wrap"><table><thead><tr><th>Username</th><th>Role</th><th>Status</th><th>Manage</th></tr></thead><tbody>${users.map((u) => `<tr><td>${esc(u.username)}</td><td>${esc(u.role)}</td><td>${u.disabled ? "Disabled" : "Active"}</td><td>${u.id !== state.user.id ? `<div class="actions"><button class="secondary small" data-user="${u.id}" data-op="${u.disabled ? "enable" : "disable"}">${u.disabled ? "Enable" : "Disable"}</button><button class="quiet small" data-user="${u.id}" data-op="${u.role === "admin" ? "standard" : "admin"}">Make ${u.role === "admin" ? "standard" : "admin"}</button><button class="quiet small" data-user="${u.id}" data-op="reset">Reset password</button></div>` : "You"}</td></tr>`).join("")}</tbody></table></div><h3 class="section-label">Add a local user</h3><form id="create-user-form"><div class="fields"><div class="field"><label for="new-user">Username</label><input id="new-user" name="username" minlength="3" maxlength="48" required autocomplete="off"></div><div class="field"><label for="user-password">Initial password</label><input id="user-password" name="password" type="password" minlength="12" maxlength="256" autocomplete="new-password" required></div><div class="field"><label for="user-role">Role</label><select id="user-role" name="role"><option value="standard">Standard user</option><option value="admin">Administrator</option></select></div></div><button type="submit" class="mt14" ${state.job.active ? "disabled" : ""}>Create user</button></form></div>` : ""}`
  );
}
async function logs() {
  const d = await api("logs");
  return (
    header(
      "Understand what happened.",
      "A traceable local audit trail, with clear error codes and private diagnostics.",
      actionButton("logs_csv", "Export logs as CSV", true, state.job.active) +
      (state.settings.advanced
        ? actionButton("diagnostics", "Export diagnostics", true, state.job.active)
        : ""),
    ) +
    `<div class="banner"><strong>Audit chain checked</strong>Events are linked with SHA-256 to detect accidental edits. This cannot defeat someone who controls the operating-system account and rewrites the entire chain. Export and retain the head hash externally for stronger evidence.</div>${state.settings.advanced ? `<div class="card"><h2>Audit head</h2><pre>${esc(d.audit_head)}</pre><p class="tiny muted">Diagnostic bundles exclude source paths, filenames, credentials, cookies, browser screenshots and databases.</p></div>` : ""}<div class="table-wrap"><table class="audit-table"><thead><tr><th>Time</th><th>Event</th><th>Details</th></tr></thead><tbody>${d.events.map((r) => `<tr><td>${esc(date(r.time))}</td><td>${esc(r.action)}</td><td class="tiny"><div class="audit-detail">${esc(r.detail)}</div></td></tr>`).join("")}</tbody></table></div><p class="tiny muted">Most recent 200 events. Export logs as CSV includes the complete audit trail.</p>`
  );
}
function help() {
  return (
    header(
      "A little guidance.",
      "A careful workflow for irreplaceable photos.",
    ) +
    `<div class="card"><h2>Your first restore</h2><ol class="help-list"><li>Keep an independent backup of your Takeout export. Extract all ZIP parts into a folder before scanning.</li><li>Create your local account, choose the folder in Setup, and scan. Review rejected files and metadata errors.</li><li>Install the verified browser component, sign in to Google, and run the connection check.</li><li>Start with a small sample. Confirm dates, locations, video playback and counts directly in Google Photos.</li><li>Start the full queue. Keep the computer awake, the source drive connected and Google storage available.</li><li>Afterwards, export your report and resolve items marked Needs review or Restore details.</li></ol></div><div class="grid2"><div class="card"><h2>If something stops</h2><p class="muted">Reconnect an unplugged drive and rescan. If Google’s controls changed, stop and update the app. If the upload result is unknown, check Google Photos before retrying.</p><p class="muted">Enable Advanced view for item details, retry controls, manual verification and a redacted diagnostic bundle.</p></div><div class="card"><h2>What this preview cannot promise</h2><p class="muted">Exactly-once upload, existing-cloud duplicate detection, every media format, native Live Photo pairing, album recreation, favorite/archive state or Google caption restoration.</p><p class="muted">No telemetry. Browser downloads contact the browser vendor; sign-in and upload contact Google and its supporting services. This is an independent tool, not a Google product.</p></div></div>`
  );
}
async function render() {
  if (!state) return;
  const version = ++renderVersion,
    currentToken = token;
  shell();
  const views = {
    dashboard,
    setup,
    queue,
    history,
    settings,
    accounts,
    logs,
    help,
  };
  const html = await views[page]();
  if (version === renderVersion && token === currentToken && $("#content"))
    $("#content").innerHTML = html;
}
async function refresh(renderPage = true) {
  if (!token) return;
  state = await api("status");
  if (renderPage) await render();
}
async function onAction(a) {
  if (a === "save-recovery") {
    if (await api("save_recovery", {recovery_key: recoveryKey})) notice("Recovery key saved", "Keep this file somewhere private.");
    return;
  }
  if (a === "close-recovery") {
    $("#recovery-modal").close();
    recoveryKey = null;
    $("#recovery-code").textContent = "";
    return;
  }
  if (a === "forgot-password") return recoveryScreen();
  if (a === "back-auth") return authScreen();
  if (a === "regenerate-recovery") {
    const password = await passwordPrompt("Replace recovery key?", "Your previous recovery key will stop working. Save the new key when it appears.");
    if (password === null) return;
    showRecovery(await api("regenerate_recovery", {password}));
    return;
  }
  if (a === "reset-settings") {
    if (!await confirmAction("Reset to default settings?", "Restore this account’s preferences. Your accounts, source selection, Google sign-in, queue and history will stay intact.", "Reset settings")) return;
    await api("reset_settings");
    await refresh();
    notice("Default settings restored");
    return;
  }
  if (["clear-data", "start-over", "uninstall"].includes(a)) {
    const uninstall = a === "uninstall";
    if (!await confirmAction(uninstall ? "Uninstall Takeout Restore?" : "Clear all local data?", "This removes ALL local app users, settings, queues, history, logs, browser downloads and saved Google sessions. Your source files, exported reports and Google Photos remain. This cannot be undone. Device verification and a final system confirmation follow.", uninstall ? "Continue to uninstall" : "Continue to clear data")) return;
    const boot = await api("bootstrap");
    let password;
    if (!boot.can_start_over) {
      password = await passwordPrompt("Confirm administrator password", "Enter your local administrator app password to continue.");
      if (password === null) return;
    }
    const done = await api(uninstall ? "uninstall" : "clear_data", {confirmation:"REMOVE ALL LOCAL DATA", password});
    if (done) {
      token = state = null;
      if (uninstall) $("#app").innerHTML = '<div class="auth-page"><div class="auth-card"><h1>Uninstalled</h1><p>Local app data was removed. The app moved to Bin and will close.</p></div></div>';
      else { await authScreen(); notice("All local app data cleared", "Create a new account to start again."); }
    }
    return;
  }
  if (a.startsWith("go-")) {
    page = a.slice(3);
    return render();
  }
  if (a === "dismiss") {
    $("#notice").hidden = true;
    return;
  }
  if (a === "logout") {
    await api("logout");
    token = null;
    state = null;
    return authScreen();
  }
  if (a === "search") {
    search = $("#queue-search").value;
    filter = $("#queue-filter").value;
    offset = 0;
    return render();
  }
  if (a === "prev" || a === "next") {
    offset = Math.max(0, offset + (a === "prev" ? -100 : 100));
    return render();
  }
  if (
    ["upload", "upload_sample"].includes(a) &&
    !(await confirmAction(
      "Start uploading to Google Photos?",
      "Files will be copied, metadata will be merged into the copies, and the copies will be uploaded. Your Google storage quota applies. Review a small sample before a full restore.",
      "Start upload",
    ))
  )
    return;
  if (
    a === "disconnect_google" &&
    !(await confirmAction(
      "Disconnect Google?",
      "This removes the encrypted saved session. Your history and Google account binding remain.",
      "Disconnect",
    ))
  )
    return;
  if (
    a === "report" &&
    !(await confirmAction(
      "Export your library report?",
      "This CSV includes personal filenames, album names and metadata restoration details. Keep it somewhere private.",
      "Choose destination",
    ))
  )
    return;
  await api(a);
  await refresh();
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  while (formBusy) await new Promise((r) => setTimeout(r, 20));
  try {
    if (b.dataset.page) {
      page = b.dataset.page;
      return await render();
    }
    if (b.dataset.action) return await onAction(b.dataset.action);
    if (b.dataset.detail) {
      const data = await api("queue", { status: filter, search, offset });
      return details(
        "Item details",
        data.items.find((r) => r.id === Number(b.dataset.detail)),
      );
    }
    if (b.dataset.item) {
      const p = { id: Number(b.dataset.item), action: b.dataset.op };
      if (p.action === "retry" && b.dataset.state === "review") {
        p.confirm_duplicate_risk = await confirmAction(
          "Retry an uncertain upload?",
          "Check Google Photos first. This item may already be present; retrying could create a duplicate.",
          "Retry anyway",
        );
        if (!p.confirm_duplicate_risk) return;
      }
      if (p.action === "verify") {
        p.confirmed = await confirmAction(
          "Mark this item verified?",
          "Confirm that you checked this item and its requested restoration details directly in Google Photos. This only updates your local record.",
          "Mark verified",
        );
        if (!p.confirmed) return;
      }
      await api("item_action", p);
      return refresh();
    }
    if (b.dataset.user) {
      const p = { id: b.dataset.user, action: b.dataset.op };
      if (p.action === "reset") {
        $("#modal-title").textContent = "Reset local password";
        $("#modal-content").innerHTML =
          '<p>The saved Google session will be removed. History stays intact.</p><label for="reset-password">New password (12–256 characters)</label><input id="reset-password" type="password" minlength="12" maxlength="256" autocomplete="new-password" required>';
        $("#modal-ok").textContent = "Reset password";
        $("#modal").showModal();
        const accepted = await new Promise((r) =>
          $("#modal").addEventListener(
            "close",
            () => r($("#modal").returnValue === "ok"),
            { once: true },
          ),
        );
        if (!accepted) return;
        p.password = $("#reset-password").value;
        $("#reset-password").value = "";
      } else if (
        !(await confirmAction(
          "Update user access?",
          `Apply the ${p.action} action to this local user?`,
        ))
      )
        return;
      await api("manage_user", p);
      return refresh();
    }
  } catch (_) {
    /* public errors are already shown */
  }
});
document.addEventListener("change", async (e) => {
  if (e.target.id === "advanced-toggle") {
    try {
      await api("save_settings", {
        settings: { ...state.settings, advanced: e.target.checked },
      });
      await refresh();
    } catch (_) {
      e.target.checked = state.settings.advanced;
    }
  }
});
document.addEventListener("submit", async (e) => {
  if (e.target.id === "modal-form") return;
  e.preventDefault();
  if (formBusy) return;
  formBusy = true;
  const f = e.target,
    b = f.querySelector("button[type=submit]");
  if (b) b.disabled = true;
  try {
    const p = Object.fromEntries(new FormData(f));
    if (f.id === "auth-form") {
      const r = await api(
        f.dataset.register === "true" ? "register" : "login",
        p,
      );
      token = r.token;
      page = "dashboard";
      $("#notice").hidden = true;
      await refresh();
      showRecovery(r.recovery_key);
    } else if (f.id === "recovery-form") {
      await api("recover_password", p);
      f.reset();
      await authScreen();
      notice("Password reset", "Sign in with your new password, then save your replacement recovery key.");
    } else if (f.id === "settings-form") {
      for (const k of [
        "scratch_gb",
        "retry_limit",
        "upload_timeout_minutes",
        "auto_lock_minutes",
      ])
        if (k in p) p[k] = Number(p[k]);
      await api("save_settings", { settings: { ...state.settings, ...p } });
      notice(
        "Preferences saved",
        "Rescan to apply changes to unsubmitted items.",
      );
      await refresh();
    } else if (f.id === "password-form") {
      await api("change_password", p);
      f.reset();
      notice("Password updated");
    } else if (f.id === "create-user-form") {
      await api("create_user", p);
      f.reset();
      notice("User created");
      await refresh();
    }
  } catch (_) {
  } finally {
    formBusy = false;
    if (b) b.disabled = false;
  }
});
for (const event of ["pointerdown", "keydown"])
  document.addEventListener(event, () => {
    if (token && Date.now() - activityTime > 30000) {
      activityTime = Date.now();
      api("activity").catch(() => {});
    }
  });
setInterval(async () => {
  if (!token || pollBusy || formBusy || ($("#modal").open || $("#recovery-modal").open)) return;
  pollBusy = true;
  try {
    const previous = state?.job.active;
    await refresh(false);
    if (
      ["dashboard", "setup"].includes(page) ||
      previous !== state.job.active
    ) {
      if (["dashboard", "setup", "queue", "history"].includes(page))
        await render();
    }
  } catch (_) {
  } finally {
    pollBusy = false;
  }
}, 3000);
window.addEventListener("pywebviewready", () =>
  authScreen().catch(() =>
    notice("Unable to start", "Restart the application.", true),
  ),
);
