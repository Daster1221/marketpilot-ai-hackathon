"use strict";

const tg = window.Telegram?.WebApp;
const initData = tg?.initData || "";
const demo = !initData && new URLSearchParams(location.search).get("preview") === "1";
const previewStore = "salstek-miniapp-drafts-v1";
const view = document.querySelector("#view");
const dock = document.querySelector("#dock");
const createButton = document.querySelector("#create");
const botLink = "https://t.me/salavatsteklo_bot";
const nativeBack = !demo && tg?.isVersionAtLeast?.("6.1") ? tg.BackButton : null;
const statusNames = {
  DRAFT: "Черновик", PENDING_APPROVAL: "На согласовании", APPROVED: "Одобрен",
  QUEUED: "Ожидает отправки", SCHEDULED: "В контент-плане", SENDING: "Отправляется", PUBLISHED: "Опубликован",
  REJECTED: "Отклонён", FAILED: "Ошибка", CANCELLED: "Отменён",
};
const platformNames = {telegram: "Telegram", vk: "ВКонтакте", max: "MAX"};
const sourcePages = [
  ["О компании", "o-kompanii/"],
  ["Архитектурное стекло", "products/arkhitekturnoe-steklo/"],
  ["Интерьерное стекло", "products/interernoe-steklo/"],
  ["Оконные продукты", "products/okonnoe-steklo/"],
  ["Реализованные проекты", "projects/"],
  ["Технические документы", "service-support/documents/"],
];
const state = {
  tab: "work", screen: "root", filter: "all", listPage:0, returnTo: "root",
  data: null, error: "", day: "", month: "", planFilter: "all", sections: [], messages: [], aiBusy: false, draft: {title: "", body: ""}, saving: false,
};
let postRequest = 0;

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function samplePosts() {
  const topics = [
    ["Архитектурное стекло: современные решения", "APPROVED", "2026-11-16T13:00:00Z", "vk", 1],
    ["Интерьерное стекло в офисах и домах", "PENDING_APPROVAL", "2026-11-20T07:00:00Z", "telegram", 1],
    ["Энергоэффективные стеклопакеты", "SCHEDULED", "2026-11-21T13:00:00Z", "vk", 1],
    ["Как выбрать стекло для витрины", "PENDING_APPROVAL", "2026-11-24T07:00:00Z", "telegram", null],
    ["Документация для проектировщиков", "PENDING_APPROVAL", "2026-11-25T07:00:00Z", "telegram", null],
  ];
  return topics.map(([title, status, due, platform, plan_id], index) => ({
    id: index + 1, title, status, due, platform, plan_id,
    body: "Пример темы для демонстрации кабинета. Характеристики уточняются по официальному каталогу.",
  }));
}

function readPreview() {
  try {
    return JSON.parse(localStorage.getItem(previewStore) || "[]");
  } catch {
    return [];
  }
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: {"X-Telegram-Init-Data": initData, "Content-Type": "application/json", ...options.headers},
    });
  } catch {
    throw new Error("Нет связи с кабинетом. Проверьте подключение и попробуйте ещё раз.");
  }
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    if (typeof result?.detail === "string") throw Object.assign(new Error(result.detail),{status:response.status});
    throw new Error(response.status === 422 ? "Проверьте заполнение полей." : "Кабинет временно недоступен. Попробуйте ещё раз.");
  }
  if (!result) throw new Error("Не удалось загрузить данные кабинета.");
  return result;
}

function dateText(iso, options) {
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: state.data.timezone || "Asia/Yekaterinburg", ...options,
  }).format(new Date(iso));
}

const buckets = {
  review: {title: "На согласовании", statuses: ["PENDING_APPROVAL"], empty: "Все посты проверены."},
  drafts: {title: "Черновики", statuses: ["DRAFT", "REJECTED"], empty: "Нажмите «Новый пост», чтобы написать черновик."},
  all: {title: "Все посты", empty: "Здесь появятся ваши посты."},
};
const timedStatuses = ["APPROVED", "SCHEDULED", "QUEUED", "SENDING"];

function heading(title, {back = false, company = false, preview = false} = {}) {
  return `<header class="screen-head">
    ${back && !nativeBack ? '<button type="button" class="back" data-back>Назад</button>' : ""}
    ${company ? '<p class="company">Салаватстекло</p>' : ""}
    <h1>${escapeHTML(title)}</h1>
  </header>
  ${demo && preview ? `<p class="preview">Демонстрация · <a href="${botLink}">Открыть бота в Telegram</a></p>` : ""}`;
}

function chevron() {
  return '<span class="chevron" aria-hidden="true"></span>';
}

function postRows(posts) {
  return posts.map(post => {
    const status = escapeHTML(statusNames[post.status] || post.status);
    return `<button type="button" class="row" data-post="${post.id}">
      <span class="row-copy"><strong>${escapeHTML(post.title)}</strong>
      <small>${status} · ${escapeHTML(platformNames[post.platform])}</small></span>
      ${chevron()}
    </button>`;
  }).join("");
}

function selectPosts(filter) {
  const posts = state.data.posts;
  const statuses = buckets[filter].statuses;
  return statuses ? posts.filter(post => statuses.includes(post.status)) : posts;
}

const icons = {
  home: '<path d="M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
  chat: '<path d="M6 3h12a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4h-6l-5 4v-4H6a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4Z"/><path d="M7 10h.01m5 0h.01m5 0h.01" stroke-width="3"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 2v6m10-6v6M3 10h18"/>',
  profile: '<circle cx="12" cy="7" r="4"/><path d="M4 22v-2a5 5 0 0 1 5-5h6a5 5 0 0 1 5 5v2"/>',
  building: '<path d="M3 22h18M5 22V7h7v15m0-19h7v19M8 10h1m-1 4h1m-1 4h1m6-11h1m-1 4h1m-1 4h1m-1 4h1"/>',
  settings: '<path d="M3 5h7m5 0h6M3 12h12m5 0h1M3 19h3m5 0h10"/><circle cx="12" cy="5" r="2"/><circle cx="17" cy="12" r="2"/><circle cx="8" cy="19" r="2"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 1 1 4 3c-1 1-1 1-1 2m0 3h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  chart: '<path d="M4 21v-5m5 5v-9m5 9V8m5 13V3"/>',
  clip: '<path d="m9 13 7-7a3 3 0 0 1 4 4L10 20a5 5 0 0 1-7-7l9-9m-5 12 9-9"/>',
  layers: '<path d="m12 2 11 6-11 6L1 8l11-6Zm-11 11 11 6 11-6M1 18l11 6 11-6"/>',
  bell: '<path d="M4 17c2-2 3-4 3-7a5 5 0 0 1 10 0c0 3 1 5 3 7v1H4zm6 3a2 2 0 0 0 4 0M12 3V2"/>',
  sparkle: '<path d="M11 3c0 5-3 8-8 9 5 0 8 3 8 8 1-5 4-8 9-8-5-1-8-4-9-9Zm7-1v6m-3-3h6"/>',
  send: '<path d="m3 10 18-7-7 18-3-8-8-3Zm8 3 10-10"/>',
  file: '<path d="M6 2h8l5 5v15H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Zm8 0v6h5M8 12h7m-7 4h7"/>',
  arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
  eye: '<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2"/>',
  users: '<circle cx="10" cy="7" r="3"/><path d="M3 21v-3a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v3M18 4a3 3 0 0 1 0 6m2 4a4 4 0 0 1 2 4v3"/>',
};
function icon(name) {
  return `<svg class="icon icon-${name}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">${icons[name]}</svg>`;
}

const tabs = [
  ["work", "home", "Главная"], ["chat", "chat", "Маркетолог"], ["plan", "calendar", "План"], ["profile", "profile", "Профиль"],
];
dock.querySelector(".tabs").innerHTML = tabs.map(([key, symbol, label]) =>
  `<button type="button" data-tab="${key}">${icon(symbol)}${label}</button>`
).join("");

function aiShortcuts() {
  return `<div class="shortcuts">
    <button type="button" data-ai="ideas">${icon("file")}Идеи постов</button>
  </div>`;
}

function aiForm(chat = false) {
  return `<form id="ai-form" class="ai-form">
    ${chat ? `<label class="attachment" title="Добавить документ">${icon("clip")}
      <input type="file" aria-label="Добавить документ" id="material-file" accept=".pdf,.docx,.xlsx,.txt" ${state.aiBusy ? "disabled" : ""}></label>` : icon("sparkle")}
    <textarea name="task" aria-label="Задача для AI" placeholder="${chat ? "Напишите задачу…" : "Поставьте задачу AI…"}" rows="${chat ? 1 : 2}" maxlength="1600" required ${state.aiBusy ? "disabled" : ""}></textarea>
    <button class="send" type="submit" aria-label="Отправить задачу" ${state.aiBusy ? "disabled" : ""}>${icon("send")}</button>
  </form>`;
}

const numberFormat = new Intl.NumberFormat("ru", {notation: "compact", maximumFractionDigits: 1});

function metricCards({linked = false} = {}) {
  const {counts = {}, metrics = []} = state.data;
  const reach = metrics.map(metric => metric.data.reach).filter(Number.isFinite);
  const subscribers = metrics.find(metric => Number.isFinite(metric.data.subscribers))?.data.subscribers;
  const tag = linked ? "button" : "div";
  const action = linked ? ' type="button" data-section="analytics"' : "";
  return `<div class="metrics">${[
    ["calendar", counts.published ?? 0, "Публикаций<br>за 7 дней", demo ? "+3" : ""],
    ["eye", demo ? 8400 : (reach.length ? reach.reduce((a, b) => a + b, 0) : null), "Охват", demo ? "+27%" : ""],
    ["users", demo ? "+352" : subscribers, "Подписчиков", demo ? "+5%" : ""],
  ].map(([symbol, value, label, delta]) => `<${tag} class="metric"${action}>
    <span class="metric-top">${icon(symbol)}${delta ? `<span>${delta}</span>` : ""}</span>
    <strong>${value == null ? "—" : typeof value === "number" ? numberFormat.format(value) : value}</strong>
    <small>${label}</small>
  </${tag}>`).join("")}</div>`;
}

function dayKey(iso) {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: state.data.timezone, year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(iso));
}

function planPosts() {
  return state.data.posts.filter(post => post.due && (timedStatuses.includes(post.status) ||
    post.status === "PENDING_APPROVAL" || (post.plan_id && post.status === "DRAFT")))
    .sort((left, right) => Date.parse(left.due) - Date.parse(right.due));
}

function monthDate() {
  const key = state.month || dayKey(new Date()).slice(0, 7);
  return new Date(key + "-01T12:00:00Z");
}

function calendar(posts) {
  const first = monthDate();
  const offset = (first.getUTCDay() + 6) % 7;
  const month = first.getUTCMonth();
  const dates = new Set(posts.map(post => dayKey(post.due)));
  const dayCount = new Date(Date.UTC(first.getUTCFullYear(), month + 1, 0)).getUTCDate();
  const size = Math.ceil((offset + dayCount) / 7) * 7;
  const days = Array.from({length: size}, (_, i) => {
    const date = new Date(first);
    date.setUTCDate(1 - offset + i);
    const key = date.toISOString().slice(0, 10);
    return `<button type="button" class="${date.getUTCMonth() === month ? "" : "outside"} ${dates.has(key) ? "has-posts" : ""}"
      data-day="${key}" aria-pressed="${key === state.day}" aria-label="${date.toLocaleDateString("ru", {timeZone: "UTC", day: "numeric", month: "long", year: "numeric"})}">${date.getUTCDate()}</button>`;
  });
  return `<section class="panel month-calendar" aria-label="Календарь публикаций">
    <div class="month-heading"><h2>${first.toLocaleDateString("ru", {timeZone: "UTC", month: "long", year: "numeric"}).replace(/ г\.$/, "")}</h2>
      <div><button type="button" data-month="-1" aria-label="Предыдущий месяц">‹</button><button type="button" data-month="1" aria-label="Следующий месяц">›</button></div></div>
    <div class="calendar-grid">${["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map(day => `<span>${day}</span>`).join("")}${days.join("")}</div>
  </section>`;
}

function planRows(posts, showStatus = true) {
  return posts.map((post, index) => {
    const status = {APPROVED: "Готов к публикации", DRAFT: "В плане", SCHEDULED: "В плане"}[post.status] || statusNames[post.status];
    const when = dateText(post.due, {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"});
    return `<button type="button" class="plan-row" data-post="${post.id}">
      <span class="plan-photo photo-${index % 3}" aria-hidden="true"></span>
      <span class="row-copy"><strong>${escapeHTML(post.title)}</strong><small>
        <span class="platform-mark" aria-hidden="true">${post.platform === "vk" ? "ᴠκ" : icon(post.platform === "telegram" ? "send" : "chat")}</span>
        ${escapeHTML(platformNames[post.platform])} · ${when}</small></span>
      ${showStatus ? `<span class="badge" data-status="${post.status}">${escapeHTML(status)}</span>` : ""}<span aria-hidden="true" class="ellipsis">›</span>
    </button>`;
  }).join("");
}

function brandHeader(withBell = false) {
  return `<header class="brand-row">
    <div class="brand">
      <img class="brand-logo" src="./assets/salstek-logo.png" width="426" height="228" alt="Салаватстекло">
      <span>AI-маркетолог</span>
    </div>
    ${withBell ? `<button type="button" class="bell" data-filter="review" aria-label="На согласовании">${icon("bell")}</button>` : ""}
  </header>`;
}

function profileName() {
  return demo ? "Айдар" : tg?.initDataUnsafe?.user?.first_name || "";
}

function showWork() {
  const count = demo ? selectPosts("review").length : state.data.posts.length;
  const noun = new Intl.PluralRules("ru").select(count);
  const label = `${count} ${noun === "one" ? "публикация" : noun === "few" ? "публикации" : "публикаций"}`;
  const upcoming = planPosts().filter(post => new Date(post.due) >= new Date()).slice(0, 2);
  return `<div class="dashboard">
    ${brandHeader(true)}
    <header class="greeting"><h1>Обзор</h1><p class="muted">Создавайте публикации вместе<br>с ИИ-агентом</p></header>
    <button class="button secondary marketer-home" data-section="marketer">Маркетолог и документы →</button>
    ${demo ? `<section class="ai-panel design-task"><h2>О чём будет пост?</h2>${aiForm()}<button class="button primary" type="submit" form="ai-form">Создать с ИИ →</button></section>` : homeComposer()}
    <button type="button" class="panel row review-row" data-filter="${demo ? "review" : "all"}">
      ${icon("layers")}<span class="row-copy"><strong>${demo ? "На согласовании" : "Мои посты"}</strong><small>${label}</small></span>
      <span class="row-count">${count}</span>${chevron()}
    </button>
    <section class="dashboard-plan" aria-labelledby="plan-heading">
      <div class="section-title"><h2 id="plan-heading">${demo ? "Ближайшие публикации" : "Последние посты"}</h2><button type="button" ${demo ? 'data-tab="plan"' : 'data-filter="all"'}>${demo ? "Весь план" : "Все посты"} ${icon("arrow")}</button></div>
      <div class="panel plan-panel">${!demo && state.data.posts.length ? postRows(state.data.posts.slice(0,3)) : upcoming.length ? planRows(upcoming, false) : '<p class="empty">Ближайших публикаций пока нет.</p>'}</div>
    </section>
    ${demo ? `<p class="preview">Демонстрация · <a href="${botLink}">Открыть в Telegram</a></p>` : ""}
  </div>`;
}

function showChat() {
  return demo ? showDesignFlow() : showLiveFlow();
}

function profileRow(label, description, target, symbol) {
  return `<button type="button" class="row" data-section="${target}">${icon(symbol)}
    <span class="row-copy"><strong>${label}</strong>${description ? `<small>${description}</small>` : ""}</span>${chevron()}</button>`;
}

function showProfile() {
  const name = profileName() || "Владелец";
  return `<div class="profile">${heading("Профиль")}
    <div class="panel profile-user"><span class="avatar">${escapeHTML(Array.from(name)[0])}</span><span class="row-copy"><strong>${escapeHTML(name)}</strong><small>SMM-менеджер</small></span></div>
    <div class="panel">
      ${profileRow("Компания", "Салаватстекло", "company", "building")}
      ${profileRow("Маркетолог и документы", "Память, знания и контент-план", "marketer", "file")}
      ${profileRow("Настройки AI", "Модель, стиль, тон", "settings", "settings")}
      ${profileRow("Публикации", "Подключённые площадки", "channels", "calendar")}
      <label class="row notification-row">${icon("bell")}<span class="row-copy"><strong>Уведомления</strong>
        <small>Звук автоматических сообщений бота</small></span>
        <input type="checkbox" role="switch" id="notifications" aria-label="Уведомления" ${!demo ? "disabled" : ""} ${state.data.profile.notifications ? "checked" : ""}>
      </label><p class="error profile-error" hidden></p>
    </div>
    <div class="panel">
      ${profileRow("Помощь", "", "help", "help")}
      ${profileRow("О приложении", "", "about", "info")}
    </div>
  </div>`;
}

function showCompany() {
  return heading("Компания", {back: true}) + (!demo ? `<section class="panel post-body"><b>${escapeHTML(state.data.profile.company||"Компания")}</b><p>${escapeHTML(state.data.profile.summary||"Справку с сайта можно обновить в Telegram-боте.")}</p>${state.data.profile.site?`<a data-source-link href="${escapeHTML(state.data.profile.site)}">${escapeHTML(state.data.profile.site)}</a>`:''}</section>` : '') + '<div class="panel">' +
    profileRow("Материалы", "Каталог и документы", "sources", "layers") +
    profileRow("Аналитика", "Отчёт за неделю", "analytics", "chart") + "</div>";
}

function showSettings() {
  const profile = state.data.profile;
  return heading("Настройки", {back: true}) + `${profile.can_manage_users?'<button type="button" class="panel row" data-section="users"><span class="row-copy"><strong>Пользователи и доступ</strong><small>Добавить пользователя, посмотреть ники</small></span>›</button>':""}<form id="profile-form">
    <fieldset class="model-options"><legend>Модель для ваших задач</legend>${(profile.model_options||[]).map(m=>`<label class="model-option"><input type="radio" name="model" value="${escapeHTML(m.id)}" ${profile.model===m.id?'checked':''}><span><strong>${escapeHTML(m.title)}</strong><small>${escapeHTML(m.description)}</small><small>${m.input_price} ₽ вход / ${m.output_price} ₽ выход за 1 млн токенов</small></span></label>`).join('')}</fieldset><p class="muted model-note">Выбор действует в боте и Mini App. Новый запрос использует выбранную модель. Баланс ProxyAPI общий; цена зависит от объёма текста и рассуждений.</p>
    ${[["audience", "Аудитория"], ["tone", "Стиль и тон"], ["goals", "Цели"]].map(([name, title]) =>
      `<label>${title}<textarea name="${name}" maxlength="600" rows="2">${escapeHTML(profile[name])}</textarea></label>`).join("")}
    <label class="check-label"><input name="share_documents" type="checkbox" ${!demo ? "disabled" : ""} ${profile.share_documents ? "checked" : ""}>Разрешить AI обрабатывать документы компании</label>
    <p class="error" role="alert" hidden></p><p class="notice" role="status" hidden>Настройки сохранены</p>
    <button type="submit" class="button primary">Сохранить настройки</button>
  </form>`;
}

function showChannels() {
  const accounts = state.data.profile.accounts;
  return heading("Публикации", {back: true}) + `<div class="panel">${accounts.length ? accounts.map(account =>
    `<div class="row"><span class="row-copy"><strong>${escapeHTML(platformNames[account.platform])}</strong><small>${escapeHTML(account.destination)}</small></span></div>`
  ).join("") : '<p class="empty">Подключённых площадок пока нет.</p>'}</div>
  <div class="stack-actions"><a class="button primary" data-bot-link href="${botLink}?start=channels">Управлять площадками в боте</a>
    <button type="button" class="button secondary" data-filter="all">Все посты</button></div>`;
}

function showHelp() {
  return heading("Помощь", {back: true}) + `<div class="panel post-body">
    <p>На главной можно поставить задачу AI и открыть очередь согласования.</p>
    <p>В чате можно подготовить идеи и черновики, а в плане — выбрать день и открыть пост.</p>
    <p>Публикацию подтверждает владелец в карточке поста в Telegram.</p>
  </div><a class="button secondary" data-bot-link href="${botLink}">Открыть бота</a>`;
}

function showAbout() {
  return heading("О приложении", {back: true}) + '<div class="panel post-body"><strong>Салаватстекло · AI-маркетолог</strong><p>Подготовка постов, контент-план и согласование публикаций в Telegram.</p></div>';
}

function showAnalytics() {
  const {counts = {}} = state.data;
  return heading("Аналитика", {back: true}) + `<p class="muted analytics-period">${demo?'За последние 7 дней':'За всё время'}</p>` + metricCards() +
    `<section class="panel analytics-summary">
      <p>Подготовлено <strong>${counts.created ?? 0}</strong></p>
      <p>В расписании <strong>${counts.scheduled ?? 0}</strong></p>
      <p>Ошибки отправки <strong>${counts.failed ?? 0}</strong></p>
    </section>
    ${!demo && !state.data.metrics?.length ? '<p class="empty">Показатели аудитории пока не собраны.</p>' : ""}`;
}

function showList() {
  const bucket = buckets[state.filter];
  const posts = selectPosts(state.filter);
  const pages=Math.max(1,Math.ceil(posts.length/20));state.listPage=Math.min(state.listPage,pages-1);
  const content = posts.length ? postRows(posts.slice(state.listPage*20,state.listPage*20+20)) : `<p class="empty">${bucket.empty}</p>`;
  return heading(bucket.title, {back: true}) + `<div class="panel">${content}</div>${pages>1?`<nav class="list-pages" aria-label="Страницы постов"><button class="button secondary" data-list-page="${state.listPage-1}" ${state.listPage===0?'disabled':''}>Назад</button><span>${state.listPage+1} / ${pages}</span><button class="button secondary" data-list-page="${state.listPage+1}" ${state.listPage===pages-1?'disabled':''}>Далее</button></nav>`:''}`;
}

function showPlan() {
  const posts = planPosts();
  const month = monthDate().toISOString().slice(0, 7);
  const visible = posts.filter(post => {
    const day = dayKey(post.due);
    return (state.day ? day === state.day : day.startsWith(month)) &&
      (state.planFilter === "all" || (state.planFilter === "scheduled" ?
        timedStatuses.includes(post.status) : post.status === "PENDING_APPROVAL"));
  });
  const filters = [["all", "Все"], ["scheduled", "Запланированы"], ["review", "На согласовании"]];
  return `<div class="plan-header">${heading("План публикаций")}<button class="send plan-add" data-create type="button" aria-label="Новый пост"><span class="plus" aria-hidden="true"></span></button></div>
    <p class="muted plan-description">Даты по Уфе (UTC+5). Согласованные посты отправляются автоматически.</p>
    ${!demo&&liveCompose.message?`<p class="plan-success" role="status">${escapeHTML(liveCompose.message)}</p>`:""}
    ${calendar(posts)}
    <h2 class="plan-list-heading">${state.day ? new Date(state.day + "T12:00:00Z").toLocaleDateString("ru", {timeZone: "UTC", day: "numeric", month: "long"}) : "Ближайшие публикации"}</h2>
    <div class="plan-filters" aria-label="Статусы публикаций">${filters.map(([key, label]) =>
      `<button type="button" data-plan-filter="${key}" aria-pressed="${state.planFilter === key}">${label}</button>`).join("")}</div>
    <div class="panel plan-panel">${visible.length ? planRows(visible) : '<p class="empty">Публикаций пока нет.</p>'}</div>
    <button type="button" class="button secondary plan-create" data-open-calendar-plan>Создать контент-план с ИИ</button>`;
}

function showSources() {
  return heading("Материалы", {back: true}) + '<div class="panel">' + state.data.sources.map(({title, url}) =>
    `<a class="row" href="${escapeHTML(url)}" target="_blank" rel="noopener" data-source-link>
      <span class="row-copy"><strong>${escapeHTML(title)}</strong></span><span aria-hidden="true">↗</span>
    </a>`
  ).join("") + "</div>";
}

function showComposer() {
  return heading("Новый пост", {back: true}) + `
    <form id="draft-form">
      <label>Тема<input name="title" value="${escapeHTML(state.draft.title)}" maxlength="160" placeholder="О чём пост?" required></label>
      <label>Текст<textarea name="body" maxlength="900" placeholder="Напишите пост для Telegram" required>${escapeHTML(state.draft.body)}</textarea></label>
      <p class="error" role="alert" hidden></p>
      <button class="button primary" type="submit">Сохранить черновик</button>
    </form>`;
}

function postHead(post) {
  return heading(post.title, {back: true}) + `<p class="meta">
    <span class="badge" data-status="${escapeHTML(post.status)}">${escapeHTML(statusNames[post.status] || post.status)}</span>
    <span>${escapeHTML(platformNames[post.platform])}</span>
    ${post.due && (timedStatuses.includes(post.status) || post.status === "PUBLISHED") ?
      `<span>${dateText(post.due, {day: "numeric", month: "long", hour: "2-digit", minute: "2-digit"})}</span>` : ""}
  </p>`;
}

function syncNavigation() {
  dock.hidden = !state.data || ["create", "post"].includes(state.screen) || (state.tab === "chat" && state.screen === "root");
  createButton.hidden = state.screen !== "list";
  view.classList.toggle("chat-view", state.tab === "chat" && state.screen === "root");
  dock.querySelectorAll("[data-tab]").forEach(tab => {
    if (tab.dataset.tab === (state.screen === "marketer" ? "chat" : state.tab)) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  if (state.screen === "root") nativeBack?.hide();
  else nativeBack?.show();
}

function render() {
  const sections = {
    company: showCompany, settings: showSettings, channels: showChannels, marketer: showMarketer, users: showUsers,
    help: showHelp, about: showAbout, analytics: showAnalytics, sources: showSources,
  };
  syncNavigation();
  if (state.error) {
    view.innerHTML = heading("Не удалось открыть редакцию") +
      `<p class="muted">${escapeHTML(state.error)}</p><p class="loading">
      <a class="button secondary" data-bot-link href="${botLink}">Вернуться в бот</a></p>`;
  } else if (state.screen === "create") {
    view.innerHTML = showComposer();
  } else if (state.screen === "list") {
    view.innerHTML = showList();
  } else if (sections[state.screen]) {
    view.innerHTML = sections[state.screen]();
  } else if (state.data) {
    view.innerHTML = {work: showWork, chat: showChat, plan: showPlan, profile: showProfile}[state.tab]();
  }
}

function focusView() {
  view.focus({preventScroll: true});
  window.scrollTo(0, 0);
}

async function openPost(id, {saved = false} = {}) {
  const current = state.data.posts.find(post => post.id === id);
  if (!current) return;
  const request = ++postRequest;
  state.screen = "post";
  syncNavigation();
  const confirmation = saved ? '<p class="notice" role="status">Черновик сохранён</p>' : "";
  view.innerHTML = postHead(current) + confirmation + '<p class="loading" role="status">Загружаем пост…</p>';
  focusView();
  try {
    const post = demo ? current : await api("./posts/" + id);
    if (request !== postRequest || state.screen !== "post") return;
    const action = post.status === "PENDING_APPROVAL" ? "Проверить пост в боте" : "Открыть в боте";
    view.innerHTML = postHead(post) + confirmation +
      `<div id="post-image-slot"></div><article class="panel post-body">${safePostHTML(post.body_html || post.body || "В посте пока нет текста.")}</article>` +
      (demo ? "" : `${["DRAFT","APPROVED","SCHEDULED","QUEUED"].includes(post.status)?`<button type="button" class="button primary" data-live-edit="${post.id}">Редактировать пост</button>`:""}<a class="button secondary" data-bot-link href="${botLink}?start=post_${id}">${action}</a>`);
    if (!demo && post.has_image) {
     try{
      const imageResponse=await fetch('./post-images/'+id,{headers:{'X-Telegram-Init-Data':initData}});
      if(imageResponse.ok && request===postRequest && state.screen==='post'){
        if(window.livePostImage)URL.revokeObjectURL(window.livePostImage);
        window.livePostImage=URL.createObjectURL(await imageResponse.blob());
        const photo=document.createElement('img');photo.src=window.livePostImage;photo.alt='Изображение поста';photo.style='width:100%;border-radius:16px;margin-bottom:14px';
        document.querySelector('#post-image-slot')?.append(photo);
      }
     }catch{
      if(request===postRequest&&state.screen==='post'){
       const slot=document.getElementById('post-image-slot');if(slot)slot.innerHTML='<p class="muted">Изображение временно не загрузилось. Текст поста доступен ниже.</p>';
      }
     }
    }
  } catch (error) {
    if (request !== postRequest || state.screen !== "post") return;
    view.innerHTML = postHead(current) + confirmation + `<p class="loading error" role="alert">${escapeHTML(error.message)}</p>
      <button type="button" class="button secondary" data-post="${id}">Повторить</button>`;
  }
}

function goBack() {
  if (state.saving) return;
  if (state.screen === "create") {
    state.draft = Object.fromEntries(new FormData(document.querySelector("#draft-form")));
  }
  if (state.screen === "list" || state.sections.length && !["create", "post"].includes(state.screen)) {
    state.filter = "all";
    state.screen = state.sections.pop() || "root";
  } else {
    state.screen = state.returnTo || "root";
  }
  postRequest++;
  render();
  focusView();
}

nativeBack?.onClick(goBack);
document.addEventListener("click", event => {
  const bot = event.target.closest("[data-bot-link]");
  if (bot && !demo && tg?.openTelegramLink) {
    event.preventDefault();
    tg.openTelegramLink(bot.href);
    return;
  }
  const source = event.target.closest("[data-source-link]");
  if (source && !demo && tg?.openLink) {
    event.preventDefault();
    tg.openLink(source.href);
    return;
  }
  const button = event.target.closest("button");
  if (!button) return;
  if (button.hasAttribute("data-back")) return goBack();
  if(button.hasAttribute("data-list-page")){state.listPage=Math.max(0,Number(button.dataset.listPage)||0);render();focusView();return;}
  if (button.dataset.post) {
    if (state.screen !== "post") state.returnTo = state.screen;
    return openPost(Number(button.dataset.post));
  }
  if (button.dataset.tab) {
    state.tab = button.dataset.tab;
    state.screen = state.tab === "chat" ? "marketer" : "root";
    state.sections = [];
  } else if (button.dataset.section) {
    state.sections.push(state.screen);
    state.screen = button.dataset.section;
  } else if (button.dataset.day) {
    state.day = state.day === button.dataset.day ? "" : button.dataset.day;
    if (state.day) state.month = state.day.slice(0, 7);
    render();
    view.querySelector(`[data-day="${button.dataset.day}"]`)?.focus({preventScroll: true});
    return;
  } else if (button.dataset.month) {
    const first = monthDate();
    first.setUTCMonth(first.getUTCMonth() + Number(button.dataset.month));
    state.month = first.toISOString().slice(0, 7);
    state.day = "";
  } else if (button.dataset.planFilter) {
    state.planFilter = button.dataset.planFilter;
  } else if (button.dataset.draftIdeas) {
    const message = state.messages[Number(button.dataset.draftIdeas)];
    if (message?.ideas && !message.used) return runAssistant("drafts", "Создать черновики", message);
  } else if (button.dataset.ai) {
    return runAssistant(button.dataset.ai, button.textContent.trim());
  } else if (button.dataset.filter) {
    state.sections.push(state.screen);
    state.filter = button.dataset.filter;state.listPage=0;
    state.screen = "list";
  } else if (button.hasAttribute("data-create")) {
    state.returnTo = state.screen;
    state.screen = "create";
  } else {
    return;
  }
  render();
  focusView();
});

function addMessage(message) {
  state.messages.push({...message, time: dateText(new Date(), {hour: "2-digit", minute: "2-digit"})});
}

function refreshChat() {
  if (state.tab === "chat" && state.screen === "root") {
    render();
    window.scrollTo(0, document.documentElement.scrollHeight);
  }
}

async function runAssistant(action, text, ideaMessage) {
  if (!demo) { liveFlow.task = action === "ask" ? text : ""; liveFlow.workflow=null; liveFlow.step=0; state.tab="chat"; state.screen="root"; render(); return; }
  if (!text || state.aiBusy) return;
  state.tab = "chat";
  state.screen = "root";
  state.sections = [];
  addMessage({user: true, text});
  state.aiBusy = true;
  refreshChat();
  try {
    const result = demo ? (action === "ideas" ? {
      text: "Идеи для постов · 3",
      ideas: [
        {topic: "Как делают современное стекло", goal: "Процесс и технологии"},
        {topic: "Экологичное производство", goal: "Переработка и снижение выбросов"},
        {topic: "Где используется наше стекло", goal: "Архитектура и строительство"},
      ],
    } : {text: "Откройте мини-апп из Telegram, чтобы отправить задачу AI."}) :
      await api("./assistant", {method: "POST", body: JSON.stringify({
        action, text: action === "ask" ? text : "", topics: ideaMessage?.ideas.map(idea => idea.topic) || [],
      })});
    if (result.posts?.length) state.data.posts.unshift(...result.posts);
    if (ideaMessage && result.posts?.length) ideaMessage.used = true;
    addMessage({text: result.text, ideas: result.ideas, postId: result.post_id, postIds: result.posts?.map(post => post.id)});
  } catch (error) {
    addMessage({text: error.message});
  } finally {
    state.aiBusy = false;
    refreshChat();
  }
}

async function saveProfile(changes) {
  const saved = demo ? changes : await api("./data", {method: "PATCH", body: JSON.stringify(changes)});
  Object.assign(state.data.profile, saved);
}

view.addEventListener("change", async event => {
  const field = event.target;
  if (field.id === "notifications") {
    const enabled = field.checked;
    const error = view.querySelector(".profile-error");
    field.disabled = true;
    error.hidden = true;
    try {
      await saveProfile({notifications: enabled});
    } catch (failure) {
      field.checked = !enabled;
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      field.disabled = false;
    }
  } else if (field.id === "material-file" && field.files.length && !state.aiBusy) {
    const file = field.files[0];
    state.aiBusy = true;
    addMessage({user: true, text: file.name});
    refreshChat();
    try {
      const result = demo ? {text: "Для загрузки документа откройте приложение в Telegram."} :
        await api("./materials?name=" + encodeURIComponent(file.name), {
          method: "POST", body: file, headers: {"Content-Type": "application/octet-stream"},
        });
      addMessage({text: result.text});
    } catch (failure) {
      addMessage({text: failure.message});
    } finally {
      state.aiBusy = false;
      refreshChat();
    }
  }
});

view.addEventListener("submit", async event => {
  if (event.target.id === "ai-form") {
    event.preventDefault();
    return runAssistant("ask", event.target.elements.task.value.trim());
  }
  if (event.target.id === "profile-form") {
    event.preventDefault();
    const form = event.target;
    const button = form.querySelector("[type=submit]");
    const error = form.querySelector(".error");
    const notice = form.querySelector(".notice");
    button.disabled = true;
    error.hidden = notice.hidden = true;
    try {
      await saveProfile({
        ...Object.fromEntries(new FormData(form)),
        share_documents: form.elements.share_documents.checked,
      });
      notice.hidden = false;
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      button.disabled = false;
    }
    return;
  }
  if (event.target.id !== "draft-form") return;
  event.preventDefault();
  if (state.saving) return;
  const form = event.target;
  const values = Object.fromEntries(new FormData(form));
  const button = form.querySelector("[type=submit]");
  const error = form.querySelector(".error");
  values.title = values.title.trim();
  values.body = values.body.trim();
  if (!values.title || !values.body) {
    error.textContent = "Заполните тему и текст поста.";
    error.hidden = false;
    form.elements[values.title ? "body" : "title"].focus();
    return;
  }
  state.saving = true;
  button.disabled = true;
  button.textContent = "Сохраняем…";
  error.hidden = true;
  try {
    let post;
    if (demo) {
      post = {...values, id: Date.now(), status: "DRAFT", platform: "telegram", due: new Date().toISOString()};
      localStorage.setItem(previewStore, JSON.stringify([post, ...readPreview()]));
    } else {
      post = (await liveJob({operation:"manual", ...values})).posts[0];
    }
    state.data.posts.unshift(post);
    state.draft = {title: "", body: ""};
    state.tab = "work";
    state.sections = ["root"];
    state.filter = "drafts";
    state.returnTo = "list";
    openPost(post.id, {saved: true});
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
  } finally {
    state.saving = false;
    button.disabled = false;
    button.textContent = "Сохранить черновик";
  }
});

async function start() {
  tg?.ready?.();
  tg?.expand?.();
  if (!demo) {
    tg?.setHeaderColor?.(tg?.isVersionAtLeast?.("6.9") ? "#edf1f4" : "bg_color");
    tg?.setBackgroundColor?.("#edf1f4");
  }
  try {
    state.data = demo ? {
      posts: [...readPreview(), ...samplePosts()],
      counts: {published: 12, created: 15, scheduled: 2, failed: 0},
      profile: {can_manage_users:true, model: "Gemini", audience: "", tone: "", goals: "", accounts: [], notifications: true},
      sources: sourcePages.map(([title, path]) => ({title, url: "https://salstek.ru/" + path})),
      timezone: "Asia/Yekaterinburg",
    } : await api("./data");
  } catch (error) {
    state.error = error.message;
  }
  render();
  if (!demo && state.data) {
    try {
      const saved=savedLiveJob();
      if(saved?.id||saved?.key){
        if(['marketer','document','document_delete'].includes(saved.operation)){
          state.screen='marketer';state.tab='chat';marketerUI.busy=true;render();
          try{await resumeLiveJob(saved);marketerUI.loaded=false;await loadMarketer();marketerUI.notice='Результат предыдущей задачи восстановлен.';}
          catch(error){marketerUI.error=error.message;}
          finally{marketerUI.busy=false;}
        }else{liveFlow.busy=true;liveFlow.task=saved.topic||"";liveFlow.workflow=saved.workflow;state.tab="chat";render();const result=await resumeLiveJob(saved);acceptLiveResult(result);await refreshLiveData();}
      }
    }catch(error){liveFlow.error=error.message;}
    finally{liveFlow.busy=false;render();}
  }
}
start();
