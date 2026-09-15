/**
 * Reusable WebSocket connection manager for the session_{id} channel group.
 *
 * Usage (on the main session page):
 *   const conn = createSessionSocket(sessionId, {
 *       onMessage: (event) => { ... your full switch statement ... },
 *       onConnectionChange: (state) => { ... update a visible indicator of websocket connection ... },
 *   });
 *   conn.connect();
 *
 * Usage (on a different page that only cares about status, e.g. a dashboard badge):
 *   const conn = createSessionSocket(sessionId, {
 *       onMessage: (event) => {
 *           if (event.type === 'session_status') updateBadge(event.status);
 *       },
 *   });
 *   conn.connect();
 *
 * Call conn.disconnect() when leaving the page / removing the badge, to stop
 * reconnect attempts and close cleanly.
 */

const TERMINAL_STATUSES = ['complete', 'error', 'finished', 'stopped'];

const PAUSE_CONF_TEXT = {
    'pause_set': 'Pause between grids is set',
    'pause_unset': 'Pause between grids unset',
};

const PAUSE_STATUS_TEXT = {
    'signal_send': 'Pause between grids signal received',
    'signal_received': 'Pause between grids signal resolved',
};

const SESSION_STATUS_TEXT = {
    'running': 'Session is running',
    'complete': 'Session is complete',
    'finished': 'Session is complete', // alternative status from frontend 
    'error': 'Error in grid aquisition',
    'stopped': 'Session was stopped',
    'killed': 'Session was killed',
};

function createSessionSocket(sessionId, options = {}) {
    const {
        onMessage = () => {},
        // onConnectionChange = () => {},
        basePath = '/websocket/session_id=',
        maxReconnectAttempts = Infinity, // set a finite number if you want a hard cap
        baseDelayMs = 5000,
    } = options;

    const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    const url = `${protocol}${window.location.host}${basePath}${sessionId}`;

    let socket = null;
    let reconnectAttempts = 0;
    let reconnectTimeoutHandle = null;
    let intentionalClose = false;

    function connect() {
                // onConnectionChange('connecting');
        socket = new WebSocket(url);

        socket.onopen = function () {
            reconnectAttempts = 0;
            // onConnectionChange('connected');
        };

        socket.onmessage = function (e) {
            let event;
            try {
                event = JSON.parse(e.data);
            } catch (err) {
                console.error('Failed to parse WS message', err, e.data);
                return;
            }

            onMessage(event);
        };

        socket.onclose = function (e) {
            console.warn('Session socket closed', e.code, e.reason);
            // onConnectionChange('disconnected');

            if (!intentionalClose) {
                scheduleReconnect();
            }
        };

        socket.onerror = function (e) {
            console.error('Session socket error', e);
            // onclose always follows onerror -- reconnect logic lives there only
        };
    }

    function scheduleReconnect() {
        if (reconnectAttempts >= maxReconnectAttempts) {
            // onConnectionChange('failed');
            return;
        }

        reconnectAttempts++;

        // onConnectionChange('connecting');
        reconnectTimeoutHandle = setTimeout(connect, baseDelayMs);
    }

    function disconnect() {
        intentionalClose = true;
        if (reconnectTimeoutHandle) clearTimeout(reconnectTimeoutHandle);
        if (socket) socket.close();
    }

    // function send(data) {
    //     if (socket && socket.readyState === WebSocket.OPEN) {
    //         socket.send(JSON.stringify(data));
    //     }
    // }

    return { connect, disconnect };
}