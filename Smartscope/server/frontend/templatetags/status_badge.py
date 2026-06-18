from django import template

register = template.Library()


@register.filter
def status_color(value):
    color_map = {
        'complete': 'success',
        'finished': 'success',
        'running': 'primary',
        'error': 'danger',
        'killed': 'warning',
        'stopped': 'secondary',
    }
    return color_map.get(value, 'primary')
