$(document).ready(async function () {

    initTooltips()
    checkState()
    await loadSidePanelState()
    pushState()
    selected()
    toggleSearchBar('sidebarGroups')
    toggleSearchBar('sidebarSessions')
    toggleCheckboxLabel()
    initBrowser()
    adjustThirdSection()
    $(window).on('resize', adjustThirdSection)
})

// ---- Re-init on HTMX history restore (back/forward) ----
document.addEventListener('htmx:historyRestore', async function() {
    initTooltips()
    checkState()
    await loadSidePanelState()
    pushState()
    selected()
    toggleCheckboxLabel()
    initBrowser()
    adjustThirdSection()
})

function initBrowser() {
    console.log('typing: init browser')
    // ---- Sidebar collapse ----
    initSidebarCollapse()

    // ---- Sidebar search ----
    $('#sidebar-container').off('input').on('input', '.sidebar-search', function() {
        console.log('typing:', $(this).val())
        const query = $(this).val().toLowerCase();
        const targetId = $(this).data('target');
        $(`#${targetId} a`).each(function() {
            const matches = $(this).text().toLowerCase().includes(query);
            $(this).toggle(matches);
        })
    })

    // ---- Sidebar resizer ----
    $('#sidebar-resizer').off('mousedown.resize').on('mousedown.resize', function(e) {
        e.preventDefault(); // prevents text selection and default drag behavior

        $(document).on('mousemove.resize', function(e) {
            $('#sidebar-container').css({
                'width': e.clientX + 'px',
                'flex': 'none'
            })
            toggleCheckboxLabel()
        })
        $(document).on('mouseup.resize', function() {
            $(document).off('mousemove.resize mouseup.resize')
            $(document).one('click.resize', function(e) {
            e.stopPropagation();
            e.preventDefault();
        }, true);
        })
    })

    // ---- Section height resizers ----
    $(document).off('mousedown.sectionResize', '.section-resizer')
                .on('mousedown.sectionResize', '.section-resizer', function(e) {
        const $resizer = $(this)
        const $above = $resizer.prev('.sidebar-section')
        const $below = $resizer.next('.sidebar-section')
        const startY = e.clientY
        const startAboveHeight = $above.outerHeight()
        const startBelowHeight = $below.outerHeight()
        const minHeight = 120

        $(document).on('mousemove.sectionResize', function(e) {
            const delta = e.clientY - startY
            const newAbove = startAboveHeight + delta
            const newBelow = startBelowHeight - delta

            // Respect minimum height for both neighbors
            if (newAbove < minHeight || newBelow < minHeight) return

            $above.css({ 'flex': 'none', 'height': newAbove + 'px' })
            $below.css({ 'flex': 'none', 'height': newBelow + 'px' })

            // Sync scroll areas
            $above.find('#sidebarGroups, #sidebarSessions, #sidebarGrids')
                .css('max-height', getScrollMaxHeight($above, newAbove) + 'px') 
            $below.find('#sidebarGroups, #sidebarSessions, #sidebarGrids')
                .css('max-height', getScrollMaxHeight($below, newBelow) + 'px')
            adjustThirdSection();
        })

        $(document).on('mouseup.sectionResize', function() {
            $(document).off('mousemove.sectionResize mouseup.sectionResize')
        })

        e.preventDefault()
    })

    // ---- Checkbox filter ----
    $('#filterOwnSessions').off('change').on('change', async function() {
        currentState['own_sessions'] = $(this).is(':checked') ? 'true' : 'false'
        await loadSidePanel(null, null, push = false)
        if (currentState['group'] !== undefined) {
            loadSidePanel('group', currentState['group'])
        }
        pushState()
    })

}

function initTooltips() {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
        bootstrap.Tooltip.getInstance(el)?.dispose()
    })
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
        new bootstrap.Tooltip(el, { trigger: 'hover', container: 'body' })
    })
}

function hideAllTooltips() {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
        bootstrap.Tooltip.getInstance(el)?.hide()
    })
}

function initSidebarCollapse() {
  $('#sidebarCollapse').off('click.collapse').on('click.collapse', function () {
    // e.preventDefault()
    hideAllTooltips()
    const isExpanded = parseInt($('#sidebar-container').css('width')) > 0
    console.log('InitSidebar: ', isExpanded)
    const hasBrowserState = ['group', 'session_id', 'grid_id'].some(
        key => currentState[key] !== undefined
    )

    if (!hasBrowserState && !isExpanded) {
        // not on browser page, sidebar closed -> navigate to browser page
        // setSidebarOpen(true) will be called on DOMContentLoaded
        window.location.href = $(this).attr('href')
        return
    }

    // all other cases just toggle
    setSidebarOpen(!isExpanded)
  })
}

function setSidebarOpen(open) {
    const sidebarNav = document.querySelector('#sidebarNav')
    if (open) {
        bootstrap.Collapse.getOrCreateInstance(sidebarNav).show()
        $('#sidebar-container').css({ 'width': '200px', 'min-width': '100px' })
        $('#sidebar-resizer').show()
    } else {
        bootstrap.Collapse.getOrCreateInstance(sidebarNav).hide()
        $('#sidebar-container').css({ 'width': '0', 'min-width': '0' })
        $('#sidebar-resizer').hide()
    }
}

function getScrollMaxHeight($section, sectionHeight) {
    const titleHeight = $section.find('.sidebar-separator-title').outerHeight(true) || 0
    const searchHeight = $section.find('.position-relative:visible').outerHeight(true) || 0
    return Math.max(0, sectionHeight - titleHeight - searchHeight)
}

function toggleCheckboxLabel() {
    const width = $('#sidebar-container').width()
    const $label = $('label[for="filterOwnSessions"]')
    const $checkbox = $('#filterOwnSessions')
    if (width < 225) {
        $label.hide()
        bootstrap.Tooltip.getOrCreateInstance($checkbox[0]).enable()
    } else {
        $label.show()
        bootstrap.Tooltip.getOrCreateInstance($checkbox[0]).disable()
    }
}
