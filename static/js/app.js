// YTS Automation Web Interface - Linux server-side execution
let selectedDevice = null;
let selectedShortId = null;
let currentSessionId = null;
let logInterval = null;
let lastLogSeq = 0;

async function getJson(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
}

async function checkEnvironment() {
    const nodeStatus = document.getElementById('node-status');
    const ytsStatus = document.getElementById('yts-status');
    const adbStatus = document.getElementById('adb-status');
    const networkStatus = document.getElementById('network-status');
    [nodeStatus, ytsStatus, adbStatus, networkStatus].forEach(el => {
        if (el) { el.textContent = '⏳ Checking...'; el.className = 'value loading'; }
    });
    try {
        const data = await getJson('/api/check-environment');
        if (nodeStatus) { nodeStatus.textContent = data.node_installed ? '✅ Installed' : '❌ Not found'; nodeStatus.className = 'value ' + (data.node_installed ? 'success' : 'error'); }
        if (ytsStatus) { ytsStatus.textContent = data.yts_installed ? '✅ Ready' : '❌ Not found'; ytsStatus.className = 'value ' + (data.yts_installed ? 'success' : 'error'); }
        if (adbStatus) { adbStatus.textContent = data.device_count ? `✅ ${data.device_count} found` : '❌ No devices found'; adbStatus.className = 'value ' + (data.device_count ? 'success' : 'error'); }
        if (networkStatus) {
            const rejected = Object.keys(data.rejected_devices || {}).length;
            networkStatus.textContent = rejected ? `⚠️ ${rejected} device(s) outside 192.168.x.x` : '✅ 192.168.x.x supported';
            networkStatus.className = 'value ' + (rejected ? 'error' : 'success');
        }
        await discoverDevices();
    } catch (error) {
        console.error('Environment check error:', error);
        if (nodeStatus) nodeStatus.textContent = '❌ Server check failed';
        if (ytsStatus) ytsStatus.textContent = '—';
        if (adbStatus) { adbStatus.textContent = '❌ Server ADB unavailable'; adbStatus.className = 'value error'; }
        if (networkStatus) networkStatus.textContent = '—';
    }
}

async function discoverDevices() {
    const deviceDiv = document.getElementById('devices');
    try {
        const data = await getJson('/api/discover-devices', {method: 'POST'});
        if (!data.devices?.length) {
            const rejected = Object.keys(data.rejected || {});
            deviceDiv.innerHTML = rejected.length
                ? `<p>⚠️ No supported DUTs found. ${rejected.length} device(s) are outside 192.168.x.x.</p>`
                : '<p>⚠️ No ADB DUTs found on the server.</p>';
            return;
        }
        const grid = document.createElement('div');
        grid.className = 'device-grid';
        data.devices.forEach((device, index) => {
            const item = document.createElement('div');
            item.className = 'device-item';
            item.id = `device-${index}`;
            const hasShortId = device.has_short_id && device.short_id && device.short_id !== 'Not found';
            if (device.network_valid === false) {
                item.innerHTML = `<strong>📱 ${escapeHtml(device.id)}</strong><br><span class="badge error">❌ Unsupported network</span><br><span style="font-size:12px;color:#7f8c8d;">${escapeHtml(device.network_error || '')}</span>`;
            } else {
                item.innerHTML = `<strong>📱 ${escapeHtml(device.id)}</strong><br>${hasShortId ? `<span class="badge success">✅ Short ID: ${escapeHtml(device.short_id)}</span>` : '<span class="badge error">❌ No Short ID</span>'}<br><span style="font-size:12px;color:#7f8c8d;">Click to select</span>`;
                if (hasShortId) item.addEventListener('click', () => selectDevice(device.id, device.short_id));
            }
            grid.appendChild(item);
        });
        deviceDiv.replaceChildren(grid);
    } catch (error) {
        console.error('Device discovery error:', error);
        deviceDiv.innerHTML = `❌ Error discovering devices: ${escapeHtml(error.message)}`;
    }
}

async function selectDevice(deviceId, shortId) {
    document.querySelectorAll('.device-item').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.device-item').forEach(el => { if (el.querySelector('strong')?.textContent.includes(deviceId)) el.classList.add('selected'); });
    selectedDevice = deviceId;
    selectedShortId = shortId;
    const status = document.getElementById('testStatus');
    status.className = 'test-status ready';
    status.innerHTML = `✅ Device selected: ${escapeHtml(deviceId)}`;
    const refresh = document.getElementById('refreshDetailsBtn');
    if (refresh) refresh.style.display = 'inline-block';
    await fetchDeviceDetails(deviceId);
}

async function fetchDeviceDetails(deviceId) {
    try {
        const data = await getJson(`/api/device-details/${encodeURIComponent(deviceId)}`);
        const details = data.details || {};
        const values = {
            'detail-device-id': deviceId,
            'detail-model': details.model || 'Unknown',
            'detail-manufacturer': details.manufacturer || 'Unknown',
            'detail-android': details.android_version || 'Unknown',
            'detail-patch': details.security_patch || 'Unknown',
            'detail-product': details.product || 'Unknown',
            'detail-fingerprint': details.fingerprint || 'Unknown',
            'detail-shortid': selectedShortId || 'Not found',
            'detail-network': data.network || '192.168.x.x supported'
        };
        document.getElementById('deviceDetails').style.display = 'block';
        Object.entries(values).forEach(([id, value]) => setText(id, value));
    } catch (error) { console.error('Error fetching device details:', error); }
}

async function refreshDeviceDetails() { if (selectedDevice) await fetchDeviceDetails(selectedDevice); }

async function loadTests() {
    try {
        const data = await getJson('/api/test-commands');
        const select = document.getElementById('testSelect');
        select.innerHTML = '<option value="">-- Select a test --</option>';
        data.tests.forEach(test => {
            const option = document.createElement('option');
            option.value = test.name;
            option.textContent = test.name;
            option.dataset.isManual = test.is_manual ? 'true' : 'false';
            select.appendChild(option);
        });
        select.onchange = () => select.value ? showInstructions() : document.getElementById('instructionsBox').className = 'instructions-box';
    } catch (error) { console.error('Error loading tests:', error); }
}

async function showInstructions() {
    const testName = document.getElementById('testSelect')?.value;
    if (!testName) return;
    try {
        const data = await getJson(`/api/test-instruction/${encodeURIComponent(testName)}`);
        document.getElementById('instructionsBox').className = 'instructions-box show';
        setText('instruction-title', `📖 ${data.test_name}`);
        let content = '';
        if (Number(data.wait_time) > 0) content += `<p><strong>⏱️ Wait Time:</strong> ${escapeHtml(String(data.wait_time))} seconds</p>`;
        content += `<pre style="margin-top:10px;">${escapeHtml(data.instruction || 'Follow the documented YTS instructions.')}</pre>`;
        document.getElementById('instruction-content').innerHTML = content;
    } catch (error) { alert('Error loading instructions: ' + error.message); }
}

async function runTest() {
    const select = document.getElementById('testSelect');
    const testName = select?.value;
    if (!testName) return alert('Please select a test');
    if (!selectedDevice || !selectedShortId) return alert('Please select a DUT with a valid Short ID');
    const option = select.options[select.selectedIndex];
    if (option?.dataset.isManual === 'true' && !confirm('⚠️ This test requires user interaction on the device. Continue?')) return;
    try {
        const data = await getJson('/api/run-test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({test_name:testName, device_id:selectedDevice, short_id:selectedShortId})});
        currentSessionId = data.session_id;
        lastLogSeq = 0;
        document.getElementById('logs').innerHTML = '';
        const status = document.getElementById('testStatus');
        status.className = 'test-status running';
        status.innerHTML = `▶️ Running test: <strong>${escapeHtml(testName)}</strong> <span class="spinner">⏳</span>`;
        addLog(`🚀 Test started: ${testName}`, 'info');
        addLog(`📱 DUT: ${selectedDevice} (Short ID: ${selectedShortId})`, 'info');
        if (logInterval) clearInterval(logInterval);
        await pollLogs();
        logInterval = setInterval(pollLogs, 2000);
    } catch (error) { alert('Failed to start test: ' + error.message); }
}

async function pollLogs() {
    if (!currentSessionId) return;
    try {
        const data = await getJson(`/api/test-status/${encodeURIComponent(currentSessionId)}`);
        if (Array.isArray(data.logs)) {
            data.logs.filter(log => Number(log.seq || 0) > lastLogSeq).forEach(log => addLog(log.message || '', 'info', log.time || null));
            lastLogSeq = data.logs.reduce((max, log) => Math.max(max, Number(log.seq || 0)), lastLogSeq);
        }
        if (data.status === 'completed' || data.status === 'failed') {
            if (logInterval) clearInterval(logInterval);
            logInterval = null;
            const status = document.getElementById('testStatus');
            status.className = `test-status ${data.status}`;
            status.innerHTML = `${data.status === 'completed' ? '✅' : '❌'} Test ${data.status}: ${escapeHtml(data.result || 'Done')}`;
            addLog(`📊 Test ${data.status}: ${data.result || 'N/A'}`, data.result === 'PASSED' ? 'success' : 'error');
        }
    } catch (error) { console.error('Test status polling failed:', error); }
}

async function runSuite() {
    if (!selectedDevice || !selectedShortId) return alert('Please select a device with a valid Short ID');
    const names = Array.from(document.querySelectorAll('#testSelect option:checked')).map(o => o.value).filter(Boolean);
    if (!names.length) return alert('Select tests before running a suite');
    try {
        const data = await getJson('/api/run-suite', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({test_names:names, device_id:selectedDevice, short_id:selectedShortId})});
        currentSessionId = data.session_id;
        lastLogSeq = 0;
        if (logInterval) clearInterval(logInterval);
        document.getElementById('logs').innerHTML = '';
        await pollLogs();
        logInterval = setInterval(pollLogs, 2000);
    } catch (error) { alert('Failed to start suite: ' + error.message); }
}

function addLog(message, type='info', time=null) {
    const logDiv = document.getElementById('logs');
    if (!logDiv) return;
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    if (time) { const stamp=document.createElement('span'); stamp.className='log-time'; stamp.textContent=`[${time}]`; entry.appendChild(stamp); }
    entry.appendChild(document.createTextNode(` ${message}`));
    logDiv.appendChild(entry);
    logDiv.scrollTop = logDiv.scrollHeight;
}

function clearLogs() { document.getElementById('logs').innerHTML='<div style="color:#7f8c8d;">Logs cleared...</div>'; lastLogSeq=0; }

async function loadResults() {
    try {
        const data = await getJson('/api/test-results');
        const display = document.getElementById('resultsDisplay');
        display.style.display='block';
        display.textContent = typeof data.results === 'string' ? data.results : JSON.stringify(data.results, null, 2);
    } catch (error) { alert('Error loading results: ' + error.message); }
}

function setText(id,value){const el=document.getElementById(id);if(el)el.textContent=value;}
function escapeHtml(value){if(value===null||value===undefined)return '';return String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');}

document.addEventListener('DOMContentLoaded',()=>{loadTests();checkEnvironment();});
