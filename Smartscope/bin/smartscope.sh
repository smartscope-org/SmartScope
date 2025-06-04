#!/bin/bash

echo "Setting up environment"

export $(grep -E '^[A-Za-z_]+=' Docker/Smartscope/smartscope.conf | xargs)

env | sort

uv run $@