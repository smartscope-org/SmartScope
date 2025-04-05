const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value
var interval = null

async function loadlogs() {
    console.log('SENDING REQUEST!')
    let url = `/api/sessions/${session_id}/get_logs`
    data = await apifetchAsync(url, null, 'GET', 'Loading log files')
    console.log(data)
    if (data.reload === true) {
        location.reload();
    }
    // queue = document.getElementById('queue')
    // queue.innerHTML = data.queue
    out = document.getElementById('out')
    out.innerHTML = data.out
    proc = document.getElementById('proc')
    proc.innerHTML = data.proc
    elements = [out, proc]
    for (const i in elements) {
        console.log(i, elements[i])
        elements[i].scrollTop = elements[i].scrollHeight;
    }
    disk.innerHTML = `Hard drive: ${data.disk[0]} GB total, ${data.disk[1]} GB free, ${data.disk[2]}% full`
    isPaused(data.paused)
    isStopFile(data.is_stop_file)
    setPause(data)
}

// start or stop the session
async function startSession(start = true, screeningMode = false) {
    let url = `/api/sessions/${session_id}/run_session/`;
    var str = start ? 'start' : 'stop';
    var r = confirm(`Do you want to ${str} this session?`);

    if (r == true) {
        // try {
            let requestData = { 'start': start, 'screening_mode': screeningMode };
            return apifetchAsync(url, requestData, "POST", message='Starting session')
        //     const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || "";
        //     const response = await fetch(url, {
        //         method: "POST",
        //         headers: {
        //             "Content-Type": "application/json",
        //             "X-CSRFToken": csrfToken
        //         },
        //         body: JSON.stringify(requestData)
        //     });

        //     if (!response.ok) {
        //         throw new Error(`Server error: ${response.status} ${response.statusText}`);
        //     }

        //     console.log("API Response:", response);
        //     return response; // Returns the Response object directly

        // } catch (error) {
        //     console.error("API Error:", error);
        //     return { error: error.message };
        // }
        
    } else {
        console.log("Cancelled by user");
    }
}

async function togglePause() {
    console.log('toggling pause')
    let url = `/api/sessions/${session_id}/pause_between_grids/`
    resp = await apifetchAsync(url, { 'pause': '' }, 'PUT', 'Toggling auto-pause');
    setPause(resp)
    console.log('Response:', resp)

}

async function continueRun(value) {
    let url = `/api/sessions/${session_id}/continue_run/`
    resp = await apifetchAsync(url, { 'continue': value }, 'PUT', 'Continuing or skipping');
    isPaused(resp)
    console.log('Response:', resp)

}

function setPause(data) {
    pause = document.getElementById('pause')
    pause.classList.remove('btn-outline-success')
    pause.classList.remove('btn-outline-danger')
    console.log(data.pause)
    if (data.pause === true) {
        pause.classList.add('btn-outline-success')
    } else {
        pause.classList.add('btn-outline-danger')
    }
}

function isStopFile(data) {
    console.log('Is Stop File?', data)

    if (data == true) {
        $('#stopSignal').removeClass('d-none')
        return
    }
    $('#stopSignal').addClass('d-none')

}

function isPaused(paused) {
    paused_div = document.getElementById('paused')
    if (paused === true) {
        paused_div.classList.remove('hidden')
    } else {
        paused_div.classList.add('hidden')
    }
}

 function autoRefresh(enable = true) {
    if (enable === true){
        console.log('Autorefresh enabled')
        interval = setInterval(async function () {
            console.log("Refreshing!");
            await loadlogs();
            await checkIsRunning(document.getElementById('start-button'))
        }
            , 10000);
        return
    }
    console.log('Autorefresh disabled')
    clearInterval(interval);
};


//checkIsRunning tracks staus of the session and changes the button from start to stop and vice versa

async function checkIsRunning(element, response = null) {
    const url = `/api/sessions/${session_id}/check_is_running/`;
    if (!response) {
        response = await apifetchAsync(url, null, 'GET', 'Checking if session is running');
    }
    console.log('Response from checkIsRunning: ',response.status )
    const isRunning = response.status === 'running';

    // Toggle button styles and update value/text
    element.classList.toggle('btn-outline-danger', isRunning);
    element.classList.toggle('btn-outline-primary', !isRunning);
    element.value = isRunning ? 'stop' : 'start';
    element.innerHTML = isRunning ? 'Stop' : 'Start';

    // Force an attribute update to ensure it registers correctly
    element.setAttribute("value", isRunning ? "stop" : "start");

    let dropdown = document.querySelector(".dropdown-menu");
    if (element.value=="stop"){
            dropdown.style.display = "none";
    }
    if (isRunning && interval == null) {
        autoRefresh(isRunning);
    }
    if (!isRunning && interval != null) {
        autoRefresh(isRunning)
    }
    return response;
}

$(document).ready(async function () {
    loadlogs(); run_status = await checkIsRunning(document.getElementById('start-button')); console.log(run_status)
});

$(document).ready(function () {
    $(".screening-type").on("click", async function () {
        let startButton = document.getElementById("start-button");
        if (!startButton) {
            console.error("Start button not found!");
            return;
        }

        // set the button value to start
        let isStarting = startButton.getAttribute("value") === "start";
        console.log("Session Mode:", isStarting ? "Start" : "Stop");

        // select the screenig mode
        let screeningMode = isStarting ? $(this).data("mode") === true : null;
        console.log(`Screening Mode: ${screeningMode ? "Atlas Only" : "Full Screening"}`);

        let dropdown = document.querySelector(".dropdown-menu");
        if (!dropdown) {
            console.error("Dropdown menu not found!");
            return;
        }

        try {
            // Call the startSession function
            let run_status = await startSession(isStarting, screeningMode);
            console.log("Session Status:", run_status);

            // Call checkisRunning to check session and update UI
            await checkIsRunning(startButton, run_status);
        } catch (error) {
            console.error("Error in session start/stop:", error);
        }
    });
    $(".session-toggle").on("click", async function () {
        let startButton = document.getElementById("start-button");
        if (!startButton) {
            console.error("Start button not found!");
            return;
        }

        let isStarting = startButton.getAttribute("value") === "start";
        console.log("Button Clicked - Mode:", isStarting ? "Start" : "Stop");
        if (isStarting) {
            return;
        }

        try {
            // Call the startSession 
            let run_status = await startSession(isStarting, null);
            console.log("Run Status:", run_status);

            // Call checkisRunning to check session and update UI
            await checkIsRunning(startButton, run_status);
        } catch (error) {
            console.error("Error in session start/stop:", error);
        }
    });
});

$('#force-start-button').on('click', async function () {
    console.log(this)
    let val = (this.value === "start");
    run_status = await startSession(val);
})

$('#removeLockButton, #forceKill').on('click', async function () {
    console.log(`Running ${this.value}`)
    let url = `/api/sessions/${session_id}/${this.value}/`
    data = await apifetchAsync(url, null, 'POST', 'Removing microscope lock file')
    console.log(data)
})

// $('#stop-button').on('click', function () { start(start = false);is_running=false; checkIsRunning()})
$('#pause').on('click', function () { togglePause() })
$('#continue-next, #continue').on('click', function () { console.log(this, this.value); continueRun(this.value) })

