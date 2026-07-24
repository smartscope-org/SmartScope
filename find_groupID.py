from nextpyp.client import Client, Credentials

PATH_TO_NEXTPYP_TOKEN = "/path/to/token"
with open(PATH_TO_NEXTPYP_TOKEN) as f:
    nextpyp_token = f.read().strip()

client = Client(
    url_base='https://research-bartesaghilab-08.oit.duke.edu/', 
    credentials = Credentials(
        userid='sh696',
        token=nextpyp_token
))
group_id = client.services.sessions.groups()
print("Groups: ", group_id)