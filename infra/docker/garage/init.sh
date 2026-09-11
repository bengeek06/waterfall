#!/bin/sh
# Bootstrap the single-node Garage cluster the API stores import sources in (E13-02).
#
# Runs as a compose one-shot service on every `up`, so every step is idempotent: an
# already-initialised stack must exit 0 without changing anything. The steps are the ones
# a single-node Garage requires -- wait for RPC, assign and apply a layout, import the
# application key, create the bucket, grant the key on it -- and none of them can be
# skipped by pre-seeding a volume, because the node identity is generated on first start.
#
# `key import` (not `key create`): the credentials must be exactly the ones the API is
# configured with, and `key create` returns randomly generated ones.
set -eu

: "${GARAGE_RPC_SECRET:?GARAGE_RPC_SECRET must be set}"
: "${GARAGE_ACCESS_KEY_ID:?GARAGE_ACCESS_KEY_ID must be set}"
: "${GARAGE_SECRET_ACCESS_KEY:?GARAGE_SECRET_ACCESS_KEY must be set}"
: "${GARAGE_BUCKET:?GARAGE_BUCKET must be set}"

KEY_NAME="${GARAGE_KEY_NAME:-waterfall-app}"
ZONE="${GARAGE_ZONE:-waterfall}"
CAPACITY="${GARAGE_CAPACITY:-10G}"
READY_ATTEMPTS="${GARAGE_READY_ATTEMPTS:-60}"

log() { echo "garage-init: $*"; }

# 1. Wait for the node to answer RPC. `depends_on: service_started` only guarantees the
#    container exists; the server still has to generate its node key (on a first boot) and
#    open its RPC socket. The CLI finds both the key and the address to dial through the
#    metadata directory and garage.toml this container mounts read-only -- `--rpc-host`
#    would need the node's full ID, which does not exist yet the first time around.
attempt=1
until garage status >/dev/null 2>&1; do
  if [ "$attempt" -ge "$READY_ATTEMPTS" ]; then
    log "node did not answer RPC after ${attempt}s, giving up"
    garage status || true
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 1
done
log "node is up"

# 2. Cluster layout. Version 0 means "no node has a role yet": that is the only state in
#    which assigning is correct, and re-applying an already-applied version fails with
#    "Invalid new layout version".
#    The version is parsed out of the CLI's human-readable output, so treat a failed parse
#    as an error rather than as "not initialised yet": defaulting to 0 on an already-
#    initialised cluster (e.g. after an image bump reworded the line) would re-run `layout
#    apply --version 1`, which fails, and the api service would never start again.
layout_version=$(garage layout show 2>/dev/null | sed -n 's/^Current cluster layout version: *//p')
if [ -z "${layout_version:-}" ]; then
  log "could not read the cluster layout version (unexpected 'garage layout show' output)"
  garage layout show || true
  exit 1
fi
if [ "$layout_version" = "0" ]; then
  # `node id` prints `<full id>@<rpc address>`; layout assign wants the ID alone.
  node_id=$(garage node id -q 2>/dev/null | cut -d '@' -f 1)
  if [ -z "${node_id:-}" ]; then
    log "could not read the node ID from 'garage node id'"
    garage node id || true
    exit 1
  fi
  log "assigning layout to node $node_id (zone=$ZONE, capacity=$CAPACITY)"
  garage layout assign -z "$ZONE" -c "$CAPACITY" "$node_id" >/dev/null
  garage layout apply --version 1 >/dev/null
  log "layout applied (version 1)"
else
  log "layout already applied (version $layout_version)"
fi

# 3. Application key. Imported with the exact credentials the API uses, so the same .env
#    works against a freshly created cluster and an existing one.
if garage key info "$GARAGE_ACCESS_KEY_ID" >/dev/null 2>&1; then
  # A key ID can never be recreated in Garage, even after deletion. If the secret in the
  # environment no longer matches the stored one, every API call would fail signature
  # verification with no hint as to why -- so say so instead of exiting 0 on a broken setup.
  stored_secret=$(garage key info --show-secret "$GARAGE_ACCESS_KEY_ID" 2>/dev/null |
    sed -n 's/^Secret key: *//p')
  # An unreadable secret is not a mismatching secret. Falling through would print the
  # "pick a new GARAGE_ACCESS_KEY_ID" advice below for a pure parsing problem, and send a
  # developer off minting a new key -- polluting the cluster with a key ID that can never
  # be removed -- to fix something that has nothing to do with the credentials.
  if [ -z "${stored_secret:-}" ]; then
    log "could not read the stored secret for $GARAGE_ACCESS_KEY_ID (unexpected 'garage key info' output)"
    exit 1
  fi
  if [ "$stored_secret" != "$GARAGE_SECRET_ACCESS_KEY" ]; then
    log "key $GARAGE_ACCESS_KEY_ID exists with a different secret key."
    log "Garage cannot reassign a secret to an existing key ID: either restore the"
    log "original GARAGE_SECRET_ACCESS_KEY, or pick a new GARAGE_ACCESS_KEY_ID."
    exit 1
  fi
  log "key $GARAGE_ACCESS_KEY_ID already imported"
else
  garage key import --yes -n "$KEY_NAME" \
    "$GARAGE_ACCESS_KEY_ID" "$GARAGE_SECRET_ACCESS_KEY" >/dev/null
  log "imported key $GARAGE_ACCESS_KEY_ID as '$KEY_NAME'"
fi

# 4. Bucket.
if garage bucket info "$GARAGE_BUCKET" >/dev/null 2>&1; then
  log "bucket $GARAGE_BUCKET already exists"
else
  garage bucket create "$GARAGE_BUCKET" >/dev/null
  log "created bucket $GARAGE_BUCKET"
fi

# 5. Permissions. Unconditional: `bucket allow` sets the permissions rather than adding
#    to them, so replaying it is a no-op.
garage bucket allow --read --write --owner "$GARAGE_BUCKET" --key "$GARAGE_ACCESS_KEY_ID" >/dev/null
log "granted read/write/owner on $GARAGE_BUCKET to $GARAGE_ACCESS_KEY_ID"
log "done"
