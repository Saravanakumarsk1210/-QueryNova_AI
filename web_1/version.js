(function () {
  'use strict';

  var COLORS = {
    good_queries: '#4caf50',
    data_not_found: '#f44336',
    empty_result_fallback: '#ff9800',
    invalid_or_prose: '#9e9e9e',
    empty_or_missing: '#607d8b'
  };

  var LABELS = {
    good_queries: 'Good queries (valid SQL)',
    data_not_found: 'Data not found',
    empty_result_fallback: 'Empty-result fallback (WHERE 1=0)',
    invalid_or_prose: 'Invalid or prose only',
    empty_or_missing: 'Empty or missing SQL'
  };

  function getParam(name) {
    var m = new RegExp('[?&]' + name + '=([^&]*)').exec(window.location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function escapeHtml(s) {
    if (s == null) return '';
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function renderTable(rows) {
    var thead = document.getElementById('table-head');
    var tbody = document.getElementById('table-body');
    if (!rows.length) {
      thead.innerHTML = '';
      tbody.innerHTML = '<tr><td colspan="4">No rows</td></tr>';
      return;
    }
    var keys = Object.keys(rows[0]);
    thead.innerHTML = '<tr>' + keys.map(function (k) { return '<th>' + escapeHtml(k) + '</th>'; }).join('') + '</tr>';
    tbody.innerHTML = rows.map(function (row) {
      return '<tr>' + keys.map(function (k) { return '<td>' + escapeHtml(row[k] || '') + '</td>'; }).join('') + '</tr>';
    }).join('');
  }

  function drawPieChart(summary) {
    var total = summary.total || 0;
    var segmentKeys = ['good_queries', 'data_not_found', 'empty_result_fallback', 'invalid_or_prose', 'empty_or_missing'];
    var segments = segmentKeys.map(function (k) { return { key: k, value: summary[k] || 0 }; }).filter(function (s) { return s.value > 0; });

    var svg = document.getElementById('pie-chart');
    var legendEl = document.getElementById('chart-legend');
    var summaryEl = document.getElementById('summary-text');

    if (total === 0) {
      svg.innerHTML = '<text x="100" y="100" text-anchor="middle" fill="#546e7a" font-size="14">No data</text>';
      legendEl.innerHTML = '';
      summaryEl.innerHTML = 'No rows in this version.';
      return;
    }

    var cx = 100, cy = 100, r = 80;
    var acc = 0;
    var pathParts = [];
    segments.forEach(function (s) {
      var ratio = s.value / total;
      var start = acc * 360;
      var sweep = ratio * 360;
      acc += ratio;
      var x1 = cx + r * Math.cos((start - 90) * Math.PI / 180);
      var y1 = cy + r * Math.sin((start - 90) * Math.PI / 180);
      var x2 = cx + r * Math.cos((start + sweep - 90) * Math.PI / 180);
      var y2 = cy + r * Math.sin((start + sweep - 90) * Math.PI / 180);
      var large = sweep > 180 ? 1 : 0;
      pathParts.push('<path fill="' + COLORS[s.key] + '" d="M' + cx + ',' + cy + ' L' + x1 + ',' + y1 + ' A' + r + ',' + r + ' 0 ' + large + ',1 ' + x2 + ',' + y2 + ' Z"/>');
    });
    svg.innerHTML = pathParts.join('');

    legendEl.innerHTML = segments.map(function (s) {
      var pct = total ? ((s.value / total) * 100).toFixed(1) : 0;
      return '<div class="legend-item"><span class="legend-dot" style="background:' + COLORS[s.key] + '"></span><span>' + escapeHtml(LABELS[s.key]) + ': ' + s.value + ' (' + pct + '%)</span></div>';
    }).join('');

    var parts = ['Total: ' + total + ' queries.'];
    segmentKeys.forEach(function (k) {
      var v = summary[k] || 0;
      if (v > 0) parts.push(LABELS[k] + ': ' + v);
    });
    if (summary.with_clarification) parts.push('With clarification (asked): ' + summary.with_clarification);
    summaryEl.innerHTML = parts.join(' &middot; ');
  }

  function showError(msg) {
    var el = document.getElementById('version-error');
    el.textContent = msg;
    el.hidden = false;
  }

  function hideError() {
    document.getElementById('version-error').hidden = true;
  }

  function loadVersion() {
    var file = getParam('file');
    if (!file || !file.match(/^results\d*\.csv$/)) {
      showError('Missing or invalid file. Use ?file=results7.csv');
      return;
    }

    document.getElementById('version-title').textContent = file + ' – Version Analysis';
    document.getElementById('download-csv').href = '/api/version-history/' + encodeURIComponent(file);
    document.getElementById('download-csv').setAttribute('download', file);
    hideError();

    fetch('/api/version-history/' + encodeURIComponent(file) + '/analysis')
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { throw new Error(d.error || res.statusText); });
        return res.json();
      })
      .then(function (data) {
        renderTable(data.rows || []);
        drawPieChart(data.summary || {});
      })
      .catch(function (err) {
        showError(err.message || 'Failed to load version');
        renderTable([]);
        drawPieChart({});
      });
  }

  loadVersion();
})();
