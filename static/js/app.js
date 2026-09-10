// ============================================================
// YTS Automation Web Interface
// Frontend JavaScript
// ============================================================

// Global state
let selectedDevice = null;
let selectedShortId = null;
let currentSessionId = null;
let logInterval = null;
let lastLogCount = 0;
let deviceDetails = {};

// ============================================================
// Environment Check
// ============================================================

async function checkEnvironment() {
    try {
        const nodeStatus = document.getElementById('node-status');
        const ytsStatus = document.getElementById('yts-status');
        const adbStatus = document.getElementById('adb-status');

        nodeStatus.textContent = '⏳ Checking...';
        nodeStatus.className = 'value loading';

        ytsStatus.textContent = '⏳ Checking...';
        ytsStatus.className = 'value loading';

        adbStatus.textContent = '⏳ Checking...';
        adbStatus.className = 'value loading';

        const response = await fetch('/api/check-environment');
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Environment check failed');
        }

        // Node.js
        nodeStatus.textContent = data.node_installed
            ? '✅ Installed'
            : '❌ Not found';

        nodeStatus.className =
            'value ' + (data.node_installed ? 'success' : 'error');

        // YTS CLI
        ytsStatus.textContent = data.yts_installed
            ? '✅ Installed'
            : '❌ Not found';

        ytsStatus.className =
            'value ' + (data.yts_installed ? 'success' : 'error');

        // ADB
        adbStatus.textContent =
            data.device_count > 0
                ? `✅ ${data.device_count} found`
                : '❌ No devices found';

        adbStatus.className =
            'value ' + (data.device_count > 0 ? 'success' : 'error');

        // Discover devices if available
        if (data.device_count > 0) {
            await discoverDevices();
        }

    } catch (error) {
        console.error('Environment check failed:', error);

        const nodeStatus = document.getElementById('node-status');
        const ytsStatus = document.getElementById('yts-status');
        const adbStatus = document.getElementById('adb-status');

        nodeStatus.textContent = '❌ Error';
        nodeStatus.className = 'value error';

        ytsStatus.textContent = '❌ Error';
        ytsStatus.className = 'value error';

        adbStatus.textContent = '❌ Error';
        adbStatus.className = 'value error';
    }
}

// ============================================================
// Device Discovery
// ============================================================

async function discoverDevices() {
    try {
        const response = await fetch('/api/discover-devices', {
            method: 'POST'
        });

        const data = await response.json();

        const deviceDiv = document.getElementById('devices');

        if (!data.success) {
            deviceDiv.innerHTML =
                `❌ ${escapeHtml(data.error || 'Failed to discover devices')}`;
            return;
        }

        if (!data.devices || data.devices.length === 0) {
            deviceDiv.innerHTML =
                '<p>⚠️ No devices found. Please connect a device and enable USB debugging.</p>';
            return;
        }

        const grid = document.createElement('div');
        grid.className = 'device-grid';

        data.devices.forEach((device, index) => {
            const deviceItem = document.createElement('div');

            deviceItem.className = 'device-item';
            deviceItem.id = `device-${index}`;

            const hasShortId =
                device.has_short_id &&
                device.short_id &&
                device.short_id !== 'Not found';

            deviceItem.innerHTML = `
                <strong>📱 ${escapeHtml(device.id)}</strong><br>
                ${
                    hasShortId
                        ? `<span class="badge success">
                               ✅ Short ID: ${escapeHtml(device.short_id)}
                           </span>`
                        : `<span class="badge error">
                               ❌ No Short ID
                           </span>`
                }
                <br>
                <span style="font-size:12px;color:#7f8c8d;">
                    Click to select
                </span>
            `;

            // Avoid inline onclick handlers.
            deviceItem.addEventListener('click', () => {
                selectDevice(device.id, device.short_id);
            });

            grid.appendChild(deviceItem);
        });

        deviceDiv.innerHTML = '';
        deviceDiv.appendChild(grid);

    } catch (error) {
        console.error('Device discovery error:', error);

        document.getElementById('devices').innerHTML =
            `❌ Error discovering devices: ${escapeHtml(error.message)}`;
    }
}

// ============================================================
// Device Selection
// ============================================================

async function selectDevice(deviceId, shortId) {

    // Clear previous selection
    document
        .querySelectorAll('.device-item')
        .forEach(element => {
            element.classList.remove('selected');
        });

    // Find selected device safely
    const deviceItems =
        document.querySelectorAll('.device-item');

    deviceItems.forEach(element => {
        const strong =
            element.querySelector('strong');

        if (
            strong &&
            strong.textContent.includes(deviceId)
        ) {
            element.classList.add('selected');
        }
    });

    selectedDevice = deviceId;
    selectedShortId = shortId;

    // Update status
    const statusElement =
        document.getElementById('testStatus');

    statusElement.className =
        'test-status ready';

    statusElement.innerHTML =
        `✅ Device selected: ${escapeHtml(deviceId)}`;

    // Show refresh details button
    const refreshButton =
        document.getElementById('refreshDetailsBtn');

    if (refreshButton) {
        refreshButton.style.display =
            'inline-block';
    }

    // Fetch device details
    await fetchDeviceDetails(deviceId);
}

// ============================================================
// Device Details
// ============================================================

async function fetchDeviceDetails(deviceId) {
    try {
        const response =
            await fetch(
                `/api/device-details/${encodeURIComponent(deviceId)}`
            );

        const data =
            await response.json();

        if (!data.success) {
            console.error(
                'Failed to fetch device details:',
                data.error
            );
            return;
        }

        const details =
            data.details || {};

        deviceDetails = details;

        const deviceDetailsElement =
            document.getElementById(
                'deviceDetails'
            );

        if (deviceDetailsElement) {
            deviceDetailsElement.style.display =
                'block';
        }

        setText(
            'detail-device-id',
            deviceId
        );

        setText(
            'detail-model',
            details.model || 'Unknown'
        );

        setText(
            'detail-manufacturer',
            details.manufacturer || 'Unknown'
        );

        setText(
            'detail-android',
            details.android_version || 'Unknown'
        );

        setText(
            'detail-patch',
            details.security_patch || 'Unknown'
        );

        setText(
            'detail-product',
            details.product || 'Unknown'
        );

        setText(
            'detail-fingerprint',
            details.fingerprint || 'Unknown'
        );

        setText(
            'detail-shortid',
            selectedShortId || 'Not found'
        );

    } catch (error) {
        console.error(
            'Error fetching device details:',
            error
        );
    }
}

// ============================================================
// Refresh Device Details
// ============================================================

async function refreshDeviceDetails() {
    if (!selectedDevice) {
        return;
    }

    await fetchDeviceDetails(
        selectedDevice
    );
}

// ============================================================
// Load Tests
// ============================================================

async function loadTests() {
    try {
        const response =
            await fetch('/api/test-commands');

        const data =
            await response.json();

        if (!data.success) {
            throw new Error(
                data.error || 'Failed to load tests'
            );
        }

        const select =
            document.getElementById(
                'testSelect'
            );

        if (!select) {
            console.error(
                'testSelect element not found'
            );
            return;
        }

        // Reset selection
        select.innerHTML =
            '<option value="">-- Select a test --</option>';

        data.tests.forEach(test => {

            const option =
                document.createElement('option');

            option.value =
                test.name;

            // ====================================================
            // IMPORTANT:
            // Only display the test name.
            // Do NOT display Auto / Manual.
            // ====================================================

            option.textContent =
                test.name;

            /*
             * Keep manual information internally.
             *
             * This allows runTest() to continue showing the
             * confirmation dialog when required, without
             * displaying "Manual" or "Auto" in the UI.
             */
            option.dataset.isManual =
                test.is_manual
                    ? 'true'
                    : 'false';

            select.appendChild(option);
        });


        // ========================================================
        // AUTOMATIC TEST INSTRUCTION LOADING
        // ========================================================
        //
        // When the user selects a test from the dropdown,
        // automatically load the corresponding instructions.
        //
        // No separate button click is required.
        // ========================================================

        select.onchange = async function () {

            const testName =
                select.value;

            console.log(
                'Test selected:',
                testName
            );

            // If default option is selected,
            // hide the instruction box.
            if (!testName) {

                const instructionBox =
                    document.getElementById(
                        'instructionsBox'
                    );

                if (instructionBox) {
                    instructionBox.className =
                        'instructions-box';
                }

                return;
            }

            console.log(
                'Loading instructions for:',
                testName
            );

            await showInstructions();
        };

    } catch (error) {

        console.error(
            'Error loading tests:',
            error
        );
    }
}

// ============================================================
// Show Test Instructions
// ============================================================

async function showInstructions() {

    const testSelect =
        document.getElementById(
            'testSelect'
        );

    const testName =
        testSelect
            ? testSelect.value
            : '';

    if (!testName) {
        alert(
            'Please select a test first'
        );
        return;
    }

    try {

        const response =
            await fetch(
                `/api/test-instruction/${encodeURIComponent(testName)}`
            );

        const data =
            await response.json();

        if (!data.success) {
            throw new Error(
                data.error ||
                'Failed to load instructions'
            );
        }

        const box =
            document.getElementById(
                'instructionsBox'
            );

        if (box) {
            box.className =
                'instructions-box show';
        }

        setText(
            'instruction-title',
            `📖 ${data.test_name}`
        );

        const instructionContent =
            document.getElementById(
                'instruction-content'
            );

        if (!instructionContent) {
            return;
        }

        // ========================================================
        // IMPORTANT:
        // Do NOT display Auto / Manual type.
        // ========================================================

        let content = '';

        if (
            data.wait_time !== undefined &&
            data.wait_time !== null &&
            Number(data.wait_time) > 0
        ) {

            content += `
                <p>
                    <strong>⏱️ Wait Time:</strong>
                    ${escapeHtml(
                        String(data.wait_time)
                    )}
                    seconds
                </p>
            `;
        }

        /*
         * Do not expose the raw test command.
         * Only display the instruction text.
         */

        content += `
            <pre style="margin-top:10px;">${escapeHtml(
                data.instruction ||
                'Follow on-screen instructions.'
            )}</pre>
        `;

        instructionContent.innerHTML =
            content;

    } catch (error) {

        console.error(
            'Error loading instructions:',
            error
        );

        alert(
            'Error loading instructions: ' +
            error.message
        );
    }
}

// ============================================================
// Run Test
// ============================================================

async function runTest() {

    const testSelect =
        document.getElementById(
            'testSelect'
        );

    const testName =
        testSelect
            ? testSelect.value
            : '';

    if (!testName) {
        alert(
            'Please select a test'
        );
        return;
    }

    if (!selectedDevice) {
        alert(
            'Please select a device'
        );
        return;
    }

    if (
        !selectedShortId ||
        selectedShortId === 'Not found'
    ) {
        alert(
            'Selected device does not have a short ID. ' +
            'Run "yts discover" first.'
        );
        return;
    }

    // ========================================================
    // Manual test confirmation
    //
    // This behavior remains, but the user does NOT see
    // "Manual" or "Auto" in the test selection list.
    // ========================================================

    const selectedOption =
        testSelect.options[
            testSelect.selectedIndex
        ];

    if (
        selectedOption &&
        selectedOption.dataset.isManual === 'true'
    ) {

        const confirmed =
            confirm(
                '⚠️ This test requires user interaction on the device. Continue?'
            );

        if (!confirmed) {
            return;
        }
    }

    try {

        const response =
            await fetch(
                '/api/run-test',
                {
                    method: 'POST',

                    headers: {
                        'Content-Type':
                            'application/json'
                    },

                    body: JSON.stringify({
                        test_name:
                            testName,

                        device_id:
                            selectedDevice,

                        short_id:
                            selectedShortId
                    })
                }
            );

        const data =
            await response.json();

        if (
            !response.ok ||
            !data.success
        ) {

            alert(
                'Failed to start test: ' +
                (
                    data.error ||
                    'Unknown error'
                )
            );

            return;
        }

        currentSessionId =
            data.session_id;

        const statusElement =
            document.getElementById(
                'testStatus'
            );

        statusElement.className =
            'test-status running';

        statusElement.innerHTML =
            `▶️ Running test:
             <strong>${escapeHtml(testName)}</strong>
             <span class="spinner">⏳</span>`;

        document.getElementById(
            'logs'
        ).innerHTML = '';

        lastLogCount = 0;

        addLog(
            '🚀 Test started: ' +
            testName,
            'info'
        );

        addLog(
            `📱 Device: ${selectedDevice} ` +
            `(Short ID: ${selectedShortId})`,
            'info'
        );

        // Start polling
        if (logInterval) {
            clearInterval(
                logInterval
            );
        }

        logInterval =
            setInterval(
                pollLogs,
                2000
            );

    } catch (error) {

        console.error(
            'Error starting test:',
            error
        );

        alert(
            'Error: ' +
            error.message
        );
    }
}

// ============================================================
// Poll Test Logs / Status
// ============================================================

async function pollLogs() {

    if (!currentSessionId) {
        return;
    }

    try {

        const response =
            await fetch(
                `/api/test-status/${encodeURIComponent(currentSessionId)}`
            );

        const data =
            await response.json();

        if (
            !response.ok ||
            !data.success
        ) {

            console.error(
                'Test status error:',
                data.error
            );

            return;
        }

        // Update logs
        if (Array.isArray(data.logs)) {

            const newLogs =
                data.logs.slice(
                    lastLogCount
                );

            newLogs.forEach(log => {

                addLog(
                    log.message || '',
                    'info',
                    log.time || null
                );

            });

            lastLogCount =
                data.logs.length;
        }

        // Update test status
        if (
            data.status === 'completed' ||
            data.status === 'failed'
        ) {

            if (logInterval) {

                clearInterval(
                    logInterval
                );

                logInterval = null;
            }

            const statusElement =
                document.getElementById(
                    'testStatus'
                );

            statusElement.className =
                `test-status ${data.status}`;

            const passed =
                data.result === 'PASSED';

            statusElement.innerHTML =
                `${data.status === 'completed' ? '✅' : '❌'}
                 Test ${data.status}:
                 ${escapeHtml(data.result || 'Done')}`;

            addLog(
                `📊 Test ${data.status} with result: ${
                    data.result || 'N/A'
                }`,
                passed
                    ? 'success'
                    : 'error'
            );
        }

    } catch (error) {

        console.error(
            'Error polling logs:',
            error
        );
    }
}

// ============================================================
// Add Log
// ============================================================

function addLog(
    message,
    type = 'info',
    time = null
) {

    const logDiv =
        document.getElementById(
            'logs'
        );

    if (!logDiv) {
        return;
    }

    const timestamp =
        time ||
        new Date().toLocaleTimeString();

    const entry =
        document.createElement('div');

    entry.className =
        `log-entry ${type}`;

    const timestampSpan =
        document.createElement('span');

    timestampSpan.className =
        'timestamp';

    timestampSpan.textContent =
        `[${timestamp}]`;

    entry.appendChild(
        timestampSpan
    );

    entry.appendChild(
        document.createTextNode(
            ` ${message}`
        )
    );

    logDiv.appendChild(
        entry
    );

    logDiv.scrollTop =
        logDiv.scrollHeight;
}

// ============================================================
// Clear Logs
// ============================================================

function clearLogs() {

    const logs =
        document.getElementById(
            'logs'
        );

    if (!logs) {
        return;
    }

    logs.innerHTML =
        '<div style="color:#7f8c8d;">Logs cleared...</div>';

    lastLogCount = 0;
}

// ============================================================
// Load Previous Results
// ============================================================

async function loadResults() {

    try {

        const response =
            await fetch(
                '/api/test-results'
            );

        const data =
            await response.json();

        const display =
            document.getElementById(
                'resultsDisplay'
            );

        if (!display) {
            return;
        }

        if (data.success) {

            display.style.display =
                'block';

            display.textContent =
                data.results ||
                'No results available';

        } else {

            display.textContent =
                data.error ||
                'Unable to load results';
        }

    } catch (error) {

        console.error(
            'Error loading results:',
            error
        );

        alert(
            'Error loading results: ' +
            error.message
        );
    }
}

// ============================================================
// Utility Functions
// ============================================================

function setText(
    elementId,
    value
) {

    const element =
        document.getElementById(
            elementId
        );

    if (element) {

        element.textContent =
            value;
    }
}


function escapeHtml(value) {

    if (
        value === null ||
        value === undefined
    ) {
        return '';
    }

    return String(value)
        .replace(
            /&/g,
            '&amp;'
        )
        .replace(
            /</g,
            '&lt;'
        )
        .replace(
            />/g,
            '&gt;'
        )
        .replace(
            /"/g,
            '&quot;'
        )
        .replace(
            /'/g,
            '&#039;'
        );
}

// ============================================================
// Initialize Application
// ============================================================

document.addEventListener(
    'DOMContentLoaded',
    () => {

        checkEnvironment();

        loadTests();

    }
);
