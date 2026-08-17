import logging
from django.shortcuts import render

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group

from Smartscope.core.models.tags import SampleTypeTag, UserGroupTag, Tag, TagGrid, SampleTag, ProjectTag
from Smartscope.core.models import AutoloaderGrid


logger = logging.getLogger(__name__)

class TagTypeDoesNotExist(Exception):
    pass

TAG_TYPE_MAP = {
    'sample': SampleTag,
    'project': ProjectTag,
    'sample_type': SampleTypeTag,
}

def get_tag_type(tag_type) -> Tag:
    if tag_type not in TAG_TYPE_MAP:
        raise TagTypeDoesNotExist(f'Tag type {tag_type} does not exist, must be one of {TAG_TYPE_MAP.keys()}')
    return TAG_TYPE_MAP[tag_type]

def get_sample_types(request):
    sample_types = SampleTypeTag.objects.all()
    return render(request, 'list_tags_dropdown.html', {'sample_types': sample_types})

def get_grid_tags(grid_id, tag_type:Tag):
    return TagGrid.objects.filter(grid_id=grid_id, content_type=tag_type)

def create_tag_question(request):
    # context = 
    return render(request, 'tags/create_tag_question.html')

def search_tags(request, tag_type:str):
    tag = request.GET.get('tag')
    logger.debug(f'Searching for tag {tag} of type {tag_type}')
    tags = get_tag_type(tag_type).objects.filter(name__icontains=tag)
    logger.debug(f'Found tags: {tags}')
    return render(request, 'tags/tags_list_dropdown.html', context={'tags': tags})

def remove_tag_from_grid(request, object_id:int):
    if request.method == 'DELETE':
        logger.debug(f"Removing tag with id {object_id}")
        tag = TagGrid.objects.get(pk=object_id)
        content_type = ContentType.objects.get_for_model(tag.content_object)
        grid_id = tag.grid_id
        tag.delete()
    grid_tags = get_grid_tags(grid_id, tag_type = content_type)
    context = {'tags': grid_tags}
    return render(request, 'tags/tags_list.html', context=context)

def add_tag_to_grid(request, tag_type: Tag, grid_id:str):
    if request.method == 'POST':
        content_type = ContentType.objects.get_for_model(tag_type)
        grid_id = AutoloaderGrid.objects.get(grid_id=grid_id)
        tag = request.POST.get('tag')
        object_id = tag_type.objects.get(name=tag)
        tag_instance, _ = TagGrid.objects.get_or_create(content_type=content_type, object_id=object_id.pk, grid_id=grid_id)
        grid_tags = get_grid_tags(grid_id, content_type)
        context = {'tags': grid_tags}
        return render(request, 'tags/tags_list.html', context=context)
    
def add_sample_type_tag(request, grid_id):
    return add_tag_to_grid(request, SampleTypeTag, grid_id=grid_id)

def add_project_tag(request, grid_id):
      return add_tag_to_grid(request, ProjectTag, grid_id=grid_id)

def create_project_tag(request, grid_id):
    if request.method == 'POST':
        name = request.POST.get('tag')
        group_name = request.POST.get('group')
        if name and group_name and (request.user.is_staff or request.user.groups.filter(name=group_name).exists()):
            ProjectTag.objects.get_or_create(
                name=name, group_name=Group.objects.get(name=group_name),
                defaults={'user_id': request.user})
    choices = ProjectTag.objects.filter(group_name__in=request.user.groups.all().values_list('name', flat=True))
    applied_project_tags = get_grid_tags(grid_id, ContentType.objects.get_for_model(ProjectTag))
    context = {'tags': choices, 'grid_id': grid_id, 'user_groups': request.user.groups.all(),
                'applied_project_tags': applied_project_tags}
    return render(request, 'tags/project_tags_choices.html', context=context)
      
def delete_project_tag(request, grid_id):
    if request.method == 'POST':
        pk = request.POST.get('pk')
        tag = ProjectTag.objects.filter(pk=pk).first()
        if tag and (request.user.is_staff or request.user.groups.filter(name=tag.group_name_id).exists()):
            content_type = ContentType.objects.get_for_model(ProjectTag)
            TagGrid.objects.filter(content_type=content_type, object_id=tag.pk).delete()
            tag.delete()
    choices = ProjectTag.objects.filter(group_name__in=request.user.groups.all().values_list('name', flat=True))
    applied_project_tags = get_grid_tags(grid_id, ContentType.objects.get_for_model(ProjectTag))
    context = {'tags': choices, 'grid_id': grid_id, 'user_groups': request.user.groups.all(),
                'applied_project_tags': applied_project_tags}
    return render(request, 'tags/project_tags_choices.html', context=context)
    
def tag_manager(request, grid_id):
    context = { 'grid_id': grid_id }
    sample_type_tags = get_grid_tags(grid_id, ContentType.objects.get_for_model(SampleTypeTag))
    sample_type_tags_choices = SampleTypeTag.objects.all()
    context['sample_type_tags'] = sample_type_tags
    context['sample_type_tags_choices'] = sample_type_tags_choices
    projects_tags = get_grid_tags(grid_id, ContentType.objects.get_for_model(ProjectTag))
    context['projects_tags'] = projects_tags
    context['projects_tags_choices'] = ProjectTag.objects.filter(group_name__in=request.user.groups.all().values_list('name', flat=True))
    context['user_groups'] = request.user.groups.all()


    return render(request, 'tags/tags_manager.html', context=context)