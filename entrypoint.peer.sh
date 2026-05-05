#!/bin/bash

echo "[Peer $PEER_ID] Waiting for tracker at $TRACKER_HOST:5000..."
while ! nc -z $TRACKER_HOST 5000; do
    sleep 1
done
echo "[Peer $PEER_ID] Tracker is up!"


if [ ! "$(ls -A /app/shared_files/)" ]; then
    echo "[Peer $PEER_ID] Creating test ISO..."
    dd if=/dev/zero of=/app/shared_files/test_peer${PEER_ID}.iso bs=1M count=10 2>/dev/null
fi

echo "[Peer $PEER_ID] Starting peer on port $PEER_PORT..."
exec python -u src/peer/client.py --port $PEER_PORT