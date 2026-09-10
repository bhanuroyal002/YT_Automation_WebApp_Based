// YTS Automation Web Interface - Linux local execution
let selectedDevice = null;
let selectedShortId = null;
let currentSessionId = null;
let logInterval = null;
let lastLogSeq = 0;

async function getJson(url, options = {}) {
    const response = await fetch(url, options);
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok || data.success === false) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
}

function isNetworkDevice(deviceId) {
    return typeof deviceId === 'string' && deviceId.includes(':');
}

function getDeviceHost(deviceId) {
    if (!isNetworkDevice(deviceId)) return null;
    const value = deviceId.slice(0, deviceId.lastIndexOf(':')).replace(/^\[/, '').replace(/\]$/, '');
    return value;
}

function isSupportedDutNetwork(deviceId) {
    const host = getDeviceHost(deviceId);
    if (!host) return true; // USB ADB is supported.
    const parts = host.split('.').map(Number);
    return parts.length === 4 && parts[0] === 192 && parts.every(n => Number.isInteger(n) && n >= 0 && n <= 255);
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
        if (nodeStatus) {
            nodeStatus.textContent = data.node_installed ? '✅ Installed' : '❌ Not found';
            nodeStatus.className = 'value ' + (data.node_installed ? 'success' : 'error');
        }
        if (ytsStatus) {
            ytsStatus.textContent = data.yts_installed ? '✅ Ready' : '❌ Not found';
            ytsStatus.className = 'value ' + (data.yts_installed ? 'success' : 'error');
        }
        const devices = data.devices || [];
        const supported = devices.filter(isSupportedDutNetwork);
        if (adbStatus) {
            adbStatus.textContent = supported.length ? `✅ ${supported.length} found` : '❌ No supported devices found';
            adbStatus.className = 'value ' + (supported.length ? 'success' : 'error');
        }
        const networkDevices = devices.filter(isNetworkDevice);
        const unsupported = networkDevices.filter(d => !isSupportedDutNetwork(d));
        if (networkStatus) {
            networkStatus.textContent = unsupported.length
                ? `⚠️ ${unsupported.length} outside 192.168.x.x`
                : '✅ 192.168.x.x supported';
            networkStatus.className = 'value ' + (unsupported.length ? 'error' : 'success');
        }
        await discoverDevices(false);
    } catch (error) {
        console.error('Environment check error:', error);
        if (nodeStatus) nodeStatus.textContent = '❌ Server check failed';
        if (ytsStatus) ytsStatus.textContent = '—';
        if (adbStatus) { adbStatus.textContent = '❌ ADB unavailable'; adbStatus.className = 'value error'; }
        if (networkStatus) { networkStatus.textContent = '—'; networkStatus.className = 'value'; }
    }
}

async function discoverDevices(showAlert = true) {
    const deviceDiv = document.getElementById('devices');
    try {
        const data = await getJson('/api/discover-devices', {method: 'POST'});
        const devices = (data.devices || []).filter(device => isSupportedDutNetwork(device.id));
        const rejected = (data.devices || []).filter(device => !isSupportedDutNetwork(device.id));
        if (!devices.length) {
            deviceDiv.innerHTML = rejected.length
                ? `<p>⚠️ No supported DUTs found. ${rejected.length} network device(s) are outside 192.168.x.x.</p>`
                : '<p>⚠️ No ADB DUTs found. Connect the DUT and click Discover Devices.</p>';
            return;
        }
        const grid = document.createElement('div');
        grid.className = 'device-grid';
        devices.forEach((device, index) => {
            const item = document.createElement('div');
            item.className = 'device-item';
            item.id = `device-${index}`;
            const hasShortId = device.has_short_id && device.short_id && device.short_id !== 'Not found';
            const networkBadge = isNetworkDevice(device.id)
                ? '<span class="badge success">✅ 192.168.x.x network</span>'
                : '<span class="badge success">✅ USB ADB</span>';
            item.innerHTML = `<strong>📱 ${escapeHtml(device.id)}</strong><br>${networkBadge}<br>${hasShortId ? `<span class="badge success">✅ Short ID: ${escapeHtml(device.short_id)}</span>` : '<span class="badge error">❌ No Short ID</span>'}<br><span style="font-size:12px;color:#7f8c8d;">Click to select</span>`;
            if (hasShortId) item.addEventListener('click', () => selectDevice(device.id, device.short_id));
            grid.appendChild(item);
        });
        deviceDiv.replaceChildren(grid);
    } catch (error) {
        console.error('Device discovery error:', error);
        deviceDiv.innerHTML = `❌ Error discovering devices: ${escapeHtml(error.message)}`;
        if (showAlert) alert('Error discovering devices: ' + error.message);
    }
}

async function selectDevice(deviceId, shortId) {
    if (!isSupportedDutNetwork(deviceId)) return alert('Only 192.168.x.x network DUTs are supported.');
    document.querySelectorAll('.device-item').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.device-item').forEach(el => {
        if (el.querySelector('strong')?.textContent.includes(deviceId)) el.classList.add('selected');
    });
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
            'detail-network': isNetworkDevice(deviceId) ? '192.168.x.x' : 'USB ADB'
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
        select.onchange = () => select.value ? showInstructions() : hideInstructions();
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
        if (data.is_manual) content += '<p><strong>⚠️ Manual test:</strong> User interaction is required on the DUT.</p>';
        content += `<pre style="margin-top:10px;white-space:pre-wrap;">${escapeHtml(data.instruction || 'Follow the documented YTS instructions.')}</pre>`;
        document.getElementById('instruction-content').innerHTML = content;
    } catch (error) { alert('Error loading instructions: ' + error.message); }
}

function hideInstructions() {
    const box = document.getElementById('instructionsBox');
    if (box) box.className = 'instructions-box';
}

async function runTest() {
    const select = document.getElementById('testSelect');
    const testName = select?.value;
    if (!testName) return alert('Please select a test');
    if (!selectedDevice || !selectedShortId) return alert('Please select a DUT with a valid Short ID');
    if (!isSupportedDutNetwork(selectedDevice)) return alert('Only 192.168.x.x network DUTs are supported.');
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
