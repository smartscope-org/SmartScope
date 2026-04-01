#!/usr/bin/env python3
"""SmartScope Globus Pipeline Setup.

One-stop script to authenticate with Globus, deploy the preprocessing
flow, and register the compute function. Run inside the SmartScope
container or anywhere with globus-sdk installed.

Usage:
    python setup_globus.py                              # Interactive: auth + deploy + register
    python setup_globus.py auth                         # Just authenticate
    python setup_globus.py deploy-flow                  # Just deploy/update the flow
    python setup_globus.py register-func                # Register the default compute function
    python setup_globus.py register-func -f my_func.py  # Register a custom compute function
    python setup_globus.py status                       # Show current config

To write a custom compute function, copy scripts/compute_function_template.py
and implement the run_preprocessing() function for your HPC environment.
"""

import json
import sys
from pathlib import Path

# ---------- Defaults ----------

CLIENT_ID = "7df9d534-fb19-4d79-8e83-642f1cdcf081"
TOKEN_FILE = Path("/opt/config/smartscope_tokens.json")
FLOW_DEFINITION_FILE = Path(__file__).resolve().parent.parent / \
    "Smartscope" / "core" / "pipelines" / "globus_flow_definition.json"

# All scopes needed for the full pipeline
SCOPES = [
    "urn:globus:auth:scope:transfer.api.globus.org:all",
    "https://auth.globus.org/scopes/eec9b274-0c81-4334-bdc2-54e90e689b9a/manage_flows",
    "https://auth.globus.org/scopes/eec9b274-0c81-4334-bdc2-54e90e689b9a/run_manage",
    "https://auth.globus.org/scopes/eec9b274-0c81-4334-bdc2-54e90e689b9a/view_flows",
    "https://auth.globus.org/scopes/facd7ccc-c5f4-42aa-916b-a0e270e2c2a9/all",
]

# ---------- Token helpers ----------

def _load_tokens():
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return {}

def _save_tokens(tokens):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    TOKEN_FILE.chmod(0o600)

# ---------- Auth ----------

def do_auth():
    from globus_sdk import NativeAppAuthClient

    print("\n=== Globus Authentication ===\n")

    auth_client = NativeAppAuthClient(CLIENT_ID)
    auth_client.oauth2_start_flow(
        requested_scopes=SCOPES,
        refresh_tokens=True,
    )

    url = auth_client.oauth2_get_authorize_url()
    print(f"Visit this URL and log in:\n\n  {url}\n")
    code = input("Paste the authorization code here: ").strip()

    token_response = auth_client.oauth2_exchange_code_for_tokens(code)

    # Merge into existing tokens (preserves funcx_service etc.)
    existing = _load_tokens()
    for rs, data in token_response.by_resource_server.items():
        existing[rs] = dict(data)
    _save_tokens(existing)

    print(f"\nTokens saved to {TOKEN_FILE}")
    for rs in token_response.by_resource_server:
        print(f"  - {rs}")

    return existing

# ---------- Deploy Flow ----------

def do_deploy_flow(tokens=None):
    from globus_sdk import NativeAppAuthClient, FlowsClient, RefreshTokenAuthorizer

    print("\n=== Deploy Globus Flow ===\n")

    if tokens is None:
        tokens = _load_tokens()

    if "flows.globus.org" not in tokens:
        print("Error: No flows token. Run 'setup_globus.py auth' first.")
        return None

    auth_client = NativeAppAuthClient(CLIENT_ID)
    t = tokens["flows.globus.org"]
    authorizer = RefreshTokenAuthorizer(
        t["refresh_token"], auth_client,
        access_token=t["access_token"],
        expires_at=t["expires_at_seconds"],
    )
    fc = FlowsClient(authorizer=authorizer)

    definition = json.loads(FLOW_DEFINITION_FILE.read_text())
    input_schema = {
        "type": "object",
        "required": ["input"],
        "properties": {
            "input": {
                "type": "object",
                "required": ["source_collection", "destination_collection",
                             "compute_endpoint", "compute_function",
                             "compute_kwargs", "transfer_items", "label"],
                "properties": {
                    "source_collection": {"type": "string"},
                    "destination_collection": {"type": "string"},
                    "compute_endpoint": {"type": "string"},
                    "compute_function": {"type": "string"},
                    "compute_kwargs": {"type": "object"},
                    "transfer_items": {"type": "array"},
                    "label": {"type": "string"},
                    "results_label": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }

    # Check for existing SmartScope flows
    existing_flows = []
    for flow in fc.list_flows():
        if "SmartScope" in flow.get("title", ""):
            existing_flows.append(flow)

    def _create_new_flow():
        title = input("Flow title [SmartScope Globus Preprocessing]: ").strip()
        title = title or "SmartScope Globus Preprocessing"

        # Get subscription ID if user has multiple
        try:
            result = fc.create_flow(title=title, definition=definition, input_schema=input_schema)
        except Exception as e:
            if "SUBSCRIPTION_MUST_BE_SPECIFIED" in str(e):
                sub_id = input("Subscription ID (from Globus web app): ").strip()
                result = fc.create_flow(title=title, definition=definition,
                                        input_schema=input_schema, subscription_id=sub_id)
            else:
                raise
        return result["id"]

    if existing_flows:
        print("Existing SmartScope flows found:")
        for i, flow in enumerate(existing_flows):
            print(f"  [{i+1}] {flow['title']}  ({flow['id']})")
        print(f"  [N] Deploy a new flow")

        choice = input("\nUpdate existing or deploy new? ").strip()
        if choice.upper() == "N":
            flow_id = _create_new_flow()
            print(f"\nNew flow deployed: {flow_id}")
        else:
            idx = int(choice) - 1
            flow_id = existing_flows[idx]["id"]
            fc.update_flow(flow_id, definition=definition, input_schema=input_schema)
            print(f"\nFlow updated: {flow_id}")
    else:
        flow_id = _create_new_flow()
        print(f"\nFlow deployed: {flow_id}")

    # Re-auth with flow-specific scope
    _reauth_for_flow(flow_id, tokens)

    return flow_id

def _reauth_for_flow(flow_id, tokens):
    """Add flow-specific run scope to tokens."""
    from globus_sdk import NativeAppAuthClient, SpecificFlowClient

    flow_scope = SpecificFlowClient(flow_id).scopes.user
    if any(flow_id in str(v) for v in tokens.values()):
        return  # Already have flow-specific tokens

    print(f"\nFlow-specific auth needed for {flow_id}")
    auth_client = NativeAppAuthClient(CLIENT_ID)
    auth_client.oauth2_start_flow(
        requested_scopes=SCOPES + [flow_scope],
        refresh_tokens=True,
    )
    url = auth_client.oauth2_get_authorize_url()
    print(f"\nVisit this URL:\n\n  {url}\n")
    code = input("Paste the authorization code: ").strip()

    token_response = auth_client.oauth2_exchange_code_for_tokens(code)
    for rs, data in token_response.by_resource_server.items():
        tokens[rs] = dict(data)
    _save_tokens(tokens)
    print("Flow-specific tokens saved.")

# ---------- Register Compute Function ----------

def do_register_function(tokens=None, function_file=None):
    from globus_sdk import NativeAppAuthClient, ComputeClientV2, RefreshTokenAuthorizer
    from globus_compute_sdk.sdk.client import FunctionRegistrationData
    import importlib.util

    print("\n=== Register Compute Function ===\n")

    if tokens is None:
        tokens = _load_tokens()

    if "funcx_service" not in tokens:
        print("Error: No compute token. Run 'setup_globus.py auth' first.")
        return None

    auth_client = NativeAppAuthClient(CLIENT_ID)
    t = tokens["funcx_service"]
    authorizer = RefreshTokenAuthorizer(
        t["refresh_token"], auth_client,
        access_token=t["access_token"],
        expires_at=t["expires_at_seconds"],
    )
    cc = ComputeClientV2(authorizer=authorizer)

    # Load the compute function from file
    if function_file is None:
        function_file = str(Path(__file__).resolve().parent / "register_compute_function.py")
        print(f"Using default function: {function_file}")
    else:
        print(f"Using custom function: {function_file}")

    spec = importlib.util.spec_from_file_location("compute_func", function_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "run_preprocessing"):
        print(f"Error: {function_file} must define a 'run_preprocessing' function.")
        return None

    func = mod.run_preprocessing
    reg_data = FunctionRegistrationData(function=func)
    result = cc.post("/v3/functions", data=reg_data.to_dict())
    func_id = result.data["function_uuid"]

    print(f"Function registered: {func_id}")
    print(f"Source: {function_file}")

    return func_id

# ---------- Status ----------

def do_status():
    print("\n=== SmartScope Globus Status ===\n")

    tokens = _load_tokens()
    if not tokens:
        print(f"No tokens found at {TOKEN_FILE}")
        return

    print(f"Token file: {TOKEN_FILE}")
    print(f"Token scopes:")
    for rs in tokens:
        print(f"  - {rs}")

    print(f"\nFlow definition: {FLOW_DEFINITION_FILE}")
    print(f"  Exists: {FLOW_DEFINITION_FILE.exists()}")

# ---------- Interactive Setup ----------

def do_full_setup():
    print("=" * 50)
    print("  SmartScope Globus Pipeline Setup")
    print("=" * 50)

    # Step 1: Auth
    tokens = _load_tokens()
    if tokens and "flows.globus.org" in tokens and "funcx_service" in tokens:
        reauth = input("\nExisting tokens found. Re-authenticate? [y/N]: ").strip().lower()
        if reauth == "y":
            tokens = do_auth()
    else:
        tokens = do_auth()

    # Step 2: Deploy flow
    flow_id = do_deploy_flow(tokens)

    # Step 3: Register function
    func_id = do_register_function(tokens)

    # Summary
    print("\n" + "=" * 50)
    print("  Setup Complete")
    print("=" * 50)
    print(f"\n  Flow ID:     {flow_id}")
    print(f"  Function ID: {func_id}")
    print(f"  Token file:  {TOKEN_FILE}")
    print(f"\n  Enter these in the SmartScope preprocessing form,")
    print(f"  or they will appear in the dropdowns automatically.")
    print()


# ---------- CLI ----------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="SmartScope Globus Pipeline Setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")
    sub.default = "setup"

    sub.add_parser("setup", help="Full interactive setup (auth + deploy + register)")
    sub.add_parser("auth", help="Authenticate with Globus")
    sub.add_parser("deploy-flow", help="Deploy or update the Globus Flow")

    reg = sub.add_parser("register-func", help="Register a compute function")
    reg.add_argument("--function", "-f", metavar="FILE",
                     help="Path to a Python file containing run_preprocessing(). "
                          "Default: the bundled SLURM-based function. "
                          "Copy scripts/compute_function_template.py to get started.")

    sub.add_parser("status", help="Show current configuration")

    args = parser.parse_args()
    cmd = args.command or "setup"

    if cmd == "setup":
        do_full_setup()
    elif cmd == "auth":
        do_auth()
    elif cmd == "deploy-flow":
        do_deploy_flow()
    elif cmd == "register-func":
        do_register_function(function_file=getattr(args, "function", None))
    elif cmd == "status":
        do_status()
