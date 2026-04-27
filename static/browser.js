$(document).ready(async function () {

    checkState()
    await loadSidePanelState()
    pushState()
    selected()
    toggleSearchBar('sidebarGroups')
    toggleSearchBar('sidebarSessions')
    toggleCheckboxLabel()
    initBrowser()
})

// ---- Re-init on HTMX history restore (back/forward) ----
document.addEventListener('htmx:historyRestore', async function() {
    checkState()
    await loadSidePanelState()
    pushState()
    selected()
    toggleCheckboxLabel()
    initBrowser()
})

function initBrowser() {
    // ---- Sidebar collapse ----
    $('#sidebarCollapse').off('click').on('click', function () {
        // console.log($(this).attr('aria-expanded'), $(this).attr('aria-expanded') == "false")
        const sidebarNav = document.querySelector('#sidebarNav')
        const isExpanded = parseInt($('#sidebar-container').css('width')) > 0
        console.log('isExpanded:', isExpanded)
        let tooltip = $(this).parent().attr('aria-describedby')
        console.log(tooltip,  $(this).parent())
        $(this).parent().removeAttr('aria-describedby')
        $(`#${tooltip}`).remove()
        if (isExpanded) {
            console.log('>>> collapsing')
            bootstrap.Collapse.getOrCreateInstance(sidebarNav).hide()
            $('#sidebar-container').css({'width': '0', 'min-width': '0'})
            $('#sidebar-resizer').hide()
            $(this).attr('aria-expanded', 'false')
        } else {
            bootstrap.Collapse.getOrCreateInstance(sidebarNav).show()
            console.log('>>> expanding')
            $('#sidebar-container').css({'width': '200px', 'min-width': '100px'})
            $('#sidebar-resizer').show()
            $(this).attr('aria-expanded', 'true')
        }
    })

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
        $(document).on('mousemove.resize', function(e) {
            $('#sidebar-container').css({
                'width': e.clientX + 'px',
                'flex': 'none'
            })
            toggleCheckboxLabel()
        })
        $(document).on('mouseup.resize', function() {
            $(document).off('mousemove.resize mouseup.resize')
        })
    })

    // ---- Section height resizers ----
    $(document).off('mousedown.sectionResize', '.section-resizer').on('mousedown', '.section-resizer', function(e) {
        const $section = $(this).prev()
        const $list = $section.find('#sidebarGroups, #sidebarSessions, #sidebarGrids')
        const startY = e.clientY
        const startHeight = $section.outerHeight()

        $(document).on('mousemove.sectionResize', function(e) {
            const newHeight = startHeight + (e.clientY - startY)
            $section.css({
                'max-height': newHeight + 'px',
                'height': newHeight + 'px'
            })
            $list.css({
                'max-height': (newHeight - 80) + 'px',
                'height': 'auto'
            })
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

    // ---- microscopeActivity / sessionHistory collapse sidebar ----
    document.querySelectorAll('#microscopeActivity, #sessionHistory').forEach(btn => {
        btn.removeEventListener('click', collapseSidebar)
        btn.addEventListener('click', collapseSidebar)
    })
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

function collapseSidebar() {
    const sidebarNav = document.querySelector('#sidebarNav')
    const isExpanded = $(sidebarNav).hasClass('show')
    if (isExpanded) {
        const tooltip = $(this).parent().attr('aria-describedby')
        $(this).parent().removeAttr('aria-describedby')
        $(`#${tooltip}`).remove()

        const toggleBtn = $('#sidebarCollapse')
        bootstrap.Collapse.getOrCreateInstance(sidebarNav).hide()
        toggleBtn.attr('aria-expanded', 'false')
        $('#sidebar-container').css({'width': '0', 'min-width': '0'})
        $('#sidebar-resizer').hide()
    }
}
