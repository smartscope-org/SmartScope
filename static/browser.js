$(document).ready(async function () {

    checkState()
    await loadSidePanelState()
    pushState()
    selected()
})

$('#sidebarCollapse').on('click', function () {
    console.log($(this).attr('aria-expanded'), $(this).attr('aria-expanded') == "false")
    let tooltip = $(this).parent().attr('aria-describedby')
    console.log(tooltip,  $(this).parent())
    $(this).parent().removeAttr('aria-describedby')
    $(`#${tooltip}`).remove()
    if ($(this).attr('aria-expanded') == "false") {
        $('#sidebar-container').css({'width': '0', 'min-width': '0'})
        $('#sidebar-resizer').hide()
    } else {
        $('#sidebar-container').css({'width': '200px', 'min-width': '100px'})
        $('#sidebar-resizer').show()
    }
})

$('#sidebar-container').on('input', '.sidebar-search', function() {
    console.log('typing:', $(this).val())
    const query = $(this).val().toLowerCase();
    const targetId = $(this).data('target');
    $(`#${targetId} a`).each(function() {
        const matches = $(this).text().toLowerCase().includes(query);
        $(this).toggle(matches);
    })
})

$('#sidebar-resizer').on('mousedown', function(e) {
    $(document).on('mousemove.resize', function(e) {
        $('#sidebar-container').css({
            'width': e.clientX + 'px',
            'flex': 'none'
        })
    })
    $(document).on('mouseup.resize', function() {
        $(document).off('mousemove.resize mouseup.resize')
    })
})

// Section height resizers
$(document).on('mousedown', '.section-resizer', function(e) {
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