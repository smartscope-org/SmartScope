var url = window.location.href;
var currentState = new Object



var pathname = new URL(url).pathname;

path = pathname.split('/')

function delay(fn, ms) {
    let timer = 0
    return function(...args) {
      clearTimeout(timer)
      timer = setTimeout(fn.bind(this, ...args), ms || 0)
    }
  }

function selected() {
    $('.list-group-item.active', '#sidebar-container').removeClass('active');
    for (const [key, val] of Object.entries(currentState)) {
        // console.log(`${key}, ${val}`)
        if (['group', 'session_id', 'grid_id'].includes(key) && val !== undefined) {
            $(`#${val}`).addClass('active')
        }
    }
}



async function loadSidePanelState() {
    await loadSidePanel(null, null, push = false)
    for (const [key, val] of Object.entries(currentState)) {
        // console.log(`${key}, ${val}`)
        if (['group', 'session_id'].includes(key) && val !== undefined) {
            await loadSidePanel(key, val, push = false)
            if ( key == 'session_id' ) {
                const conn = createSessionSocket(val, {
                    onMessage: function (event) {
                        if (event.type !== 'session_logs' && event.type !== 'log_batch') {
                            showNotification(event);
                        }
                    },
                });
                conn.connect();
            }
        } else if (key == 'grid_id') {
            await loadReport(key, val, push = false)
        }
    }
}

function pushState() {
    var string = "?"
    for (const [key, value] of Object.entries(currentState)) {
        string += `${key}=${value}&`;
    }
    window.history.replaceState(currentState, document.title, pathname + string)
}

function updateFullMeta(data) {
    console.log(data)
    fullmeta = {
        ...fullmeta, ...data,
        atlas: { ...fullmeta.atlas, ...data.atlas },
        squares: { ...fullmeta.squares, ...data.squares },
        holes: { ...fullmeta.holes, ...data.holes }
    }
    console.log(fullmeta)
}

(function() {
    const idGen = () => {
        return Math.floor((1 + Math.random()) * 0x10000)
            .toString(16)
            .substring(1);
    }

    const createLoadingMessage = (message) => {
        let id = idGen()
        $('#loadingMessages').append(
            `<div class="notification d-inline-flex justify-content-end">
                <div id="${id}" class="alert mb-0 mt-1 alert-primary fade show" role="alert">
                    <span>${message}</span>
                </div>
            </div>`)
        return id
    }

    const processLoadingMessage = (response, id) => {
        let elem = $(`#loadingMessages [id="${id}"]`)
        if (response.ok) {
            elem.removeClass('alert-primary').addClass('alert-success')
            setTimeout(function() {
                $(`#loadingMessages [id="${id}"]`).alert('close');
                $(`#loadingMessages [id="${id}"]`).parent().remove()
            }, 2000);
        } else {
            elem.removeClass('alert-primary').addClass('alert-danger')
        }
    }

    window.createLoadingMessage = createLoadingMessage;
    window.processLoadingMessage = processLoadingMessage;
})()

function createHTMXloadingMessage(event, message) {
    console.log('Creating htmx loading message')
    messageID = createLoadingMessage(message)
    event.target.setAttribute('messageid', messageID)
}
function applyTagFilter() {
      currentState['sample_type_tag'] = Array.from(document.querySelectorAll('.filter-sample-type:checked')).map(e => e.value)
      currentState['project_tag'] = Array.from(document.querySelectorAll('.filter-project:checked')).map(e => e.value)
      loadSidePanel('group', currentState['group'])
      $('#sidebarGrids').html('')
      bootstrap.Dropdown.getOrCreateInstance(document.querySelector('.bi-funnel')).hide()
}

function clearTagFilter() {
    currentState['sample_type_tag'] = []
    currentState['project_tag'] = []
    for (const e of document.querySelectorAll('.filter-sample-type, .filter-project')) { e.checked = false }
    loadSidePanel('group', currentState['group'])
    $('#sidebarGrids').html('')
}

function createLongHTMXloadingMessage(event,message) {
    console.log('Creating long htmx loading message')
    messageID = createLoadingMessage(message)
    event.target.setAttribute('messageid', messageID)
    // event.target.setAttribute('hx-target', `#${messageID}`)
    event.target.setAttribute("hx-vals", JSON.stringify({message_id:messageID}))
}

function processHTMXloadingMessage(event) {
    console.log('Processing htmx loading message')
    const responseCode = event.detail.xhr.status;
    const response = {ok: responseCode < 400}
    processLoadingMessage(response, event.target.getAttribute('messageid'))
}

async function fetchAsync(url, message='alert') {
    let id = createLoadingMessage(message)
    let response = await fetch(url);
    processLoadingMessage(response,id)
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.indexOf("application/json") !== -1) {
        return response.json()
    } else {
        return response.text()
    }
};


async function apifetchAsync(url, dict, method, message='alert!') {
    content = {
        method: method,
        headers: {
            'X-CSRFToken': csrftoken,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'mode': 'same-origin'
        },
        signal: AbortSignal.timeout(120000)
    }
    let id = createLoadingMessage(message)
    if (dict != null) {
        content.body = JSON.stringify(dict)
    }
    let response = await fetch(url, content);
    processLoadingMessage(response,id)
    let data = await response.json();
    return data;
};

function pickHex(color1, color2, min, max, val) {
    var value = (val - min) / (max - min)
    var p = Math.min.apply(null, [1, value]);
    console.log(value, p)
    var w = p * 2 - 1;
    var w1 = (w / 1 + 1) / 2;
    var w2 = 1 - w1;
    var rgb = [Math.round(color1[0] * w1 + color2[0] * w2),
    Math.round(color1[1] * w1 + color2[1] * w2),
    Math.round(color1[2] * w1 + color2[2] * w2)];
    return rgb;
}

function arrayRemove(arr, value) {

    return arr.filter(function (ele) {
        return ele != value;
    });
}

async function updateTarget(type, ids, key, new_value, useAPI = false) {
    console.log(`UPDATING ${type}, ${ids}, ${key} to ${new_value}`)

    var dict = {}
    dict['key'] = key
    dict['new_value'] = new_value
    dict['type'] = type
    dict['ids'] = ids
    console.log(dict)
    var url = `/api/updatetargets/`
    if (socket !== null) {
        if (socket.readyState !== WebSocket.OPEN) {
            console.log('Websocket closed, cannot run update')

        } else {
            console.log('Using websocket')
            return await websocketSend('update.target', dict)
        }
    }
    if (useAPI) {
        console.log('Running api')
        return await apifetchAsync(url, dict, "PATCH")
    }
}

function checkState() {

    var state = url.match(/([a-zA-Z_]+)=([a-zA-Z0-9-_%]*)/g)
    if (state != null) {
        for (i in state) {
            var split = state[i].split('=')
            currentState[split[0]] = split[1]
        }
    }
    console.log(currentState)
}

async function loadSidePanel(requestfield = null, id = null, push = true) {
    const loadInto = { 'group': 'sidebarSessions', 'session_id': 'sidebarGrids' }
    var loadinto = 'sidebarGroups'
    var url = "/api/sidepanel/"
    var params = []
    if (requestfield !== null) {
        params.push(`${requestfield}=${id}`)
        currentState[requestfield] = id
        loadinto = loadInto[requestfield]
    }
    if (currentState['own_sessions'] !== undefined) {
        params.push(`own_sessions=${currentState['own_sessions']}`)
    }
    for (const v of (currentState['sample_type_tag'] || [])) { params.push(`sample_type_tag=${v}`) }
    for (const v of (currentState['project_tag'] || [])) { params.push(`project_tag=${v}`) }
    if (params.length > 0) {
        url += '?' + params.join('&')
    }

    console.log(url, push)
    let models = await fetchAsync(url, message=`Loading ${requestfield}.`)
    $(`#${loadinto}`).html(models)
    toggleSearchBar(loadinto)
    adjustThirdSection()

    if (push) {
        pushState()
        selected()
    }
}

function toggleSearchBar(sectionId) {
    const $section = $(`#${sectionId}`)
    const $search = $section.siblings('.position-relative')
    // console.log(sectionId, $section.find('a').length, $search.length)
    if ($section.find('a').length > 3) {
        $search.show()
    } else {
        $search.hide()
    }
}

function adjustThirdSection() {
    const $sections = $('.sidebar-section');
    const $third = $sections.eq(2);
    const $container = $('#sidebar-container');
    
    const containerHeight = $container.innerHeight();
    const firstHeight = $sections.eq(0).outerHeight(true);
    const secondHeight = $sections.eq(1).outerHeight(true);
    const resizersHeight = $('.section-resizer').toArray()
                            .reduce((sum, el) => sum + $(el).outerHeight(true), 0);
    
    const remaining = containerHeight - firstHeight - secondHeight - resizersHeight;
    
    if (remaining > 0) {
        const headerHeight = $third.find('li').outerHeight(true) || 0;
        const scrollMaxHeight = remaining - headerHeight;
        if (scrollMaxHeight > 0) {
            $third.find('#sidebarGrids')
                  .css('max-height', scrollMaxHeight + 'px');
        }
    }
}

async function loadReport(requestfield = null, id = null, push = true) {
    console.log(`Loading report for grid: ${requestfield}, ${id}, ${push}`)
    var url = `/api/report/?grid_id=${id}`
    console.log(url)
    var report = await fetchAsync(url,message=`Loading report for grid ${id}`)
    var isNotFound = typeof report === 'string' && report.indexOf('data-report-not-found') !== -1;

    console.log('Previous grid:', currentState.grid_id)
    if (currentState.grid_id && currentState.grid_id != id) {
        console.log('Resetting hole and square state')
        delete currentState['hole']
        delete currentState['square']
        delete currentState['squareMethod']
        delete currentState['squareDisplayType']
        delete currentState['atlasMethod']
        delete currentState['atlasDisplayType']
    }

    currentState[requestfield] = id
    if (push) {
        console.log('Pushing state')
        pushState()
        selected()
    }
    $(`#main`).html(report)
    if (isNotFound) {
        return;
    }
    
    if (typeof csrftoken == 'undefined') {
        console.log('loading script', reportscript, typeof csrftoken)
        $.getScript(reportscript);
        $.getScript(websocketscript);
        while (typeof csrftoken == 'undefined') {
            console.log('loading script', typeof csrftoken)
            await new Promise(r => setTimeout(r, 500));
        }
    }

    await reportMain()
    websocketMain()
    console.trace('htmx.process called here')
    htmx.process(htmx.find('#main'))
}

// placeholder for no executed function
function noop() {}

// placeholder for no executed function
function noop() {}

function showNotification(event) {
    const container = document.getElementById('reportNotifications');
    if (!container) return;

    let text = null;
    let colorClass = null;

    switch (event.type) {
        case 'session_status':
            if (event.replay) return; // only live status changes, not replay-on-connect
            text = SESSION_STATUS_TEXT[event.status] || capitalize(event.status);
            colorClass = 'report-notification-status';
            break;

        case 'pause_status':
            text = PAUSE_STATUS_TEXT[event.status] || capitalize(event.status);
            colorClass = 'report-notification-pause';
            break;

        case 'pause_conf':
            text = PAUSE_CONF_TEXT[event.status] || capitalize(event.status);
            colorClass = 'report-notification-pause';
            break;

        default:
            return; // not a message type this element cares about
    }

    renderNotificationText(container, text, colorClass);
}

function capitalize(word) {
    if (!word) return '';
    return word.charAt(0).toUpperCase() + word.slice(1);
}

function renderNotificationText(container, text, colorClass) {
    container.innerHTML = '';
    container.classList.remove('report-notification-status', 'report-notification-pause');
    container.classList.add(colorClass);

    const item = document.createElement('span');
    item.className = `report-notification-text ${colorClass} report-notification-pulse`;

    const words = text.trim().split(' ');
    const lastWord = words.pop();

    const leading = document.createElement('span');
    leading.className = 'report-notification-text-leading';
    leading.textContent = words.length ? words.join(' ') + ' ' : '';

    const trailing = document.createElement('span');
    trailing.className = 'report-notification-text-bold';
    trailing.textContent = lastWord;

    item.appendChild(leading);
    item.appendChild(trailing);
    container.appendChild(item);
    container.style.display = '';

    // remove the pulse class once the animation finishes, so it stays still after
    item.addEventListener('animationend', function () {
        item.classList.remove('report-notification-pulse');
    }, { once: true });
}
