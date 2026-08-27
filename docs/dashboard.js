"use strict";

const byId = (id) => document.getElementById(id);

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function appendCell(row, content, className) {
  const cell = node("td", className);
  if (content instanceof Node) cell.append(content);
  else cell.textContent = content ?? "—";
  row.append(cell);
}

function time(value) {
  if (!value || value === "NOT_ATTEMPTED") return value === "NOT_ATTEMPTED" ? "Not attempted" : "Not available";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function spread(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number}`;
}

function price(value) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value}`;
}

function pct(value) {
  return value === null || value === undefined ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}

function signed(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function decisionBadge(value) {
  const badge = node("span", "decision");
  if (value === "BET") {
    badge.classList.add("bet");
    badge.textContent = "▲ BET";
  } else if (value === "NO BET") {
    badge.classList.add("no-bet");
    badge.textContent = "— NO BET";
  } else {
    badge.classList.add("unavailable");
    badge.textContent = "! UNAVAILABLE";
  }
  badge.setAttribute("aria-label", value);
  return badge;
}

function renderStatus(data) {
  const status = data.status;
  const badge = byId("system-badge");
  badge.textContent = status.system_status;
  badge.classList.add(status.system_status === "OPERATIONAL" ? "operational" : "attention");
  byId("generated-at").textContent = `Static artifact generated ${time(data.product.generated_at)}`;
  if (status.warning) {
    byId("warning").hidden = false;
    byId("warning").textContent = status.warning;
  }
  const items = [
    ["Season / week", `${status.season} / ${status.week}`],
    ["Last data refresh", time(status.last_successful_data_refresh)],
    ["Splash line lock", time(status.splashsports_line_locked_at)],
    ["DraftKings odds", time(status.draftkings_odds_at)],
    ["Card publication", time(status.card_published_at)],
    ["Freshness", status.freshness],
    ["Next refresh", time(status.next_scheduled_refresh)],
    ["Automation", status.schedule_status],
  ];
  const grid = byId("status-grid");
  items.forEach(([label, value]) => {
    const item = node("div", "status-item");
    item.append(node("span", "label", label), node("span", "value", value));
    grid.append(item);
  });
  const sources = byId("source-freshness");
  status.sources.forEach((source) => {
    const card = node("div", "source-card");
    card.append(node("strong", "", `${source.data_type.toUpperCase()} · ${source.state}`));
    card.append(node("p", "", source.provider || "Explicit fallback"));
    card.append(node("p", "", `Observed: ${time(source.observed_at)}`));
    if (source.fallback_code) card.append(node("p", "", `Fallback: ${source.fallback_code}`));
    sources.append(card);
  });
  (status.context || []).forEach((context) => {
    const card = node("article", "source-card");
    card.append(node("strong", "", context.context_class.replaceAll("_", " ")));
    card.append(node("span", context.state === "CURRENT" ? "" : "stale", context.state));
    card.append(node("small", "", `Mode: ${context.source_mode.replaceAll("_", " ")}`));
    card.append(node("small", "", `Records: ${context.record_count}`));
    card.append(node("small", "", `Observed: ${time(context.latest_observed_at)}`));
    if (context.fallback_reason) card.append(node("small", "stale", context.fallback_reason));
    sources.append(card);
  });
}

function renderTopFive(data) {
  const container = byId("top-five");
  data.top_five.forEach((game) => {
    const card = node("article", "top-card");
    card.append(node("div", "rank", `#${game.top_five_rank}`));
    card.append(node("h3", "", game.matchup));
    card.append(node("p", "pick-line", `${game.selected_team} ${spread(game.selected_locked_spread)}`));
    card.append(node("p", "mini-meta", `Confidence ${game.confidence} · SplashSports lock`));
    card.append(node("span", "change-mark", game.change));
    container.append(card);
  });
}

function renderContest(data) {
  const body = byId("contest-body");
  data.splashsports_card.games.forEach((game) => {
    const row = document.createElement("tr");
    const matchup = node("span", "", game.matchup);
    matchup.append(node("span", "subline", time(game.kickoff)));
    appendCell(row, matchup, "matchup");
    appendCell(row, `${game.home_team} ${spread(game.locked_home_spread)}`, "mono");
    appendCell(row, `${game.selected_team} ${spread(game.selected_locked_spread)}`);
    appendCell(row, node("span", "confidence", game.confidence));
    appendCell(row, game.is_top_five ? `#${game.top_five_rank}` : "—", game.is_top_five ? "top-tag" : "");
    appendCell(row, `${signed(game.model_projected_home_margin)} / ${signed(game.adjusted_projected_home_margin)}`, "mono");
    appendCell(row, game.change);
    appendCell(row, game.context);
    body.append(row);
  });
}

function renderDraftKings(data) {
  const body = byId("draftkings-body");
  data.draftkings_board.games.forEach((game) => {
    const row = document.createElement("tr");
    appendCell(row, decisionBadge(game.decision));
    const matchup = node("span", "", game.matchup);
    matchup.append(node("span", "subline", game.selected_team || "No DraftKings offer"));
    appendCell(row, matchup, "matchup");
    appendCell(row, game.offered_spread === null ? "—" : `${spread(game.offered_spread)} · ${price(game.offered_price)}`, "mono");
    appendCell(row, `${spread(game.model_fair_spread)} / ${signed(game.spread_edge_points)} pts`, "mono");
    appendCell(row, `${pct(game.estimated_cover_probability)} / BE ${pct(game.break_even_probability)}`);
    const ev = node("span", game.expected_value > 0 ? "positive" : game.expected_value < 0 ? "negative" : "", `${pct(game.expected_value)} / ${Number(game.suggested_units || 0).toFixed(2)}u`);
    appendCell(row, ev);
    appendCell(row, time(game.offer_captured_at));
    const reason = node("span", "", game.reason);
    reason.append(node("span", game.freshness === "CURRENT" ? "subline" : "subline stale", game.freshness));
    appendCell(row, reason);
    appendCell(row, game.change);
    body.append(row);
  });
}

function renderChanges(data) {
  const list = byId("changes");
  if (!data.changes_since_last_refresh.length) {
    list.append(node("li", "", "No material changes in the latest official refresh."));
    return;
  }
  data.changes_since_last_refresh.forEach((change) => {
    const item = node("li");
    item.append(node("span", "change-category", change.category));
    item.append(document.createTextNode(`${change.matchup}: ${change.change}`));
    item.append(node("span", "subline", time(change.observed_at)));
    list.append(item);
  });
}

function renderMarket(data) {
  const container = byId("market-comparison");
  if (!data.market_comparison.length) {
    container.append(node("div", "empty-state", "No secondary book observations are available."));
    return;
  }
  data.market_comparison.forEach((offer) => {
    const item = node("div", "market-row");
    const identity = node("div");
    identity.append(node("strong", "", `${offer.bookmaker} · ${offer.matchup}`));
    identity.append(node("span", "market-context", `Context only · ${time(offer.observed_at)}`));
    const movement = offer.home_spread_movement === null ? "first observation" : `move ${signed(offer.home_spread_movement)}`;
    item.append(identity, node("span", "mono", `H ${spread(offer.home_spread)} ${price(offer.home_price)} · ${movement}`));
    container.append(item);
  });
}

function record(summary) {
  if (!summary) return "Not available";
  return `${summary.win_count}-${summary.loss_count}-${summary.push_count}`;
}

function renderResults(data) {
  const results = data.results;
  byId("profitability-note").textContent = results.profitability_note;
  if (!results.available) {
    byId("results-pending").textContent = "Postgame grading has not completed. Results will appear only from governed final-score and closing-line custody.";
    return;
  }
  byId("results-pending").hidden = true;
  byId("results-content").hidden = false;
  const summary = results.weekly_summary;
  const draftkings = summary.draftkings;
  const cards = [
    ["Full card ATS", record(summary.full_card)],
    ["Top 5 ATS", record(summary.top_five)],
    ["DraftKings BET record", draftkings ? record(draftkings) : "Not available"],
    ["DraftKings units / ROI", draftkings ? `${signed(draftkings.realized_profit_units, 2)}u / ${signed(draftkings.roi_percent, 1)}%` : "Not available"],
  ];
  const grid = byId("weekly-summary");
  cards.forEach(([label, value]) => {
    const card = node("div", "summary-card");
    card.append(node("span", "label", label), node("strong", "", value));
    grid.append(card);
  });
  const body = byId("results-body");
  results.games.forEach((game) => {
    const row = document.createElement("tr");
    const final = node("span", "", game.matchup);
    final.append(node("span", "subline", game.final_score));
    appendCell(row, final, "matchup");
    appendCell(row, String(game.splashsports_ats_result).toUpperCase());
    appendCell(row, game.top_five ? "TOP 5" : "FULL CARD");
    appendCell(row, node("span", "confidence", game.confidence));
    appendCell(row, game.draftkings ? (game.draftkings.decision === "BET" ? `BET · ${String(game.draftkings.ats_result).toUpperCase()}` : "NO BET · NOT WAGERED") : "Not available");
    appendCell(row, game.draftkings ? `${spread(game.draftkings.closing_spread)} / ${signed(game.draftkings.clv_points)}` : `${spread(game.contest_closing_home_spread)} / ${signed(game.contest_clv_points)}`, "mono");
    appendCell(row, String(game.hook_outcome).replaceAll("_", " "));
    appendCell(row, String(game.key_number_outcome).replaceAll("_", " "));
    appendCell(row, String(game.backdoor_outcome).replaceAll("_", " "));
    body.append(row);
  });
  const segments = byId("segments");
  summary.segments.forEach((segment) => {
    const item = node("div", "segment-row");
    item.append(node("span", "", `${segment.dimension_code.replaceAll("_", " ")} · ${segment.category_code.replaceAll("_", " ")}`));
    item.append(node("strong", "mono", `${record(segment)} · ${segment.ats_win_rate === null ? "—" : `${Number(segment.ats_win_rate).toFixed(1)}%`}`));
    segments.append(item);
  });
  const lessons = byId("lessons");
  summary.lessons_learned.forEach((lesson) => {
    const item = node("li");
    item.append(node("strong", "", `${lesson.lesson_code.replaceAll("_", " ")} · ${lesson.sample_status}`));
    item.append(node("span", "subline", lesson.narrative));
    lessons.append(item);
  });
}

async function start() {
  try {
    const response = await fetch("dashboard.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Static dashboard payload returned ${response.status}`);
    const data = await response.json();
    if (data.schema_version !== "v3-public-dashboard-v1") throw new Error("Unsupported dashboard payload version");
    renderStatus(data);
    renderTopFive(data);
    renderContest(data);
    renderDraftKings(data);
    renderChanges(data);
    renderMarket(data);
    renderResults(data);
  } catch (error) {
    const message = byId("fatal-error");
    message.hidden = false;
    message.textContent = `Dashboard unavailable: ${error.message}. The site will not fabricate replacement data.`;
    byId("system-badge").textContent = "UNAVAILABLE";
    byId("system-badge").classList.add("attention");
  }
}

start();
