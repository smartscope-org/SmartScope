from nextpyp.client import Client

client = Client('https://research-bartesaghilab-08.oit.duke.edu/', None)
token_data = client.services.apps.request_token(
    user_id='sh696',
    app_name='smartscope',
    app_permission_ids= [
        "project_list",
        "project_listen",
        "session_list",
        "session_read",
        "session_write",
        "session_control",
        "session_create",
        "session_delete",
        "session_export",
        "session_listen",
        "group_list",
    ]
)

print(f'token data: {token_data}')
