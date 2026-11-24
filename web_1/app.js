(function () {
  var OUT_OF_SCOPE_STANDARD_MESSAGE = 'detected out of scope user question, try with relevant question or try with better prompt';
  'use strict';

  var PIPELINE_STEPS = [
    { id: 'security_sanitize', label: 'Security & Pre-Filter',   desc: 'Sanitize prompt and check prohibited DDL' },
    { id: 'fast_cache',        label: 'Fast Rewriter Cache',    desc: 'Check zero-LLM date shift cache' },
    { id: 'date_resolver',     label: 'Date Boundaries',        desc: 'Resolve relative date phrases to ISO dates' },
    { id: 'hybrid_rag',        label: 'Hybrid RAG Search',      desc: 'FAISS + BM25 schema retrieval' },
    { id: 'sql_generation',    label: 'Dialect SQL Synthesis',  desc: 'Synthesize SQL via Groq API' },
    { id: 'quality_gate',      label: 'AST & LLM Quality Gate', desc: 'Validate security and query semantics' },
    { id: 'db_execution',      label: 'DB Role Execution',      desc: 'Execute query on SQLite database' },
    { id: 'summarize',         label: 'Executive Summary',      desc: 'Synthesize plain English summary' },
    { id: 'done',              label: 'Complete',               desc: 'Final result ready' }
  ];

  var stepIndex = {};
  PIPELINE_STEPS.forEach(function (s, i) { stepIndex[s.id] = i + 1; });

  /** Per-chat pipeline run (supports background streaming when switching chats). */
  var runByChatId = {};
  function rs(chatId) {
    if (chatId == null || chatId === '') return null;
    var k = String(chatId);
    if (!runByChatId[k]) {
      runByChatId[k] = {
        isLoading: false,
        submittedQuery: '',
        currentStep: 0,
        stepStatus: {},
        result: null,
        thinkingExpanded: false,
        abortController: null
      };
    }
    return runByChatId[k];
  }
  function activeRs() {
    return state.activeChatId != null ? rs(state.activeChatId) : null;
  }
  function lastAssistantFromMessages() {
    var messages = state.chatMessages || [];
    for (var j = messages.length - 1; j >= 0; j--) {
      if (messages[j] && messages[j].role === 'assistant') return messages[j];
    }
    return null;
  }
  /** Result for pipeline subtitle / timeline: in-flight, or last assistant when idle. */
  function pipelineResultForUi() {
    var r = activeRs();
    if (!r) return null;
    if (r.result) return r.result;
    if (r.isLoading) return null;
    var a = lastAssistantFromMessages();
    if (!a) return null;
    return {
      sql: a.sql,
      sql_error: a.sql_error,
      clarification: a.clarification,
      sem: {}
    };
  }

  var elements = {};
  /** Only the latest loadChatMessages() result may apply (avoids stale GET overwriting a newer turn). */
  var loadMessagesGeneration = 0;

  var state = {
    chats: [],
    activeChatId: null,
    selectedStepId: null,
    chatMessages: [],
    sqlResultCache: {},
    sqlResultBySql: {},
    resultsMaximized: false,
    maximizedMessageId: null,
    createChatUnauthorized: false,
    isGuest: false
  };

  var sqlFetchInflight = {};
  var editTargetMessageId = null;

  function get(id) {
    if (!elements[id]) elements[id] = document.getElementById(id);
    return elements[id];
  }

  function apiFetch(url, opts) {
    var o = opts ? Object.assign({}, opts) : {};
    o.credentials = 'include';
    return fetch(url, o);
  }

  function loadChats() {
    apiFetch('/api/chats')
      .then(function (res) {
        return res.ok ? res.json() : Promise.reject(new Error(res.statusText));
      })
      .then(function (data) {
        var list = (data && data.chats) || [];
        state.chats = list;
        // Always start fresh — show welcome screen, no active chat.
        // Previous conversations are visible in the sidebar list.
        renderChatList();
        renderChatContent();
      })
      .catch(function () {
        renderChatList();
      });
  }

  function makeChatTitle(query) {
    var q = (query || '').trim();
    if (!q) return 'New chat';
    if (q.length <= 40) return q;
    return q.slice(0, 37) + '...';
  }

  function renderChatList() {
    var listEl = get('chat-list');
    if (!listEl) return;
    if (!state.chats.length) {
      listEl.innerHTML = '<p class="placeholder chat-empty-msg">No chats yet.</p>';
      return;
    }
    listEl.innerHTML = state.chats.map(function (chat) {
      var classes = 'chat-list-item';
      if (chat.id === state.activeChatId) classes += ' active';
      var cr = rs(chat.id);
      var loading = cr && cr.isLoading;
      var badge = chat.result && chat.result.sql ? '<span class="chat-list-item-badge">SQL</span>' : '';
      var spin = loading ? '<span class="chat-list-item-spinner" aria-hidden="true"></span>' : '';
      var title = escapeHtml(chat.title || 'Untitled');
      var chatId = escapeHtml(String(chat.id));
      return '<div class="' + classes + '" data-chat-id="' + chatId + '">' +
        spin +
        '<span class="chat-list-item-title">' + title + '</span>' +
        badge +
        '<button type="button" class="chat-item-btn chat-item-btn--delete" aria-label="Delete chat" data-chat-id="' + chatId + '" title="Delete">&#128465;</button>' +
      '</div>';
    }).join('');
  }

  function setActiveChat(chat) {
    if (typeof closeSchemaPage === 'function') closeSchemaPage();
    collapseResultsDock();
    state.sqlResultCache = {};
    state.sqlResultBySql = {};
    state.activeChatId = chat ? chat.id : null;
    state.chatMessages = [];
    state.selectedStepId = null;

    var topbarTitle = get('topbar-chat-title');
    var editTopbarBtn = get('btn-edit-topbar-title');
    if (chat && chat.id) {
      if (topbarTitle) topbarTitle.textContent = chat.title || 'New chat';
      if (editTopbarBtn) editTopbarBtn.hidden = false;
    } else {
      if (topbarTitle) topbarTitle.textContent = 'QueryNova AI';
      if (editTopbarBtn) editTopbarBtn.hidden = true;
    }

    if (chat) {
      get('query-input').value = '';
      var r = rs(chat.id);
      var pl = get('pipeline-placeholder');
      var tl = get('pipeline-timeline');
      if (pl && tl) {
        if (r.isLoading) {
          pl.hidden = true;
          tl.hidden = false;
        } else {
          pl.hidden = false;
          tl.hidden = true;
        }
      }
    } else {
      get('query-input').value = '';
      var pl0 = get('pipeline-placeholder');
      var tl0 = get('pipeline-timeline');
      if (pl0) pl0.hidden = false;
      if (tl0) tl0.hidden = true;
      clearQueryResultsDock();
    }
    renderChatContent();
    updatePipelineUI();
    syncAskStopButtons();
    renderChatList();
    if (chat && chat.id) loadChatMessages(chat.id);
  }

  function loadChatMessages(chatId) {
    if (!chatId) return;
    var gen = ++loadMessagesGeneration;
    return apiFetch('/api/chats/' + encodeURIComponent(chatId))
      .then(function (res) { return res.ok ? res.json() : Promise.reject(new Error(res.statusText)); })
      .then(function (data) {
        if (gen !== loadMessagesGeneration) return;
        state.chatMessages = (data && data.messages) ? data.messages : [];
        var r = rs(chatId);
        if (r && !r.isLoading) {
          r.result = null;
          var hasAssistant = false;
          (state.chatMessages || []).forEach(function (m) {
            if (m && m.role === 'assistant') hasAssistant = true;
          });
          if (hasAssistant) {
            PIPELINE_STEPS.forEach(function (s) {
              r.stepStatus[s.id] = 'done';
            });
            r.currentStep = PIPELINE_STEPS.length;
          }
        }
        renderChatContent();
        updatePipelineUI();
        syncAskStopButtons();
      })
      .catch(function () {
        if (gen !== loadMessagesGeneration) return;
        state.chatMessages = [];
        renderChatContent();
      });
  }

  function createNewChat(titleOrQuery) {
    var title = (titleOrQuery && String(titleOrQuery).trim()) ? String(titleOrQuery).trim() : 'New chat';
    if (title.length > 200) title = title.slice(0, 197) + '...';
    state.createChatUnauthorized = false;
    return apiFetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title || 'New chat' })
    })
      .then(function (res) {
        if (!res.ok) return res.text().then(function (t) { throw new Error(t || res.statusText); });
        return res.json();
      })
      .then(function (chat) {
        if (!chat) return null;
        state.chats.unshift(chat);
        setActiveChat(chat);
        return chat;
      })
      .catch(function () {
        return null;
      });
  }

  function updateChatResult(chatId, submittedQuery, result) {
    if (!chatId) return;
    var sq = submittedQuery || '';
    var i;
    for (i = 0; i < state.chats.length; i++) {
      if (String(state.chats[i].id) === String(chatId)) {
        state.chats[i] = {
          id: state.chats[i].id,
          title: state.chats[i].title || makeChatTitle(sq),
          query: sq,
          result: result
        };
        break;
      }
    }
    renderChatList();
  }

  function syncAskStopButtons() {
    var r = activeRs();
    var ask = get('btn-ask');
    var stop = get('btn-stop');
    var loading = !!(r && r.isLoading);
    if (ask) { ask.disabled = loading; ask.hidden = loading; }
    if (stop) stop.hidden = !loading;
  }

  function formatErrorMessage(msg) {
    if (!msg) return 'An error occurred.';
    var str = typeof msg === 'string' ? msg : String(msg);
    try {
      var parsed = JSON.parse(str);
      if (parsed.detail) return typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail);
      if (parsed.error) return typeof parsed.error === 'string' ? parsed.error : JSON.stringify(parsed.error);
      if (parsed.message) return typeof parsed.message === 'string' ? parsed.message : JSON.stringify(parsed.message);
    } catch (_) {}
    return str;
  }

  function showError(msg) {
    var el = get('error-banner');
    el.textContent = formatErrorMessage(msg);
    el.hidden = false;
  }

  function hideError() {
    get('error-banner').hidden = true;
  }

    function formatCellHtml(cell) {
    if (cell === null || cell === undefined) {
      return '<span class="null-val">NULL</span>';
    }
    if (typeof cell === 'boolean') {
      return '<span class="bool-val ' + (cell ? 'bool-true' : 'bool-false') + '">' + (cell ? 'TRUE' : 'FALSE') + '</span>';
    }
    var s = String(cell);
    if (s === '') {
      return '<span class="empty-str-val">(empty)</span>';
    }
    return escapeHtml(s);
  }

  function renderSqlResultsInto(rootEl, data, error) {
    if (!rootEl) return;
    var isInlineCard = !!rootEl.querySelector('.result-inline-card');
    var statusEl = rootEl.querySelector('.result-inline-status') || rootEl.querySelector('.results-status');
    var wrapper = rootEl.querySelector('.results-table-wrapper');
    var placeholderEl = rootEl.querySelector('.results-placeholder');
    if (!statusEl || !wrapper) return;

    if (!data && !error) {
      statusEl.textContent = 'Loading…';
      wrapper.innerHTML = '';
      if (wrapper.style) wrapper.style.display = 'none';
      return;
    }

    if (placeholderEl) placeholderEl.classList.add('hidden');

    if (error) {
      statusEl.textContent = 'Error: ' + error;
      wrapper.innerHTML = '';
      if (wrapper.style) wrapper.style.display = 'none';
      return;
    }

    if (!data.columns || !data.rows) {
      statusEl.textContent = 'No rows returned.';
      wrapper.innerHTML = '';
      if (wrapper.style) wrapper.style.display = 'none';
      return;
    }

    var cols = data.columns;
    var rows = data.rows;

    if (rows.length === 0) {
      var dialectNote = data.dialect ? ' on ' + escapeHtml(data.dialect) : '';
      statusEl.textContent = 'Query executed cleanly' + dialectNote + ' · 0 rows returned.';
      wrapper.innerHTML = '<div class="zero-results-card"><span class="zero-results-badge"><i class="fa-solid fa-circle-check"></i> Clean execution</span><span class="zero-results-text">No records matched your filter criteria. Zero rows returned is a valid SQL result, not an error.</span></div>';
      if (wrapper.style) wrapper.style.display = '';
      return;
    }

    var execInfo = '';
    if (data.execution_time_ms != null) execInfo += ' in ' + data.execution_time_ms + ' ms';
    if (data.dialect) execInfo += ' (' + escapeHtml(data.dialect) + ')';
    statusEl.textContent = 'Showing ' + rows.length + ' row(s)' + execInfo + '.';

    // For the inline card: show only top 10 rows in a mini preview table
    var displayRows = (isInlineCard && rows.length > 10) ? rows.slice(0, 10) : rows;
    var hasMore = isInlineCard && rows.length > 10;

    var thead = '<thead><tr><th class="row-num-col">#</th>' + cols.map(function (c) {
      return '<th>' + escapeHtml(String(c)) + '</th>';
    }).join('') + '</tr></thead>';
    var tbody = '<tbody>' + displayRows.map(function (row, idx) {
      var cells = Array.isArray(row) ? row : cols.map(function (c) { return row[c]; });
      return '<tr><td class="row-num-col">' + (idx + 1) + '</td>' + cells.map(function (cell) {
        return '<td>' + formatCellHtml(cell) + '</td>';
      }).join('') + '</tr>';
    }).join('') + '</tbody>';

    var moreHint = hasMore
      ? '<div class="mini-table-more">Showing 10 of ' + rows.length + ' rows — click VIEW for full table</div>'
      : '';

    wrapper.innerHTML = '<table class="mini-results-table">' + thead + tbody + '</table>' + moreHint;
    if (wrapper.style) wrapper.style.display = '';
  }

  /** Clears the expanded dock only (inline blocks use their own DOM). */
  function clearQueryResultsDock() {
    var dock = get('query-results-dock');
    if (dock) renderSqlResultsInto(dock, null, null);
  }

  function applySqlResultToMessage(messageId, entry) {
    var mid = String(messageId);
    state.sqlResultCache[mid] = entry;
    var el = document.querySelector('.result-inline-wrap[data-message-id="' + mid + '"]');
    if (el) renderSqlResultsInto(el, entry.data, entry.error);
    if (state.resultsMaximized && String(state.maximizedMessageId) === mid) {
      var dock = get('query-results-dock');
      if (dock) renderSqlResultsInto(dock, entry.data, entry.error);
    }
  }

  function executeSqlForMessage(messageId, sql, wrapEl) {
    var mid = String(messageId);
    if (!sql || !wrapEl) return;

    var cachedBySql = state.sqlResultBySql[sql];
    if (cachedBySql) {
      applySqlResultToMessage(mid, cachedBySql);
      return;
    }

    if (sqlFetchInflight[sql]) {
      sqlFetchInflight[sql].then(function () {
        var entry = state.sqlResultBySql[sql];
        if (entry) applySqlResultToMessage(mid, entry);
      });
      return;
    }

    renderSqlResultsInto(wrapEl, null, null);
    var statusEl = wrapEl.querySelector('.results-status');
    if (statusEl) {
      statusEl.textContent = 'Running query…';
      statusEl.hidden = false;
    }
    var placeholderEl = wrapEl.querySelector('.results-placeholder');
    if (placeholderEl) {
      placeholderEl.classList.remove('hidden');
      var ph = placeholderEl.querySelector('p');
      if (ph) ph.textContent = 'Loading results…';
    }
    var wrapper = wrapEl.querySelector('.results-table-wrapper');
    if (wrapper) wrapper.innerHTML = '';

    sqlFetchInflight[sql] = apiFetch('/api/execute-sql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql: sql, limit: 100 })
    })
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || res.statusText); });
        return res.json();
      })
      .then(function (data) {
        var entry = { data: data, error: null };
        state.sqlResultBySql[sql] = entry;
        applySqlResultToMessage(mid, entry);
      })
      .catch(function (err) {
        var msg = err.message || 'Execution failed';
        var entry = { data: null, error: msg };
        state.sqlResultBySql[sql] = entry;
        applySqlResultToMessage(mid, entry);
      })
      .then(function () {
        delete sqlFetchInflight[sql];
      });

    return sqlFetchInflight[sql];
  }

  function inlineResultsShell(messageId, sql) {
    var mid = messageId != null ? String(messageId) : 'live';
    return (
      '<div class="result-inline-wrap" data-message-id="' + escapeHtml(mid) + '" data-sql="' + escapeHtml(sql) + '">' +
      '<div class="result-inline-card" data-expand-for="' + escapeHtml(mid) + '" role="button" tabindex="0" title="Click to open table">' +
      '<div class="result-inline-card-icon">' +
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' +
      '</div>' +
      '<div class="result-inline-card-body">' +
      '<span class="result-inline-title">Query results</span>' +
      '<span class="results-status result-inline-status">Loading…</span>' +
      '</div>' +
      '<div class="btn-download-wrap" data-mid="' + escapeHtml(mid) + '">' +
      '<button type="button" class="btn-download-results" title="Download results">' +
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
      ' Download' +
      '</button>' +
      '<div class="download-dropdown" hidden>' +
      '<button type="button" class="download-option" data-format="csv" data-mid="' + escapeHtml(mid) + '">CSV</button>' +
      '<button type="button" class="download-option" data-format="xlsx" data-mid="' + escapeHtml(mid) + '">XLSX</button>' +
      '</div>' +
      '</div>' +
      '</div>' +
      '<div class="results-table-wrapper" style="display:none"></div>' +
      '<div class="results-placeholder" style="display:none"><p>Loading results…</p></div>' +
      '</div>'
    );
  }

  function hydrateInlineResults() {
    var wraps = document.querySelectorAll('.result-inline-wrap');
    wraps.forEach(function (wrap) {
      var mid = wrap.getAttribute('data-message-id');
      var sql = wrap.getAttribute('data-sql');
      if (!mid || !sql) return;
      var cached = state.sqlResultCache[mid];
      if (!cached && sql) cached = state.sqlResultBySql[sql];
      if (cached) {
        state.sqlResultCache[mid] = cached;
        renderSqlResultsInto(wrap, cached.data, cached.error);
        return;
      }
      executeSqlForMessage(mid, sql, wrap);
    });
  }

  function expandResultsDock(messageId) {
    var mid = String(messageId);
    state.maximizedMessageId = mid;
    state.resultsMaximized = true;

    // Get cached data
    var cached = state.sqlResultCache[mid];
    if (!cached) {
      var w = document.querySelector('.result-inline-wrap[data-message-id="' + mid + '"]');
      var sql = w && w.getAttribute('data-sql');
      if (sql) cached = state.sqlResultBySql[sql];
    }

    var overlay = get('spreadsheet-overlay');
    var tableWrap = get('spreadsheet-table-wrap');
    var subtitle = get('spreadsheet-subtitle');

    // Switch to split-screen layout
    var grid = get('main-grid');
    if (grid) {
      grid.classList.remove('grid--chat-only');
      grid.classList.add('grid--split-results');
    }

    if (!overlay || !tableWrap) return;

    // Build full spreadsheet table
    if (cached && cached.data && cached.data.columns && cached.data.rows) {
      var cols = cached.data.columns;
      var rows = cached.data.rows;
      if (subtitle) subtitle.textContent = rows.length + ' rows · CSV';
      var thead = '<thead><tr><th class="ss-row-num">#</th>' +
        cols.map(function (c) { return '<th>' + escapeHtml(String(c)) + '</th>'; }).join('') +
        '</tr></thead>';
      var tbody = '<tbody>' + rows.map(function (row, idx) {
        var cells = Array.isArray(row) ? row : cols.map(function (c) { return row[c]; });
        return '<tr><td class="ss-row-num">' + (idx + 1) + '</td>' +
          cells.map(function (cell) { return '<td>' + formatCellHtml(cell) + '</td>'; }).join('') +
          '</tr>';
      }).join('') + '</tbody>';
      tableWrap.innerHTML = '<table class="ss-table">' + thead + tbody + '</table>';
    } else if (cached && cached.error) {
      tableWrap.innerHTML = '<p class="ss-error">Error: ' + escapeHtml(cached.error) + '</p>';
      if (subtitle) subtitle.textContent = 'Error';
    } else {
      tableWrap.innerHTML = '<p class="ss-loading">Loading…</p>';
      if (subtitle) subtitle.textContent = 'CSV';
    }

    overlay.hidden = false;
    document.body.classList.add('spreadsheet-open');
  }

  function collapseResultsDock() {
    state.resultsMaximized = false;
    state.maximizedMessageId = null;

    var overlay = get('spreadsheet-overlay');
    if (overlay) overlay.hidden = true;
    document.body.classList.remove('spreadsheet-open');

    var grid = get('main-grid');
    var chatPanel = get('chat-panel-main');
    if (grid) { grid.classList.add('grid--chat-only'); grid.classList.remove('grid--split-results'); }
    if (chatPanel) chatPanel.classList.remove('chat-panel--minimized');

    // Also hide old dock if present
    var dock = get('query-results-dock');
    if (dock) dock.hidden = true;
    document.body.classList.remove('results-dock-open');
  }

  function getStepSummaryLine(stepId, result) {
    if (!result) return '';
    if (stepId === 'memory_load') return 'Loaded.';
    if (stepId === 'preflight') return 'OK.';
    if (stepId === 'scope_gate') {
      var sg = result.scope_gate;
      if (sg && sg.verdict) return String(sg.verdict).replace(/_/g, ' ') + '.';
      return 'Checked.';
    }
    if (stepId === 'planning' && result.sem) return 'Metric: ' + (result.sem.metric || '—');
    if (stepId === 'semantic' && result.sem) {
      var m = result.sem.metric || '';
      var flags = [];
      if (result.sem.has_date_filter) flags.push('date');
      if (result.sem.has_condition_filter) flags.push('condition');
      if (result.sem.has_department_filter) flags.push('department');
      return (m ? m + '; ' : '') + (flags.length ? 'Flags: ' + flags.join(', ') : 'Extracted.');
    }
    if (stepId === 'date_and_entities') {
      var parts = [];
      var sem = result.sem || {};
      if (sem.start_date && sem.end_date) parts.push(sem.start_date + ' → ' + sem.end_date);
      if (result.entities && result.entities.length) parts.push('Entities: ' + result.entities.join(', '));
      return parts.length ? parts.join(' · ') : 'Mapped.';
    }
    if (stepId === 'guardrails') {
      var n = (result.requested_cols && result.requested_cols.length) || 0;
      return n ? n + ' column(s) selected' : 'Applied.';
    }
    if (stepId === 'schema_validation') return 'Valid.';
    if (stepId === 'sql_generation') {
      if (result.sql_error && !result.sql) return 'Error: ' + (result.sql_error.slice(0, 50) + (result.sql_error.length > 50 ? '…' : ''));
      if (result.sql) return 'SQL generated.';
      return '—';
    }
    if (stepId === 'done') {
      if (result.clarification) return 'Clarification asked.';
      if (result.sql && !result.sql_error) return '✓ Ready.';
      if (result.sql_error) return 'Failed.';
      return 'Done.';
    }
    return '';
  }

  function renderPipelineSteps(activeStep, result) {
    var timelineEl = get('pipeline-timeline');
    if (!timelineEl) return;
    var r = activeRs();
    var stepStatus = (r && r.stepStatus) || {};
    var currentStep = (r && r.currentStep) || 0;
    var loading = r && r.isLoading;

    var html = PIPELINE_STEPS.map(function (step, i) {
      var sid = step.id;
      var status = stepStatus[sid] || 'pending';
      if (currentStep > i && !stepStatus[sid]) status = 'done';

      var outcome = '';
      if (status === 'active' && loading) {
        outcome = 'Running…';
      } else if (status === 'done' || status === 'error') {
        outcome = getStepSummaryLine(sid, result) || (status === 'error' ? 'Error' : 'Done');
      } else {
        outcome = step.desc || '';
      }

      var iconHtml = '';
      if (status === 'pending') {
        iconHtml = '<span class="timeline-icon timeline-icon--pending">' + (i + 1) + '</span>';
      } else if (status === 'active') {
        iconHtml = '<span class="timeline-icon timeline-icon--active"><span class="spinner"></span></span>';
      } else if (status === 'error') {
        iconHtml = '<span class="timeline-icon timeline-icon--error">✕</span>';
      } else {
        iconHtml = '<span class="timeline-icon timeline-icon--done">✓</span>';
      }

      var rowClass = 'timeline-row timeline-row--' + status;
      return '<div class="' + rowClass + '">' + iconHtml +
        '<div class="timeline-body">' +
        '<span class="timeline-label">' + (i + 1) + '. ' + escapeHtml(step.label) + '</span>' +
        (outcome ? '<span class="timeline-outcome">' + escapeHtml(outcome) + '</span>' : '') +
        '</div></div>';
    }).join('');
    timelineEl.innerHTML = html;
  }

  function escapeHtml(s) {
    if (s == null) return '';
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  /** Project avatar icon for assistant replies. */
  function assistantAvatarHtml() {
    return (
      '<div class="assistant-avatar" style="width:24px;height:24px;border-radius:6px;overflow:hidden;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;">' +
      '<img src="qnsql.webp" alt="QueryNova" style="width:100%;height:100%;object-fit:cover;" />' +
      '</div>'
    );
  }

  function wrapAssistantTurn(innerHtml) {
    if (!innerHtml) return '';
    return (
      '<div class="assistant-turn">' +
      '<div class="assistant-turn-header" style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">' +
      assistantAvatarHtml() +
      '<span class="assistant-label" style="font-weight:600;font-size:14px;color:var(--text-primary);">QueryNova AI</span>' +
      '</div>' +
      '<div class="assistant-msg">' + innerHtml + '</div></div>'
    );
  }

  function renderMarkdown(text) {
    if (!text || !String(text).trim()) return '';
    var s = String(text).trim();

    // 1. Escape HTML to prevent XSS
    s = escapeHtml(s);

    // 2. Fenced code blocks ```sql ... ``` or ``` ... ```
    s = s.replace(/```(?:sql)?\s*([\s\S]*?)\s*```/gi, function (_, codeBlock) {
      return '<div class="md-code-block-wrap"><pre class="md-code-block"><code class="language-sql">' + codeBlock.trim() + '</code></pre></div>';
    });

    // 3. Blockquotes: &gt; line or > line
    s = s.replace(/^&gt;\s*(.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');
    s = s.replace(/^>\s*(.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');

    // 4. Headings: ### Heading or ## Heading
    s = s.replace(/^###\s*(.+)$/gm, '<h4 class="md-heading">$1</h4>');
    s = s.replace(/^##\s*(.+)$/gm, '<h3 class="md-heading">$1</h3>');

    // 5. Bold: **text**
    s = s.replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>');

    // 6. Italic: *text*
    s = s.replace(/(^|[^\*])\*([^\*]+)\*([^\*]|$)/g, '$1<em>$2</em>$3');

    // 7. Inline code: `code`
    s = s.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>');

    // 8. Unordered lists: - item or * item
    s = s.replace(/(?:^[*-]\s+.+(?:\r?\n|$))+/gm, function (listBlock) {
      var items = listBlock.trim().split(/\r?\n/).map(function (line) {
        return '<li>' + line.replace(/^[*-]\s+/, '') + '</li>';
      }).join('');
      return '<ul class="md-list">' + items + '</ul>';
    });

    // 9. Paragraphs separated by blank lines
    var paragraphs = s.split(/\n\s*\n/);
    return paragraphs.map(function (p) {
      p = p.trim();
      if (!p) return '';
      if (/^<(h[1-6]|ul|ol|div|blockquote|pre)/i.test(p)) return p;
      return '<p class="md-p">' + p.replace(/\n/g, '<br>') + '</p>';
    }).join('');
  }

  function diagnosticCardHtml(m) {
    if (!m) return '';
    var status = m.status || (m.is_valid ? 'valid' : (m.corrected_sql ? 'corrected' : 'error'));
    var isCorrected = status === 'corrected' || (m.original_sql && m.corrected_sql && m.original_sql !== m.corrected_sql);
    var isClarification = status === 'clarification' || !!m.clarification;
    var isSecurity = status === 'security_rejected';
    var isValid = status === 'valid';

    var html = '<div class="diagnostic-card">';

    // 1. Header Banner
    if (isCorrected) {
      var catBadge = m.error_category
        ? '<span class="diag-badge-category">' + escapeHtml(m.error_category.replace(/_/g, ' ').toUpperCase()) + '</span>'
        : '';
      html += '<div class="diag-banner diag-banner--corrected">' +
        '<div class="diag-banner-left">' +
        '<span class="diag-badge diag-badge--corrected"><i class="fa-solid fa-bolt"></i> SQL Correction Applied</span>' +
        catBadge +
        '</div>' +
        '<span class="diag-guard-tag">Semantic Guard: ' + escapeHtml((m.semantic_guard || 'safe_mechanical').replace(/_/g, ' ')) + '</span>' +
        '</div>';
    } else if (isSecurity) {
      var secBadge = m.error_category
        ? '<span class="diag-badge-category">' + escapeHtml(m.error_category.replace(/_/g, ' ').toUpperCase()) + '</span>'
        : '';
      html += '<div class="diag-banner diag-banner--security">' +
        '<div class="diag-banner-left">' +
        '<span class="diag-badge diag-badge--security"><i class="fa-solid fa-shield-halved"></i> Security Guard Blocked</span>' +
        secBadge +
        '</div>' +
        '<span class="diag-guard-tag">Read-Only Sandbox</span>' +
        '</div>';
    } else if (isValid) {
      html += '<div class="diag-banner diag-banner--valid">' +
        '<span class="diag-badge diag-badge--valid"><i class="fa-solid fa-circle-check"></i> Valid SQL Query</span>' +
        '<span class="diag-guard-tag">Executed Cleanly</span>' +
        '</div>';
    } else if (isClarification) {
      html += '<div class="diag-banner diag-banner--clarification">' +
        '<span class="diag-badge diag-badge--clarification"><i class="fa-solid fa-circle-info"></i> Clarification Required</span>' +
        '<span class="diag-guard-tag">Incomplete Query</span>' +
        '</div>';
    }

    // 2. Before / After Visual Diff for Corrected Queries
    if ((isCorrected || (isSecurity && m.corrected_sql)) && m.original_sql && m.corrected_sql) {
      html += '<div class="diag-diff-grid">' +
        '<div class="diag-diff-panel diff-panel--orig">' +
        '<div class="diff-header"><span class="diff-chip chip--del"><i class="fa-solid fa-circle-xmark"></i> Original Query</span></div>' +
        '<pre class="diff-code-text"><code>' + escapeHtml(m.original_sql) + '</code></pre>' +
        '</div>' +
        '<div class="diag-diff-panel diff-panel--corr">' +
        '<div class="diff-header"><span class="diff-chip chip--ins"><i class="fa-solid fa-circle-check"></i> Corrected Query</span></div>' +
        '<pre class="diff-code-text"><code>' + escapeHtml(m.corrected_sql) + '</code></pre>' +
        '</div>' +
        '</div>';

      if (m.diff && m.diff.changes && m.diff.changes.length > 0) {
        var diffChips = m.diff.changes.map(function(ch) {
          if (ch.tag === 'replace') {
            return '<span class="diff-delta-chip"><del class="diff-del">' + escapeHtml(ch.from) + '</del> <i class="fa-solid fa-arrow-right"></i> <ins class="diff-ins">' + escapeHtml(ch.to) + '</ins></span>';
          } else if (ch.tag === 'delete') {
            return '<span class="diff-delta-chip"><del class="diff-del">' + escapeHtml(ch.from) + '</del></span>';
          } else if (ch.tag === 'insert') {
            return '<span class="diff-delta-chip"><ins class="diff-ins">' + escapeHtml(ch.to) + '</ins></span>';
          }
          return '';
        }).filter(Boolean).join(' ');
        if (diffChips) {
          html += '<div class="diag-changes-row"><span class="diff-summary-label">Key Changes:</span> ' + diffChips + '</div>';
        }
      }
    }

    // 3. Error Callout
    if (m.error_identified && !isValid) {
      html += '<div class="diag-callout diag-callout--error">' +
        '<div class="diag-callout-title"><i class="fa-solid fa-triangle-exclamation"></i> Issue Diagnosed</div>' +
        '<div class="diag-callout-text">' + renderMarkdown(m.error_identified) + '</div>' +
        '</div>';
    }

    // 4. Learning Rule Box
    if (m.learning_tip && String(m.learning_tip).trim()) {
      html += '<div class="diag-callout diag-callout--tip">' +
        '<div class="diag-callout-title"><i class="fa-solid fa-lightbulb"></i> PostgreSQL Learning Concept</div>' +
        '<div class="diag-callout-text">' + renderMarkdown(m.learning_tip) + '</div>' +
        '</div>';
    } else if (m.explanation && !m.error_identified) {
      html += '<div class="diag-callout diag-callout--info">' +
        '<div class="diag-callout-text">' + renderMarkdown(m.explanation) + '</div>' +
        '</div>';
    }

    // 5. Interactive Clause Breakdown Accordion
    if (m.clause_breakdown && typeof m.clause_breakdown === 'object' && Object.keys(m.clause_breakdown).length > 0) {
      html += '<details class="clause-breakdown-details">' +
        '<summary class="clause-breakdown-summary"><i class="fa-solid fa-layer-group"></i> Clause-by-Clause Explanation <span class="clause-hint">(Click to expand)</span></summary>' +
        '<div class="clause-breakdown-list">';
      Object.keys(m.clause_breakdown).forEach(function(clauseKey) {
        html += '<div class="clause-row">' +
          '<span class="clause-badge">' + escapeHtml(clauseKey) + '</span>' +
          '<span class="clause-explanation">' + escapeHtml(m.clause_breakdown[clauseKey]) + '</span>' +
          '</div>';
      });
      html += '</div></details>';
    }

    html += '</div>';
    return html;
  }

  function summaryBlockHtml(summaryText, title) {
    if (!summaryText || !String(summaryText).trim()) return '';
    var headerTitle = title || 'Query Insights Summary';
    return (
      '<div class="summary-box-card">' +
      '<div class="summary-box-header">' +
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>' +
      ' ' + escapeHtml(headerTitle) + '</div>' +
      '<div class="summary-box-body">' + renderMarkdown(summaryText) + '</div>' +
      '</div>'
    );
  }

  function sqlBlockHtml(sql, dialect) {
    var langLabel = dialect ? escapeHtml(dialect) : 'PostgreSQL / SQL';
    return (
      '<div class="sql-block-wrap">' +
      '<div class="sql-block-header">' +
      '<span class="sql-block-lang"><span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:#ff6b00; margin-right:6px;"></span>' + langLabel + '</span>' +
      '<div style="display:flex; gap:6px;">' +
      '<button type="button" class="btn-apply-editor" data-sql="' + escapeHtml(sql) + '" aria-label="Apply SQL to editor" style="background:rgba(255,107,0,0.15); color:#ff6b00; border:1px solid rgba(255,107,0,0.3); padding:2px 8px; border-radius:4px; font-size:12px; cursor:pointer;">Apply to Editor</button>' +
      '<button type="button" class="btn-copy-sql" aria-label="Copy SQL to clipboard">Copy</button>' +
      '</div>' +
      '</div>' +
      '<pre class="sql">' + escapeHtml(sql) + '</pre>' +
      '</div>'
    );
  }

  function updatePipelineUI() {
    var subtitleEl = get('pipeline-subtitle');
    if (!subtitleEl) return;
    var r = activeRs();
    var pr = pipelineResultForUi();
    var activeStep = r && r.isLoading ? Math.min(r.currentStep + 1, PIPELINE_STEPS.length) : (r ? r.currentStep : 0);
    if (r && r.isLoading) {
      var activeId = null;
      var stepStatus = r.stepStatus || {};
      for (var k = 0; k < PIPELINE_STEPS.length; k++) {
        if (stepStatus[PIPELINE_STEPS[k].id] === 'active') {
          activeId = PIPELINE_STEPS[k].label;
          break;
        }
      }
      subtitleEl.textContent = activeId ? 'Running: ' + activeId + '…' : 'Running…';
    } else {
      subtitleEl.textContent = pr ? 'How this answer was built' : 'Real-time execution';
    }
    var timelineEl = get('pipeline-timeline');
    if (timelineEl) renderPipelineSteps(activeStep, pr);
  }

  var OPTION_LABELS = { start_time: 'Start time', end_time: 'End time' };

  function renderChatContent() {
    var content = get('chat-content');
    var messages = state.chatMessages || [];
    var ar = activeRs();
    var submittedQ = (ar && ar.submittedQuery) ? String(ar.submittedQuery).trim() : '';

    // If there's no chat history and no active submission, show welcome screen.
    var welcome = document.getElementById('chat-welcome');
    if (!messages.length && !submittedQ) {
      if (welcome) welcome.style.display = '';
      content.hidden = true;
      content.innerHTML = '';
      return;
    }
    if (welcome) welcome.style.display = 'none';
    content.hidden = false;
    var html = '';

    var lastUserMsgId = null;
    var u;
    for (u = messages.length - 1; u >= 0; u--) {
      if (messages[u] && messages[u].role === 'user') {
        lastUserMsgId = messages[u].id;
        break;
      }
    }

    // Render persisted message history.
    messages.forEach(function (m) {
      if (!m) return;
      if (m.role === 'user') {
        var isLastUser = m.id != null && lastUserMsgId != null && String(m.id) === String(lastUserMsgId);
        var showActions = isLastUser && !(ar && ar.isLoading);
        var actionsHtml = showActions
          ? '<div class="user-msg-actions">' +
            '<button type="button" class="msg-action-btn msg-action-copy" data-msg-id="' + escapeHtml(String(m.id)) + '" title="Copy message"><i class="fa-regular fa-copy"></i></button>' +
            '<button type="button" class="msg-action-btn msg-action-edit" data-msg-id="' + escapeHtml(String(m.id)) + '" title="Edit message"><i class="fa-solid fa-pen"></i></button>' +
            '</div>'
          : '';
        html += '<div class="user-msg"><div class="user-msg-wrap" data-edit-id="' + escapeHtml(String(m.id)) + '"><span class="user-msg-bubble" data-msg-id="' + escapeHtml(String(m.id)) + '">' + escapeHtml(m.content || '') + '</span>' + actionsHtml + '</div></div>';
      } else if (m.role === 'assistant') {
        var ab = '';
        var isDiagnostic = m.status === 'corrected' || (m.original_sql && m.corrected_sql) || (m.error_category != null);

        if (m.clarification) {
          if (m.original_sql) {
            ab += diagnosticCardHtml(m);
          } else {
            ab += '<div class="result-block clarification"><p><strong>Clarification needed:</strong></p>' + renderMarkdown(m.clarification) + '</div>';
          }
        } else if (isDiagnostic) {
          ab += diagnosticCardHtml(m);
          var activeSql = m.sql || m.corrected_sql;
          if (activeSql) {
            ab += sqlBlockHtml(activeSql, m.dialect);
            ab += inlineResultsShell(m.id, activeSql);
          }
        } else if (m.sql_error && !m.sql) {
          var isJudgeRejection = (m.sql_error || '').toLowerCase().indexOf('judge rejected') !== -1;
          var isOutOfScope = String(m.sql_error || '').trim() === OUT_OF_SCOPE_STANDARD_MESSAGE;
          if (isJudgeRejection) {
            ab += '<div class="result-block error result-judge">';
            ab += '<p><strong>Data not found.</strong> Could not generate a valid answer for this question.</p>';
            ab += '<button type="button" class="btn btn-try-again">Try again</button>';
            ab += '</div>';
          } else if (isOutOfScope) {
            ab += '<div class="result-block clarification">';
            ab += '<p><strong>Out of scope:</strong></p><p>' + renderMarkdown(m.sql_error) + '</p>';
            ab += '</div>';
          } else {
            if (m.content || m.summary) ab += summaryBlockHtml(m.content || m.summary, 'Execution Error');
            ab += '<div class="result-block error">' + renderMarkdown(m.sql_error) + '</div>';
          }
        } else if (m.sql) {
          if (m.clause_breakdown) {
            ab += diagnosticCardHtml(m);
          } else if (m.content || m.summary) {
            ab += summaryBlockHtml(m.content || m.summary, 'Query Insights Summary');
          }
          ab += sqlBlockHtml(m.sql, m.dialect);
          if (m.sql_error && (!m.content || m.content.indexOf(m.sql_error) === -1)) ab += '<p class="result-block error">Note: ' + renderMarkdown(m.sql_error) + '</p>';
          ab += inlineResultsShell(m.id, m.sql);
        } else if (m.content || m.summary) {
          ab += summaryBlockHtml(m.content || m.summary, 'Assistant Response');
        } else {
          ab += '<div class="result-block">Pipeline completed. No SQL or clarification returned.</div>';
        }
        html += wrapAssistantTurn(ab);
      }
    });

    // Determine whether to render the current submission (if it isn't already the latest user message).
    var lastUserContent = null;
    for (var i = messages.length - 1; i >= 0; i--) {
      if (messages[i] && messages[i].role === 'user') {
        lastUserContent = messages[i].content || '';
        break;
      }
    }
    var shouldRenderCurrentUser = submittedQ && (lastUserContent !== submittedQ);

    if (shouldRenderCurrentUser) {
      html += '<div class="user-msg"><span class="user-msg-bubble">' + escapeHtml(submittedQ) + '</span></div>';
    }

    if (ar && ar.isLoading && !ar.result) {
      var expanded = ar.thinkingExpanded;
      var arrow = expanded ? '▲' : '▼';
      var stMap = ar.stepStatus || {};
      var thinkInner = '';

      thinkInner += '<div class="result-block thinking-block">';
      thinkInner += '<div class="thinking-header" data-action="toggle-thinking" role="button" tabindex="0" aria-expanded="' + expanded + '">';
      thinkInner += '<span class="loading-inline"></span> Thinking <span class="thinking-arrow">' + arrow + '</span>';
      thinkInner += '</div>';

      if (expanded) {
        thinkInner += '<div class="thinking-steps">';
        PIPELINE_STEPS.forEach(function (step, i) {
          var sid = step.id;
          var status = stMap[sid] || 'pending';
          if (ar.currentStep > i && !stMap[sid]) status = 'done';

          // Only render steps that have been reached (active, done, error)
          // Pending steps beyond current are not shown yet
          if (status === 'pending' && ar.currentStep <= i) return;

          var statusClass = 'thinking-step--' + status;
          var prefix = (status === 'done')
            ? '<span class="thinking-step-tick">✓</span>'
            : '<span class="thinking-step-num">' + (i + 1) + '.</span>';
          var label = step.label;
          var outcome = '';
          if (status === 'active') {
            outcome = '<span class="thinking-step-dots"><span></span><span></span><span></span></span>';
          } else if (status === 'done' || status === 'error') {
            var txt = getStepSummaryLine(sid, ar.result || {}) || (status === 'error' ? 'Error' : 'Done');
            outcome = '<span class="thinking-step-outcome">' + escapeHtml(txt) + '</span>';
          }

          thinkInner += '<div class="thinking-step ' + statusClass + ' thinking-step--reveal">' +
            prefix +
            '<span class="thinking-step-label">' + escapeHtml(label) + '</span>' +
            outcome +
            '</div>';
        });
        thinkInner += '</div>';
      }

      thinkInner += '</div>';
      html += wrapAssistantTurn(thinkInner);
    } else if (ar && ar.result) {
      // If the last assistant message already matches current result, don't duplicate it.
      var lastAssistant = null;
      for (var j = messages.length - 1; j >= 0; j--) {
        if (messages[j] && messages[j].role === 'assistant') { lastAssistant = messages[j]; break; }
      }
      var alreadyHasThisAssistant =
        lastAssistant &&
        String(lastAssistant.sql || '') === String(ar.result.sql || '') &&
        String(lastAssistant.sql_error || '') === String(ar.result.sql_error || '') &&
        String(lastAssistant.clarification || '') === String(ar.result.clarification || '');

      if (!alreadyHasThisAssistant) {
        var r = ar.result;
        var liveBody = '';
        var isDiagLive = r.status === 'corrected' || (r.original_sql && r.corrected_sql) || (r.error_category != null);

        if (r.clarification) {
          if (r.original_sql) {
            liveBody += diagnosticCardHtml(r);
          } else {
            liveBody += '<div class="result-block clarification"><p><strong>Clarification needed:</strong></p>' + renderMarkdown(r.clarification) + '</div>';
          }
        } else if (isDiagLive) {
          liveBody += diagnosticCardHtml(r);
          var liveSqlToRun = r.sql || r.corrected_sql;
          if (liveSqlToRun) {
            liveBody += sqlBlockHtml(liveSqlToRun, r.dialect);
            liveBody += inlineResultsShell('live', liveSqlToRun);
          }
        } else if (r.sql_error && !r.sql) {
          var isJudgeRejection2 = (r.sql_error || '').toLowerCase().indexOf('judge rejected') !== -1;
          var isOutOfScope2 = String(r.sql_error || '').trim() === OUT_OF_SCOPE_STANDARD_MESSAGE;
          if (isJudgeRejection2) {
            liveBody += '<div class="result-block error result-judge">';
            liveBody += '<p><strong>Data not found.</strong> Could not generate a valid answer for this question.</p>';
            liveBody += '<button type="button" class="btn btn-try-again">Try again</button>';
            liveBody += '</div>';
          } else if (isOutOfScope2) {
            liveBody += '<div class="result-block clarification">';
            liveBody += '<p><strong>Out of scope:</strong></p><p>' + renderMarkdown(r.sql_error) + '</p>';
            liveBody += '</div>';
          } else {
            liveBody += '<div class="result-block error">' + renderMarkdown(r.sql_error) + '</div>';
          }
        } else if (r.sql) {
          if (r.clause_breakdown) {
            liveBody += diagnosticCardHtml(r);
          } else {
            var liveSummary = r.summary || r.content;
            if (liveSummary) liveBody += summaryBlockHtml(liveSummary, 'Query Insights Summary');
          }
          liveBody += sqlBlockHtml(r.sql, r.dialect);
          if (r.sql_error) liveBody += '<p class="result-block error">Note: ' + renderMarkdown(r.sql_error) + '</p>';
          liveBody += inlineResultsShell('live', r.sql);
        } else if (r.summary || r.content) {
          liveBody += summaryBlockHtml(r.summary || r.content, 'Assistant Response');
        } else if (!r.sql && !r.clarification && !r.sql_error) {
          liveBody += '<div class="result-block">Pipeline completed. No SQL or clarification returned.</div>';
        }
        html += wrapAssistantTurn(liveBody);
      }
    }

    content.innerHTML = html;
    hydrateInlineResults();
    syncAskStopButtons();
    if (html.indexOf('class="placeholder"') === -1) {
      content.classList.remove('chat-content--animating');
      void content.offsetWidth;
      content.classList.add('chat-content--animating');
      window.clearTimeout(content._animTimer);
      content._animTimer = window.setTimeout(function () {
        content.classList.remove('chat-content--animating');
      }, 480);
    }
    // Keep UI at the newest message.
    content.scrollTop = content.scrollHeight;
  }

  function runQuery(query, chosenOption) {
    var q = (query || '').trim();
    if (!q) return;

    if (typeof closeSchemaPage === 'function') closeSchemaPage();

    var ensureChat;
    if (!state.activeChatId) {
      ensureChat = createNewChat(q);
    } else {
      ensureChat = Promise.resolve(
        state.chats.find(function (c) {
          return String(c.id) === String(state.activeChatId);
        }) || null
      );
    }

    ensureChat.then(function (chat) {
      if (!chat && !state.activeChatId) {
        showError('Could not create chat. Check that the server is running and try again.');
        return;
      }

      // Clear the type bar once the question is accepted; it already appears in the chat thread.
      var inputEl = get('query-input');
      if (inputEl) inputEl.value = '';

      var chatId = (chat && chat.id) || state.activeChatId;
      if (!chatId || String(chatId) === 'undefined' || String(chatId) === 'null' || String(chatId) === 'NaN') {
        showError('No active conversation. Please click "+ New conversation" to start a new chat.');
        return;
      }

      var r = rs(chatId);
      if (r.abortController) {
        try {
          r.abortController.abort();
        } catch (abortErr) {}
      }
      r.abortController = new AbortController();
      var thisQuerySignal = r.abortController.signal;

      r.submittedQuery = q;
      r.currentStep = 0;
      r.result = null;
      r.stepStatus = {};
      r.thinkingExpanded = false;
      r.isLoading = true;
      state.selectedStepId = null;
      hideError();
      collapseResultsDock();

      var pl = get('pipeline-placeholder');
      var tl = get('pipeline-timeline');
      if (pl) pl.hidden = true;
      if (tl) tl.hidden = false;
      syncAskStopButtons();
      updatePipelineUI();
      renderChatContent();
      clearQueryResultsDock();

      var body = { query: q, stream: true };
      if (chosenOption) body.chosen_option = chosenOption;

      var streamChatId = String(chatId);

      apiFetch('/api/chats/' + encodeURIComponent(chatId) + '/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: thisQuerySignal
      })
        .then(function (res) {
          if (!res.ok) return res.text().then(function (t) { throw new Error(t || res.statusText); });
          return res.body.getReader();
        })
        .then(function (reader) {
          var decoder = new TextDecoder();
          var buffer = '';

          function processPayload(textBlock) {
            if (!textBlock) return;
            var lines = textBlock.split('\n');
            lines.forEach(function (line) {
              var trimmed = line.trim();
              if (trimmed.indexOf('data: ') !== 0) return;
              try {
                var data = JSON.parse(trimmed.slice(6));
                var rx = rs(streamChatId);
                if (!rx) return;
                if (data.type === 'progress' && data.step_id) {
                  var sid = data.step_id;
                  var st = data.status;
                  if (st === 'start') rx.stepStatus[sid] = 'active';
                  else if (st === 'done') {
                    rx.stepStatus[sid] = 'done';
                    var stepNum = stepIndex[sid];
                    if (stepNum) rx.currentStep = stepNum;
                  } else if (st === 'error') {
                    rx.stepStatus[sid] = 'error';
                  }
                  if (String(state.activeChatId) === streamChatId) updatePipelineUI();
                  renderChatList();
                } else if (data.type === 'result' && data.result) {
                  var resObj = data.result;
                  rx.result = resObj;
                  var activeResultSql = resObj.sql || resObj.corrected_sql;
                  if (activeResultSql && resObj.columns && resObj.rows) {
                    state.sqlResultBySql[activeResultSql] = { data: resObj, error: null };
                  }
                  updateChatResult(streamChatId, rx.submittedQuery, resObj);
                  rx.currentStep = PIPELINE_STEPS.length;
                  rx.stepStatus.done = 'done';
                  rx.isLoading = false;
                  rx.abortController = null;
                  if (String(state.activeChatId) === streamChatId) {
                    updatePipelineUI();
                    renderChatContent();
                    syncAskStopButtons();
                  }
                  loadChatMessages(streamChatId);
                  renderChatList();
                } else if (data.type === 'error') {
                  rx.isLoading = false;
                  rx.abortController = null;
                  if (String(state.activeChatId) === streamChatId) {
                    showError(data.error || 'Unknown error');
                    renderChatContent();
                    syncAskStopButtons();
                  }
                  loadChatMessages(streamChatId);
                  renderChatList();
                }
              } catch (_) {}
            });
          }

          function read() {
            return reader.read().then(function (chunk) {
              if (chunk.done) {
                if (buffer && buffer.trim()) {
                  processPayload(buffer);
                  buffer = '';
                }
                var rx = rs(streamChatId);
                if (rx) {
                  rx.isLoading = false;
                  rx.abortController = null;
                }
                if (String(state.activeChatId) === streamChatId) {
                  updatePipelineUI();
                  syncAskStopButtons();
                  renderChatContent();
                }
                loadChatMessages(streamChatId);
                renderChatList();
                return;
              }
              if (thisQuerySignal.aborted) return;
              buffer += decoder.decode(chunk.value, { stream: true });
              var lines = buffer.split('\n');
              buffer = lines.pop() || '';
              processPayload(lines.join('\n'));
              return read();
            });
          }
          return read();
        })
        .catch(function (err) {
          var rx = rs(streamChatId);
          if (err && err.name === 'AbortError') {
            if (rx && rx.abortController && thisQuerySignal !== rx.abortController) {
              return;
            }
            if (rx) {
              rx.isLoading = false;
              rx.abortController = null;
            }
            renderChatList();
            if (String(state.activeChatId) === streamChatId) {
              syncAskStopButtons();
              renderChatContent();
              updatePipelineUI();
              loadChatMessages(streamChatId);
            }
            return;
          }
          if (rx) {
            rx.isLoading = false;
            rx.abortController = null;
          }
          if (String(state.activeChatId) === streamChatId) {
            if (!rx || !rx.result) {
              showError(err.message || 'Request failed');
            }
            renderChatContent();
            updatePipelineUI();
            syncAskStopButtons();
          }
          renderChatList();
        });
    });
  }

  /* ── Copy toast ─────────────────────────────────────── */
  var _toastTimer = null;
  function showCopyToast() {
    var toast = document.getElementById('copy-toast');
    if (!toast) return;
    toast.classList.add('copy-toast--visible');
    if (_toastTimer) window.clearTimeout(_toastTimer);
    _toastTimer = window.setTimeout(function () {
      toast.classList.remove('copy-toast--visible');
    }, 1800);
  }

  /* ── Inline edit ─────────────────────────────────────── */
  var _inlineEditMsgId = null;

  function enterInlineEdit(msgId) {
    // Cancel any existing inline edit first
    if (_inlineEditMsgId) cancelInlineEdit();

    var m = null;
    (state.chatMessages || []).forEach(function (x) {
      if (x && String(x.id) === String(msgId)) m = x;
    });
    if (!m) return;

    _inlineEditMsgId = String(msgId);

    // Find the user-msg-wrap for this message
    var wrap = document.querySelector('.user-msg-wrap[data-edit-id="' + _inlineEditMsgId + '"]');
    if (!wrap) {
      // Fallback: find by bubble data-msg-id
      var bubble = document.querySelector('.user-msg-bubble[data-msg-id="' + _inlineEditMsgId + '"]');
      if (bubble) wrap = bubble.closest('.user-msg-wrap');
    }
    if (!wrap) return;

    var originalText = m.content || '';
    wrap.setAttribute('data-original-text', originalText);

    wrap.innerHTML =
      '<div class="user-msg-edit-bubble">' +
      '<textarea class="user-msg-edit-textarea" maxlength="4000">' + escapeHtml(originalText) + '</textarea>' +
      '<div class="user-msg-edit-actions">' +
      '<button type="button" class="btn-edit-cancel">Cancel</button>' +
      '<button type="button" class="btn-edit-send">Send</button>' +
      '</div>' +
      '</div>';

    var ta = wrap.querySelector('.user-msg-edit-textarea');
    if (ta) {
      ta.focus();
      ta.setSelectionRange(ta.value.length, ta.value.length);
      ta.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') cancelInlineEdit();
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitInlineEdit(); }
      });
    }

    var cancelBtn = wrap.querySelector('.btn-edit-cancel');
    var sendBtn = wrap.querySelector('.btn-edit-send');
    if (cancelBtn) cancelBtn.addEventListener('click', cancelInlineEdit);
    if (sendBtn) sendBtn.addEventListener('click', submitInlineEdit);
  }

  function cancelInlineEdit() {
    _inlineEditMsgId = null;
    renderChatContent();
  }

  function submitInlineEdit() {
    var mid = _inlineEditMsgId;
    var cid = state.activeChatId;
    if (!mid || !cid) { cancelInlineEdit(); return; }

    var wrap = document.querySelector('.user-msg-wrap[data-edit-id="' + mid + '"]');
    var ta = wrap && wrap.querySelector('.user-msg-edit-textarea');
    var text = ta ? String(ta.value || '').trim() : '';
    if (!text) { cancelInlineEdit(); return; }

    _inlineEditMsgId = null;

    apiFetch('/api/chats/' + encodeURIComponent(cid) + '/messages/from/' + encodeURIComponent(mid), { method: 'DELETE' })
      .then(function (res) {
        if (!res.ok) return res.text().then(function (t) { throw new Error(t || res.statusText); });

        // Immediately remove the edited message and everything after it from local state
        // so the old assistant response is cleared before the new query renders.
        var midNum = String(mid);
        var cutIdx = -1;
        for (var i = 0; i < state.chatMessages.length; i++) {
          if (String(state.chatMessages[i].id) === midNum) { cutIdx = i; break; }
        }
        if (cutIdx !== -1) {
          state.chatMessages = state.chatMessages.slice(0, cutIdx);
        }

        // Reset the active run state so no stale result is shown
        var r = rs(cid);
        if (r) {
          r.result = null;
          r.currentStep = 0;
          r.stepStatus = {};
        }

        // Clear only the message-ID keyed cache — sqlResultBySql is keyed by SQL
        // string so it's safe to keep (new query will have different SQL).
        state.sqlResultCache = {};

        // Re-render immediately — chat now shows only messages before the edited one
        renderChatContent();
        updatePipelineUI();

        runQuery(text);
      })
      .catch(function () {
        showError('Could not edit message. Try again.');
        renderChatContent();
      });
  }

  /* ── Download helpers ───────────────────────────────────── */
  function _getResultDataForMid(mid) {
    var cached = state.sqlResultCache[mid];
    if (!cached) {
      var w = document.querySelector('.result-inline-wrap[data-message-id="' + mid + '"]');
      var sql = w && w.getAttribute('data-sql');
      if (sql) cached = state.sqlResultBySql[sql];
    }
    return (cached && cached.data) ? cached.data : null;
  }

  function downloadCsv(mid) {
    var data = _getResultDataForMid(mid);
    if (!data || !data.columns || !data.rows) return;
    var lines = [data.columns.map(function (c) {
      return '"' + String(c).replace(/"/g, '""') + '"';
    }).join(',')];
    data.rows.forEach(function (row) {
      lines.push(row.map(function (cell) {
        var v = cell != null ? String(cell) : '';
        return '"' + v.replace(/"/g, '""') + '"';
      }).join(','));
    });
    var blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'query_results.csv'; a.click();
    URL.revokeObjectURL(url);
  }

  function downloadXlsx(mid) {
    var data = _getResultDataForMid(mid);
    if (!data || !data.columns || !data.rows) return;
    // Build a minimal XLSX (Office Open XML) without external libraries.
    var cols = data.columns;
    var rows = data.rows;

    function xmlEsc(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
    }
    function colLetter(n) { // 0-indexed → A, B, … Z, AA …
      var s = '';
      n++;
      while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
      return s;
    }

    var sharedStrings = [];
    var ssMap = {};
    function si(val) {
      var v = String(val == null ? '' : val);
      if (ssMap[v] === undefined) { ssMap[v] = sharedStrings.length; sharedStrings.push(v); }
      return ssMap[v];
    }

    // Build sheet rows XML
    var sheetRows = '';
    // Header row
    sheetRows += '<row r="1">';
    cols.forEach(function (c, ci) {
      sheetRows += '<c r="' + colLetter(ci) + '1" t="s"><v>' + si(c) + '</v></c>';
    });
    sheetRows += '</row>';
    rows.forEach(function (row, ri) {
      var rowNum = ri + 2;
      sheetRows += '<row r="' + rowNum + '">';
      cols.forEach(function (_, ci) {
        var cell = row[ci];
        var num = cell !== null && cell !== '' && !isNaN(Number(cell));
        if (num) {
          sheetRows += '<c r="' + colLetter(ci) + rowNum + '"><v>' + xmlEsc(cell) + '</v></c>';
        } else {
          sheetRows += '<c r="' + colLetter(ci) + rowNum + '" t="s"><v>' + si(cell) + '</v></c>';
        }
      });
      sheetRows += '</row>';
    });

    var ssXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="' + sharedStrings.length + '" uniqueCount="' + sharedStrings.length + '">' +
      sharedStrings.map(function (s) { return '<si><t xml:space="preserve">' + xmlEsc(s) + '</t></si>'; }).join('') +
      '</sst>';

    var sheetXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      '<sheetData>' + sheetRows + '</sheetData></worksheet>';

    var wbXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      '<sheets><sheet name="Results" sheetId="1" r:id="rId1"/></sheets></workbook>';

    var relsXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>' +
      '</Relationships>';

    var wbRelsXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
      '</Relationships>';

    var contentTypesXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
      '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>' +
      '</Types>';

    // Minimal ZIP builder (stored, no compression)
    function strToBytes(str) {
      var bytes = [];
      for (var i = 0; i < str.length; i++) {
        var c = str.charCodeAt(i);
        if (c < 128) { bytes.push(c); }
        else if (c < 2048) { bytes.push(0xC0 | (c >> 6), 0x80 | (c & 63)); }
        else { bytes.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63)); }
      }
      return bytes;
    }
    function crc32(bytes) {
      var table = [];
      for (var i = 0; i < 256; i++) {
        var c = i;
        for (var j = 0; j < 8; j++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
        table[i] = c;
      }
      var crc = 0xFFFFFFFF;
      for (var k = 0; k < bytes.length; k++) crc = table[(crc ^ bytes[k]) & 0xFF] ^ (crc >>> 8);
      return (crc ^ 0xFFFFFFFF) >>> 0;
    }
    function u16(n) { return [n & 0xFF, (n >> 8) & 0xFF]; }
    function u32(n) { return [n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF, (n >> 24) & 0xFF]; }

    var files = [
      { name: '[Content_Types].xml', data: contentTypesXml },
      { name: '_rels/.rels', data: wbRelsXml },
      { name: 'xl/workbook.xml', data: wbXml },
      { name: 'xl/_rels/workbook.xml.rels', data: relsXml },
      { name: 'xl/worksheets/sheet1.xml', data: sheetXml },
      { name: 'xl/sharedStrings.xml', data: ssXml }
    ];

    var zip = []; var central = []; var offset = 0;
    files.forEach(function (f) {
      var nameBytes = strToBytes(f.name);
      var dataBytes = strToBytes(f.data);
      var crc = crc32(dataBytes);
      var local = [0x50,0x4B,0x03,0x04, 20,0, 0,0, 0,0, 0,0, 0,0]
        .concat(u32(crc)).concat(u32(dataBytes.length)).concat(u32(dataBytes.length))
        .concat(u16(nameBytes.length)).concat(u16(0))
        .concat(nameBytes).concat(dataBytes);
      var cenEntry = [0x50,0x4B,0x01,0x02, 20,0, 20,0, 0,0, 0,0, 0,0]
        .concat(u32(crc)).concat(u32(dataBytes.length)).concat(u32(dataBytes.length))
        .concat(u16(nameBytes.length)).concat(u16(0)).concat(u16(0)).concat(u16(0)).concat(u16(0))
        .concat(u32(0)).concat(u32(offset)).concat(nameBytes);
      central = central.concat(cenEntry);
      offset += local.length;
      zip = zip.concat(local);
    });
    var cenSize = central.length;
    var eocd = [0x50,0x4B,0x05,0x06, 0,0, 0,0]
      .concat(u16(files.length)).concat(u16(files.length))
      .concat(u32(cenSize)).concat(u32(offset))
      .concat(u16(0));
    zip = zip.concat(central).concat(eocd);

    var blob = new Blob([new Uint8Array(zip)], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'query_results.xlsx'; a.click();
    URL.revokeObjectURL(url);
  }

  function openNewChatModal() {
    var modal = get('new-chat-modal');
    var input = get('new-chat-title-input');
    if (modal) modal.hidden = false;
    if (input) {
      input.value = '';
      input.focus();
    }
  }

  function closeNewChatModal() {
    var modal = get('new-chat-modal');
    if (modal) {
      modal.hidden = true;
      modal.removeAttribute('data-edit-chat-id');
    }
  }

  function handleNewChatClick() {
    openNewChatModal();
  }

  function renameChat(chatId, newTitle) {
    if (!newTitle) return Promise.resolve(null);
    var t = String(newTitle).trim();
    if (!t) return Promise.resolve(null);
    if (!chatId || String(chatId) === 'null' || String(chatId) === 'undefined') {
      return createNewChat(t).then(function (chat) {
        if (chat) setActiveChat(chat);
        return chat;
      });
    }
    var id = String(chatId);
    return apiFetch('/api/chats/' + encodeURIComponent(id), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t })
    })
      .then(function (res) {
        if (!res.ok) return res.text().then(function (tx) { throw new Error(tx || res.statusText); });
        return res.json();
      })
      .then(function (updatedChat) {
        if (!updatedChat) return null;
        var found = false;
        for (var i = 0; i < state.chats.length; i++) {
          if (String(state.chats[i].id) === id) {
            state.chats[i].title = updatedChat.title;
            found = true;
            break;
          }
        }
        if (!found) {
          state.chats.unshift(updatedChat);
        }
        if (String(state.activeChatId) === id) {
          var tt = get('topbar-chat-title');
          if (tt) tt.textContent = updatedChat.title;
        }
        renderChatList();
        hideError();
        return updatedChat;
      })
      .catch(function (err) {
        showError((err && err.message) ? err.message : 'Could not rename conversation.');
        return null;
      });
  }

  function handleTopbarEditClick() {
    if (!state.activeChatId) {
      openNewChatModal();
      return;
    }
    var activeChat = null;
    for (var i = 0; i < state.chats.length; i++) {
      if (String(state.chats[i].id) === String(state.activeChatId)) {
        activeChat = state.chats[i];
        break;
      }
    }
    var currentTitle = activeChat ? activeChat.title : 'New chat';
    var modal = get('new-chat-modal');
    var input = get('new-chat-title-input');
    if (input) input.value = currentTitle;
    if (modal) {
      modal.setAttribute('data-edit-chat-id', String(state.activeChatId));
      modal.hidden = false;
    }
    if (input) {
      input.focus();
      input.select();
    }
  }

  function handleModalCreate() {
    var modal = get('new-chat-modal');
    var editChatId = modal ? modal.getAttribute('data-edit-chat-id') : null;
    var input = get('new-chat-title-input');
    var title = input ? input.value.trim() : '';
    closeNewChatModal();

    if (editChatId) {
      if (title) renameChat(editChatId, title);
    } else {
      createNewChat(title || null).then(function (chat) {
        if (chat) setActiveChat(chat);
      });
    }
  }

  function openEditMessageModal(messageId) {
    editTargetMessageId = messageId;
    var modal = get('edit-message-modal');
    var ta = get('edit-message-text');
    var m;
    (state.chatMessages || []).forEach(function (x) {
      if (x && String(x.id) === String(messageId)) m = x;
    });
    if (ta) ta.value = m ? (m.content || '') : '';
    if (modal) modal.hidden = false;
    if (ta) ta.focus();
  }

  function closeEditMessageModal() {
    editTargetMessageId = null;
    var modal = get('edit-message-modal');
    if (modal) modal.hidden = true;
  }

  function saveEditedMessage() {
    var ta = get('edit-message-text');
    var text = ta ? String(ta.value || '').trim() : '';
    var mid = editTargetMessageId;
    var cid = state.activeChatId;
    if (!text || !mid || !cid) {
      closeEditMessageModal();
      return;
    }
    closeEditMessageModal();
    apiFetch('/api/chats/' + encodeURIComponent(cid) + '/messages/from/' + encodeURIComponent(mid), { method: 'DELETE' })
      .then(function (res) {
        if (!res.ok) return res.text().then(function (t) { throw new Error(t || res.statusText); });
        runQuery(text);
      })
      .catch(function () {
        showError('Could not edit message. Try again.');
      });
  }

  function handleStopGeneration() {
    var r = activeRs();
    if (!r || !r.isLoading || !r.abortController) return;
    try {
      r.abortController.abort();
    } catch (e) {}
    r.isLoading = false;
    r.abortController = null;
    syncAskStopButtons();
    renderChatContent();
    updatePipelineUI();
    if (state.activeChatId) loadChatMessages(state.activeChatId);
    renderChatList();
  }

  function deleteChat(chatId) {
    if (chatId === undefined || chatId === null) return;
    var id = String(chatId);
    delete runByChatId[id];
    apiFetch('/api/chats/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(function (res) {
        if (!res.ok) return Promise.reject(new Error(res.statusText));
        var wasActive = String(state.activeChatId) === id;
        state.chats = state.chats.filter(function (c) { return String(c.id) !== id; });
        if (wasActive && state.chats.length) {
          setActiveChat(state.chats[0]);
        } else if (wasActive) {
          setActiveChat(null);
        } else {
          renderChatList();
        }
      })
      .catch(function () {
        renderChatList();
      });
  }

  function handleChatListClick(e) {
    var target = e.target;
    if (target && target.classList && target.classList.contains('chat-item-btn--delete')) {
      e.preventDefault();
      e.stopPropagation();
      var id = target.getAttribute('data-chat-id');
      if (id) deleteChat(id);
      return;
    }
    while (target && target !== get('chat-list')) {
      if (target.classList && target.classList.contains('chat-list-item')) {
        var id = target.getAttribute('data-chat-id');
        if (!id) return;
        var chat = null;
        for (var i = 0; i < state.chats.length; i++) {
          if (String(state.chats[i].id) === id) {
            chat = state.chats[i];
            break;
          }
        }
        if (chat) {
          setActiveChat(chat);
          closeSidebar();
        }
        return;
      }
      target = target.parentNode;
    }
  }

  function toggleSidebar() {
    var open = document.body.classList.toggle('sidebar-open');
    var backdrop = get('sidebar-backdrop');
    var sidebar = get('chat-sidebar');
    if (backdrop) backdrop.setAttribute('aria-hidden', open ? 'false' : 'true');
    if (sidebar) sidebar.setAttribute('aria-hidden', open ? 'false' : 'true');
  }

  function closeSidebar() {
    document.body.classList.remove('sidebar-open');
    var backdrop = get('sidebar-backdrop');
    var sidebar = get('chat-sidebar');
    if (backdrop) backdrop.setAttribute('aria-hidden', 'true');
    if (sidebar) sidebar.setAttribute('aria-hidden', 'true');
  }

  var sidebarToggle = get('btn-sidebar-toggle');
  if (sidebarToggle) sidebarToggle.addEventListener('click', toggleSidebar);
  var sidebarBackdrop = get('sidebar-backdrop');
  if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeSidebar);

  get('query-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var input = get('query-input');
    var q = input ? String(input.value || '').trim() : '';
    if (!q) return;
    input.value = '';
    runQuery(q);
  });

  var queryInput = get('query-input');
  if (queryInput) {
    queryInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        var q = String(queryInput.value || '').trim();
        if (!q) return;
        queryInput.value = '';
        runQuery(q);
      }
    });
  }

  var btnStop = get('btn-stop');
  if (btnStop) btnStop.addEventListener('click', handleStopGeneration);

  var newChatBtn = get('btn-new-chat');
  if (newChatBtn) newChatBtn.addEventListener('click', handleNewChatClick);

  var editTopbarBtn = get('btn-edit-topbar-title');
  if (editTopbarBtn) editTopbarBtn.addEventListener('click', handleTopbarEditClick);

  var btnSchema = get('btn-schema');
  var schemaPageView = get('schema-page-view');
  var btnCloseSchemaPage = get('btn-close-schema-page');

  function openSchemaPage() {
    if (!schemaPageView) return;
    schemaPageView.hidden = false;
    var welcome = document.getElementById('chat-welcome');
    var content = document.getElementById('chat-content');
    if (welcome) welcome.style.display = 'none';
    if (content) content.hidden = true;
    if (btnSchema) btnSchema.classList.add('active');
  }

  function closeSchemaPage() {
    if (!schemaPageView) return;
    schemaPageView.hidden = true;
    if (btnSchema) btnSchema.classList.remove('active');
    var welcome = document.getElementById('chat-welcome');
    var content = document.getElementById('chat-content');
    var hasMsgs = (state.chatMessages && state.chatMessages.length > 0) || (activeRs() && activeRs().submittedQuery);
    if (hasMsgs) {
      if (welcome) welcome.style.display = 'none';
      if (content) content.hidden = false;
    } else {
      if (welcome) welcome.style.display = '';
      if (content) content.hidden = true;
    }
  }

  if (btnSchema) {
    btnSchema.addEventListener('click', function (e) {
      e.preventDefault();
      if (schemaPageView && !schemaPageView.hidden) {
        closeSchemaPage();
      } else {
        openSchemaPage();
      }
    });
  }

  if (btnCloseSchemaPage) {
    btnCloseSchemaPage.addEventListener('click', function (e) {
      e.preventDefault();
      closeSchemaPage();
    });
  }

  var schemaImg = get('schema-page-img');
  var btnZoom = get('btn-zoom-schema-page');
  var zoomText = get('schema-zoom-text');
  var zoomIcon = get('schema-zoom-icon');

  function toggleSchemaZoom() {
    if (!schemaImg) return;
    var isZoomed = schemaImg.classList.toggle('schema-page-img--zoomed');
    if (zoomText) zoomText.textContent = isZoomed ? 'Fit' : 'Zoom';
    if (zoomIcon) {
      zoomIcon.className = isZoomed ? 'fa-solid fa-compress' : 'fa-solid fa-magnifying-glass-plus';
    }
  }

  if (schemaImg) {
    schemaImg.addEventListener('click', toggleSchemaZoom);
  }
  if (btnZoom) {
    btnZoom.addEventListener('click', toggleSchemaZoom);
  }

  var modalCreate = get('modal-create');
  var modalCancel = get('modal-cancel');
  var modalBackdrop = get('modal-backdrop');
  var modalInput = get('new-chat-title-input');
  if (modalCreate) modalCreate.addEventListener('click', handleModalCreate);
  if (modalCancel) modalCancel.addEventListener('click', closeNewChatModal);
  if (modalBackdrop) modalBackdrop.addEventListener('click', closeNewChatModal);
  if (modalInput) modalInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') handleModalCreate();
    if (e.key === 'Escape') closeNewChatModal();
  });

  var editSave = get('edit-modal-save');
  var editCancel = get('edit-modal-cancel');
  var editBackdrop = get('edit-modal-backdrop');
  if (editSave) editSave.addEventListener('click', saveEditedMessage);
  if (editCancel) editCancel.addEventListener('click', closeEditMessageModal);
  if (editBackdrop) editBackdrop.addEventListener('click', closeEditMessageModal);
  var editTa = get('edit-message-text');
  if (editTa) editTa.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeEditMessageModal();
    if (e.ctrlKey && e.key === 'Enter') saveEditedMessage();
  });

  var chatList = get('chat-list');
  if (chatList) chatList.addEventListener('click', handleChatListClick);

  var collapseResultsBtn = get('btn-collapse-results');
  if (collapseResultsBtn) collapseResultsBtn.addEventListener('click', collapseResultsDock);

  // Spreadsheet overlay close + copy
  var ssClose = get('btn-spreadsheet-close');
  if (ssClose) ssClose.addEventListener('click', collapseResultsDock);

  var ssCopy = get('btn-spreadsheet-copy');
  if (ssCopy) ssCopy.addEventListener('click', function () {
    var tableWrap = get('spreadsheet-table-wrap');
    var rows = tableWrap ? tableWrap.querySelectorAll('tr') : [];
    var lines = [];
    rows.forEach(function (tr) {
      var cells = tr.querySelectorAll('th, td');
      var vals = [];
      cells.forEach(function (td, i) { if (i > 0) vals.push(td.textContent || ''); }); // skip row-num col
      lines.push(vals.join('\t'));
    });
    var text = lines.join('\n');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        var orig = ssCopy.innerHTML;
        ssCopy.textContent = 'Copied!';
        window.setTimeout(function () { ssCopy.innerHTML = orig; }, 1800);
      });
    }
  });

  function handleThinkingToggle() {
    var r = activeRs();
    if (r) r.thinkingExpanded = !r.thinkingExpanded;
    renderChatContent();
  }

  get('chat-content').addEventListener('click', function (e) {
    var target = e.target;
    var applySqlBtn = target.closest && target.closest('.btn-apply-editor');
    if (applySqlBtn) {
      e.preventDefault();
      var swrap = applySqlBtn.closest('.sql-block-wrap');
      var pre = swrap && swrap.querySelector('pre.sql');
      var text = pre ? String(pre.textContent || '') : (applySqlBtn.getAttribute('data-sql') || '');
      var inputEl = document.getElementById('chat-input') || document.querySelector('textarea');
      if (inputEl && text) {
        inputEl.value = text;
        inputEl.focus();
        showCopyToast('Applied SQL to Editor');
      }
      return;
    }
    var copySqlBtn = target.closest && target.closest('.btn-copy-sql');
    if (copySqlBtn) {
      e.preventDefault();
      var swrap = copySqlBtn.closest('.sql-block-wrap');
      var pre = swrap && swrap.querySelector('pre.sql');
      var text = pre ? String(pre.textContent || '') : '';
      if (text && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          var t = copySqlBtn.textContent;
          copySqlBtn.textContent = 'Copied';
          copySqlBtn.classList.add('btn-copy-sql--done');
          window.setTimeout(function () {
            copySqlBtn.textContent = t;
            copySqlBtn.classList.remove('btn-copy-sql--done');
          }, 1800);
        });
      }
      return;
    }
    // Download option (CSV / XLSX) — must check before card click
    var dlOption = target.closest && target.closest('.download-option');
    if (dlOption) {
      e.stopPropagation();
      var fmt = dlOption.getAttribute('data-format');
      var dlMid = dlOption.getAttribute('data-mid');
      // Close dropdown
      var wrap2 = dlOption.closest('.btn-download-wrap');
      var dd = wrap2 && wrap2.querySelector('.download-dropdown');
      if (dd) dd.hidden = true;
      if (fmt === 'csv') downloadCsv(dlMid);
      else if (fmt === 'xlsx') downloadXlsx(dlMid);
      return;
    }
    // Download button — toggle dropdown, stop propagation so card doesn't open
    var dlBtn = target.closest && target.closest('.btn-download-results');
    if (dlBtn) {
      e.stopPropagation();
      var wrap3 = dlBtn.closest('.btn-download-wrap');
      var dd2 = wrap3 && wrap3.querySelector('.download-dropdown');
      if (dd2) {
        dd2.hidden = !dd2.hidden;
        // Close all other open dropdowns
        document.querySelectorAll('.download-dropdown').forEach(function (d) {
          if (d !== dd2) d.hidden = true;
        });
      }
      return;
    }
    // Card click → open spreadsheet (but not if clicking inside download area)
    var card = target.closest && target.closest('.result-inline-card');
    if (card && !target.closest('.btn-download-wrap')) {
      var cardId = card.getAttribute('data-expand-for');
      if (cardId) expandResultsDock(cardId);
      return;
    }
    // Legacy expand button
    var expandBtn = target.closest && target.closest('.btn-expand-inline');
    if (expandBtn) {
      var expandId = expandBtn.getAttribute('data-expand-for');
      if (expandId) expandResultsDock(expandId);
      return;
    }
    if (target.closest && (target.closest('.thinking-header') || target.closest('[data-action="toggle-thinking"]'))) {
      handleThinkingToggle();
      return;
    }
    if (target.classList && target.classList.contains('clarification-option')) {
      var option = target.getAttribute('data-option');
      var ar0 = activeRs();
      if (option && ar0 && ar0.submittedQuery) runQuery(ar0.submittedQuery, option);
    }
    if (target.classList && target.classList.contains('btn-try-again')) {
      var rta = activeRs();
      if (rta) {
        rta.result = null;
        rta.currentStep = 0;
      }
      updatePipelineUI();
      renderChatContent();
    }
    // Legacy modal edit button (kept for safety)
    var editBtn = target.closest && target.closest('.btn-edit-user-msg');
    if (editBtn) {
      var mid = editBtn.getAttribute('data-msg-id');
      if (mid) openEditMessageModal(mid);
      return;
    }
    // Inline edit icon
    var inlineEditBtn = target.closest && target.closest('.msg-action-edit');
    if (inlineEditBtn) {
      var mid2 = inlineEditBtn.getAttribute('data-msg-id');
      if (mid2) enterInlineEdit(mid2);
      return;
    }
    // Inline copy icon
    var copyMsgBtn = target.closest && target.closest('.msg-action-copy');
    if (copyMsgBtn) {
      var mid3 = copyMsgBtn.getAttribute('data-msg-id');
      var bubble = mid3 && document.querySelector('.user-msg-bubble[data-msg-id="' + mid3 + '"]');
      var msgText = bubble ? (bubble.textContent || '').trim() : '';
      if (msgText && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(msgText).then(function () {
          showCopyToast();
        });
      }
      return;
    }
  });

  get('chat-content').addEventListener('keydown', function (e) {
    var target = e.target;
    if (target.closest && target.closest('.thinking-header') && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      handleThinkingToggle();
    }
  });

  // Close download dropdowns when clicking outside
  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('.btn-download-wrap')) {
      document.querySelectorAll('.download-dropdown').forEach(function (d) { d.hidden = true; });
    }
  });

  function startApp() {
    loadChats();
    renderChatList();
  }

  startApp();
})();
