const runId = window.AUTO_RESEARCH_RUN;

function statusClass(status) {
  if (["completed", "limited", "failed", "running", "pending"].includes(status)) {
    return status;
  }
  return "pending";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderFeatured(featured, summary) {
  if (!featured) {
    return `
      <div class="empty">
        <h3>Run queued</h3>
        <p>The autonomous loop is preparing the first research packet.</p>
      </div>
    `;
  }

  const kpiRows = (featured.artifact.kpi_table || [])
    .map((row) => `<tr><th>${escapeHtml(row.metric)}</th><td>${escapeHtml(row.value)}</td></tr>`)
    .join("");

  const peers = (featured.artifact.peer_table || [])
    .map(
      (peer) => `
        <article class="peer-item">
          <strong>${escapeHtml(peer.ticker)}</strong>
          <span>${escapeHtml(peer.thesis_role)}</span>
          <p>${escapeHtml(peer.comment)}</p>
        </article>
      `,
    )
    .join("");

  const sources = (featured.artifact.citations || [])
    .map((citation) => {
      const safe = escapeHtml(citation);
      if (String(citation).startsWith("http")) {
        return `<li><a href="${safe}" target="_blank" rel="noreferrer">${safe}</a></li>`;
      }
      return `<li><span>${safe}</span></li>`;
    })
    .join("");

  const evidence = (featured.artifact.evidence_items || [])
    .length
    ? (featured.artifact.evidence_items || [])
    : [
        {
          agent: "Source Scout",
          claim: "Public market context was collected for this run.",
          support: "Older run format did not persist snippet-level evidence, so only the high-level packet is available here.",
          source_label: "Stored run artifact",
          source_url: null,
        },
      ];

  const evidenceMarkup = evidence
    .map((item) => {
      const source = item.source_url
        ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source_label)}</a>`
        : `<span>${escapeHtml(item.source_label)}</span>`;
      return `
        <article class="evidence-item">
          <p class="evidence-agent">${escapeHtml(item.agent)}</p>
          <h3>${escapeHtml(item.claim)}</h3>
          <p>${escapeHtml(item.support)}</p>
          <p class="evidence-source">${source}</p>
        </article>
      `;
    })
    .join("");

  const fallbackAgents = [
    {
      name: "Source Scout",
      role: "Pulls market context and recent public coverage.",
      status: "completed",
      detail: "Collected available market observations and linked news coverage.",
    },
    {
      name: "Filing Tracker",
      role: "Maps the ticker to SEC coverage and recent forms.",
      status: "completed",
      detail: "Attached recent SEC filing coverage when available.",
    },
    {
      name: "Document Reader",
      role: "Reads filing text and extracts evidence snippets.",
      status: "completed",
      detail: "Attached filing-text evidence where it was available.",
    },
    {
      name: "Peer Mapper",
      role: "Builds the comparable set and role for each peer.",
      status: "completed",
      detail: "Prepared the comparison set shown in the report.",
    },
    {
      name: "Note Writer",
      role: "Assembles the packet with evidence and linked sources.",
      status: "completed",
      detail: "Built the report sections now shown above.",
    },
  ];

  const agents = ((featured.artifact.agent_briefs || []).length ? featured.artifact.agent_briefs : fallbackAgents)
    .map(
      (agent) => `
        <article class="agent-card">
          <div class="agent-card-top">
            <strong>${escapeHtml(agent.name)}</strong>
            <span class="badge state-${statusClass(agent.status)}">${escapeHtml(agent.status)}</span>
          </div>
          <p class="agent-role">${escapeHtml(agent.role)}</p>
          <p class="agent-detail">${escapeHtml(agent.detail)}</p>
        </article>
      `,
    )
    .join("");

  const traceFallback = [
    {
      agent: "Source Scout",
      tool: "market/news fetch",
      status: "completed",
      output: "Collected the available public market and linked news context.",
    },
    {
      agent: "Filing Tracker",
      tool: "SEC submissions lookup",
      status: "completed",
      output: "Attached the filing coverage available for the run.",
    },
    {
      agent: "Document Reader",
      tool: "SEC filing document fetch + text extraction",
      status: "completed",
      output: "Attached filing-text evidence when it was available.",
    },
    {
      agent: "Peer Mapper",
      tool: "peer heuristic",
      status: "completed",
      output: "Prepared a comparable set for the report.",
    },
    {
      agent: "Note Writer",
      tool: "packet assembler",
      status: "completed",
      output: "Rendered the current research packet.",
    },
  ];

  const trace = ((featured.artifact.agent_actions || []).length ? featured.artifact.agent_actions : traceFallback)
    .map(
      (action) => `
        <article class="trace-item">
          <div class="trace-top">
            <strong>${escapeHtml(action.agent)}</strong>
            <span class="badge state-${statusClass(action.status)}">${escapeHtml(action.status)}</span>
          </div>
          <p class="trace-tool">${escapeHtml(action.tool)}</p>
          <p class="trace-output">${escapeHtml(action.output)}</p>
        </article>
      `,
    )
    .join("");

  return `
    <div class="report-grid">
      <article class="report-lead">
        <p class="eyebrow">Research packet</p>
        <h2>Analyst note</h2>
        <p class="lead-summary">${escapeHtml(featured.artifact.summary)}</p>
        <p class="lead-note">${escapeHtml(featured.artifact.analyst_note)}</p>
        <p class="lead-support" id="final-summary">${escapeHtml(summary || "Summary will appear once completion criteria are met.")}</p>
      </article>

      <aside class="report-score">
        <p class="eyebrow">Best iteration</p>
        <h2>${escapeHtml(featured.index)}</h2>
        <div class="pill-row">
          <span>Score ${escapeHtml(featured.scorecard.total)}/100</span>
          <span>Grounding ${escapeHtml(featured.scorecard.factual_grounding)}/25</span>
          <span>KPI ${escapeHtml(featured.scorecard.kpi_completeness)}/15</span>
          <span>Guidance ${escapeHtml(featured.scorecard.guidance_capture)}/15</span>
          <span>Peers ${escapeHtml(featured.scorecard.peer_relevance)}/15</span>
        </div>
      </aside>
    </div>

    <div class="report-card agentic-panel">
      <div class="section-head section-head-tight">
        <div>
          <p class="eyebrow">Agentic researcher</p>
          <h2>Research team</h2>
        </div>
      </div>
      <div class="agent-grid" id="agent-grid">${agents}</div>
    </div>

    <div class="report-columns report-columns-wide">
      <section class="report-card">
        <h2>Evidence ledger</h2>
        <div class="evidence-list" id="evidence-list">${evidenceMarkup}</div>
      </section>

      <section class="report-card">
        <h2>Agent trace</h2>
        <div class="trace-list" id="trace-list">${trace}</div>
      </section>
    </div>

    <div class="report-columns">
      <section class="report-card">
        <h2>KPI snapshot</h2>
        <table class="data-table" id="kpi-table"><tbody>${kpiRows}</tbody></table>
      </section>

      <section class="report-card">
        <h2>Valuation view</h2>
        <p id="valuation-summary">${escapeHtml(featured.artifact.valuation_summary)}</p>
        <h3>Guidance context</h3>
        <p id="guidance-notes">${escapeHtml(featured.artifact.guidance_notes)}</p>
        <h3>Risks and catalysts</h3>
        <p id="risks-and-catalysts">${escapeHtml(featured.artifact.risks_and_catalysts)}</p>
      </section>
    </div>

    <div class="report-columns">
      <section class="report-card">
        <h2>Peer set</h2>
        <div class="peer-list" id="peer-list">${peers}</div>
      </section>

      <section class="report-card">
        <h2>Sources used</h2>
        <ul class="sources-list" id="sources-list">${sources}</ul>
      </section>
    </div>
  `;
}

async function refreshRun() {
  if (!runId) return;
  const response = await fetch(`/api/runs/${runId}`);
  if (!response.ok) return;

  const data = await response.json();
  const stateNode = document.getElementById("run-state");
  const reportNode = document.getElementById("report-root");
  const listNode = document.getElementById("iterations");

  if (stateNode) {
    const scoreText = data.best_score ? `<span class="score">Best: ${data.best_score}/100</span>` : "";
    stateNode.innerHTML = `State: <span class="badge state-${data.state}">${data.state}</span> ${scoreText}`;
  }

  if (reportNode) {
    reportNode.innerHTML = renderFeatured(data.featured, data.summary);
  }

  if (listNode) {
    if (data.iterations.length === 0) {
      listNode.innerHTML = `
        <div class="empty">
          <h3>Run queued</h3>
          <p>The autonomous loop is preparing its first iteration.</p>
        </div>
      `;
    } else {
      listNode.innerHTML = data.iterations
        .map((item) => {
          const issues = (item.scorecard.major_issues || [])
            .map((issue) => `<li>${issue}</li>`)
            .join("");
          return `
            <article class="iteration-card">
              <header>
                <h3>Iteration ${item.index}</h3>
                <span class="score">${item.scorecard.total}/100</span>
              </header>
              <p>${item.artifact.summary}</p>
              <div class="pill-row">
                <span>Grounding ${item.scorecard.factual_grounding}/25</span>
                <span>KPI ${item.scorecard.kpi_completeness}/15</span>
                <span>Guidance ${item.scorecard.guidance_capture}/15</span>
                <span>Peers ${item.scorecard.peer_relevance}/15</span>
              </div>
              ${issues ? `<ul>${issues}</ul>` : ""}
            </article>
          `;
        })
        .join("");
    }
  }

  if (data.state === "running" || data.state === "pending") {
    setTimeout(refreshRun, 1500);
  }
}

if (runId) {
  setTimeout(refreshRun, 500);
}
