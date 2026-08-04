const zoomState = {}
let panZoomState = { enabled: false, svgId: null }

function initZoomPan(svgId) {
    let svg = document.getElementById(svgId)
    if (!svg) return
    let [x, y, w, h] = svg.getAttribute('viewBox').split(' ').map(Number)
    zoomState[svgId] = {
        baseW: w, baseH: h,
        x, y, w, h,
        minScale: 1,
        maxScale: 8,
        isPanning: false,
        panStartScreen: null,
        panStartVB: null
    }
}

function getSvgPoint(svg, clientX, clientY) {
    let pt = svg.createSVGPoint()
    pt.x = clientX
    pt.y = clientY
    return pt.matrixTransform(svg.getScreenCTM().inverse())
}

function applyViewBox(svg, state) {
    svg.setAttribute('viewBox', `${state.x} ${state.y} ${state.w} ${state.h}`)
}

function zoomAt(svgId, clientX, clientY, deltaY) {
    let svg = document.getElementById(svgId)
    let state = zoomState[svgId]
    if (!svg || !state) return

    let cursor = getSvgPoint(svg, clientX, clientY)
    let zoomFactor = deltaY < 0 ? 0.9 : 1.1
    let newW = state.w * zoomFactor
    let newH = state.h * zoomFactor

    let scale = state.baseW / newW
    if (scale < state.minScale) { newW = state.baseW; newH = state.baseH }
    if (scale > state.maxScale) {
        newW = state.baseW / state.maxScale
        newH = state.baseH / state.maxScale
    }

    let ratioX = (cursor.x - state.x) / state.w
    let ratioY = (cursor.y - state.y) / state.h
    state.x = cursor.x - ratioX * newW
    state.y = cursor.y - ratioY * newH
    state.w = newW
    state.h = newH

    applyViewBox(svg, state)
}

function setZoomLevel(svgId, scale) {
    // scale = 1 means fully zoomed out; e.g. scale=2 shows half the extent, centered
    let svg = document.getElementById(svgId)
    let state = zoomState[svgId]
    if (!svg || !state) return

    scale = Math.min(Math.max(scale, state.minScale), state.maxScale)
    let newW = state.baseW / scale
    let newH = state.baseH / scale

    // keep current center fixed
    let cx = state.x + state.w / 2
    let cy = state.y + state.h / 2

    state.w = newW
    state.h = newH
    state.x = cx - newW / 2
    state.y = cy - newH / 2

    applyViewBox(svg, state)
}

function isPanZoomActive(svgId) {
    return panZoomState.enabled && panZoomState.svgId === svgId
}

function startPan(svgId, clientX, clientY) {
    let state = zoomState[svgId]
    if (!state) return
    state.isPanning = true
    state.panStartScreen = { x: clientX, y: clientY }
    state.panStartVB = { x: state.x, y: state.y }
}

function updatePan(svgId, clientX, clientY) {
    let svg = document.getElementById(svgId)
    let state = zoomState[svgId]
    if (!svg || !state || !state.isPanning) return

    let rect = svg.getBoundingClientRect()
    let dxScreen = clientX - state.panStartScreen.x
    let dyScreen = clientY - state.panStartScreen.y
    let dxSvg = dxScreen * (state.w / rect.width)
    let dySvg = dyScreen * (state.h / rect.height)

    state.x = state.panStartVB.x - dxSvg
    state.y = state.panStartVB.y - dySvg
    applyViewBox(svg, state)
}

function endPan(svgId) {
    let state = zoomState[svgId]
    if (state) state.isPanning = false
}

function resetZoomPan(svgId) {
    let svg = document.getElementById(svgId)
    let state = zoomState[svgId]
    if (!svg || !state) return
    state.x = 0; state.y = 0
    state.w = state.baseW; state.h = state.baseH
    applyViewBox(svg, state)
}

// --- Gate everything behind popupFull ---

function isCardFull(el) {
    return $(el).closest('.holeCard').hasClass('popupFull')
}

$('#main').on('mousedown', '.panZoomBtn', function () {
    console.log('panZoomBtn mousedown fired')
    event.stopPropagation()
    let card = $(this).closest('.holeCard')
    let svg = card.find('svg')[0]
    if (!svg) return

    panZoomState.enabled = !panZoomState.enabled
    console.log('panZoomState now:', panZoomState.enabled)
    panZoomState.svgId = panZoomState.enabled ? svg.id : null
    $(this).toggleClass('active', panZoomState.enabled)
    card.toggleClass('panZoomActive', panZoomState.enabled)

    if (panZoomState.enabled && !zoomState[svg.id]) initZoomPan(svg.id)
})

$('#main').on('wheel', '.holeCard svg', function (event) {
    if (!isCardFull(this) || !isPanZoomActive(this.id)) return
    event.preventDefault()
    if (!zoomState[this.id]) initZoomPan(this.id)
    zoomAt(this.id, event.originalEvent.clientX, event.originalEvent.clientY, event.originalEvent.deltaY)
})

$('#main').on('mousedown', '.holeCard svg', function (event) {
    if (!isCardFull(this) || !isPanZoomActive(this.id)) return
    if (!zoomState[this.id]) initZoomPan(this.id)
    startPan(this.id, event.clientX, event.clientY)
    event.preventDefault()
})

$('#main').on('mousemove', '.holeCard svg', function (event) {
    if (!isCardFull(this) || !isPanZoomActive(this.id)) return
    updatePan(this.id, event.clientX, event.clientY)
})

$(document).on('mouseup', function () {
    if (panZoomState.svgId) endPan(panZoomState.svgId)
})

$('#main').on('click', '.zoomPreset', function () {
    event.stopPropagation()
    let card = $(this).closest('.holeCard')
    let svg = card.find('svg')[0]
    if (!svg || !card.hasClass('popupFull')) return
    if (!zoomState[svg.id]) initZoomPan(svg.id)
    setZoomLevel(svg.id, parseFloat($(this).data('scale')))

    // also activate pan/zoom mode so wheel/drag work immediately after
    panZoomState.enabled = true
    panZoomState.svgId = svg.id
    card.find('.panZoomBtn').addClass('active')
    card.addClass('panZoomActive')
})

$('#main').on('click', '.zoomResetBtn', function () {
    event.stopPropagation()
    let card = $(this).closest('.holeCard')
    let svg = card.find('svg')[0]
    if (!svg) return
    resetZoomPan(svg.id)
})