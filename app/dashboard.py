# sandbox/app/dashboard.py
"""
Simple metrics dashboard for sandbox tool.
For V1 testing and demo visualization.
"""

from flask import Flask, render_template_string, jsonify
from app.main import startup, get_metrics

app = Flask(__name__)

# Initialize tool on startup
startup()

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Sandbox Tool Metrics</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        h1 {
            color: #333;
        }
        .metric-card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .metric-value {
            font-size: 48px;
            font-weight: bold;
            color: #4CAF50;
        }
        .metric-label {
            font-size: 14px;
            color: #666;
            text-transform: uppercase;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #f8f8f8;
            font-weight: bold;
        }
        .refresh-btn {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        .refresh-btn:hover {
            background: #45a049;
        }
        .timestamp {
            color: #999;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <h1>Sandbox Snapshot Notebook - Metrics Dashboard</h1>
    <button class="refresh-btn" onclick="location.reload()">Refresh</button>
    <p class="timestamp">Last updated: <span id="timestamp"></span></p>
    
    <div class="grid">
        <div class="metric-card">
            <div class="metric-label">Total Snapshots</div>
            <div class="metric-value" id="total-snapshots">-</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Total Projects</div>
            <div class="metric-value" id="total-projects">-</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Recent (24h)</div>
            <div class="metric-value" id="recent-snapshots">-</div>
        </div>
    </div>
    
    <div class="metric-card">
        <h2>Snapshots by Type</h2>
        <table>
            <thead>
                <tr>
                    <th>Type</th>
                    <th>Count</th>
                </tr>
            </thead>
            <tbody id="type-table">
            </tbody>
        </table>
    </div>
    
    <div class="metric-card">
        <h2>Projects</h2>
        <table>
            <thead>
                <tr>
                    <th>Project ID</th>
                    <th>Code Snapshots</th>
                    <th>Text Snapshots</th>
                    <th>Total</th>
                </tr>
            </thead>
            <tbody id="project-table">
            </tbody>
        </table>
    </div>
    
    <script>
        async function loadMetrics() {
            const response = await fetch('/api/metrics');
            const data = await response.json();
            
            // Update summary metrics
            document.getElementById('total-snapshots').textContent = data.snapshot_metrics.total;
            document.getElementById('total-projects').textContent = data.project_metrics.total;
            document.getElementById('recent-snapshots').textContent = data.snapshot_metrics.recent_24h;
            document.getElementById('timestamp').textContent = new Date(data.timestamp).toLocaleString();
            
            // Update snapshots by type table
            const typeTable = document.getElementById('type-table');
            typeTable.innerHTML = '';
            for (const [type, count] of Object.entries(data.snapshot_metrics.by_type)) {
                const row = typeTable.insertRow();
                row.insertCell(0).textContent = type;
                row.insertCell(1).textContent = count;
            }
            
            // Update projects table
            const projectTable = document.getElementById('project-table');
            projectTable.innerHTML = '';
            for (const [projectId, counts] of Object.entries(data.project_metrics.projects)) {
                const row = projectTable.insertRow();
                row.insertCell(0).textContent = projectId;
                row.insertCell(1).textContent = counts.code || 0;
                row.insertCell(2).textContent = counts.text || 0;
                row.insertCell(3).textContent = (counts.code || 0) + (counts.text || 0);
            }
        }
        
        // Load on page load
        loadMetrics();
        
        // Auto-refresh every 30 seconds
        setInterval(loadMetrics, 30000);
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    """Render metrics dashboard."""
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/metrics')
def api_metrics():
    """Return metrics as JSON."""
    return jsonify(get_metrics())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
