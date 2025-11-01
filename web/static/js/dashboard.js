// Trading Bot Dashboard JavaScript

// Global state management
const AppState = {
    theme: localStorage.getItem('theme') || 'dark',
    refreshIntervals: new Map(),
    cache: new Map(),
    notifications: [],
    loadingStates: new Set()
};

// Initialize Socket.IO connection
const socket = io();

// Connection status
socket.on('connect', () => {
    console.log('Connected to server');
    updateConnectionBadge(true);
    refreshStatus();
    loadModels();
    loadLogs();
    loadPerformanceChart();
    initializeTheme();
});

socket.on('disconnect', () => {
    console.log('Disconnected from server');
    updateConnectionBadge(false);
});

// Initialize theme on page load
function initializeTheme() {
    document.documentElement.setAttribute('data-theme', AppState.theme);
    updateThemeToggle();
}

// Theme toggle functionality
function toggleTheme() {
    AppState.theme = AppState.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', AppState.theme);
    localStorage.setItem('theme', AppState.theme);
    updateThemeToggle();
}

function updateThemeToggle() {
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
        const icon = toggle.querySelector('svg');
        if (AppState.theme === 'dark') {
            icon.innerHTML = '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>';
        } else {
            icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
        }
    }
}

// Enhanced notification system
function showNotification(message, type = 'info', duration = 5000) {
    const notificationId = Date.now();
    const notification = {
        id: notificationId,
        message,
        type,
        timestamp: new Date()
    };

    AppState.notifications.push(notification);

    // Create notification element
    const notificationEl = document.createElement('div');
    notificationEl.className = `notification ${type}`;
    notificationEl.setAttribute('role', 'alert');
    notificationEl.innerHTML = `
        <div class="notification-icon">
            ${type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️'}
        </div>
        <div class="notification-content">${message}</div>
        <button class="notification-close" onclick="dismissNotification(${notificationId})" aria-label="Close notification">
            ×
        </button>
    `;

    const container = document.getElementById('notifications');
    if (container) {
        container.appendChild(notificationEl);

        // Auto-dismiss after duration
        if (duration > 0) {
            setTimeout(() => dismissNotification(notificationId), duration);
        }
    }

    return notificationId;
}

function dismissNotification(id) {
    AppState.notifications = AppState.notifications.filter(n => n.id !== id);
    const notificationEl = document.querySelector(`[onclick="dismissNotification(${id})"]`);
    if (notificationEl) {
        notificationEl.parentElement.remove();
    }
}

// Loading state management
function setLoadingState(elementId, loading) {
    const element = document.getElementById(elementId);
    if (!element) return;

    if (loading) {
        AppState.loadingStates.add(elementId);
        element.classList.add('loading');
    } else {
        AppState.loadingStates.delete(elementId);
        element.classList.remove('loading');
    }
}

// Debounced API calls
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Cached API calls
async function cachedFetch(url, options = {}, cacheTime = 30000) {
    const cacheKey = `${url}-${JSON.stringify(options)}`;
    const cached = AppState.cache.get(cacheKey);

    if (cached && (Date.now() - cached.timestamp) < cacheTime) {
        return cached.data;
    }

    try {
        const response = await fetch(url, options);
        const data = await response.json();

        AppState.cache.set(cacheKey, {
            data,
            timestamp: Date.now()
        });

        return data;
    } catch (error) {
        console.error('API call failed:', error);
        throw error;
    }
}

// Bot status updates
socket.on('bot_status', (data) => {
    console.log('Bot status update:', data);
    updateBotStatus(data.status);
});

// Training complete notification
socket.on('training_complete', (data) => {
    hideTrainingStatus();
    if (data.success) {
        showNotification('Training completed successfully!', 'success');
        loadModels();
    } else {
        showNotification(`Training failed: ${data.error}`, 'error');
    }
});

// Live activity handlers
socket.on('live_analysis', (data) => {
    addActivityFeedItem({
        type: data.action?.toLowerCase() || 'info',
        message: `${data.symbol}: ${data.action} signal (${(data.confidence * 100).toFixed(0)}% confidence) @ $${data.price?.toFixed(2)}`,
        symbol: data.symbol,
        confidence: data.confidence
    });
    
    // Update last signal
    document.getElementById('live-last-signal').textContent = `${data.symbol} ${data.action}`;
    document.getElementById('live-signal-time').textContent = new Date(data.timestamp).toLocaleTimeString();
});

socket.on('signal_rejected', (data) => {
    addActivityFeedItem({
        type: 'warning',
        message: `${data.symbol}: ${data.action} rejected - ${data.reason}`,
        symbol: data.symbol
    });
});

socket.on('trade_executed', (data) => {
    addActivityFeedItem({
        type: data.action?.toLowerCase() || 'buy',
        message: `✅ ${data.symbol}: ${data.action} executed @ $${data.price.toFixed(2)} (${(data.confidence * 100).toFixed(0)}% conf, $${data.size.toFixed(0)})`,
        symbol: data.symbol
    });
    
    showNotification(`${data.action} ${data.symbol} @ $${data.price.toFixed(2)}`, 'success');
    loadPositions(); // Refresh positions
});

// Update connection badge
function updateConnectionBadge(connected) {
    const badge = document.getElementById('api-status');
    if (badge) {
        if (connected) {
            badge.textContent = 'CONNECTED';
            badge.className = 'status-badge connected';
        } else {
            badge.textContent = 'DISCONNECTED';
            badge.className = 'status-badge stopped';
        }
    }
}

// Update bot status badge and buttons
function updateBotStatus(status) {
    const badge = document.getElementById('bot-status');
    const startBtn = document.getElementById('btn-start');
    const stopBtn = document.getElementById('btn-stop');
    
    if (badge) {
        if (status === 'running') {
            badge.textContent = 'RUNNING';
            badge.className = 'status-badge running';
        } else {
            badge.textContent = 'STOPPED';
            badge.className = 'status-badge stopped';
        }
    }
    
    if (startBtn && stopBtn) {
        if (status === 'running') {
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else {
            startBtn.disabled = false;
            stopBtn.disabled = true;
        }
    }
}

// Start bot
async function startBot() {
    try {
        const response = await fetch('/api/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();
        
        if (data.success) {
            showNotification('Bot started successfully!', 'success');
            refreshStatus();
        } else {
            showNotification(`Failed to start bot: ${data.message}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

// Stop bot
async function stopBot() {
    try {
        const response = await fetch('/api/stop', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();
        
        if (data.success) {
            showNotification('Bot stopped successfully!', 'success');
            refreshStatus();
        } else {
            showNotification(`Failed to stop bot: ${data.message}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

// Refresh status
async function refreshStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        updateBotStatus(data.status);
        
        if (data.config) {
            document.getElementById('config-symbol').textContent = data.config.symbol || '-';
            document.getElementById('config-timeframe').textContent = data.config.timeframe || '-';
            document.getElementById('config-strategy').textContent = data.config.strategy || '-';
            document.getElementById('config-dryrun').textContent = data.config.dry_run ? 'Yes' : 'No';
        }
    } catch (error) {
        console.error('Failed to fetch status:', error);
    }
}

// Load performance chart
let performanceChart = null;
async function loadPerformanceChart() {
    try {
        const response = await fetch('/api/performance?hours=24');
        const result = await response.json();
        
        if (!result.success || !result.data) {
            console.log('No performance data yet');
            return;
        }
        
        const { trades, stats } = result.data;
        
        // Update stats
        document.getElementById('chart-total-trades').textContent = stats.total_trades || 0;
        document.getElementById('chart-win-rate').textContent = `${(stats.win_rate || 0).toFixed(1)}%`;
        document.getElementById('chart-avg-pnl').textContent = `${(stats.avg_pnl_pct || 0).toFixed(2)}%`;
        document.getElementById('chart-total-pnl').textContent = `$${(stats.total_pnl || 0).toFixed(2)}`;
        
        // Prepare chart data
        const labels = trades.map(t => new Date(t.exit_time).toLocaleTimeString());
        const pnlData = trades.map(t => t.cumulative_pnl || 0);
        
        // Create or update chart
        const ctx = document.getElementById('performance-chart').getContext('2d');
        
        if (performanceChart) {
            performanceChart.destroy();
        }
        
        performanceChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Cumulative P&L ($)',
                    data: pnlData,
                    borderColor: pnlData[pnlData.length - 1] >= 0 ? '#10b981' : '#ef4444',
                    backgroundColor: pnlData[pnlData.length - 1] >= 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        callbacks: {
                            label: function(context) {
                                return `P&L: $${context.parsed.y.toFixed(2)}`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#9ca3af' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { 
                            color: '#9ca3af',
                            maxTicksLimit: 10
                        }
                    }
                }
            }
        });
        
    } catch (error) {
        console.error('Failed to load performance chart:', error);
    }
}

// Train ALL pairs (auto-discover from Binance)
async function trainAllPairs() {
    if (!confirm('🌍 Train ALL liquid USDT pairs?\n\nThis will:\n• Auto-discover 80-150+ pairs from Binance\n• Train advanced ML models for each\n• Take 1-3 hours for initial training\n• Enable continuous 24h retraining\n\nContinue?')) {
        return;
    }
    
    const interval = document.getElementById('batch-interval').value;
    const lookback = parseInt(document.getElementById('batch-lookback').value);
    const optimize = document.getElementById('batch-optimize').checked;
    
    try {
        // Start training ALL pairs
        const response = await fetch('/api/batch-train', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                symbols: ['ALL'],  // Special flag to auto-discover
                interval: interval,
                lookback_days: lookback,
                optimize: optimize
            })
        });
        const data = await response.json();
        
        if (data.success) {
            showNotification(`🚀 Started training ALL pairs! Discovered ${data.symbols?.length || '?'} pairs. Check logs for progress.`, 'success');
            
            // Show progress UI
            const progressDiv = document.getElementById('batch-training-progress');
            const progressList = document.getElementById('batch-progress-list');
            progressDiv.style.display = 'block';
            progressList.innerHTML = '<p style="text-align: center; padding: 20px;">Training in progress... Check the Logs tab for detailed progress.</p>';
            
            // Switch to logs tab to watch progress
            setTimeout(() => {
                document.querySelector('[data-tab="logs"]').click();
                loadLogs();
            }, 2000);
        } else {
            showNotification(`Failed to start training: ${data.message}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

// Batch train multiple models
async function batchTrainModels() {
    const pairs = [];
    if (document.getElementById('batch-btc').checked) pairs.push('BTCUSDT');
    if (document.getElementById('batch-eth').checked) pairs.push('ETHUSDT');
    if (document.getElementById('batch-bnb').checked) pairs.push('BNBUSDT');
    if (document.getElementById('batch-sol').checked) pairs.push('SOLUSDT');
    if (document.getElementById('batch-xrp').checked) pairs.push('XRPUSDT');
    
    if (pairs.length === 0) {
        showNotification('Please select at least one pair to train', 'error');
        return;
    }
    
    const interval = document.getElementById('batch-interval').value;
    const lookback = parseInt(document.getElementById('batch-lookback').value);
    const optimize = document.getElementById('batch-optimize').checked;
    
    if (!confirm(`Train ${pairs.length} pairs? This will take approximately ${pairs.length * (optimize ? 25 : 5)} minutes.`)) {
        return;
    }
    
    // Show progress UI
    const progressDiv = document.getElementById('batch-training-progress');
    const progressList = document.getElementById('batch-progress-list');
    progressDiv.style.display = 'block';
    progressList.innerHTML = '';
    
    // Train each pair sequentially
    let successful = 0;
    let failed = 0;
    
    for (let i = 0; i < pairs.length; i++) {
        const pair = pairs[i];
        
        // Add progress item
        const item = document.createElement('div');
        item.id = `progress-${pair}`;
        item.style.cssText = 'padding: 12px; background: rgba(99, 102, 241, 0.05); border: 1px solid var(--border-color); border-radius: 8px; margin-bottom: 12px;';
        item.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="font-weight: 600;">${pair}</span>
                    <span style="color: var(--text-secondary); margin-left: 8px;">${i+1}/${pairs.length}</span>
                </div>
                <span class="status-badge" style="background: orange;">Training...</span>
            </div>
        `;
        progressList.appendChild(item);
        
        try {
            const response = await fetch('/api/train/advanced', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    symbol: pair,
                    interval: interval,
                    lookback_days: lookback,
                    optimize: optimize
                })
            });
            const data = await response.json();
            
            const statusBadge = item.querySelector('.status-badge');
            
            if (data.success) {
                statusBadge.textContent = `✅ F1: ${(data.f1*100).toFixed(1)}%`;
                statusBadge.style.background = '#10b981';
                successful++;
            } else {
                statusBadge.textContent = `❌ Failed`;
                statusBadge.style.background = '#ef4444';
                failed++;
            }
        } catch (error) {
            const statusBadge = item.querySelector('.status-badge');
            statusBadge.textContent = `❌ Error`;
            statusBadge.style.background = '#ef4444';
            failed++;
        }
    }
    
    // Show final summary
    showNotification(`Training complete: ${successful} successful, ${failed} failed`, successful > 0 ? 'success' : 'error');
    loadModels();  // Refresh models list
}

// Train single model
async function trainModel() {
    const symbol = document.getElementById('train-symbol').value;
    const interval = document.getElementById('train-interval').value;
    const lookback = parseInt(document.getElementById('train-lookback').value);
    const optimize = document.getElementById('train-optimize').checked;
    
    if (!symbol) {
        showNotification('Please enter a symbol', 'error');
        return;
    }
    
    showTrainingStatus();
    
    try {
        const response = await fetch('/api/train/advanced', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                symbol: symbol,
                interval: interval,
                lookback_days: lookback,
                optimize: optimize
            })
        });
        const data = await response.json();
        
        hideTrainingStatus();
        
        if (data.success) {
            showNotification(
                `Training complete! ${symbol} - F1: ${(data.f1*100).toFixed(1)}%, Acc: ${(data.accuracy*100).toFixed(1)}%`, 
                'success'
            );
            loadModels();
        } else {
            showNotification(`Failed to train: ${data.message}`, 'error');
        }
    } catch (error) {
        hideTrainingStatus();
        showNotification(`Error: ${error.message}`, 'error');
    }
}

// Show/hide training status
function showTrainingStatus() {
    document.getElementById('training-status').style.display = 'block';
}

function hideTrainingStatus() {
    document.getElementById('training-status').style.display = 'none';
}

// Load models
async function loadModels() {
    try {
        const response = await fetch('/api/models');
        const data = await response.json();
        
        const container = document.getElementById('models-list');
        
        if (data.models && data.models.length > 0) {
            container.innerHTML = data.models.map(model => `
                <div class="model-card">
                    <div class="model-header">
                        <div class="model-name">${model.symbol} ${model.interval}</div>
                        <span class="status-badge running">${model.model_type}</span>
                    </div>
                    <div class="model-metrics">
                        <div class="model-metric">
                            <span class="model-metric-label">F1 Score</span>
                            <span class="model-metric-value">${(model.f1_score * 100).toFixed(2)}%</span>
                        </div>
                        <div class="model-metric">
                            <span class="model-metric-label">Accuracy</span>
                            <span class="model-metric-value">${(model.accuracy * 100).toFixed(2)}%</span>
                        </div>
                        <div class="model-metric">
                            <span class="model-metric-label">Samples</span>
                            <span class="model-metric-value">${model.samples}</span>
                        </div>
                        <div class="model-metric">
                            <span class="model-metric-label">Trained</span>
                            <span class="model-metric-value">${new Date(model.trained_at).toLocaleDateString()}</span>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="text-muted">No trained models found. Train a model to get started!</p>';
        }
    } catch (error) {
        console.error('Failed to load models:', error);
        document.getElementById('models-list').innerHTML = '<p class="text-muted">Error loading models</p>';
    }
}

// Tab/Page switching
function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Show selected tab
    const selectedTab = document.getElementById(`page-${tabName}`);
    if (selectedTab) {
        selectedTab.classList.add('active');
    }
    
    // Update page title
    const titles = {
        'overview': 'Portfolio Overview',
        'scanner': 'Market Scanner',
        'positions': 'Active Positions',
        'analytics': 'Performance Analytics',
        'training': 'ML Model Training',
        'logs': 'System Logs',
        'settings': 'Bot Settings'
    };
    
    const pageTitle = document.querySelector('.page-title');
    if (pageTitle) {
        pageTitle.textContent = titles[tabName] || 'Dashboard';
    }
    
    // Handle positions tab auto-refresh
    if (tabName === 'positions') {
        startPositionsRefresh();
        stopPortfolioRefresh();
    } else {
        stopPositionsRefresh();
    }
    
    // Handle overview tab auto-refresh
    if (tabName === 'overview') {
        startPortfolioRefresh();
    } else {
        stopPortfolioRefresh();
    }
    
    // Load settings when switching to settings tab
    if (tabName === 'settings') {
        loadSettings();
    }
}

// Market scanner
function scanMarket() {
    const results = document.getElementById('scanner-results');
    results.innerHTML = '<div style="text-align: center; padding: 40px;"><div class="spinner" style="margin: 0 auto 20px;"></div><p>Scanning all USDT pairs... This may take 10-30 seconds</p></div>';
    
    fetch('/api/scan')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.pairs) {
                displayScanResults(data);
            } else {
                results.innerHTML = `<p class="text-muted" style="text-align: center; padding: 40px;">Error: ${data.message || 'Scan failed'}</p>`;
            }
        })
        .catch(error => {
            console.error('Scan error:', error);
            results.innerHTML = `<p class="text-muted" style="text-align: center; padding: 40px;">Error: ${error.message}</p>`;
        });
}

function displayScanResults(data) {
    const results = document.getElementById('scanner-results');
    
    const header = `
        <div style="margin-bottom: 20px; padding: 16px; background: rgba(99, 102, 241, 0.1); border: 1px solid var(--border-color); border-radius: 8px;">
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; text-align: center;">
                <div>
                    <div style="font-size: 12px; color: var(--text-secondary);">Total Scanned</div>
                    <div style="font-size: 24px; font-weight: 700; color: var(--text-primary);">${data.total_scanned}</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: var(--text-secondary);">Models Available</div>
                    <div style="font-size: 24px; font-weight: 700; color: var(--success);">${data.models_available}</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: var(--text-secondary);">Top Pairs Shown</div>
                    <div style="font-size: 24px; font-weight: 700; color: var(--text-primary);">${data.pairs.length}</div>
                </div>
            </div>
        </div>
    `;
    
    const table = `
        <table style="width: 100%;">
            <thead>
                <tr>
                    <th style="text-align: left;">Rank</th>
                    <th style="text-align: left;">Pair</th>
                    <th style="text-align: right;">Price</th>
                    <th style="text-align: right;">24h Change</th>
                    <th style="text-align: right;">Volume (24h)</th>
                    <th style="text-align: center;">ML Model</th>
                    <th style="text-align: center;">Signal</th>
                    <th style="text-align: right;">Confidence</th>
                </tr>
            </thead>
            <tbody>
                ${data.pairs.map((pair, index) => {
                    const changeClass = pair.price_change_24h >= 0 ? 'change-positive' : 'change-negative';
                    const signalClass = pair.ml_signal === 'BUY' ? 'signal-buy' : 'signal-hold';
                    
                    return `
                        <tr>
                            <td>${index + 1}</td>
                            <td style="font-weight: 600;">${pair.symbol}</td>
                            <td style="text-align: right; font-family: monospace;">$${pair.price.toFixed(pair.price < 1 ? 6 : 2)}</td>
                            <td style="text-align: right;" class="${changeClass}">${pair.price_change_24h > 0 ? '+' : ''}${pair.price_change_24h.toFixed(2)}%</td>
                            <td style="text-align: right; font-family: monospace;">$${(pair.volume_24h / 1_000_000).toFixed(1)}M</td>
                            <td style="text-align: center;">
                                ${pair.has_model ? 
                                    `<span class="status-badge running" title="Model accuracy: ${pair.model_accuracy.toFixed(1)}%">✓ ${pair.model_accuracy.toFixed(0)}%</span>` : 
                                    `<span class="status-badge stopped">No Model</span>`
                                }
                            </td>
                            <td style="text-align: center;">
                                ${pair.has_model ? 
                                    `<span class="signal-badge ${signalClass}">${pair.ml_signal}</span>` : 
                                    `<span class="text-muted">-</span>`
                                }
                            </td>
                            <td style="text-align: right;">
                                ${pair.has_model ? 
                                    `
                                    <div style="display: flex; align-items: center; justify-content: flex-end; gap: 8px;">
                                        <div class="confidence-bar">
                                            <div class="confidence-fill" style="width: ${pair.ml_confidence}%;"></div>
                                        </div>
                                        <span style="font-size: 12px; color: var(--text-secondary);">${pair.ml_confidence.toFixed(0)}%</span>
                                    </div>
                                    ` : 
                                    `<span class="text-muted">-</span>`
                                }
                            </td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
    
    results.innerHTML = header + table;
}

// Clear logs
function clearLogs() {
    if (confirm('Are you sure you want to clear the logs display?')) {
        document.getElementById('logs-content').textContent = 'Logs cleared. Refresh to reload.';
    }
}

// Load live positions with enhanced features
const loadPositions = debounce(async function() {
    try {
        setLoadingState('positions-loading', true);

        const data = await cachedFetch('/api/positions', {}, 5000); // Cache for 5 seconds

        if (data.success && data.positions) {
            displayPositions(data.positions);
            updateLiveStats(data);
        } else {
            showError('Positions Error', data.message || 'Failed to load positions');
        }
    } catch (error) {
        console.error('Error loading positions:', error);
        showError('Positions Error', 'Unable to load positions. Please try again.');
    } finally {
        setLoadingState('positions-loading', false);
    }
}, 1000);

function displayPositions(positions) {
    const container = document.getElementById('positions-table');
    
    if (!positions || positions.length === 0) {
        container.innerHTML = '<p class="text-muted" style="text-align: center; padding: 40px;">No active positions</p>';
        return;
    }
    
    const table = `
        <table style="width: 100%;">
            <thead>
                <tr>
                    <th>Pair</th>
                    <th>Entry Price</th>
                    <th>Current Price</th>
                    <th>Peak</th>
                    <th>Trail Stop</th>
                    <th>Size</th>
                    <th>P&L</th>
                    <th>Confidence</th>
                    <th>Duration</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                ${positions.map(pos => {
                    const pnlClass = pos.pnl >= 0 ? 'change-positive' : 'change-negative';
                    const peakPrice = pos.peak_price ? `$${pos.peak_price.toFixed(2)}` : '<span style="color: var(--text-secondary);">-</span>';
                    const trailingStop = pos.trailing_stop ? `$${pos.trailing_stop.toFixed(2)}` : '<span style="color: var(--text-secondary);">-</span>';
                    
                    return `
                        <tr>
                            <td style="font-weight: 600;">${pos.symbol}</td>
                            <td style="font-family: monospace;">$${pos.entry_price.toFixed(2)}</td>
                            <td style="font-family: monospace;">$${pos.current_price.toFixed(2)}</td>
                            <td style="font-family: monospace; color: #10b981;">${peakPrice}</td>
                            <td style="font-family: monospace; color: #f59e0b;">${trailingStop}</td>
                            <td>$${pos.size.toFixed(0)}</td>
                            <td class="${pnlClass}" style="font-weight: 600;">${pos.pnl > 0 ? '+' : ''}$${pos.pnl.toFixed(2)} (${pos.pnl_pct > 0 ? '+' : ''}${pos.pnl_pct.toFixed(2)}%)</td>
                            <td>${pos.ml_confidence > 0 ? (pos.ml_confidence * 100).toFixed(0) + '%' : '<span style="color: var(--text-secondary); font-size: 11px;">Loaded</span>'}</td>
                            <td>${pos.duration}</td>
                            <td>
                                <button class="btn btn-danger btn-sm" onclick="sellPosition('${pos.symbol}', ${pos.current_price})" title="Close position at market price">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                                    </svg>
                                    Sell
                                </button>
                            </td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
    
    container.innerHTML = table;
}

function updateLiveStats(data) {
    // Update bot status
    const botStatus = data.bot_status || 'stopped';
    const statusElement = document.getElementById('live-bot-status');
    if (statusElement) {
        statusElement.textContent = botStatus === 'running' ? '▶️ Running' : '⏸️ Stopped';
    }
    
    const uptimeElement = document.getElementById('live-uptime');
    if (uptimeElement) {
        uptimeElement.textContent = botStatus === 'running' ? 'Active' : 'Not running';
    }
    
    document.getElementById('live-positions-count').textContent = data.positions ? data.positions.length : 0;
    document.getElementById('live-exposure').textContent = `$${data.total_exposure || 0} exposure`;
    document.getElementById('live-total-pnl').textContent = `$${data.total_pnl || 0}`;
    document.getElementById('live-pnl-pct').textContent = `${data.total_pnl_pct || 0}%`;
}

// Load recent trades with search and export
const loadRecentTrades = debounce(async function() {
    try {
        setLoadingState('trades-loading', true);

        const data = await cachedFetch('/api/trades?limit=50', {}, 10000); // Cache for 10 seconds

        if (data.success && data.trades) {
            displayRecentTrades(data.trades);
        } else {
            showError('Trades Error', data.message || 'Failed to load trades');
        }
    } catch (error) {
        console.error('Error loading trades:', error);
        showError('Trades Error', 'Unable to load recent trades. Please try again.');
    } finally {
        setLoadingState('trades-loading', false);
    }
}, 1000);

// Filter trades based on search input
function filterTrades() {
    const searchTerm = document.getElementById('trades-search').value.toLowerCase();
    const rows = document.querySelectorAll('#recent-trades table tbody tr');

    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
    });
}

// Manual position sell function
async function sellPosition(symbol, currentPrice) {
    // Confirm with user
    const confirmed = confirm(
        `Sell ${symbol} at market price (~$${currentPrice.toFixed(2)})?\n\n` +
        `This will:\n` +
        `• Execute a market sell order\n` +
        `• Close the position immediately\n` +
        `• Record the trade in history\n\n` +
        `Are you sure?`
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        showNotification(`Selling ${symbol}...`, 'info', 2000);
        
        const response = await fetch('/api/sell_position', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ symbol: symbol })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification(
                `✅ ${symbol} sold successfully at $${data.price.toFixed(2)}! P&L: ${data.pnl > 0 ? '+' : ''}$${data.pnl.toFixed(2)}`,
                'success',
                5000
            );
            
            // Refresh positions to remove the closed position
            setTimeout(() => {
                loadPositions();
                loadRecentTrades();
            }, 1000);
        } else {
            showNotification(`❌ Failed to sell ${symbol}: ${data.message}`, 'error', 7000);
        }
    } catch (error) {
        console.error('Error selling position:', error);
        showNotification(`❌ Error selling ${symbol}: ${error.message}`, 'error', 7000);
    }
}

// Export functions
async function exportPositions() {
    try {
        const data = await cachedFetch('/api/positions');
        if (data.success && data.positions) {
            const csv = convertToCSV(data.positions, ['symbol', 'entry_price', 'current_price', 'size', 'pnl', 'pnl_pct', 'duration']);
            downloadCSV(csv, 'positions.csv');
            showNotification('Positions exported successfully', 'success');
        }
    } catch (error) {
        showNotification('Failed to export positions', 'error');
    }
}

async function exportTrades() {
    try {
        const data = await cachedFetch('/api/trades?limit=1000');
        if (data.success && data.trades) {
            const csv = convertToCSV(data.trades, ['timestamp', 'symbol', 'action', 'price', 'size', 'pnl', 'pnl_pct', 'confidence']);
            downloadCSV(csv, 'trades.csv');
            showNotification('Trades exported successfully', 'success');
        }
    } catch (error) {
        showNotification('Failed to export trades', 'error');
    }
}

// CSV conversion utility
function convertToCSV(data, headers) {
    const csvRows = [];

    // Add headers
    csvRows.push(headers.join(','));

    // Add data rows
    data.forEach(row => {
        const values = headers.map(header => {
            const value = row[header];
            // Escape commas and quotes in CSV
            if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
                return `"${value.replace(/"/g, '""')}"`;
            }
            return value || '';
        });
        csvRows.push(values.join(','));
    });

    return csvRows.join('\n');
}

// Download CSV utility
function downloadCSV(csv, filename) {
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function displayRecentTrades(trades) {
    const container = document.getElementById('recent-trades');
    
    if (!trades || trades.length === 0) {
        container.innerHTML = '<p class="text-muted" style="text-align: center; padding: 40px;">No recent trades</p>';
        return;
    }
    
    const table = `
        <table style="width: 100%;">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Pair</th>
                    <th>Action</th>
                    <th>Price</th>
                    <th>Size</th>
                    <th>P&L</th>
                    <th>Confidence</th>
                </tr>
            </thead>
            <tbody>
                ${trades.map(trade => {
                    const actionClass = trade.action === 'BUY' ? 'signal-buy' : 'signal-hold';
                    const pnlClass = trade.pnl >= 0 ? 'change-positive' : 'change-negative';
                    return `
                        <tr>
                            <td style="font-size: 12px;">${trade.timestamp}</td>
                            <td style="font-weight: 600;">${trade.symbol}</td>
                            <td><span class="signal-badge ${actionClass}">${trade.action}</span></td>
                            <td style="font-family: monospace;">$${trade.price.toFixed(2)}</td>
                            <td>$${trade.size}</td>
                            <td class="${pnlClass}">${trade.pnl ? (trade.pnl > 0 ? '+' : '') + '$' + trade.pnl.toFixed(2) : '-'}</td>
                            <td>${trade.confidence ? (trade.confidence * 100).toFixed(0) + '%' : '-'}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
    
    container.innerHTML = table;
}

// Add activity to live feed
function addActivityFeedItem(activity) {
    const feed = document.getElementById('activity-feed');
    const item = document.createElement('div');
    item.style.cssText = 'padding: 12px; border-bottom: 1px solid var(--border-color); font-size: 14px;';
    
    const icon = activity.type === 'buy' ? '📈' : activity.type === 'sell' ? '📉' : 'ℹ️';
    const time = new Date().toLocaleTimeString();
    
    item.innerHTML = `
        <span style="color: var(--text-secondary);">[${time}]</span>
        ${icon} ${activity.message}
    `;
    
    if (feed.firstChild && feed.firstChild.classList && feed.firstChild.classList.contains('text-muted')) {
        feed.innerHTML = '';
    }
    
    feed.insertBefore(item, feed.firstChild);
    
    // Keep only last 50 items
    while (feed.children.length > 50) {
        feed.removeChild(feed.lastChild);
    }
}

// Auto-refresh for positions tab
let positionsRefreshInterval = null;

function startPositionsRefresh() {
    loadPositions();
    loadRecentTrades();
    if (!positionsRefreshInterval) {
        positionsRefreshInterval = setInterval(() => {
            loadPositions();
            loadRecentTrades();
        }, 3000);  // Refresh every 3 seconds
    }
}

function stopPositionsRefresh() {
    if (positionsRefreshInterval) {
        clearInterval(positionsRefreshInterval);
        positionsRefreshInterval = null;
    }
}

// Theme toggle event listener
document.addEventListener('DOMContentLoaded', () => {
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }
});

// Initial load with enhanced setup
document.addEventListener('DOMContentLoaded', () => {
    // Setup nav item click handlers
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            // Check if this is an external link (has real href, not just #)
            const href = item.getAttribute('href');
            if (href && href !== '#') {
                // Allow normal navigation for external links
                return;
            }

            e.preventDefault();

            // Update active nav item
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            // Switch to the corresponding tab
            const tabName = item.getAttribute('data-tab');
            if (tabName) {
                switchTab(tabName);
            }
        });
    });

    // Setup keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + K: Focus search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            const searchInput = document.getElementById('trades-search');
            if (searchInput) {
                searchInput.focus();
            }
        }

        // Escape: Clear search
        if (e.key === 'Escape') {
            const searchInput = document.getElementById('trades-search');
            if (searchInput && document.activeElement === searchInput) {
                searchInput.value = '';
                filterTrades();
            }
        }
    });

    // Load initial data
    refreshStatus();
    loadModels();
    loadLogs();

    // Check for URL parameter to switch tab
    const urlParams = new URLSearchParams(window.location.search);
    const tabParam = urlParams.get('tab');

    if (tabParam) {
        // Find and activate the nav item for this tab
        const navItem = document.querySelector(`[data-tab="${tabParam}"]`);
        if (navItem) {
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            navItem.classList.add('active');
            switchTab(tabParam);
        }
    } else {
        // Check which tab is active on load
        const activeTab = document.querySelector('.nav-item.active');
        if (activeTab) {
            const tabName = activeTab.getAttribute('data-tab');
            if (tabName === 'positions') {
                startPositionsRefresh();
            } else if (tabName === 'overview') {
                startPortfolioRefresh();
            }
        } else {
            // Default to overview if no active tab
            startPortfolioRefresh();
        }
    }

    // Show welcome notification
    setTimeout(() => {
        showNotification('Dashboard loaded successfully! Use Ctrl+K to search trades.', 'success', 3000);
    }, 1000);
});

// Load logs
async function loadLogs() {
    const logsContent = document.getElementById('logs-content');
    if (!logsContent) {
        console.error('logs-content element not found');
        return;
    }
    
    try {
        const response = await fetch('/api/logs?lines=100');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        if (data.success && data.logs && data.logs.length > 0) {
            logsContent.textContent = data.logs.join('');
        } else {
            logsContent.textContent = data.logs && data.logs.length > 0 ? data.logs.join('') : 'No logs available';
        }
        
        // Auto-scroll to bottom (do this after setting content)
        setTimeout(() => {
            const container = document.querySelector('.logs-container');
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        }, 100);
    } catch (error) {
        console.error('Failed to load logs:', error);
        logsContent.textContent = `Error loading logs: ${error.message}`;
    }
}

// Show notification
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 20px;
        background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// Auto-refresh logs every 30 seconds (reduced frequency)
setInterval(loadLogs, 30000);

// ===== Bot Activity Monitor =====

const monitorState = {
    connected: false,
    collapsed: false,
    cycleId: null,
    timeframe: null,
    totalPairs: 0,
    analyzedCount: 0,
    perPair: new Map(),  // symbol -> {price, confidence, signal, reason, updatedAt}
    lastCycle: { durationMs: 0, endedAt: null },
    lastEventTime: Date.now()
};

let renderScheduled = false;

function scheduleRender() {
    if (!renderScheduled && !monitorState.collapsed) {
        renderScheduled = true;
        requestAnimationFrame(() => {
            renderMonitor();
            renderScheduled = false;
        });
    }
}

function renderMonitor() {
    // Update cycle info
    if (monitorState.cycleId) {
        document.getElementById('monitor-cycle-id').textContent = monitorState.cycleId.substring(0, 8) + '...';
    }
    document.getElementById('monitor-timeframe').textContent = monitorState.timeframe || '-';
    document.getElementById('monitor-total-pairs').textContent = monitorState.totalPairs || '-';
    
    // Update progress
    const progress = monitorState.totalPairs > 0 ? (monitorState.analyzedCount / monitorState.totalPairs) * 100 : 0;
    document.getElementById('monitor-progress-bar').style.width = `${progress}%`;
    document.getElementById('monitor-progress-bar').setAttribute('aria-valuenow', progress);
    document.getElementById('monitor-progress-text').textContent = `${monitorState.analyzedCount} / ${monitorState.totalPairs}`;
    
    // Update last cycle duration
    if (monitorState.lastCycle.durationMs > 0) {
        const seconds = (monitorState.lastCycle.durationMs / 1000).toFixed(1);
        document.getElementById('monitor-last-duration').textContent = `${seconds}s`;
    }
    
    // Render pairs list
    const container = document.getElementById('monitor-pairs-container');
    if (monitorState.perPair.size === 0) {
        container.innerHTML = '<p class="text-muted" style="text-align: center; padding: 40px;">Waiting for analysis data...</p>';
        return;
    }
    
    let html = '<div style="display: grid; gap: 8px;">';
    const sortedPairs = Array.from(monitorState.perPair.entries()).sort((a, b) => 
        (b[1].updatedAt || 0) - (a[1].updatedAt || 0)
    );
    
    for (const [symbol, data] of sortedPairs) {
        const signalClass = data.signal === 'BUY' ? 'success' : data.signal === 'SELL' ? 'danger' : data.signal === 'ERROR' ? 'warning' : 'secondary';
        const confidence = (data.confidence * 100).toFixed(0);
        const timeAgo = data.updatedAt ? Math.floor((Date.now() - data.updatedAt) / 1000) : 0;
        
        html += `
            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-weight: 600; font-size: 14px;">${symbol}</span>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="status-badge ${signalClass}" style="font-size: 11px; padding: 2px 8px;">${data.signal}</span>
                        ${data.confidence > 0 ? `<span style="font-size: 12px; color: var(--text-secondary);">${confidence}%</span>` : ''}
                    </div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 13px;">
                    <span style="color: var(--text-secondary);">${data.reason || 'Analyzing...'}</span>
                    <span style="font-family: monospace; color: var(--text-secondary);">${data.price > 0 ? '$' + data.price.toFixed(2) : '-'}</span>
                </div>
                ${timeAgo > 0 ? `<div style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;">${timeAgo}s ago</div>` : ''}
            </div>
        `;
    }
    html += '</div>';
    container.innerHTML = html;
}

function toggleMonitor() {
    monitorState.collapsed = !monitorState.collapsed;
    const body = document.getElementById('monitor-body');
    const icon = document.getElementById('monitor-collapse-icon');
    
    if (monitorState.collapsed) {
        body.style.display = 'none';
        icon.textContent = '▶';
    } else {
        body.style.display = 'block';
        icon.textContent = '▼';
        scheduleRender();
    }
}

// SocketIO handlers for monitor
socket.on('cycle_start', (data) => {
    console.log('Cycle started:', data);
    monitorState.cycleId = data.cycle_id;
    monitorState.timeframe = data.timeframe;
    monitorState.totalPairs = data.total_pairs;
    monitorState.analyzedCount = 0;
    monitorState.perPair.clear();
    monitorState.lastEventTime = Date.now();
    scheduleRender();
});

socket.on('pair_analysis_complete', (data) => {
    console.log('Pair analyzed:', data.symbol, data.signal);
    monitorState.perPair.set(data.symbol, {
        price: data.price || 0,
        confidence: data.confidence || 0,
        signal: data.signal,
        reason: data.reason,
        updatedAt: Date.now()
    });
    monitorState.analyzedCount = data.analyzed_index || (monitorState.analyzedCount + 1);
    monitorState.lastEventTime = Date.now();
    scheduleRender();
});

socket.on('cycle_complete', (data) => {
    console.log('Cycle complete:', data);
    monitorState.lastCycle = {
        durationMs: data.duration_ms,
        endedAt: Date.now()
    };
    monitorState.lastEventTime = Date.now();
    scheduleRender();
});

// Update monitor connection indicator
function updateMonitorConnection(connected) {
    monitorState.connected = connected;
    const indicator = document.getElementById('monitor-conn-indicator');
    if (indicator) {
        indicator.className = connected ? 'status-badge connected' : 'status-badge stopped';
        indicator.textContent = '●';
    }
}

socket.on('connect', () => {
    updateMonitorConnection(true);
});

socket.on('disconnect', () => {
    updateMonitorConnection(false);
});

// Check for stale data
setInterval(() => {
    const timeSinceLastEvent = Date.now() - monitorState.lastEventTime;
    if (timeSinceLastEvent > 90000 && monitorState.cycleId) {
        // Show stale warning
        const cycleEl = document.getElementById('monitor-cycle-id');
        if (cycleEl && !cycleEl.textContent.includes('stale')) {
            cycleEl.textContent += ' (stale)';
            cycleEl.style.color = '#fbbf24';
        }
    }
}, 10000);

// Load portfolio data with enhanced error handling
const loadPortfolio = debounce(async function() {
    const elementIds = ['total-balance', 'active-positions', 'total-pnl', 'win-rate'];

    try {
        // Set loading states
        elementIds.forEach(id => setLoadingState(id, true));

        const data = await cachedFetch('/api/portfolio', {}, 10000); // Cache for 10 seconds

        if (data.success) {
            // Clear any previous errors
            document.getElementById('dashboard-errors').style.display = 'none';

            // Update balance
            document.getElementById('total-balance').textContent = `$${data.balance.total.toFixed(2)}`;
            document.getElementById('balance-change').textContent = `${data.balance.free.toFixed(2)} free / ${data.balance.locked.toFixed(2)} locked`;

            // Update positions count
            const posCount = data.positions.count;
            const maxPos = 5; // TODO: Get from config
            document.getElementById('active-positions').textContent = posCount;
            document.getElementById('positions-limit').textContent = `${posCount} / ${maxPos} max`;

            // Update total P&L
            const totalPnl = data.positions.total_pnl || 0;
            const pnlElement = document.getElementById('total-pnl');
            pnlElement.textContent = `$${totalPnl.toFixed(2)}`;
            const pnlChange = document.getElementById('pnl-change');
            if (pnlChange) {
                const pnlPct = data.positions.avg_pnl_pct || 0;
                pnlChange.className = pnlPct >= 0 ? 'stat-change positive' : 'stat-change negative';
                pnlChange.textContent = `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%`;
            }

            // Update win rate
            const winRate = data.performance?.win_rate || 0;
            const totalTrades = data.performance?.total_trades || 0;
            document.getElementById('win-rate').textContent = `${winRate.toFixed(0)}%`;
            document.getElementById('trade-count').textContent = `${totalTrades} trades`;

        } else {
            showError('Failed to load portfolio data', data.message);
        }
    } catch (error) {
        console.error('Failed to load portfolio:', error);
        showError('Portfolio Error', 'Unable to load portfolio data. Please check your connection.');
    } finally {
        // Clear loading states
        elementIds.forEach(id => setLoadingState(id, false));
    }
}, 1000);

// Enhanced error display
function showError(title, message) {
    const errorContainer = document.getElementById('dashboard-errors');
    if (errorContainer) {
        errorContainer.innerHTML = `
            <div class="error-message">
                <div class="error-title">${title}</div>
                <div class="error-details">${message}</div>
            </div>
        `;
        errorContainer.style.display = 'block';
    }
}

// Auto-refresh portfolio every 10 seconds when on Overview page (reduced frequency)
let portfolioRefreshInterval = null;

function startPortfolioRefresh() {
    loadPortfolio();
    if (!portfolioRefreshInterval) {
        portfolioRefreshInterval = setInterval(loadPortfolio, 10000); // Increased to 10s
    }
}

function stopPortfolioRefresh() {
    if (portfolioRefreshInterval) {
        clearInterval(portfolioRefreshInterval);
        portfolioRefreshInterval = null;
    }
}

// Memory cleanup on page unload
window.addEventListener('beforeunload', () => {
    // Clear all intervals
    stopPortfolioRefresh();
    stopPositionsRefresh();

    // Clear all caches
    AppState.cache.clear();
    AppState.notifications.length = 0;
    AppState.loadingStates.clear();

    // Clear any remaining timeouts
    AppState.refreshIntervals.forEach(interval => clearInterval(interval));
    AppState.refreshIntervals.clear();
});

// Load settings from server
async function loadSettings() {
    try {
        const response = await fetch('/api/config');
        const data = await response.json();
        
        if (data.success && data.config) {
            const config = data.config;
            
            // Trading settings
            document.getElementById('setting-trading-mode').value = config.TRADING_MODE || 'testnet';
            document.getElementById('setting-timeframe').value = config.TIMEFRAME || '5m';
            document.getElementById('setting-dry-run').value = config.DRY_RUN || 'true';
            
            // Risk management
            document.getElementById('setting-max-position').value = config.MAX_POSITION_SIZE || 30;
            document.getElementById('setting-stop-loss').value = config.STOP_LOSS_PERCENTAGE || 1.0;
            document.getElementById('setting-take-profit').value = config.TAKE_PROFIT_PERCENTAGE || 2.0;
            
            // Model training
            document.getElementById('setting-symbols').value = config.SYMBOLS || 'ALL';
            document.getElementById('setting-retrain-interval').value = config.RETRAIN_INTERVAL_HOURS || 6;
            document.getElementById('setting-min-volume').value = config.MIN_VOLUME_USDT || 1000000;
            
            // Telegram
            document.getElementById('setting-telegram-token').value = config.TELEGRAM_TOKEN || '';
            document.getElementById('setting-telegram-chat').value = config.TELEGRAM_CHAT_ID || '';
        }
    } catch (error) {
        console.error('Failed to load settings:', error);
        showNotification('Failed to load settings', 'error');
    }
}

// Save settings to server
async function saveSettings() {
    if (!confirm('Save settings and restart bot? Open positions will remain open.')) {
        return;
    }
    
    try {
        const config = {
            TRADING_MODE: document.getElementById('setting-trading-mode').value,
            TIMEFRAME: document.getElementById('setting-timeframe').value,
            DRY_RUN: document.getElementById('setting-dry-run').value,
            MAX_POSITION_SIZE: document.getElementById('setting-max-position').value,
            STOP_LOSS_PERCENTAGE: document.getElementById('setting-stop-loss').value,
            TAKE_PROFIT_PERCENTAGE: document.getElementById('setting-take-profit').value,
            SYMBOLS: document.getElementById('setting-symbols').value,
            RETRAIN_INTERVAL_HOURS: document.getElementById('setting-retrain-interval').value,
            MIN_VOLUME_USDT: document.getElementById('setting-min-volume').value,
            TELEGRAM_TOKEN: document.getElementById('setting-telegram-token').value,
            TELEGRAM_CHAT_ID: document.getElementById('setting-telegram-chat').value
        };
        
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Settings saved! Restarting bot...', 'success');
            
            // Stop bot
            await fetch('/api/stop', {method: 'POST'});
            
            // Wait 2 seconds then restart
            setTimeout(async () => {
                await fetch('/api/start', {method: 'POST'});
                showNotification('Bot restarted with new settings!', 'success');
                refreshStatus();
            }, 2000);
        } else {
            showNotification(`Failed to save settings: ${data.message}`, 'error');
        }
    } catch (error) {
        console.error('Failed to save settings:', error);
        showNotification(`Error: ${error.message}`, 'error');
    }
}
