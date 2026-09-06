const GH_API = "https://api.github.com";
const TG_API = "https://api.telegram.org";
const API_VERSION = "2026-03-10";
const ACTIVE_STATUSES = new Set(["queued", "in_progress", "waiting", "pending", "requested"]);
const INTERNATIONAL_POINTER_VERSION = "CONTROL_PLANE_REPORT_POINTER_V1.0.0";

function allowedUsers(env) {
  return new Set(
    String(env.TELEGRAM_ALLOWED_USER_IDS || "")
      .split(/[;,]/)
      .map((x) => x.trim())
      .filter(Boolean)
  );
}

function isAuthorized(update, env) {
  const from = update?.message?.from || update?.callback_query?.from;
  const chat = update?.message?.chat || update?.callback_query?.message?.chat;
  if (!from || !chat || chat.type !== "private") return false;
  return allowedUsers(env).has(String(from.id));
}

function githubHeaders(env) {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    "X-GitHub-Api-Version": API_VERSION,
    "User-Agent": "job-search-bot-control-center",
  };
}

function projects(env) {
  return {
    spain: {
      key: "spain",
      label: "Spain",
      emoji: "🇪🇸",
      owner: env.SPAIN_GITHUB_OWNER || env.GITHUB_OWNER,
      repo: env.SPAIN_GITHUB_REPO || env.GITHUB_REPO,
      workflow: env.SPAIN_GITHUB_WORKFLOW || env.GITHUB_WORKFLOW || "production-job-search.yml",
      ref: env.SPAIN_GITHUB_REF || env.GITHUB_REF || "main",
      bucket: env.REPORTS_SPAIN || env.REPORTS,
      summaryKind: "spain",
      summaryKey: "latest/run_summary.json",
      reportKey: "latest/job_search_report.xlsx",
      reportFilename: "spain_job_search_report.xlsx",
      reportCaption: "🇪🇸 Spain — Latest job-search report",
    },
    international: {
      key: "international",
      label: "International",
      emoji: "🌍",
      owner: env.INTERNATIONAL_GITHUB_OWNER,
      repo: env.INTERNATIONAL_GITHUB_REPO || "international-academic-job-search",
      workflow: env.INTERNATIONAL_GITHUB_WORKFLOW || "production.yml",
      ref: env.INTERNATIONAL_GITHUB_REF || "main",
      bucket: env.REPORTS_INTERNATIONAL,
      summaryKind: "international",
      manifestKey: "control-plane/latest/manifest.json",
      reportFilename: "international_academic_job_report.xlsx",
      reportCaption: "🌍 International — Latest academic job report",
    },
  };
}

function requireProject(project) {
  if (!project?.owner || !project?.repo || !project?.workflow || !project?.ref) {
    throw new Error(`Project ${project?.key || "unknown"} GitHub configuration is incomplete`);
  }
  if (!project.bucket) {
    throw new Error(`Project ${project.key} R2 binding is missing`);
  }
  return project;
}

function workflowUrl(project, suffix = "") {
  const workflow = encodeURIComponent(project.workflow);
  return `${GH_API}/repos/${project.owner}/${project.repo}/actions/workflows/${workflow}${suffix}`;
}

async function listRuns(project, env) {
  requireProject(project);
  const res = await fetch(workflowUrl(project, "/runs?per_page=10"), { headers: githubHeaders(env) });
  if (!res.ok) throw new Error(`${project.label} GitHub runs API ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return Array.isArray(data.workflow_runs) ? data.workflow_runs : [];
}

async function activeRun(project, env) {
  const runs = await listRuns(project, env);
  return runs.find((run) => ACTIVE_STATUSES.has(String(run.status || ""))) || null;
}

export function dispatchInputs(project, triggerSource) {
  if (project.key === "international") {
    return {
      bootstrap_production: false,
      release_acceptance: false,
      send_telegram: false,
      max_jobs_per_source: "all",
    };
  }
  return { trigger_source: triggerSource };
}

async function dispatchWorkflow(project, env, triggerSource) {
  requireProject(project);
  const active = await activeRun(project, env);
  if (active) return { dispatched: false, active };
  const res = await fetch(workflowUrl(project, "/dispatches"), {
    method: "POST",
    headers: { ...githubHeaders(env), "Content-Type": "application/json" },
    body: JSON.stringify({
      ref: project.ref,
      inputs: dispatchInputs(project, triggerSource),
    }),
  });
  if (res.status !== 204) throw new Error(`${project.label} GitHub dispatch ${res.status}: ${await res.text()}`);
  return { dispatched: true, active: null };
}

async function tg(env, method, init = {}) {
  const res = await fetch(`${TG_API}/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, init);
  if (!res.ok) throw new Error(`Telegram ${method} ${res.status}: ${await res.text()}`);
  const data = await res.json();
  if (!data.ok) throw new Error(`Telegram ${method} failed`);
  return data;
}

function mainKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: "🇪🇸 Spain", callback_data: "menu:spain" },
        { text: "🌍 International", callback_data: "menu:international" },
      ],
    ],
  };
}

function projectKeyboard(project) {
  return {
    inline_keyboard: [
      [
        { text: `▶️ Run ${project.label}`, callback_data: `${project.key}:run` },
        { text: `🩺 ${project.label} Status`, callback_data: `${project.key}:status` },
      ],
      [
        { text: `📊 ${project.label} Today`, callback_data: `${project.key}:today` },
        { text: `📥 ${project.label} Excel`, callback_data: `${project.key}:file` },
      ],
      [{ text: "⬅️ Main menu", callback_data: "menu:main" }],
    ],
  };
}

function actionSelectorKeyboard(action) {
  const labels = {
    run: "Run",
    status: "Status",
    today: "Today",
    file: "Excel",
  };
  const label = labels[action] || action;
  return {
    inline_keyboard: [
      [
        { text: `🇪🇸 Spain ${label}`, callback_data: `spain:${action}` },
        { text: `🌍 International ${label}`, callback_data: `international:${action}` },
      ],
      [{ text: "⬅️ Main menu", callback_data: "menu:main" }],
    ],
  };
}

async function sendMessage(env, chatId, text, replyMarkup = mainKeyboard()) {
  return tg(env, "sendMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      disable_web_page_preview: true,
      ...(replyMarkup ? { reply_markup: replyMarkup } : {}),
    }),
  });
}

async function answerCallback(env, callbackId) {
  if (!callbackId) return;
  await tg(env, "answerCallbackQuery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ callback_query_id: callbackId }),
  });
}

async function objectBytes(bucket, key) {
  if (!bucket) throw new Error("R2 binding is unavailable");
  const obj = await bucket.get(key);
  if (!obj) return null;
  return new Uint8Array(await obj.arrayBuffer());
}

function bytesToText(bytes) {
  return new TextDecoder().decode(bytes);
}

async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function verifyDigest(bytes, expected, label) {
  const wanted = String(expected || "").trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(wanted)) throw new Error(`${label} manifest digest is invalid`);
  const actual = await sha256Hex(bytes);
  if (actual !== wanted) throw new Error(`${label} digest mismatch`);
}

async function internationalManifest(project) {
  const bytes = await objectBytes(project.bucket, project.manifestKey);
  if (!bytes) return null;
  const manifest = JSON.parse(bytesToText(bytes));
  if (manifest?.schema_version !== INTERNATIONAL_POINTER_VERSION || manifest?.project !== "international") {
    throw new Error("International control-plane manifest contract mismatch");
  }
  for (const field of ["summary_key", "report_key", "summary_sha256", "report_sha256"]) {
    if (!String(manifest[field] || "").trim()) throw new Error(`International manifest missing ${field}`);
  }
  if (!String(manifest.summary_key).startsWith("control-plane/runs/")) {
    throw new Error("International summary key is outside the control-plane run namespace");
  }
  if (!String(manifest.report_key).startsWith("control-plane/runs/")) {
    throw new Error("International report key is outside the control-plane run namespace");
  }
  return manifest;
}

async function latestSummary(project) {
  requireProject(project);
  if (project.summaryKind === "spain") {
    const bytes = await objectBytes(project.bucket, project.summaryKey);
    return bytes ? JSON.parse(bytesToText(bytes)) : null;
  }
  const manifest = await internationalManifest(project);
  if (!manifest) return null;
  const bytes = await objectBytes(project.bucket, manifest.summary_key);
  if (!bytes) throw new Error("International summary referenced by latest manifest is missing");
  await verifyDigest(bytes, manifest.summary_sha256, "International summary");
  return JSON.parse(bytesToText(bytes));
}

function formatSpainSummary(summary) {
  if (!summary) return "No successful Spain cloud report has been published yet.";
  const rec = summary.recommendations || {};
  const runs = summary.source_runs || {};
  const counts = { OK: 0, PARTIAL: 0, ERROR: 0 };
  Object.values(runs).forEach((item) => {
    const status = String(item?.status || "ERROR").toUpperCase();
    const key = Object.prototype.hasOwnProperty.call(counts, status) ? status : "ERROR";
    counts[key] += 1;
  });
  const needsDetailTotal = Number(summary.needs_detail_review || 0);
  const madridNeedsDetail = Number(runs.madrid?.needs_detail_review || 0);
  const otherNeedsDetail = Math.max(0, needsDetailTotal - madridNeedsDetail);
  return [
    `🇪🇸 Spain Job Search — ${summary.availability_as_of || ""}`,
    `Current actionable: ${summary.current_actionable || 0}`,
    `Today's actionable: ${summary.daily_actionable || 0}`,
    `New actionable: ${summary.new_actionable || 0}`,
    `Changed/reopened: ${summary.changed_or_reopened_actionable || 0}`,
    `APPLY: ${rec.APPLY || 0} | REVIEW: ${rec.REVIEW || 0} | LOW: ${rec.LOW_PRIORITY || 0}`,
    `Needs detail: ${needsDetailTotal} | Madrid: ${madridNeedsDetail} | Other: ${otherNeedsDetail}`,
    `Sources: ✅ ${counts.OK} | ⚠️ ${counts.PARTIAL} | ❌ ${counts.ERROR}`,
    `State jobs: ${summary.seen_state_jobs || 0}`,
  ].join("\n");
}

function formatInternationalSummary(summary) {
  if (!summary) return "No successful International control-plane report has been published yet.";
  const rec = summary.recommendations || {};
  const events = summary.events || {};
  const health = summary.source_health || {};
  const generated = String(summary.generated_at || "").slice(0, 10);
  return [
    `🌍 International Academic Job Search${generated ? ` — ${generated}` : ""}`,
    `Current actionable: ${summary.current_actionable || 0}`,
    `Today's actionable: ${summary.today_actionable || 0}`,
    `New observations: ${events.NEW || 0} | Changed: ${events.MATERIALLY_CHANGED || 0} | Reopened: ${events.REOPENED || 0}`,
    `STRONG_APPLY: ${rec.STRONG_APPLY || 0} | APPLY: ${rec.APPLY || 0} | REVIEW: ${rec.REVIEW || 0}`,
    `Review queue: ${summary.review_queue || 0} | LOW: ${summary.low_priority || 0} | SKIP: ${summary.skipped || 0}`,
    `Sources: ✅ ${health.OK || 0} | ⚠️ ${health.PARTIAL || 0} | ❌ ${health.ERROR || 0} | ? ${health.UNKNOWN || 0}`,
    `State: generation ${summary.state_generation || 0} | jobs ${summary.state_jobs || 0}`,
  ].join("\n");
}

function formatSummary(project, summary) {
  return project.summaryKind === "international"
    ? formatInternationalSummary(summary)
    : formatSpainSummary(summary);
}

async function reportPayload(project) {
  requireProject(project);
  if (project.key === "spain") {
    const bytes = await objectBytes(project.bucket, project.reportKey);
    return bytes ? { bytes } : null;
  }
  const manifest = await internationalManifest(project);
  if (!manifest) return null;
  const bytes = await objectBytes(project.bucket, manifest.report_key);
  if (!bytes) throw new Error("International Excel referenced by latest manifest is missing");
  await verifyDigest(bytes, manifest.report_sha256, "International Excel");
  return { bytes };
}

async function sendLatestReport(env, chatId, project) {
  const payload = await reportPayload(project);
  if (!payload) {
    await sendMessage(env, chatId, `${project.emoji} No ${project.label} Excel report has been published yet.`, projectKeyboard(project));
    return;
  }
  const form = new FormData();
  form.append("chat_id", String(chatId));
  form.append("caption", project.reportCaption);
  form.append(
    "document",
    new File([payload.bytes], project.reportFilename, { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" })
  );
  await tg(env, "sendDocument", { method: "POST", body: form });
}

async function readiness(env) {
  const config = projects(env);
  const spain = requireProject(config.spain);
  const international = requireProject(config.international);
  const [spainRuns, internationalRuns, spainSummary, internationalSummary, bot] = await Promise.all([
    listRuns(spain, env),
    listRuns(international, env),
    latestSummary(spain),
    latestSummary(international),
    tg(env, "getMe"),
  ]);
  if (!spainSummary) throw new Error("Spain latest summary is missing from R2");
  if (!internationalSummary) throw new Error("International latest summary is missing from R2");
  return {
    ok: true,
    projects: {
      spain: {
        github: true,
        github_latest_run: spainRuns[0]?.run_number || null,
        r2: true,
        r2_production_version: spainSummary?.production_version || null,
      },
      international: {
        github: true,
        github_latest_run: internationalRuns[0]?.run_number || null,
        r2: true,
        reporting_version: internationalSummary?.reporting_version || null,
        state_generation: internationalSummary?.state_generation || null,
      },
    },
    telegram: true,
    telegram_bot: bot?.result?.username || null,
  };
}

async function statusText(project, env) {
  const runs = await listRuns(project, env);
  const run = runs[0];
  const summary = await latestSummary(project);
  if (!run) return `${project.emoji} ${project.label}: no workflow runs found.\n\n${formatSummary(project, summary)}`;
  const state = run.conclusion || run.status || "unknown";
  return [
    `${project.emoji} ${project.label} production status`,
    `GitHub: ${state}`,
    `Run #${run.run_number || ""}`,
    run.html_url || "",
    "",
    formatSummary(project, summary),
  ].join("\n");
}

function selectorPrompt(action) {
  const prompts = {
    run: "Choose which project to run:",
    status: "Choose which project status to view:",
    today: "Choose which project summary to view:",
    file: "Choose which Excel report to download:",
  };
  return prompts[action] || "Choose a project:";
}

async function showMainMenu(env, chatId) {
  await sendMessage(
    env,
    chatId,
    "Job Search Control Center\n\nChoose a project:",
    mainKeyboard()
  );
}

async function showProjectMenu(env, chatId, project) {
  await sendMessage(
    env,
    chatId,
    `${project.emoji} ${project.label}\n\nChoose an action:`,
    projectKeyboard(project)
  );
}

async function handleProjectAction(project, action, update, env) {
  const chatId = update?.message?.chat?.id || update?.callback_query?.message?.chat?.id;
  const userId = update?.message?.from?.id || update?.callback_query?.from?.id;
  if (!chatId) return;

  if (action === "run") {
    const result = await dispatchWorkflow(project, env, `telegram:${userId}`);
    if (result.dispatched) {
      await sendMessage(env, chatId, `${project.emoji} ${project.label} production run triggered.`, projectKeyboard(project));
    } else {
      await sendMessage(env, chatId, `${project.emoji} ${project.label}: a production run is already ${result.active.status}.`, projectKeyboard(project));
    }
    return;
  }
  if (action === "status") {
    await sendMessage(env, chatId, await statusText(project, env), projectKeyboard(project));
    return;
  }
  if (action === "today" || action === "current") {
    await sendMessage(env, chatId, formatSummary(project, await latestSummary(project)), projectKeyboard(project));
    return;
  }
  if (action === "file") {
    await sendLatestReport(env, chatId, project);
    return;
  }
  await showProjectMenu(env, chatId, project);
}

async function handleAction(action, update, env) {
  const chatId = update?.message?.chat?.id || update?.callback_query?.message?.chat?.id;
  if (!chatId) return;
  const config = projects(env);

  if (["start", "menu", "help", "menu:main"].includes(action)) {
    await showMainMenu(env, chatId);
    return;
  }
  if (action === "spain" || action === "menu:spain") {
    await showProjectMenu(env, chatId, requireProject(config.spain));
    return;
  }
  if (action === "international" || action === "menu:international") {
    await showProjectMenu(env, chatId, requireProject(config.international));
    return;
  }

  // Backward compatibility for old command-menu entries and old inline keyboards:
  // generic actions never silently default to Spain; they ask which project the user means.
  if (["run", "status", "today", "current", "file"].includes(action)) {
    const normalized = action === "current" ? "today" : action;
    await sendMessage(env, chatId, selectorPrompt(normalized), actionSelectorKeyboard(normalized));
    return;
  }

  const [projectKey, projectAction] = String(action || "").split(":", 2);
  if (["spain", "international"].includes(projectKey) && ["run", "status", "today", "current", "file"].includes(projectAction)) {
    await handleProjectAction(requireProject(config[projectKey]), projectAction, update, env);
    return;
  }

  await showMainMenu(env, chatId);
}

async function handleTelegram(request, env) {
  const expected = String(env.TELEGRAM_WEBHOOK_SECRET || "");
  const provided = String(request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "");
  if (!expected || provided !== expected) return new Response("unauthorized", { status: 401 });

  const update = await request.json();
  if (!isAuthorized(update, env)) return new Response("ok");

  const chatId = update?.message?.chat?.id || update?.callback_query?.message?.chat?.id;
  try {
    if (update.callback_query) {
      await answerCallback(env, update.callback_query.id);
      await handleAction(String(update.callback_query.data || "menu:main"), update, env);
      return new Response("ok");
    }

    const text = String(update?.message?.text || "").trim();
    const command = text.split(/\s+/)[0].split("@")[0].replace(/^\//, "").toLowerCase();
    await handleAction(command || "menu", update, env);
  } catch (error) {
    console.error(error);
    if (chatId) {
      try {
        await sendMessage(env, chatId, "⚠️ Control-plane error. Check the selected project status.", mainKeyboard());
      } catch (notifyError) {
        console.error(notifyError);
      }
    }
  }
  return new Response("ok");
}

export const CONTROL_PLANE_VERSION = "INTERNATIONAL_ALL_MADRID_CRON_V1";

export function scheduledProject(controller) {
  if (controller.cron === "17 3 * * *") return "spain";
  if (!["0 4 * * *", "0 5 * * *"].includes(controller.cron)) return null;
  // Cloudflare cron is UTC. Only one of these two triggers is 06:00 in Madrid,
  // including on the days daylight saving starts and ends.
  const local = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Madrid", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(new Date(controller.scheduledTime));
  return local === "06:00" ? "international" : null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, service: "job-search-control-center", version: CONTROL_PLANE_VERSION, international_schedule: "06:00 Europe/Madrid", international_max_jobs: "all" });
    }
    if (url.pathname === "/ready" && request.method === "GET") {
      const expected = String(env.TELEGRAM_WEBHOOK_SECRET || "");
      const provided = String(request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
      if (!expected || provided !== expected) return new Response("unauthorized", { status: 401 });
      try {
        return Response.json(await readiness(env));
      } catch (error) {
        console.error(error);
        return Response.json({ ok: false, error: String(error?.message || error) }, { status: 503 });
      }
    }
    if (url.pathname === "/telegram" && request.method === "POST") {
      try {
        return await handleTelegram(request, env);
      } catch (error) {
        console.error(error);
        return new Response("ok");
      }
    }
    return new Response("not found", { status: 404 });
  },

  async scheduled(controller, env, ctx) {
    const key = scheduledProject(controller);
    if (!key) return;
    const project = requireProject(projects(env)[key]);
    ctx.waitUntil(
      dispatchWorkflow(project, env, "cloudflare-cron")
        .then((result) => console.log(JSON.stringify({ project: key, cron: controller.cron, ...result })))
        .catch((error) => { console.error(error); throw error; })
    );
  },
};
