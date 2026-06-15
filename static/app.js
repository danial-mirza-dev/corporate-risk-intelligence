/* ===================================================================
   Corporate Risk Intelligence Platform — front-end controller
   States: search -> disambiguation -> dossier. Renders the dossier
   from a single /analyze response with staggered section reveals.
   =================================================================== */
(function () {
  "use strict";

  // ---- tiny DOM helpers -------------------------------------------------
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === "class") node.className = attrs[k];
        else if (k === "html") node.innerHTML = attrs[k];
        else if (k.startsWith("on") && typeof attrs[k] === "function")
          node.addEventListener(k.slice(2), attrs[k]);
        else if (attrs[k] != null) node.setAttribute(k, attrs[k]);
      }
    }
    (children || []).forEach(function (c) {
      if (c == null) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }
  const $ = function (sel) { return document.querySelector(sel); };

  // Well-known long names → compact labels (shared with the timeline).
  const LABEL_ABBREVIATIONS = {
    "ISLAMIC REVOLUTIONARY GUARD CORPS": "IRGC",
    "IRAN REVOLUTIONARY GUARD CORPS": "IRGC",
    "REVOLUTIONARY GUARD CORPS": "IRGC",
    "ISLAMIC REVOLUTION GUARD CORPS": "IRGC",
    "NATIONAL IRANIAN OIL COMPANY": "NIOC",
    "CENTRAL BANK OF IRAN": "CBI Iran",
    "MINISTRY OF PETROLEUM": "Min. of Petroleum",
    "ISLAMIC REPUBLIC OF IRAN": "Iran (Gov.)",
  };
  function abbrev(label) {
    if (!label) return label;
    const upper = String(label).toUpperCase();
    for (const key in LABEL_ABBREVIATIONS) {
      if (upper.indexOf(key) >= 0) return LABEL_ABBREVIATIONS[key];
    }
    return label;
  }

  // ---- elements ---------------------------------------------------------
  const searchView = $("#search-view");
  const searchForm = $("#search-form");
  const searchInput = $("#search-input");
  const countrySelect = $("#country-select");
  const searchButton = $("#search-button");
  const disambig = $("#disambiguation");
  const analyzingEl = $("#analyzing");
  const analyzingName = $("#analyzing-name");
  const searchError = $("#search-error");
  const dossier = $("#dossier");
  const dossierContent = $("#dossier-content");
  const tooltip = $("#tooltip");

  let prefetch = null; // { entity_id, promise }

  // ---- events -----------------------------------------------------------
  searchForm.addEventListener("submit", function (e) {
    e.preventDefault();
    runSearch(searchInput.value.trim(), countrySelect.value);
  });
  document.querySelectorAll(".demo-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      const name = chip.dataset.name;
      const country = chip.dataset.country || "";
      searchInput.value = name;
      countrySelect.value = country;
      // Demo chips carry a known entity_id — skip /search disambiguation and go
      // straight to analysis. Free-text searches keep the disambiguation flow.
      const eid = chip.dataset.entityId;
      if (eid) {
        hide(searchError); hide(disambig);
        analyzeEntity({ entity_id: eid, label: name, entity_name: name }, country);
      } else {
        runSearch(name, country);
      }
    });
  });
  $("#back-button").addEventListener("click", resetToSearch);
  $("#panel-close").addEventListener("click", closePanel);
  $("#panel-scrim").addEventListener("click", closePanel);

  // ---- search -----------------------------------------------------------
  function runSearch(name, country) {
    if (!name) return;
    hide(searchError); hide(disambig); hide(analyzingEl);
    searchButton.disabled = true; searchButton.textContent = "Searching…";

    fetch("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, country: country }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        searchButton.disabled = false; searchButton.textContent = "Analyze";
        const candidates = data.candidates || [];
        if (!candidates.length) {
          showError("No matching entity found for “" + name + "”. " +
            "Try the full legal name, or remove the country filter.");
          return;
        }
        if (candidates.length === 1) {
          // Auto-skip disambiguation, but show a brief confirmation first.
          const only = candidates[0];
          disambig.innerHTML = "";
          disambig.appendChild(el("div", { class: "disambig-heading" },
            ["Resolved to " + (only.label || "the matching entity")]));
          show(disambig);
          setTimeout(function () { analyzeEntity(only, country); }, 1500);
          return;
        }
        renderDisambiguation(candidates, country);
        // Pre-load the top candidate in the background while the user reviews.
        beginPrefetch(candidates[0], country);
      })
      .catch(function () {
        searchButton.disabled = false; searchButton.textContent = "Analyze";
        showError("Search failed. Please try again.");
      });
  }

  function renderDisambiguation(candidates, country) {
    disambig.innerHTML = "";
    disambig.appendChild(el("div", { class: "disambig-heading" },
      ["Select the entity you want to analyze:"]));
    candidates.forEach(function (c) {
      const meta = [el("span", null, [c.country])];
      if (c.incorporation_date) {
        meta.push(el("span", { class: "sep" }, ["·"]));
        meta.push(el("span", null, [c.incorporation_date]));
      }
      if (c.company_type && c.company_type !== "Not specified") {
        meta.push(el("span", { class: "sep" }, ["·"]));
        meta.push(el("span", null, [c.company_type]));
      }
      const right = [];
      if (c.sanctioned) right.push(el("span", { class: "badge-sanctioned" }, ["SANCTIONED"]));
      right.push(el("span", { class: "candidate-network" }, [c.network_size]));

      const card = el("div", { class: "candidate-card", onclick: function () { analyzeEntity(c, country); } }, [
        el("div", { class: "candidate-main" }, [
          el("div", { class: "candidate-name" }, [c.label || "Unnamed entity"]),
          el("div", { class: "candidate-meta" }, meta),
        ]),
        el("div", { class: "candidate-right" }, right),
      ]);
      disambig.appendChild(card);
    });
    show(disambig);
  }

  function beginPrefetch(candidate, country) {
    if (!candidate || !candidate.entity_id) { prefetch = null; return; }
    const promise = fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entity_id: candidate.entity_id,
        entity_name: candidate.label,
        country: country || "",
      }),
    }).then(function (r) { return r.json(); }).catch(function () { return null; });
    prefetch = { entity_id: candidate.entity_id, promise: promise };
  }

  // ---- analyze ----------------------------------------------------------
  function analyzeEntity(candidate, country) {
    hide(disambig);
    analyzingName.textContent = candidate.label || candidate.entity_name || "entity";
    show(analyzingEl);
    animateSourceDots(true);

    let p;
    if (prefetch && prefetch.entity_id === candidate.entity_id) {
      p = prefetch.promise;
    } else {
      p = fetch("/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_id: candidate.entity_id,
          entity_name: candidate.label,
          country: country || "",
        }),
      }).then(function (r) { return r.json(); });
    }

    p.then(function (data) {
      animateSourceDots(false);
      if (!data || data.error) {
        hide(analyzingEl);
        showError((data && data.error) || "Analysis failed. Please try again.");
        return;
      }
      renderDossier(data);
    }).catch(function () {
      animateSourceDots(false);
      hide(analyzingEl);
      showError("Analysis failed. Please try again.");
    });
  }

  let dotTimer = null;
  function animateSourceDots(start) {
    const dots = Array.prototype.slice.call(document.querySelectorAll(".source-dots .dot"));
    dots.forEach(function (d) { d.classList.remove("active", "done"); });
    if (dotTimer) { clearInterval(dotTimer); dotTimer = null; }
    if (!start) { dots.forEach(function (d) { d.classList.add("done"); }); return; }
    let i = 0;
    dots[0].classList.add("active");
    dotTimer = setInterval(function () {
      if (i < dots.length) { dots[i].classList.remove("active"); dots[i].classList.add("done"); }
      i++;
      if (i < dots.length) dots[i].classList.add("active");
      else { clearInterval(dotTimer); dotTimer = null; }
    }, 900);
  }

  // ---- dossier rendering ------------------------------------------------
  function renderDossier(d) {
    dossierContent.innerHTML = "";
    window._searchedEntity = d.entity_name;   // used by breakdown tooltips
    const sections = [];

    sections.push(riskBanner(d));
    sections.push(sectionEntityProfile(d));
    const net = sectionNetwork(d);
    if (net) sections.push(net);
    const jur = sectionJurisdiction(d);
    if (jur) sections.push(jur);
    const trade = sectionTrade(d);
    if (trade) sections.push(trade);
    sections.push(sectionBrief(d));

    // Staggered reveal: 200ms between sections.
    sections.forEach(function (node, idx) {
      node.style.animationDelay = (idx * 0.2) + "s";
      dossierContent.appendChild(node);
    });

    hide(analyzingEl);
    searchView.classList.add("compact");
    hide(searchView);
    show(dossier);
    window.scrollTo({ top: 0, behavior: "smooth" });

    // Render the D3 timeline after the node is in the DOM.
    if (d.timeline_nodes && d.timeline_nodes.length && window.RiskTimeline) {
      window.RiskTimeline.render("#timeline-mount", d.timeline_nodes, openEntityPanel);
    }
  }

  // ----- risk banner -----
  function riskBanner(d) {
    const rating = (d.risk_rating || "LOW").toLowerCase();
    const sub = [];
    if (d.profile && d.profile.countries) sub.push(d.profile.countries);
    if (d.profile && d.profile.incorporation_display) sub.push(d.profile.incorporation_display);
    return el("div", { class: "risk-banner rb-" + rating }, [
      el("div", null, [
        el("div", { class: "rb-name" }, [d.entity_name]),
        el("div", { class: "rb-sub" }, [sub.join("  ·  ")]),
      ]),
      el("div", { class: "rb-finding" }, [d.key_finding || ""]),
      el("div", { class: "rb-rating" }, [
        el("span", { class: "rb-badge r-" + rating }, [d.risk_rating || "LOW"]),
        el("div", { class: "rb-confidence" },
          ["Confidence: " + ((d.brief && d.brief.confidence) || "—").toUpperCase()]),
      ]),
    ]);
  }

  // ----- section shell -----
  function sectionShell(title, sub, badges, bodyNodes) {
    const badgeNodes = (badges || []).map(function (b) {
      return el("span", { class: "source-badge" }, [b]);
    });
    const head = el("div", { class: "section-head" }, [
      el("div", null, [
        el("span", { class: "section-title" }, [title]),
        sub ? el("span", { class: "section-sub" }, [sub]) : null,
      ]),
      el("div", { class: "source-badges" }, badgeNodes),
    ]);
    return el("section", { class: "section" }, [head].concat(bodyNodes));
  }

  // ----- Section 1: Entity Profile -----
  function sectionEntityProfile(d) {
    const p = d.profile || {};
    const body = [];

    // metadata grid — Status cell only when it carries a real value.
    const cells = [
      metaCell("Country", p.countries || "Unknown"),
      metaCell("Founded", p.incorporation_display || "Not on record"),
      metaCell("Company Type", p.company_type || "Not specified"),
    ];
    const st = (p.status || "").trim();
    if (st && st !== "Unknown" && st !== "unknown" && st !== "—") {
      cells.push(metaCell("Status", st,
        st === "Active" ? "status-active" : (st === "Inactive" ? "status-inactive" : "")));
    }
    body.push(el("div", { class: "meta-grid" }, cells));

    // risk factor tags
    body.push(el("div", { class: "subsection-title" }, ["Risk Indicators"]));
    if (p.risk_factors && p.risk_factors.length) {
      const row = el("div", { class: "tag-row" }, p.risk_factors.map(function (rf) {
        const tag = el("span", { class: "risk-tag " + rf.severity }, [rf.label]);
        attachTooltip(tag, rf.label, rf.tooltip);
        return tag;
      }));
      body.push(row);
    } else {
      body.push(el("div", { class: "empty-note" }, ["No specific risk factors identified."]));
    }

    // ownership
    body.push(el("div", { class: "subsection-title" }, ["Ownership Structure"]));
    const ubo = d.ubo || {};
    if (ubo.empty) {
      const m = d.ubo_message || {
        title: "Beneficial Ownership Undisclosed",
        message: "Sayari found no registered beneficial owners.", severity: "warning",
      };
      const cls = m.severity === "warning" ? "callout amber" : "callout ownership-info";
      body.push(el("div", { class: cls }, [
        el("div", { class: "callout-title" }, [m.title]),
        el("div", null, [m.message]),
      ]));
    } else if (ubo.owners && ubo.owners.length) {
      const tree = el("div", { class: "own-tree" }, ubo.owners.map(function (o, i) {
        const children = [
          el("span", { class: "own-name" }, [o.label || "Unnamed owner"]),
          el("span", { class: "own-country" }, ["— " + (o.countries || "Unknown")]),
        ];
        if (o.sanctioned) children.push(el("span", { class: "badge-yes" }, ["SANCTIONED"]));
        else if (o.pep) children.push(el("span", { class: "risk-tag amber" }, ["PEP"]));
        return el("div", { class: "own-node" + (i > 0 ? " own-indent" : "") }, children);
      }));
      body.push(tree);
    }

    // relationships
    const rels = (p.relationships || []);
    if (rels.length) {
      body.push(el("div", { class: "subsection-title" }, ["Corporate Relationships"]));
      const shown = rels.slice(0, 20);
      const table = el("table", { class: "rel-table" }, [
        el("thead", null, [el("tr", null, [
          el("th", null, ["Entity Name"]), el("th", null, ["Relationship"]),
          el("th", null, ["Sanctioned"]), el("th", null, ["Countries"]),
        ])]),
        el("tbody", null, shown.map(function (r) {
          const nameCell = [el("span", null, [abbrev(r.label) || "—"])];
          if (r.is_pep)
            nameCell.push(el("span", { class: "risk-tag amber pep-badge", title: "Politically Exposed Person — subject to enhanced due diligence requirements" }, ["PEP"]));
          else if (r.is_person)
            nameCell.push(el("span", { class: "person-badge" }, ["PERSON"]));
          return el("tr", null, [
            el("td", null, nameCell),
            el("td", null, [r.relationship_type_label || "Connection"]),
            el("td", null, [r.sanctioned ? el("span", { class: "badge-yes" }, ["YES"])
              : el("span", { class: "badge-no" }, ["No"])]),
            el("td", null, [r.countries || "—"]),
          ]);
        })),
      ]);
      body.push(table);
      if (rels.length > 20)
        body.push(el("div", { class: "table-note" },
          ["Showing 20 of " + rels.length + " total corporate connections. " +
           "Only ownership and control relationships displayed."]));
    }

    return sectionShell("Entity Profile", null, ["Sayari"], body);
  }

  function metaCell(key, val, cls) {
    return el("div", { class: "meta-cell" }, [
      el("div", { class: "meta-key" }, [key]),
      el("div", { class: "meta-val " + (cls || "") }, [val]),
    ]);
  }

  // ----- Section 2: Sanctioned Network -----
  function sectionNetwork(d) {
    const w = d.watchlist || {};
    if (!w.path_count) return null;
    const body = [];

    const depth = w.min_depth != null ? String(w.min_depth) : (w.depth || "—");
    body.push(el("div", { class: "stat-bar" }, [
      statCell(String(w.path_count), "Sanctioned Connections Found"),
      statCell(exploredDisplay(d, w), "Entities Explored"),
      statCell(String(depth), "Degrees of Separation"),
    ]));
    if (d.network_context)
      body.push(el("div", { class: "network-context" }, [d.network_context]));

    // Sanctioned connection breakdown table.
    const breakdown = renderConnectionBreakdown(w);
    if (breakdown) body.push(breakdown);

    // shortest path callout
    if (d.shortest_path && d.shortest_path.length != null) {
      const sp = d.shortest_path;
      let desc = sp.length + " corporate relationship" + (sp.length === 1 ? "" : "s");
      if (sp.intermediates && sp.intermediates.length)
        desc += " via " + sp.intermediates.join(" → ");
      body.push(el("div", { class: "callout amber" }, [
        el("div", { class: "callout-title" }, ["Direct Network Connection Found"]),
        el("div", null, [d.entity_name + " is connected to " +
          (sp.anchor_name || "a known sanctioned entity") + " through " + desc + "."]),
      ]));
    }

    // timeline mount (D3 fills this)
    if (d.timeline_nodes && d.timeline_nodes.length) {
      body.push(el("div", { class: "subsection-title" }, ["Network Timeline"]));
      const mount = el("div", { class: "timeline-wrap", id: "timeline-mount" }, []);
      body.push(mount);
    }

    // Undated sanctioned connections (no incorporation date → not on timeline).
    const undated = d.timeline_undated || [];
    if (undated.length) {
      const items = undated.map(function (n) {
        return el("div", { class: "tl-undated-item" }, [
          el("span", { class: "tl-undated-name" }, [abbrev(n.label) || "Unknown Entity"]),
          el("span", { class: "tl-undated-program" }, [
            el("span", { class: "desig-badge" }, [n.designation_program || "International Sanctions"])]),
          el("span", { class: "tl-undated-countries" }, [n.countries || "—"]),
        ]);
      });
      body.push(el("div", { class: "tl-undated-section" }, [
        el("div", { class: "tl-undated-label" },
          ["ADDITIONAL SANCTIONED CONNECTIONS — INCORPORATION DATE UNKNOWN"]),
        el("div", { class: "tl-undated-list" }, items),
      ]));
    }

    return sectionShell("Sanctioned Network", null, ["Sayari"], body);
  }

  function statCell(num, label) {
    return el("div", { class: "stat-cell" }, [
      el("div", { class: "stat-num mono" }, [num]),
      el("div", { class: "stat-label" }, [label]),
    ]);
  }

  // BF-1: comma-format the explored count; for a small entity returning a wildly
  // larger count than its own degree, show "Extensive network" not a raw number.
  function exploredDisplay(d, w) {
    const n = Number(w.explored_count || 0);
    const degree = Number((d.profile || {}).degree || 0);
    if (degree < 50000 && n > 50000) return "Extensive network";
    return n.toLocaleString();
  }

  // SN-1: sanctioned connection breakdown table (top 10, direct-first).
  function renderConnectionBreakdown(w) {
    const paths = (w.paths || []).filter(function (p) { return p.sanctioned; });
    if (!paths.length) return null;
    const sorted = paths.slice().sort(function (a, b) {
      return (a.path_depth || 1) - (b.path_depth || 1) || (b.degree || 0) - (a.degree || 0);
    });
    const shown = sorted.slice(0, 10);
    const rows = shown.map(function (p) {
      const depth = p.path_depth || 1;
      const connAttrs = { class: "conn-type" };
      if (depth > 2)
        connAttrs.title = "This entity is " + depth + " corporate steps away from " +
          (window._searchedEntity || "the searched entity") + ". Each step represents a " +
          "documented corporate relationship in Sayari's knowledge graph.";
      const connCell = [el("span", connAttrs, [p.path_description || "Corporate network connection"])];
      if (depth === 1)
        connCell.push(el("span", { class: "badge-direct" }, ["⚡ Direct"]));
      const nameCell = [el("span", null, [abbrev(p.label) || "—"])];
      if (p.is_pep) nameCell.push(el("span", { class: "risk-tag amber pep-badge", title: "Politically Exposed Person — subject to enhanced due diligence requirements" }, ["PEP"]));
      else if (p.is_person) nameCell.push(el("span", { class: "person-badge" }, ["PERSON"]));
      return el("tr", null, [
        el("td", null, nameCell),
        el("td", null, connCell),
        el("td", null, [el("span", { class: "desig-badge" }, [p.designation_program || "International Sanctions"])]),
        el("td", null, [p.countries || "—"]),
      ]);
    });
    const body = [
      el("div", { class: "subsection-title" }, ["SANCTIONED CONNECTION BREAKDOWN"]),
      el("table", { class: "rel-table" }, [
        el("thead", null, [el("tr", null, [
          el("th", null, ["Entity"]), el("th", null, ["Connection Type"]),
          el("th", null, ["Designation"]), el("th", null, ["Countries"]),
        ])]),
        el("tbody", null, rows),
      ]),
    ];
    if (paths.length > 10)
      body.push(el("div", { class: "table-note" },
        ["Showing 10 of " + paths.length + " sanctioned connections."]));
    return el("div", null, body);
  }

  // ----- Section 3: Jurisdiction Risk (four signals) -----
  const FATF_COLOR = { high: "red", medium: "amber", low: "green" };

  function sectionJurisdiction(d) {
    const wb = d.worldbank;
    if (!wb && !d.primary_country) return null;
    const body = [];

    // Signals 1 & 2 fill asynchronously from the jurisdiction reference endpoint.
    const fatfSlot = el("div", { class: "jr-signal" }, [el("div", { class: "jr-loading" }, ["Loading FATF status…"])]);
    const sanctionsSlot = el("div", { class: "jr-signal" }, [el("div", { class: "jr-loading" }, ["Loading sanctions programs…"])]);
    body.push(fatfSlot);
    body.push(sanctionsSlot);

    // Signal 3 — FDI (live World Bank).
    if (wb && wb.fdi && wb.fdi.value != null) {
      const v = wb.fdi.value;
      const cls = v < 0 ? "neg" : (v <= 1 ? "warn" : "ok");
      body.push(el("div", { class: "jr-signal" }, [
        el("div", { class: "jr-signal-title" }, ["Foreign Direct Investment"]),
        el("div", { class: "jr-fdi-num " + cls }, [v + "% of GDP (" + (wb.fdi.year || "—") + ")"]),
        el("div", { class: "jr-signal-note" }, [wb.fdi.interpretation || ""]),
      ]));
    }

    // Signal 4 — Governance composite (single score, replaces three gauges).
    if (wb && wb.composite_score != null) {
      const c = wb.composite_score;
      const band = c >= 55 ? "green" : (c >= 30 ? "amber" : "red");
      body.push(el("div", { class: "jr-signal" }, [
        el("div", { class: "jr-signal-title" }, ["Governance Composite"]),
        el("div", { class: "jr-gov-num mono" }, [ordinal(Math.round(c)) + " percentile globally" +
          (wb.year ? " (" + wb.year + ")" : "")]),
        el("div", { class: "gauge-bar" }, [
          el("div", { class: "gauge-fill " + band, style: "width:" + c + "%" }, []),
        ]),
        el("div", { class: "jr-signal-note" },
          ["Based on World Bank Worldwide Governance Indicators — Corruption Control, " +
           "Rule of Law, and Political Stability."]),
      ]));
    }

    body.push(el("div", { class: "jr-footer" },
      ["Last assessed: " + ((wb && wb.year) || "n/a") + " · Source: World Bank / FATF"]));

    // Fetch FATF + sanctions reference and populate the two slots.
    if (d.primary_country) {
      fetch("/reference/jurisdiction/" + encodeURIComponent(d.primary_country))
        .then(function (r) { return r.json(); })
        .then(function (ref) {
          fatfSlot.innerHTML = "";
          fatfSlot.appendChild(fatfBadge(ref.fatf));
          sanctionsSlot.innerHTML = "";
          sanctionsSlot.appendChild(sanctionsSignal(ref.sanctions, !!(d.profile && d.profile.sanctioned)));
        })
        .catch(function () {
          fatfSlot.innerHTML = ""; sanctionsSlot.innerHTML = "";
        });
    } else {
      fatfSlot.innerHTML = ""; sanctionsSlot.innerHTML = "";
    }

    const badges = wb ? ["World Bank", "FATF"] : ["FATF"];
    return sectionShell("Jurisdiction Risk", null, badges, body);
  }

  function fatfBadge(f) {
    f = f || {};
    const status = f.status || "Unknown";
    let text, color;
    if (status === "Black List") { text = "⛔ FATF BLACKLISTED"; color = "red"; }
    else if (status === "Grey List") { text = "⚠️ FATF GREY LIST"; color = "amber"; }
    else if (status === "Suspended") { text = "🚫 FATF SUSPENDED"; color = "red"; }
    else if (status === "Clean") { text = "✓ FATF CLEAN"; color = FATF_COLOR[f.color] || "green"; }
    else { text = "? FATF STATUS UNKNOWN"; color = "grey"; }
    return el("div", null, [
      el("div", { class: "jr-signal-title" }, ["FATF Status"]),
      el("div", { class: "fatf-badge " + color }, [text]),
      el("div", { class: "jr-signal-note" }, [f.note || ""]),
    ]);
  }

  function sanctionsSignal(s, entitySanctioned) {
    s = s || { count: 0, programs: [], summary: "" };
    const n = s.count || 0;
    const cls = n === 0 ? "ok" : (n <= 2 ? "warn" : "neg");
    const kids = [
      el("div", { class: "jr-signal-title" }, ["Active Sanctions Programs"]),
      el("div", { class: "jr-sanctions-num " + cls },
        [n + " active international sanctions program" + (n === 1 ? "" : "s")]),
    ];
    if (n > 0) {
      const progs = (s.programs || []).slice(0, 3);
      const tags = progs.map(function (p) { return el("span", { class: "prog-tag" }, [p]); });
      if ((s.programs || []).length > 3)
        tags.push(el("span", { class: "prog-more" }, ["and " + ((s.programs.length) - 3) + " more"]));
      kids.push(el("div", { class: "prog-row" }, tags));
    }
    kids.push(el("div", { class: "jr-signal-note" }, [s.summary || ""]));
    if (n === 0) {
      const note = entitySanctioned
        ? "While this jurisdiction has no country-level sanctions programs, " +
          "individual entities registered here may carry US, EU, or UN designations. " +
          "Entity-level designations apply regardless of the host country's sanctions status."
        : "No country-level sanctions programs apply to this jurisdiction.";
      kids.push(el("div", { class: "jr-signal-note" }, [note]));
    }
    return el("div", null, kids);
  }

  // ----- Section 4: Trade Intelligence -----
  function sectionTrade(d) {
    const trade = d.trade || {};
    const comtradeData = d.comtrade;
    const finding = d.trade_finding;
    const body = [];
    const badges = comtradeData ? ["Sayari", "UN Comtrade"] : ["Sayari"];

    if (!trade.empty && trade.total) {
      body.push(el("div", { class: "trade-summary" },
        [trade.total.toLocaleString() + " documented shipment" +
          (trade.total === 1 ? "" : "s") + " found in Sayari's global trade database."]));
      const shown = (trade.shipments || []).slice(0, 5);
      body.push(el("table", { class: "rel-table" }, [
        el("thead", null, [el("tr", null, [
          el("th", null, ["Commodity"]), el("th", null, ["Origin"]),
          el("th", null, ["Destination"]), el("th", null, ["Commodity Class (HS)"]),
        ])]),
        el("tbody", null, shown.map(function (s) {
          return el("tr", null, [
            el("td", null, [s.commodity || "Not specified"]),
            el("td", null, [s.origin || "Unknown"]),
            el("td", null, [s.destination || "Unknown"]),
            el("td", null, [s.hs_description || "Not specified"]),
          ]);
        })),
      ]));

      if (comtradeData) {
        body.push(el("div", { class: "trade-compare" }, [
          el("div", { class: "compare-cell" }, [
            el("div", { class: "compare-num mono" }, [String(trade.total)]),
            el("div", { class: "compare-label" }, ["Documented Shipments (Sayari)"]),
          ]),
          el("div", { class: "compare-cell" }, [
            el("div", { class: "compare-num mono" }, [comtradeData.total_value_display || "—"]),
            el("div", { class: "compare-label" },
              ["National Export Baseline — " + (comtradeData.commodity || "") +
                " (" + comtradeData.reporter + ", " + comtradeData.year + ")"]),
          ]),
        ]));
      }
      if (finding) body.push(findingCallout(finding));
    } else {
      // zero records
      if (finding && finding.type === "opacity") {
        body.push(el("div", { class: "callout amber" }, [
          el("div", { class: "callout-title" }, ["No Documented Trade Activity"]),
          el("div", null, ["No shipment records were found in Sayari's global trade " +
            "database for this entity. For a registered trading or shipping company, " +
            "the absence of documented trade activity is atypical and may indicate " +
            "operations outside formal trade documentation systems. This pattern is " +
            "commonly associated with entities that facilitate transactions through " +
            "informal channels."]),
        ]));
      } else if (finding && (finding.type === "neutral" || finding.type === "services_no_trade")) {
        // Non-trading / software / services entity: absence of trade is expected.
        body.push(el("div", { class: "callout grey" }, [
          el("div", null, [finding.explanation ||
            "No trade records found in Sayari's global trade database."]),
        ]));
      } else {
        // No basis to render anything; skip the section entirely.
        return null;
      }
    }
    return sectionShell("Trade Intelligence", null, badges, body);
  }

  function findingCallout(f) {
    if (f.type === "anomaly")
      return el("div", { class: "callout red" }, [
        el("div", { class: "callout-title" }, ["Trade Anomaly Detected"]),
        el("div", null, [f.explanation]),
      ]);
    if (f.type === "consistent")
      return el("div", { class: "callout green" }, [
        el("div", { class: "callout-title" }, ["Consistent With Baseline"]),
        el("div", null, [f.explanation]),
      ]);
    return el("div", { class: "callout amber" }, [
      el("div", { class: "callout-title" }, [f.headline || "Trade Finding"]),
      el("div", null, [f.explanation || ""]),
    ]);
  }

  // ----- Section 5: Intelligence Brief -----
  function sectionBrief(d) {
    const b = d.brief || {};
    const rating = (d.risk_rating || "LOW").toLowerCase();

    const textEl = el("div", { class: "brief-text" }, [b.executive || ""]);
    const tabExec = el("button", { class: "brief-tab active" }, ["Executive View"]);
    const tabAnalyst = el("button", { class: "brief-tab" }, ["Analyst View"]);
    tabExec.addEventListener("click", function () {
      tabExec.classList.add("active"); tabAnalyst.classList.remove("active");
      textEl.textContent = b.executive || "";
    });
    tabAnalyst.addEventListener("click", function () {
      tabAnalyst.classList.add("active"); tabExec.classList.remove("active");
      textEl.textContent = b.analyst || "";
    });

    const head = el("div", { class: "section-head" }, [
      el("div", null, [el("span", { class: "section-title" }, ["Intelligence Brief"])]),
      el("div", { class: "source-badges" }, [
        el("span", { class: "rb-badge r-" + rating, style: "font-size:13px;padding:4px 12px" }, [d.risk_rating]),
        el("span", { class: "source-badge" }, ["Anthropic"]),
      ]),
    ]);

    const callouts = el("div", { class: "brief-callouts" }, [
      el("div", { class: "brief-callout finding" }, [
        el("div", { class: "brief-callout-label" }, ["Key Finding"]),
        el("div", { class: "brief-callout-body" }, [b.key_finding || d.key_finding || "—"]),
      ]),
      el("div", { class: "brief-callout action" }, [
        el("div", { class: "brief-callout-label" }, ["Recommended Action"]),
        el("div", { class: "brief-callout-body" }, [b.recommended_action || "—"]),
      ]),
    ]);

    const conf = (b.confidence || "medium").toLowerCase();
    const confExplain = {
      high: "Corroborated across multiple Sayari graph sources.",
      medium: "Supported by available risk indicators.",
      low: "Limited corroborating data available.",
    }[conf] || "";
    const srcNote = "Synthesis by Anthropic";

    const footer = el("div", { class: "brief-footer" }, [
      el("div", null, [
        el("span", { class: "conf-badge " + conf }, [conf.toUpperCase() + " CONFIDENCE"]),
        el("span", { style: "margin-left:10px" }, [confExplain]),
      ]),
      el("div", { style: "text-align:right" }, [
        el("div", { class: "brief-source-note" }, [srcNote]),
        el("div", null, ["Sources: Sayari · World Bank · UN Comtrade · Anthropic  ·  " +
          (d.analyzed_at || "")]),
      ]),
    ]);

    return el("section", { class: "section" }, [
      head,
      el("div", { class: "brief-toggle" }, [tabExec, tabAnalyst]),
      textEl, callouts, footer,
    ]);
  }

  // ---- slide-in entity panel -------------------------------------------
  function openEntityPanel(node) {
    const content = $("#panel-content");
    content.innerHTML = "";
    content.appendChild(el("div", { class: "panel-name" }, [node.label || "Entity"]));
    const rows = [
      ["Country", node.countries || "Unknown"],
      ["Incorporated", node.incorporation_display || "Not on record"],
      ["Network Size", (node.degree || 0).toLocaleString() + " connections"],
      ["Primary Risk", riskTypeLabel(node.primary_risk_type)],
      ["Sanctioned", node.sanctioned ? "Yes" : "No"],
    ];
    rows.forEach(function (r) {
      content.appendChild(el("div", { class: "panel-row" }, [
        el("span", { class: "k" }, [r[0]]), el("span", null, [r[1]]),
      ]));
    });
    // "Search this entity →" — pivots the dossier to this connected entity.
    const country = node.primary_country || (node.country_codes || [])[0] || "";
    content.appendChild(el("a", {
      href: "#", class: "popover-search-link",
      onclick: function (e) {
        e.preventDefault(); closePanel();
        window.triggerEntitySearch(node.label, country);
      },
    }, ["Search this entity →"]));
    $("#entity-panel").classList.add("open");
    $("#entity-panel").classList.remove("hidden");
    show($("#panel-scrim"));
  }

  window.triggerEntitySearch = function (entityName, country) {
    searchInput.value = entityName || "";
    if (country) {
      for (let i = 0; i < countrySelect.options.length; i++) {
        const opt = countrySelect.options[i];
        if (opt.value === country || opt.text.indexOf(country) >= 0) {
          countrySelect.value = opt.value; break;
        }
      }
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
    setTimeout(function () { runSearch(searchInput.value.trim(), countrySelect.value); }, 400);
  };
  function closePanel() {
    $("#entity-panel").classList.remove("open");
    setTimeout(function () { $("#entity-panel").classList.add("hidden"); }, 280);
    hide($("#panel-scrim"));
  }
  function riskTypeLabel(t) {
    return { sanctioned: "Directly Sanctioned", pep: "Politically Exposed Person",
      export_controls: "Export Controls" }[t] || "Connected Entity";
  }

  // ---- tooltip ----------------------------------------------------------
  function attachTooltip(node, title, sub) {
    node.addEventListener("mouseenter", function (e) {
      tooltip.innerHTML = "";
      tooltip.appendChild(el("div", { class: "tt-title" }, [title]));
      if (sub) tooltip.appendChild(el("div", { class: "tt-sub" }, [sub]));
      show(tooltip);
      moveTooltip(e);
    });
    node.addEventListener("mousemove", moveTooltip);
    node.addEventListener("mouseleave", function () { hide(tooltip); });
  }
  function moveTooltip(e) {
    const pad = 14;
    let x = e.clientX + pad, y = e.clientY + pad;
    const w = tooltip.offsetWidth, h = tooltip.offsetHeight;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - pad;
    tooltip.style.left = x + "px"; tooltip.style.top = y + "px";
  }
  // Expose for the timeline module.
  window.RiskApp = { attachTooltip: attachTooltip, showTooltipHTML: showTooltipHTML,
    hideTooltip: function () { hide(tooltip); }, moveTooltip: moveTooltip };
  function showTooltipHTML(html, e) { tooltip.innerHTML = html; show(tooltip); moveTooltip(e); }

  // ---- misc -------------------------------------------------------------
  function resetToSearch() {
    hide(dossier); show(searchView); searchView.classList.remove("compact");
    hide(disambig); hide(analyzingEl); prefetch = null;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function showError(msg) { searchError.textContent = msg; show(searchError); }
  function show(node) { node.classList.remove("hidden"); }
  function hide(node) { node.classList.add("hidden"); }
  function ordinal(n) {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }
})();
