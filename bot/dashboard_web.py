"""
Public Performance Dashboard
==============================
Flask-based web dashboard showing signal performance metrics.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_dashboard_routes(app, get_dashboard_fn, get_risk_manager_fn=None) -> None:
    """
    Register dashboard routes on the given Flask app.
    """
    from flask import jsonify, render_template_string
    from flask import request as flask_request

    DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>360 Crypto Eye — Performance Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; }
  header { background: #161b22; padding: 20px 40px; border-bottom: 1px solid #30363d; }
  header h1 { color: #58a6ff; font-size: 1.6rem; }
  header p { color: #8b949e; font-size: 0.9rem; margin-top: 4px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 30px 20px; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 30px; }
  .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; text-align: center; }
  .stat-card .label { color: #8b949e; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .stat-card .value { font-size: 2rem; font-weight: bold; margin-top: 8px; color: #58a6ff; }
  .stat-card .value.green { color: #3fb950; }
  .stat-card .value.red { color: #f85149; }
  .section { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 24px; }
  .section h2 { color: #58a6ff; font-size: 1.1rem; margin-bottom: 16px; border-bottom: 1px solid #30363d; padding-bottom: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th { text-align: left; padding: 8px 12px; color: #8b949e; font-weight: 500; border-bottom: 1px solid #30363d; }
  td { padding: 8px 12px; border-bottom: 1px solid #21262d; }
  tr:last-child td { border-bottom: none; }
  .win { color: #3fb950; } .loss { color: #f85149; } .be { color: #d29922; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
  .badge-long { background: #1f4e28; color: #3fb950; }
  .badge-short { background: #4e1f1f; color: #f85149; }
  footer { text-align: center; padding: 20px; color: #8b949e; font-size: 0.8rem; border-top: 1px solid #30363d; margin-top: 20px; }
</style>
</head>
<body>
<header>
  <h1>👁️ 360 Crypto Eye — Performance Dashboard</h1>
  <p>Institutional-Grade Scalping Signals • Real-Time Performance Tracking</p>
</header>
<div class="container">
  <div class="stats-grid" id="stats-grid">
    <div class="stat-card"><div class="label">Total Signals</div><div class="value" id="total-signals">—</div></div>
    <div class="stat-card"><div class="label">Win Rate</div><div class="value green" id="win-rate">—</div></div>
    <div class="stat-card"><div class="label">Profit Factor</div><div class="value" id="profit-factor">—</div></div>
    <div class="stat-card"><div class="label">Sharpe Ratio</div><div class="value" id="sharpe">—</div></div>
    <div class="stat-card"><div class="label">Max Drawdown</div><div class="value red" id="max-dd">—</div></div>
    <div class="stat-card"><div class="label">Active Signals</div><div class="value" id="active">—</div></div>
  </div>
  <div class="section">
    <h2>📊 Recent Signals (Last 20)</h2>
    <table>
      <thead><tr><th>Symbol</th><th>Side</th><th>Outcome</th><th>PnL %</th><th>Entry</th><th>Exit</th><th>Opened</th></tr></thead>
      <tbody id="signals-tbody"><tr><td colspan="7" style="text-align:center;color:#8b949e">Loading…</td></tr></tbody>
    </table>
  </div>
</div>
<footer>360 Crypto Eye Scalping • Data refreshes automatically</footer>
<script>
async function loadStats() {
  try {
    const r = await fetch('/api/stats'); const d = await r.json();
    document.getElementById('total-signals').textContent = d.total_signals ?? '0';
    document.getElementById('win-rate').textContent = d.win_rate != null ? d.win_rate.toFixed(1) + '%' : '—';
    document.getElementById('profit-factor').textContent = d.profit_factor != null ? d.profit_factor.toFixed(2) : '—';
    document.getElementById('sharpe').textContent = d.sharpe_ratio != null ? d.sharpe_ratio.toFixed(2) : '—';
    document.getElementById('max-dd').textContent = d.max_drawdown != null ? d.max_drawdown.toFixed(2) + '%' : '—';
    document.getElementById('active').textContent = d.active_signals ?? '0';
  } catch(e) { console.error('Stats load error', e); }
}
async function loadSignals() {
  try {
    const r = await fetch('/api/signals?limit=20'); const d = await r.json();
    const tbody = document.getElementById('signals-tbody');
    if (!d.signals || d.signals.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#8b949e">No signals recorded yet.</td></tr>'; return;
    }
    tbody.innerHTML = d.signals.map(s => {
      const oc = s.outcome === 'WIN' ? 'win' : s.outcome === 'LOSS' ? 'loss' : 'be';
      const sc = s.side === 'LONG' ? 'badge-long' : 'badge-short';
      const pnl = s.pnl_pct != null ? (s.pnl_pct > 0 ? '+' : '') + s.pnl_pct.toFixed(2) + '%' : '—';
      const opened = s.opened_at ? new Date(s.opened_at * 1000).toLocaleString() : '—';
      return `<tr><td><strong>${s.symbol}</strong></td><td><span class="badge ${sc}">${s.side}</span></td><td class="${oc}">${s.outcome}</td><td class="${oc}">${pnl}</td><td>${s.entry_price ? s.entry_price.toFixed(4) : '—'}</td><td>${s.exit_price ? s.exit_price.toFixed(4) : '—'}</td><td>${opened}</td></tr>`;
    }).join('');
  } catch(e) { console.error('Signals load error', e); }
}
loadStats(); loadSignals();
setInterval(() => { loadStats(); loadSignals(); }, 30000);
</script>
</body>
</html>"""

    # Capped display value for infinite profit factor (all trades are wins)
    _PROFIT_FACTOR_INF_DISPLAY = 999.99

    @app.route("/dashboard")
    def dashboard_page():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/stats")
    def api_stats():
        try:
            dash = get_dashboard_fn()
            trades = dash._results if hasattr(dash, '_results') else []
            total = len(trades)
            # Use protected win rate (BE counted as win) as the primary metric
            wins = sum(1 for t in trades if getattr(t, 'outcome', '') in ('WIN', 'BE'))
            win_rate = (wins / total * 100) if total > 0 else None
            gross_win = sum(t.pnl_pct for t in trades if getattr(t, 'pnl_pct', 0) > 0)
            gross_loss = abs(sum(t.pnl_pct for t in trades if getattr(t, 'pnl_pct', 0) < 0))
            if gross_loss > 0:
                profit_factor = round(gross_win / gross_loss, 4)
            elif gross_win > 0:
                profit_factor = _PROFIT_FACTOR_INF_DISPLAY
            else:
                profit_factor = None
            active = 0
            if get_risk_manager_fn:
                rm = get_risk_manager_fn()
                if hasattr(rm, 'active_signals') and isinstance(rm.active_signals, (list, tuple)):
                    active = len(rm.active_signals)
            if len(trades) > 1:
                import statistics
                pnls = [t.pnl_pct for t in trades]
                avg = statistics.mean(pnls)
                std = statistics.stdev(pnls)
                sharpe = avg / std if std > 0 else None
            else:
                sharpe = None
            max_dd = None
            if trades:
                equity = 0.0
                peak = 0.0
                worst_dd = 0.0
                for t in trades:
                    equity += t.pnl_pct
                    if equity > peak:
                        peak = equity
                    dd = peak - equity
                    if dd > worst_dd:
                        worst_dd = dd
                max_dd = worst_dd
            return jsonify({
                "total_signals": total,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "sharpe_ratio": sharpe,
                "max_drawdown": max_dd,
                "active_signals": active,
            })
        except Exception as exc:
            logger.error("api_stats error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/signals")
    def api_signals():
        try:
            limit = int(flask_request.args.get("limit", 20))
            dash = get_dashboard_fn()
            trades = dash._results if hasattr(dash, '_results') else []
            recent = trades[-limit:]
            signals_data = []
            for t in recent:
                signals_data.append({
                    "symbol": getattr(t, 'symbol', ''),
                    "side": getattr(t, 'side', ''),
                    "outcome": getattr(t, 'outcome', ''),
                    "pnl_pct": getattr(t, 'pnl_pct', None),
                    "entry_price": getattr(t, 'entry_price', None),
                    "exit_price": getattr(t, 'exit_price', None),
                    "opened_at": getattr(t, 'opened_at', None),
                    "closed_at": getattr(t, 'closed_at', None),
                    "timeframe": getattr(t, 'timeframe', '5m'),
                })
            return jsonify({"signals": signals_data, "total": len(trades)})
        except Exception as exc:
            logger.error("api_signals error: %s", exc)
            return jsonify({"error": str(exc)}), 500
