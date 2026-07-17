// Configuration
const REFRESH_INTERVAL = 2000; // 2 seconds

// State
let activityChart = null;
let distributionChart = null;
let queueHistory = {
    labels: [],
    data: []
};
const MAX_HISTORY_POINTS = 30;

// Initialize charts on load
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    fetchData();
    setInterval(fetchData, REFRESH_INTERVAL);
});

// Chart.js global defaults for Dark Theme
Chart.defaults.color = '#8b949e';
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";

function initCharts() {
    // Activity Chart (Line)
    const ctxActivity = document.getElementById('activityChart').getContext('2d');
    activityChart = new Chart(ctxActivity, {
        type: 'line',
        data: {
            labels: queueHistory.labels,
            datasets: [{
                label: 'Pending Jobs',
                data: queueHistory.data,
                borderColor: '#58a6ff',
                backgroundColor: 'rgba(88, 166, 255, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                pointHitRadius: 10
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 0 // Disable animation for live updates
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: '#161b22',
                    titleColor: '#c9d1d9',
                    bodyColor: '#c9d1d9',
                    borderColor: '#30363d',
                    borderWidth: 1
                }
            },
            scales: {
                x: {
                    display: false // Hide x-axis labels for cleaner look
                },
                y: {
                    beginAtZero: true,
                    grid: { color: '#30363d' },
                    ticks: { precision: 0 }
                }
            }
        }
    });

    // Distribution Chart (Doughnut)
    const ctxDist = document.getElementById('distributionChart').getContext('2d');
    distributionChart = new Chart(ctxDist, {
        type: 'doughnut',
        data: {
            labels: ['Completed', 'Running', 'Pending', 'Failed', 'Dead'],
            datasets: [{
                data: [0, 0, 0, 0, 0],
                backgroundColor: [
                    '#10b981', // completed
                    '#f1e05a', // running
                    '#58a6ff', // pending
                    '#ff7b72', // failed
                    '#d73a49'  // dead
                ],
                borderWidth: 0,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '75%',
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: '#c9d1d9',
                        usePointStyle: true,
                        padding: 20
                    }
                }
            }
        }
    });
}

async function fetchData() {
    try {
        const [statusRes, jobsRes, workersRes] = await Promise.all([
            fetch('/api/status').catch(() => null),
            fetch('/api/jobs?limit=20').catch(() => null),
            fetch('/api/workers').catch(() => null)
        ]);

        if (statusRes && statusRes.ok) {
            const status = await statusRes.json();
            updateStatusMetrics(status);
            updateActivityChart(status.pending_jobs);
            updateDistributionChart(status);
        }

        if (jobsRes && jobsRes.ok) {
            const jobs = await jobsRes.json();
            updateJobsTable(jobs);
        }

        if (workersRes && workersRes.ok) {
            const workers = await workersRes.json();
            updateWorkersTable(workers);
        }
    } catch (e) {
        console.error("Error fetching dashboard data:", e);
    }
}

function updateStatusMetrics(status) {
    // Header
    document.getElementById('header-workers').textContent = status.workers || 0;
    document.getElementById('header-queue').textContent = status.pending_jobs || 0;
    document.getElementById('header-running').textContent = status.processing_jobs || 0;

    // Metric Cards
    document.getElementById('metric-pending').textContent = status.pending_jobs || 0;
    document.getElementById('metric-running').textContent = status.processing_jobs || 0;
    document.getElementById('metric-failed').textContent = status.failed_jobs || 0;
    document.getElementById('metric-dlq').textContent = status.dead_jobs || 0;
}

function updateActivityChart(pendingCount) {
    const now = new Date();
    const timeLabel = now.getHours() + ':' + now.getMinutes() + ':' + now.getSeconds();

    queueHistory.labels.push(timeLabel);
    queueHistory.data.push(pendingCount);

    if (queueHistory.labels.length > MAX_HISTORY_POINTS) {
        queueHistory.labels.shift();
        queueHistory.data.shift();
    }

    activityChart.update();
}

function updateDistributionChart(status) {
    if(!distributionChart) return;
    distributionChart.data.datasets[0].data = [
        status.completed_jobs || 0,
        status.processing_jobs || 0,
        status.pending_jobs || 0,
        status.failed_jobs || 0,
        status.dead_jobs || 0
    ];
    distributionChart.update();
}

function updateJobsTable(jobs) {
    const tbody = document.querySelector('#jobs-table tbody');
    tbody.innerHTML = '';

    if (!jobs || jobs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-secondary);">No recent jobs found</td></tr>';
        return;
    }

    jobs.forEach(job => {
        const tr = document.createElement('tr');
        
        // ID
        const tdId = document.createElement('td');
        tdId.className = 'mono-text';
        tdId.textContent = job.id.substring(0, 8); // short ID
        
        // Command
        const tdCmd = document.createElement('td');
        const spanCmd = document.createElement('span');
        spanCmd.className = 'command-text';
        spanCmd.textContent = job.command;
        spanCmd.title = job.command;
        tdCmd.appendChild(spanCmd);
        
        // Status
        const tdStatus = document.createElement('td');
        const spanStatus = document.createElement('span');
        const state = job.state.toLowerCase();
        spanStatus.className = `status-badge badge-${state}`;
        spanStatus.textContent = job.state;
        tdStatus.appendChild(spanStatus);
        
        // Attempts
        const tdAttempts = document.createElement('td');
        tdAttempts.className = 'mono-text';
        tdAttempts.textContent = `${job.attempts} / ${job.max_retries}`;

        tr.appendChild(tdId);
        tr.appendChild(tdCmd);
        tr.appendChild(tdStatus);
        tr.appendChild(tdAttempts);
        
        tbody.appendChild(tr);
    });
}

function updateWorkersTable(workers) {
    const tbody = document.querySelector('#workers-table tbody');
    tbody.innerHTML = '';

    if (!workers || workers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-secondary);">No active workers</td></tr>';
        return;
    }

    workers.forEach(w => {
        const tr = document.createElement('tr');
        
        // Worker Name (ID)
        const tdName = document.createElement('td');
        tdName.className = 'mono-text';
        tdName.textContent = w.id || w.worker_id || 'Unknown';
        
        // Status
        const tdStatus = document.createElement('td');
        const spanStatus = document.createElement('span');
        const statusStr = w.status || (w.current_job_id ? 'Running' : 'Idle');
        const isRunning = statusStr.toLowerCase() === 'running';
        spanStatus.className = `status-badge badge-${isRunning ? 'running' : 'completed'}`;
        spanStatus.textContent = statusStr;
        tdStatus.appendChild(spanStatus);
        
        // Current Job
        const tdJob = document.createElement('td');
        tdJob.className = 'mono-text';
        tdJob.textContent = w.current_job_id ? w.current_job_id.substring(0,8) : '-';
        
        // Heartbeat
        const tdHeartbeat = document.createElement('td');
        tdHeartbeat.className = 'mono-text';
        if (w.last_heartbeat) {
            const hb = new Date(w.last_heartbeat + 'Z');
            const diff = Math.floor((new Date() - hb) / 1000);
            tdHeartbeat.textContent = diff >= 0 ? `${diff}s ago` : 'just now';
        } else {
            tdHeartbeat.textContent = '-';
        }

        tr.appendChild(tdName);
        tr.appendChild(tdStatus);
        tr.appendChild(tdJob);
        tr.appendChild(tdHeartbeat);
        
        tbody.appendChild(tr);
    });
}
