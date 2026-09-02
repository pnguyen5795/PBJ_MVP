#!/bin/sh
set -eu

data_dir="${APP_DATA_DIR:-/var/data}"
mkdir -p "$data_dir"
chown pbj:pbj "$data_dir"

exec gosu pbj "$@"
